"""Compress tab (NTFS compression), What changed (since the last scan), File types, Games."""

from __future__ import annotations

import os
from datetime import datetime

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

from diskdiet import actions, advisor, compress, history
from diskdiet.strings import fmt_size, tr
from diskdiet.ui.widgets import RIGHT, ROLE, SortItem, confirm, make_table, with_filter


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



class GrowthTab(QWidget):
    """What changed since the previous scan of the same folder (history.growth)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.summary = QLabel(tr("grow.none"))
        self.summary.setWordWrap(True)
        self.table = make_table([tr("col.path"), tr("grow.before"), tr("grow.after"),
                                 tr("grow.change")])
        self.table.cellDoubleClicked.connect(
            lambda row, _c: actions.open_in_explorer(self.table.item(row, 0).text()))
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.table, 1)

    def load(self, before: dict | None, after: dict) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(0)
        if not before:
            self.summary.setText(tr("grow.none"))
            return
        delta = after["total"] - before["total"]
        self.summary.setText(tr(
            "grow.summary", when=before["when"].replace("T", " "),
            before=fmt_size(before["total"]), after=fmt_size(after["total"]),
            change=_signed(delta),
        ))
        rows = history.growth(before, after)
        self.table.setRowCount(len(rows))
        for i, (path, a, b) in enumerate(rows):
            self.table.setItem(i, 0, QTableWidgetItem(path))
            for col, value, text in ((1, a, fmt_size(a)), (2, b, fmt_size(b)),
                                     (3, b - a, _signed(b - a))):
                cell = SortItem(text, value)
                cell.setTextAlignment(RIGHT)
                self.table.setItem(i, col, cell)
        self.table.setSortingEnabled(True)


def _signed(delta: int) -> str:
    return ("+" if delta >= 0 else "−") + fmt_size(abs(delta))


class TypesTab(QWidget):
    """Space by file extension and by kind (video, images, programs…), like WizTree."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.kinds = make_table([tr("col.kind"), tr("col.size"), tr("col.share")])
        self.kinds.setMaximumHeight(260)
        self.exts = make_table([tr("col.ext"), tr("col.kind"), tr("col.size"), tr("col.share")])
        hint = QLabel(tr("types.hint"))
        hint.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.kinds)
        layout.addWidget(with_filter(self.exts, size_col=2), 1)

    def load(self, ext_sizes: dict[str, int]) -> None:
        total = sum(ext_sizes.values()) or 1
        by_kind: dict[str, int] = {}
        for ext, size in ext_sizes.items():
            kind = advisor.kind_of(ext)
            by_kind[kind] = by_kind.get(kind, 0) + size
        _fill(self.kinds, [([tr(f"kind.file.{k}")], s) for k, s in by_kind.items()], total)
        rows = [([ext or tr("types.none"), tr(f"kind.file.{advisor.kind_of(ext)}")], s)
                for ext, s in ext_sizes.items() if s]
        _fill(self.exts, rows, total)


def _fill(table, rows: list[tuple[list[str], int]], total: int) -> None:
    """Text columns, then size and share, biggest first."""
    rows.sort(key=lambda r: -r[1])
    table.setSortingEnabled(False)
    table.setRowCount(len(rows))
    for i, (texts, size) in enumerate(rows):
        for col, text in enumerate(texts):
            table.setItem(i, col, QTableWidgetItem(text))
        for col, (text, value) in enumerate(((fmt_size(size), size),
                                             (f"{size / total:.1%}", size)), len(texts)):
            cell = SortItem(text, value)
            cell.setTextAlignment(RIGHT)
            table.setItem(i, col, cell)
    table.setSortingEnabled(True)


class GamesTab(QWidget):
    """Steam and Epic games by size and last time played (games.py)."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        hint = QLabel(tr("games.hint"))
        hint.setWordWrap(True)
        self.table = make_table([tr("col.name"), tr("games.launcher"), tr("col.size"),
                                 tr("games.played"), tr("col.path")])
        self.table.itemSelectionChanged.connect(self.selection_changed)
        self.open = QPushButton(tr("rec.open"))
        self.open.clicked.connect(lambda: actions.open_in_explorer(self.selected().path))
        self.uninstall = QPushButton(tr("prog.uninstall"))
        self.uninstall.clicked.connect(self.uninstall_selected)
        self.compress = QPushButton(tr("cmp.compress"))
        self.compress.clicked.connect(lambda: self.win.compress_tab.add(self.selected().path))
        buttons = QHBoxLayout()
        for button in (self.open, self.uninstall, self.compress):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(with_filter(self.table, size_col=2), 1)
        layout.addLayout(buttons)
        self.selection_changed()

    def load(self, found) -> None:
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(found))
        for i, game in enumerate(found):
            name = QTableWidgetItem(game.name)
            name.setData(ROLE, game)
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, QTableWidgetItem(game.launcher))
            size = SortItem(fmt_size(game.size) if game.size else "", game.size)
            size.setTextAlignment(RIGHT)
            self.table.setItem(i, 2, size)
            played = (datetime.fromtimestamp(game.last_played).strftime("%Y-%m-%d")
                      if game.last_played else tr("games.never"))
            self.table.setItem(i, 3, SortItem(played, game.last_played))
            self.table.setItem(i, 4, QTableWidgetItem(game.path))
        self.table.setSortingEnabled(True)
        self.selection_changed()

    def selected(self):
        rows = self.table.selectionModel().selectedRows()
        return self.table.item(rows[0].row(), 0).data(ROLE) if rows else None

    def selection_changed(self) -> None:
        for button in (self.open, self.uninstall, self.compress):
            button.setEnabled(self.selected() is not None)

    def uninstall_selected(self) -> None:
        game = self.selected()
        if not game or not confirm(self, tr("prog.uninstall"),
                                   tr("games.confirm", name=game.name, launcher=game.launcher)):
            return
        try:
            actions.uninstall_game(game.launcher, game.app_id)
        except OSError as err:
            QMessageBox.warning(self, tr("prog.uninstall"), tr("ui.failed", err=err))
