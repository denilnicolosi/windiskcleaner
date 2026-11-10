"""Small Qt helpers shared by the window, the tabs and the dialogs."""

from __future__ import annotations

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import QMessageBox, QTableWidget, QTableWidgetItem

from diskdiet.log import logger
from diskdiet.scanner import ScanCancelled

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
