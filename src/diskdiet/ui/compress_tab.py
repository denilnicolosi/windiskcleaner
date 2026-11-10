"""Compress tab: transparent NTFS compression of folders that are read, not written."""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from diskdiet import actions, compress
from diskdiet.strings import fmt_size, tr
from diskdiet.ui.widgets import RIGHT, ROLE, SortItem, confirm, make_table


class CompressTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        hint = QLabel(tr("cmp.hint"))
        hint.setWordWrap(True)
        self.table = make_table([tr("col.path"), tr("col.size"), tr("col.on_disk"),
                                 tr("col.estimate")])
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.algorithm = QComboBox()
        for name in compress.ALGORITHMS:
            self.algorithm.addItem(tr(f"cmp.algo.{name}"), name)
        self.algorithm.setCurrentIndex(compress.ALGORITHMS.index(compress.DEFAULT))
        add = QPushButton(tr("cmp.add"))
        add.clicked.connect(self.add_folder)
        self.estimate = QPushButton(tr("cmp.estimate"))
        self.estimate.clicked.connect(self.estimate_selected)
        self.compress = QPushButton(tr("cmp.compress"))
        self.compress.clicked.connect(self.compress_selected)
        self.uncompress = QPushButton(tr("cmp.uncompress"))
        self.uncompress.clicked.connect(self.uncompress_selected)
        buttons = QHBoxLayout()
        buttons.addWidget(QLabel(tr("cmp.algo")))
        buttons.addWidget(self.algorithm)
        for button in (add, self.estimate, self.compress, self.uncompress):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        self.selection_changed()

    def load(self, result) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        for path, size in compress.candidates(result, self.win.settings["exclude"]):
            self._row(path, size)
        self.table.setSortingEnabled(True)
        self.selection_changed()

    def _row(self, path: str, size: int | None) -> int:
        row = self.table.rowCount()
        self.table.insertRow(row)
        first = QTableWidgetItem(path)
        first.setData(ROLE, path)
        self.table.setItem(row, 0, first)
        self._cell(row, 1, size)
        self._cell(row, 2, None)
        self.table.setItem(row, 3, QTableWidgetItem(""))
        return row

    def _cell(self, row: int, col: int, size: int | None) -> None:
        cell = SortItem(fmt_size(size) if size is not None else "", size or 0)
        cell.setTextAlignment(RIGHT)
        self.table.setItem(row, col, cell)

    def add(self, path: str) -> None:
        """From the Overview's right-click menu: list the folder and select it."""
        path = os.path.normpath(path)
        self.table.setSortingEnabled(False)
        if not self._find(path):
            self._row(path, None)
        self.table.setSortingEnabled(True)
        self.table.selectRow(self._find(path).row())
        self.win.tabs.setCurrentWidget(self)

    def _find(self, path: str):
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(ROLE) == os.path.normpath(path):
                return self.table.item(row, 0)
        return None

    def add_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("cmp.add"))
        if folder:
            self.add(folder)

    def selected(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(ROLE) if rows else None

    def selection_changed(self) -> None:
        chosen = bool(self.selected())
        for button in (self.estimate, self.compress, self.uncompress):
            button.setEnabled(chosen)

    def _update(self, path: str, logical: int, used: int, ratio: float | None) -> None:
        item = self._find(path)
        if not item:
            return
        self.table.setSortingEnabled(False)
        row = item.row()
        self._cell(row, 1, logical)
        self._cell(row, 2, used)
        if ratio is not None:
            saving = max(0, used - int(logical * ratio))
            self.table.setItem(row, 3, QTableWidgetItem(
                tr("cmp.estimated", size=fmt_size(saving), pct=1 - ratio)))
        self.table.setSortingEnabled(True)

    def estimate_selected(self) -> None:
        path = self.selected()
        if not path:
            return

        def job(_progress, _cancelled):
            logical, used, _files = compress.on_disk(path)
            return logical, used, compress.estimate(path)

        self.win.run(job, lambda out: self._update(path, *out))

    def compress_selected(self) -> None:
        path, algorithm = self.selected(), self.algorithm.currentData()
        if not path or not confirm(self, tr("cmp.compress"),
                                   tr("cmp.confirm", path=path, algo=algorithm)):
            return

        def job(_progress, _cancelled):
            report = actions.compress(path, algorithm, source="compress")
            return report, compress.on_disk(path)

        def done(out):
            report, (logical, used, _files) = out
            self._update(path, logical, used, None)
            self.win.session.merge(report)
            self.win.journal_tab.reload()
            text = tr("cmp.done", size=fmt_size(report.compressed))
            if report.skipped:
                text += "\n\n" + "\n".join(f"{p} — {why}" for p, why in report.skipped)
            QMessageBox.information(self, tr("cmp.compress"), text)

        self.win.run(job, done)

    def uncompress_selected(self) -> None:
        path = self.selected()
        if not path or not confirm(self, tr("cmp.uncompress"), tr("cmp.un_confirm", path=path)):
            return

        def job(_progress, _cancelled):
            grown = actions.uncompress(path)
            return grown, compress.on_disk(path)

        def done(out):
            grown, (logical, used, _files) = out
            self._update(path, logical, used, None)
            QMessageBox.information(self, tr("cmp.uncompress"),
                                    tr("cmp.undone", size=fmt_size(grown)))

        self.win.run(job, done)

