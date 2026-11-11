"""Small Qt helpers shared by the window, the tabs and the dialogs."""

from __future__ import annotations

import re

from PySide6.QtCore import QEvent, QObject, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLineEdit,
    QMessageBox,
    QTableView,
    QTableWidget,
    QTableWidgetItem,
    QToolTip,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from windiskcleaner.log import logger
from windiskcleaner.scanner import ScanCancelled
from windiskcleaner.strings import tr

PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
           "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#86bcb6"]
GREY_FREE, GREY_UNSCANNED, GREY_OTHER = "#d4d4d4", "#8c8c8c", "#b0b0b0"
ROLE = Qt.ItemDataRole.UserRole
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
MAX_ROWS = 200
PADDING = 12  # px of air after the longest text
MAX_FIT = 420  # px: a fitted column never grows past this, the stretch column takes the rest
YES, NO = QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.No


class Worker(QThread):
    """Runs fn(progress, cancelled) off the UI thread."""

    progress = Signal(object, object)
    done = Signal(object)
    failed = Signal(str)  # empty string = cancelled by the user

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    def run(self) -> None:
        try:
            self.done.emit(self.fn(self.progress.emit, self.isInterruptionRequested))
        except ScanCancelled:
            self.failed.emit("")
        except Exception as err:  # shown to the user instead of killing the thread silently
            logger.exception("background job failed")
            self.failed.emit(str(err) or repr(err))


class SortItem(QTableWidgetItem):
    """Table cell that sorts by a number rather than by its text."""

    def __init__(self, text: str, value: float):
        super().__init__(text)
        self.value = value

    def __lt__(self, other) -> bool:
        return self.value < getattr(other, "value", 0)


def make_table(headers: list[str], stretch: int = -1) -> QTableWidget:
    """A read-only table whose columns fit their content; `stretch` (default: the last)
    takes the remaining width."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    auto_fit(table, stretch % len(headers))
    return table


class _ElidedTips(QObject):
    """Shows the whole text of a cell whose text does not fit (paths are elided with "…")."""

    def __init__(self, view: QAbstractItemView):
        super().__init__(view)
        self.view = view

    def eventFilter(self, _obj, event) -> bool:
        if event.type() != QEvent.Type.ToolTip:
            return False
        index = self.view.indexAt(event.pos())
        text = index.data() if index.isValid() else None
        if not isinstance(text, str) or index.data(Qt.ItemDataRole.ToolTipRole):
            return False  # nothing to say, or the cell has its own tooltip
        if self.view.visualRect(index).width() >= self.view.sizeHintForIndex(index).width():
            QToolTip.hideText()
            return True
        QToolTip.showText(event.globalPos(), text, self.view)
        return True


def auto_fit(view: QAbstractItemView, stretch: int) -> None:
    """Keep every column wide enough for its content, without the user resizing by hand.

    Column `stretch` (usually the path or name) fills what is left. The others are fitted
    whenever rows arrive, and grow when a cell gets wider text; between loads they never
    shrink, so a width the user chose is kept. A fitted column stops at MAX_FIT.
    """
    header = view.horizontalHeader() if isinstance(view, QTableView) else view.header()
    header.setStretchLastSection(False)
    stretchy, free = QHeaderView.ResizeMode.Stretch, QHeaderView.ResizeMode.Interactive
    for col in range(header.count()):
        header.setSectionResizeMode(col, stretchy if col == stretch else free)
    state = {"pending": False, "grow_only": True}

    def fit() -> None:
        state["pending"] = False
        for col in range(header.count()):
            if col == stretch:
                continue
            content = max(view.sizeHintForColumn(col), header.sectionSizeHint(col))
            want = min(MAX_FIT, content + PADDING)
            if not state["grow_only"] or want > header.sectionSize(col):
                header.resizeSection(col, want)
        state["grow_only"] = True

    def later(grow_only: bool) -> None:
        if not isValid(header):
            return  # the model reports its own teardown after the view is gone
        state["grow_only"] = state["grow_only"] and grow_only
        if not state["pending"]:
            state["pending"] = True
            QTimer.singleShot(0, header, fit)  # once, after the load; dropped with the view

    view.viewport().installEventFilter(_ElidedTips(view))
    model = view.model()
    model.rowsInserted.connect(lambda *_: later(False))
    model.modelReset.connect(lambda *_: later(False))
    model.dataChanged.connect(lambda *_: later(True))
    later(False)  # the header labels alone


def swatch(colour: str) -> QPixmap:
    pixmap = QPixmap(12, 12)
    pixmap.fill(QColor(colour))
    return pixmap


def confirm(parent, title: str, text: str, details: str = "") -> bool:
    """Yes/No question; No is the default so Enter never destroys anything."""
    box = QMessageBox(QMessageBox.Icon.Warning, title, text, YES | NO, parent)
    box.setDefaultButton(NO)
    if details:
        box.setDetailedText(details)
    return box.exec() == YES


_SIZE_TOKEN = re.compile(r"^([<>])(\d+(?:[.,]\d+)?)([kmgt]?)b?$", re.IGNORECASE)
_UNITS = {"": 1, "k": 1 << 10, "m": 1 << 20, "g": 1 << 30, "t": 1 << 40}


def matches(query: str, text: str, size: float | None = None) -> bool:
    """Every word of `query` is in `text`; ">500mb" / "<2g" compare with `size` instead."""
    text = text.lower()
    for token in query.lower().split():
        size_test = _SIZE_TOKEN.match(token)
        if size_test and size is not None:
            limit = float(size_test[2].replace(",", ".")) * _UNITS[size_test[3]]
            if (size <= limit) if size_test[1] == ">" else (size >= limit):
                return False
        elif token not in text:
            return False
    return True


def with_filter(table: QTableWidget, size_col: int | None = None,
                on_query=None) -> QWidget:
    """`table` under a filter box. Rows are hidden as the user types, or, with `on_query`,
    the owner rebuilds the table itself (to search more rows than it shows)."""
    box = QLineEdit()
    box.setPlaceholderText(tr("ui.filter"))
    box.setClearButtonEnabled(True)

    def apply() -> None:
        query = box.text()
        for row in range(table.rowCount()):
            cells = [table.item(row, c) for c in range(table.columnCount())]
            text = " ".join(c.text() for c in cells if c)
            cell = cells[size_col] if size_col is not None else None
            table.setRowHidden(row, not matches(query, text, getattr(cell, "value", None)))

    pending = [False]

    def later(*_args) -> None:  # once, after a whole reload
        if isValid(table) and not pending[0]:
            pending[0] = True
            QTimer.singleShot(0, table, lambda: (pending.__setitem__(0, False), apply()))

    if on_query:
        box.textChanged.connect(on_query)
    else:
        box.textChanged.connect(apply)
        table.model().rowsInserted.connect(later)
    holder = QWidget()
    layout = QVBoxLayout(holder)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(box)
    layout.addWidget(table, 1)
    return holder
