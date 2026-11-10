"""Small Qt helpers shared by the window, the tabs and the dialogs."""

from __future__ import annotations

import re

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QLineEdit,
    QMessageBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from diskdiet.log import logger
from diskdiet.scanner import ScanCancelled
from diskdiet.strings import tr

PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f",
           "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#86bcb6"]
GREY_FREE, GREY_UNSCANNED, GREY_OTHER = "#d4d4d4", "#8c8c8c", "#b0b0b0"
ROLE = Qt.ItemDataRole.UserRole
RIGHT = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
MAX_ROWS = 200
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


def make_table(headers: list[str]) -> QTableWidget:
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
    table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.horizontalHeader().setStretchLastSection(True)
    return table


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
        if not pending[0]:
            pending[0] = True
            QTimer.singleShot(0, lambda: (pending.__setitem__(0, False), apply()))

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
