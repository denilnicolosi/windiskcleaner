"""The tabs of the main window. Thin: decisions are made in the Qt-free modules."""

from __future__ import annotations

import os
import subprocess
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from diskdiet import actions, journal, system, vhdx
from diskdiet.duplicates import find_duplicates
from diskdiet.log import logger
from diskdiet.rules import RESTORE_POINT, Action, Safety
from diskdiet.strings import fmt_size, pick, tr
from diskdiet.ui.pie import PieWidget
from diskdiet.ui.review_dialog import ReviewDialog
from diskdiet.ui.terminal import Terminal, decode
from diskdiet.ui.widgets import (
    GREY_FREE,
    GREY_OTHER,
    GREY_UNSCANNED,
    MAX_ROWS,
    NO,
    PALETTE,
    RIGHT,
    ROLE,
    YES,
    SortItem,
    confirm,
    make_table,
    swatch,
)

CHECKED, UNCHECKED = Qt.CheckState.Checked, Qt.CheckState.Unchecked


class Overview(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.stack = []
        self.volume = None
        self.up = QPushButton(tr("ui.up"))
        self.up.clicked.connect(self.go_up)
        self.crumb = QLabel()
        self.crumb.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.pie = PieWidget()
        self.pie.clicked.connect(lambda i: self.enter(self.slice_nodes[i]))
        self.pie.context.connect(lambda i, pos: self.menu(self.slice_nodes[i], pos))
        self.table = make_table(
            [tr("col.name"), tr("col.size"), tr("col.share"), tr("col.files")]
        )
        header = self.table.horizontalHeader()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.table.cellDoubleClicked.connect(lambda row, _c: self.enter(self.row_nodes[row]))
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.table_menu)
        top = QHBoxLayout()
        top.addWidget(self.up)
        top.addWidget(self.crumb, 1)
        split = QSplitter()
        split.addWidget(self.pie)
        split.addWidget(self.table)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 1)
        split.setSizes([640, 520])
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(split, 1)
        self.slice_nodes, self.row_nodes = [], []

    def load(self, root, volume) -> None:
        self.stack, self.volume = [root], volume
        self.refresh()

    def enter(self, node) -> None:
        if node is not None and node.children:
            self.stack.append(node)
            self.refresh()

    def go_up(self) -> None:
        if len(self.stack) > 1:
            self.stack.pop()
            self.refresh()

    def refresh(self) -> None:
        node = self.stack[-1]
        self.crumb.setText(node.path)
        self.up.setEnabled(len(self.stack) > 1)
        rows = [(k.name, k.size, k.files, k, "") for k in node.children if k.size > 0]
        own = node.size - sum(k.size for k in node.children)
        if own > 0:
            rows.append((tr("ui.files_here"), own, None, None, ""))
        rows.sort(key=lambda r: -r[1])
        top, rest = rows[:10], rows[10:]
        shown = [(*r[:4], PALETTE[i]) for i, r in enumerate(top)]
        if rest:
            shown.append((tr("ui.other"), sum(r[1] for r in rest), None, None, GREY_OTHER))
        if len(self.stack) == 1 and self.volume:
            unscanned = self.volume.total - self.volume.free - node.size
            if unscanned > 0:
                shown.append((tr("ui.unscanned"), unscanned, None, None, GREY_UNSCANNED))
            shown.append((tr("ui.free"), self.volume.free, None, None, GREY_FREE))
        self.pie.set_slices([(r[0], r[1], r[4]) for r in shown])
        self.slice_nodes = [r[3] for r in shown]
        # The table lists every child: the slices that were merged into "other" appear singly.
        listed = [r for r in shown if r[4] != GREY_OTHER] + rest
        listed.sort(key=lambda r: -r[1])
        total = sum(r[1] for r in listed) or 1
        self.row_nodes = [r[3] for r in listed]
        self.table.setRowCount(len(listed))
        for i, (name, size, files, _node, colour) in enumerate(listed):
            first = QTableWidgetItem(name)
            if colour:
                first.setIcon(swatch(colour))
            cells = [first, QTableWidgetItem(fmt_size(size)),
                     QTableWidgetItem(f"{size / total:.1%}"),
                     QTableWidgetItem("" if files is None else f"{files:,}")]
            for col, cell in enumerate(cells):
                if col:
                    cell.setTextAlignment(RIGHT)
                self.table.setItem(i, col, cell)

    # ---- right click -----------------------------------------------------------------
    def table_menu(self, pos) -> None:
        row = self.table.rowAt(pos.y())
        if row >= 0:
            self.menu(self.row_nodes[row], self.table.viewport().mapToGlobal(pos))

    def menu(self, node, global_pos) -> None:
        if node is None:  # free space, "other", loose files: not one folder
            return
        menu = QMenu(self)
        menu.addAction(tr("file.open"), lambda: actions.open_in_explorer(node.path))
        delete = menu.addAction(tr("file.trash"), lambda: self.delete(node))
        if actions.is_protected(node.path):
            delete.setEnabled(False)
            delete.setText(tr("file.protected"))
        menu.exec(global_pos)

    def delete(self, node) -> None:
        text = tr("file.trash_confirm", path=node.path, size=fmt_size(node.size))
        if not confirm(self, tr("rec.confirm_title"), text):
            return
        parent = self.stack[-1]

        def job(_progress, _cancelled):
            return actions.delete([node.path], [os.path.dirname(node.path)], source="overview")

        def finished(outcome):
            if outcome.deleted and node in parent.children:
                parent.children.remove(node)
                for ancestor in self.stack[: self.stack.index(parent) + 1]:
                    ancestor.size -= node.size
                    ancestor.files -= node.files
                self.refresh()
            self.win.show_report(outcome)

        self.win.run(job, finished)


class RecPanel(QWidget):
    """Recommendations of the given categories (None = all the others)."""

    SPECIAL = {"system", "archive"}

    def __init__(self, win, categories: set[str] | None):
        super().__init__()
        self.win, self.categories = win, categories
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(
            [tr("col.name"), tr("col.size"), tr("col.safety"), tr("col.action")]
        )
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        self.tree.currentItemChanged.connect(lambda *_: self.show_detail())
        self.tree.itemDoubleClicked.connect(lambda *_: self.review_button.click())
        self.why = QLabel()
        self.why.setWordWrap(True)
        self.why.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.paths = QPlainTextEdit()
        self.paths.setReadOnly(True)
        self.paths.setMaximumHeight(90)
        self.clean = QPushButton(tr("rec.clean"))
        self.clean.clicked.connect(self.clean_checked)
        self.clean.setVisible(categories is None)
        self.review_button = QPushButton(tr("rec.review"))
        self.review_button.clicked.connect(self.review)
        self.open = QPushButton(tr("rec.open"))
        self.open.clicked.connect(lambda: actions.open_in_explorer(self.current().paths[0]))
        self.tool = QPushButton(tr("rec.tool"))
        self.tool.clicked.connect(self.open_tool)
        buttons = QHBoxLayout()
        for button in (self.clean, self.review_button, self.open, self.tool):
            buttons.addWidget(button)
        buttons.addStretch(1)
        self.commands = QHBoxLayout()  # one button per command of the selected item
        layout = QVBoxLayout(self)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.why)
        layout.addWidget(self.paths)
        layout.addLayout(self.commands)
        layout.addLayout(buttons)
        self.show_detail()

    def load(self, recs) -> None:
        self.tree.clear()
        groups: dict[str, QTreeWidgetItem] = {}
        totals: dict[str, int] = {}
        for rec in recs:
            wanted = (
                rec.category in self.categories if self.categories
                else rec.category not in self.SPECIAL
            )
            if not wanted:
                continue
            if rec.category not in groups:
                groups[rec.category] = QTreeWidgetItem(self.tree, [tr(f"cat.{rec.category}")])
                groups[rec.category].setExpanded(True)
            item = QTreeWidgetItem(groups[rec.category], [
                rec.title, fmt_size(rec.size) if rec.size else "",
                tr(f"safety.{rec.safety.value}"), tr(f"action.{rec.action.value}"),
            ])
            item.setData(0, ROLE, rec)
            if rec.action is Action.DELETE and rec.safety is Safety.SAFE:
                item.setCheckState(0, UNCHECKED)
            totals[rec.category] = totals.get(rec.category, 0) + rec.size
        for category, group in groups.items():
            group.setText(1, fmt_size(totals[category]) if totals[category] else "")
        self.show_detail()

    def current(self):
        item = self.tree.currentItem()
        return item.data(0, ROLE) if item else None

    def show_detail(self) -> None:
        rec = self.current()
        self.why.setText(rec.why if rec else "")
        self.paths.setPlainText("\n".join(rec.paths[:MAX_ROWS]) if rec else "")
        self.review_button.setEnabled(bool(rec and rec.action is Action.REVIEW))
        self.open.setEnabled(bool(rec and rec.paths))
        self.tool.setEnabled(bool(rec and rec.tool))
        while self.commands.count():
            widget = self.commands.takeAt(0).widget()
            if widget:
                widget.deleteLater()
        for cmd in rec.commands if rec else ():
            shield = "🛡 " if cmd.admin else ""
            button = QPushButton(f"▶ {shield}{pick(cmd.label)}")
            button.setToolTip(subprocess.list2cmdline(cmd.argv))
            button.clicked.connect(lambda _checked=False, c=cmd: self.run_command(c))
            self.commands.addWidget(button)
        self.commands.addStretch(1)

    # ---- commands --------------------------------------------------------------------
    def open_tool(self) -> None:
        try:
            actions.launch(self.current().tool)
        except OSError as err:
            QMessageBox.warning(self, self.current().title, tr("ui.failed", err=err))

    def run_command(self, cmd) -> None:
        title = pick(cmd.label)
        if cmd.admin and not system.is_admin():
            if confirm(self, title, tr("cmd.need_admin")):
                self.win.relaunch_admin()
            return
        values = self.ask_values(cmd, title) if cmd.ask else [""]
        if not values:
            return
        try:
            queue = [cmd.build(value) for value in values]
        except ValueError:
            QMessageBox.warning(self, title, tr("cmd.bad_value"))
            return
        if cmd.changes:
            lines = "\n".join(subprocess.list2cmdline(argv) for argv in queue)
            box = QMessageBox(QMessageBox.Icon.Warning, title, tr("cmd.confirm", line=lines),
                              YES | NO, self)
            box.setDefaultButton(NO)
            point = None
            if cmd.admin:  # it changes Windows itself: offer a restore point first
                point = QCheckBox(tr("cmd.restore_point"))
                point.setChecked(True)
                box.setCheckBox(point)
            if box.exec() != YES:
                return
            if point is not None and point.isChecked():
                queue.insert(0, RESTORE_POINT.build())
        Terminal(self, title, queue).exec()

    def ask_values(self, cmd, title: str) -> list[str]:
        """Values for the command: ticked in a list when the tool can list them, else typed."""
        options = []
        if cmd.options_from:
            try:
                listed = subprocess.run(list(cmd.options_from), capture_output=True, timeout=30,
                                        creationflags=vhdx.NO_WINDOW)
                options = cmd.options(decode(listed.stdout))
            except (OSError, subprocess.SubprocessError) as err:
                logger.warning("could not list options with %s: %s", cmd.options_from, err)
        if not options:
            value, ok = QInputDialog.getText(self, title, pick(cmd.ask))
            return [value.strip()] if ok else []
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        dialog.resize(560, 360)
        choices = QListWidget()
        for value, line in options:
            item = QListWidgetItem(line)
            item.setData(ROLE, value)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(UNCHECKED)
            choices.addItem(item)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(pick(cmd.ask)))
        layout.addWidget(choices, 1)
        layout.addWidget(buttons)
        if not dialog.exec():
            return []
        items = [choices.item(i) for i in range(choices.count())]
        return [item.data(ROLE) for item in items if item.checkState() == CHECKED]

    # ---- guided check ----------------------------------------------------------------
    def review(self) -> None:
        rec = self.current()
        if not rec or rec.action is not Action.REVIEW:
            return
        if not self.closed_first([rec]):
            return
        archive = rec.category == "archive"
        dialog = ReviewDialog(self.win, rec, archive, self.win.archive_destination())
        if not dialog.items:
            QMessageBox.information(self, rec.title, tr("rev.empty"))
            return
        dialog.exec()

    # ---- safe cleanup ----------------------------------------------------------------
    def checked(self) -> list[QTreeWidgetItem]:
        found = []
        for g in range(self.tree.topLevelItemCount()):
            group = self.tree.topLevelItem(g)
            for i in range(group.childCount()):
                item = group.child(i)
                if item.checkState(0) == CHECKED and not item.isDisabled():
                    found.append(item)
        return found

    def closed_first(self, recs) -> bool:
        """False if the user stops because a program that owns these files is still open."""
        open_now = sorted({r.process for r in recs if r.process and system.running(r.process)})
        if not open_now:
            return True
        return confirm(self, tr("rec.confirm_title"),
                       tr("rec.still_open", apps="\n".join(f"• {p}" for p in open_now)))

    def clean_checked(self) -> None:
        items = self.checked()
        if not items:
            QMessageBox.information(self, tr("rec.confirm_title"), tr("rec.none_checked"))
            return
        recs = [item.data(0, ROLE) for item in items]
        if not self.closed_first(recs):
            return
        plan = [(rec, actions.preview(rec.paths)) for rec in recs]
        how = "rec.how_permanent" if any(r.permanent for r in recs) else "rec.how_trash"
        text = tr(
            "rec.confirm",
            n=sum(len(targets) for _rec, targets in plan),
            size=fmt_size(sum(r.size for r in recs)),
            titles="\n".join(f"• {r.title}" for r in recs),
            how=tr(how),
        )
        details = "\n".join(t for _rec, targets in plan for t in targets[:MAX_ROWS])
        if not confirm(self, tr("rec.confirm_title"), text, details):
            return

        count = sum(len(targets) for _rec, targets in plan)

        def job(progress, _cancelled):
            total, done = actions.Report(), 0
            for rec, targets in plan:
                total.merge(actions.delete(
                    targets, rec.paths, permanent=rec.permanent, source=rec.id,
                    progress=lambda i, _n, path, done=done: progress((done + i, count), path),
                ))
                done += len(targets)
            return total

        def finished(total):
            for item in items:
                item.setCheckState(0, UNCHECKED)
                item.setDisabled(True)
            self.win.show_report(total)

        self.win.run(job, finished, self.win.item_progress)


class FileTable(QTableWidget):
    def __init__(self, win):
        super().__init__(0, 3)
        self.win = win
        self.setHorizontalHeaderLabels([tr("col.size"), tr("col.modified"), tr("col.path")])
        self.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.verticalHeader().setVisible(False)
        self.horizontalHeader().setStretchLastSection(True)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self.menu)

    def load(self, files) -> None:
        self.setSortingEnabled(False)
        self.setRowCount(len(files))
        for i, f in enumerate(files):
            day = datetime.fromtimestamp(f.mtime).strftime("%Y-%m-%d")
            self.setItem(i, 0, SortItem(fmt_size(f.size), f.size))
            self.setItem(i, 1, SortItem(day, f.mtime))
            self.setItem(i, 2, QTableWidgetItem(f.path))
        self.setSortingEnabled(True)

    def menu(self, pos) -> None:
        row = self.rowAt(pos.y())
        if row < 0:
            return
        path = self.item(row, 2).text()
        menu = QMenu(self)
        menu.addAction(tr("file.open"), lambda: actions.open_in_explorer(path))
        menu.addAction(tr("file.trash"), lambda: self.trash(row, path))
        menu.exec(self.viewport().mapToGlobal(pos))

    def trash(self, row: int, path: str) -> None:
        size = self.item(row, 0).text()
        text = tr("file.trash_confirm", path=path, size=size)
        if not confirm(self, tr("rec.confirm_title"), text):
            return
        outcome = actions.delete([path], [path], source="files")
        if outcome.deleted:
            self.removeRow(row)
        self.win.show_report(outcome)


class Duplicates(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.find = QPushButton(tr("dup.find"))
        self.find.clicked.connect(self.search)
        self.trash = QPushButton(tr("dup.trash"))
        self.trash.clicked.connect(self.trash_checked)
        self.status = QLabel(tr("dup.hint"))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("col.path")])
        top = QHBoxLayout()
        top.addWidget(self.find)
        top.addWidget(self.trash)
        top.addWidget(self.status, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.tree, 1)

    def search(self) -> None:
        if not self.win.result:
            QMessageBox.information(self, tr("tab.dups"), tr("ui.no_scan"))
            return
        files = self.win.result.big_files
        min_size = self.win.settings["dup_min_mb"] << 20

        def job(progress, cancelled):
            return find_duplicates(
                files, min_size=min_size, progress=progress, cancelled=cancelled
            )

        def on_progress(done, total):
            self.status.setText(tr("dup.progress", pct=done * 100 // total))
            self.win.set_progress(done, total)

        self.win.run(job, self.load, on_progress)

    def load(self, groups) -> None:
        self.tree.clear()
        for group in groups[:MAX_ROWS]:
            head = QTreeWidgetItem(self.tree, [tr(
                "dup.group", n=len(group.paths), size=fmt_size(group.size),
                wasted=fmt_size(group.wasted),
            )])
            head.setExpanded(True)
            for path in group.paths:
                child = QTreeWidgetItem(head, [path])
                child.setCheckState(0, UNCHECKED)
        self.status.setText(tr(
            "dup.summary", groups=len(groups), size=fmt_size(sum(g.wasted for g in groups)),
        ))

    def trash_checked(self) -> None:
        chosen = []
        for g in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(g)
            kids = [head.child(i) for i in range(head.childCount())]
            ticked = [k for k in kids if k.checkState(0) == CHECKED]
            if ticked and len(ticked) == len(kids):
                QMessageBox.warning(self, tr("tab.dups"), tr("dup.keep_one"))
                return
            chosen += ticked
        if not chosen:
            QMessageBox.information(self, tr("tab.dups"), tr("rec.none_checked"))
            return
        paths = [item.text(0) for item in chosen]
        size = sum(os.path.getsize(p) for p in paths if os.path.exists(p))
        text = tr("dup.confirm", n=len(paths), size=fmt_size(size))
        if not confirm(self, tr("rec.confirm_title"), text, "\n".join(paths)):
            return

        def finished(outcome):
            for item in chosen:
                item.parent().removeChild(item)
            self.win.show_report(outcome)

        def job(progress, _cancelled):
            return actions.delete(
                paths, paths, source="duplicates",
                progress=lambda i, n, path: progress((i, n), path),
            )

        self.win.run(job, finished, self.win.item_progress)


class SystemTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.recs = RecPanel(win, {"system"})
        self.disks = make_table([tr("col.size"), tr("col.kind"), tr("col.path")])
        self.disks.setMaximumHeight(110)
        self.disks.itemSelectionChanged.connect(self.selection_changed)
        self.compact = QPushButton(tr("vhdx.compact"))
        self.compact.clicked.connect(self.compact_selected)
        self.hint = QLabel(tr("vhdx.hint"))
        self.hint.setWordWrap(True)
        box = QGroupBox(tr("vhdx.title"))
        inner = QVBoxLayout(box)
        inner.addWidget(self.hint)
        inner.addWidget(self.disks)
        inner.addWidget(self.compact, 0, Qt.AlignmentFlag.AlignLeft)
        layout = QVBoxLayout(self)
        layout.addWidget(self.recs, 1)
        layout.addWidget(box)
        self.selection_changed()

    def load(self, result, recs) -> None:
        self.recs.load(recs)
        disks = vhdx.find(result.big_files)
        self.disks.setRowCount(len(disks))
        for i, f in enumerate(disks):
            k = vhdx.kind(f.path)
            self.disks.setItem(i, 0, QTableWidgetItem(fmt_size(f.size)))
            kind_item = QTableWidgetItem(tr(f"kind.{k}"))
            kind_item.setData(ROLE, k)
            self.disks.setItem(i, 1, kind_item)
            self.disks.setItem(i, 2, QTableWidgetItem(f.path))
        self.selection_changed()

    def selected(self) -> tuple[str, str] | None:
        row = self.disks.currentRow()
        if row < 0:
            return None
        return self.disks.item(row, 1).data(ROLE), self.disks.item(row, 2).text()

    def selection_changed(self) -> None:
        chosen = self.selected()
        self.compact.setEnabled(bool(chosen and chosen[0] != "other"))
        self.hint.setText(tr("vhdx.other") if chosen and chosen[0] == "other" else tr("vhdx.hint"))

    def compact_selected(self) -> None:
        kind, path = self.selected()
        if kind == "docker" and system.running("Docker Desktop.exe"):
            QMessageBox.warning(self, tr("vhdx.title"), tr("vhdx.docker_running"))
            return
        if not confirm(self, tr("vhdx.title"), tr("vhdx.confirm", path=path)):
            return
        try:
            if system.is_admin():  # already elevated: show diskpart's output in the terminal
                Terminal(self, tr("vhdx.title"), [vhdx.prepare(path)]).exec()
                return
            vhdx.compact(path)
        except (OSError, ValueError) as err:
            QMessageBox.warning(self, tr("vhdx.title"), tr("ui.failed", err=err))
            return
        QMessageBox.information(self, tr("vhdx.title"), tr("vhdx.started"))


class ProgramsTab(QWidget):
    def __init__(self, win):
        super().__init__()
        self.win = win
        self.programs = []
        self.table = make_table(
            [tr("col.name"), tr("col.size"), tr("col.publisher"), tr("col.installed")]
        )
        self.table.itemSelectionChanged.connect(
            lambda: self.uninstall.setEnabled(self.table.currentRow() >= 0)
        )
        hint = QLabel(tr("prog.hint"))
        hint.setWordWrap(True)
        self.uninstall = QPushButton(tr("prog.uninstall"))
        self.uninstall.setEnabled(False)
        self.uninstall.clicked.connect(self.uninstall_selected)
        apps = QPushButton(tr("prog.open"))
        apps.clicked.connect(lambda: actions.launch("ms-settings:appsfeatures"))
        buttons = QHBoxLayout()
        buttons.addWidget(self.uninstall)
        buttons.addWidget(apps)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)

    def load(self, programs) -> None:
        self.programs = programs
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(programs))
        for i, p in enumerate(programs):
            name = QTableWidgetItem(p.name)
            name.setData(ROLE, p)
            self.table.setItem(i, 0, name)
            self.table.setItem(i, 1, SortItem(fmt_size(p.size) if p.size else "", p.size))
            self.table.setItem(i, 2, QTableWidgetItem(p.publisher))
            self.table.setItem(i, 3, QTableWidgetItem(p.installed))
        self.table.setSortingEnabled(True)

    def uninstall_selected(self) -> None:
        row = self.table.currentRow()
        if row < 0:
            return
        program = self.table.item(row, 0).data(ROLE)
        key = "prog.confirm" if program.uninstall else "prog.confirm_settings"
        if not confirm(self, tr("prog.uninstall"), tr(key, name=program.name)):
            return
        try:
            actions.uninstall(program.uninstall)
        except OSError as err:
            # Some uninstall commands are not directly startable: Windows' own list still is.
            QMessageBox.warning(self, tr("prog.uninstall"), tr("ui.failed", err=err))
            actions.launch("ms-settings:appsfeatures")


class JournalTab(QWidget):
    """Everything DiskDiet removed or moved, with a way back."""

    def __init__(self, win):
        super().__init__()
        self.win = win
        self.table = make_table([
            tr("col.when"), tr("col.size"), tr("col.how"), tr("col.state"), tr("col.path"),
        ])
        self.table.itemSelectionChanged.connect(self.selection_changed)
        hint = QLabel(tr("log.hint"))
        hint.setWordWrap(True)
        self.restore = QPushButton(tr("log.restore"))
        self.restore.clicked.connect(self.restore_selected)
        open_bin = QPushButton(tr("bin.open"))
        open_bin.clicked.connect(lambda: actions.launch("shell:RecycleBinFolder"))
        empty = QPushButton(tr("bin.empty"))
        empty.clicked.connect(self.win.empty_bin)
        buttons = QHBoxLayout()
        for button in (self.restore, open_bin, empty):
            buttons.addWidget(button)
        buttons.addStretch(1)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table, 1)
        layout.addLayout(buttons)
        self.reload()

    def reload(self) -> None:
        entries = journal.load()[::-1]
        self.table.setSortingEnabled(False)
        self.table.setRowCount(len(entries))
        for i, e in enumerate(entries):
            when = QTableWidgetItem(e["when"].replace("T", " "))
            when.setData(ROLE, e)
            self.table.setItem(i, 0, when)
            self.table.setItem(i, 1, SortItem(fmt_size(e["size"]), e["size"]))
            self.table.setItem(i, 2, QTableWidgetItem(tr(f"log.mode.{e['mode']}")))
            self.table.setItem(i, 3, QTableWidgetItem(tr(f"log.state.{e['state']}")))
            self.table.setItem(i, 4, QTableWidgetItem(e["path"]))
        self.table.setSortingEnabled(True)
        self.selection_changed()

    def selected(self) -> dict | None:
        row = self.table.currentRow()
        return self.table.item(row, 0).data(ROLE) if row >= 0 else None

    def selection_changed(self) -> None:
        entry = self.selected()
        recoverable = entry and entry["state"] == "removed" and entry["mode"] != journal.PERMANENT
        self.restore.setEnabled(bool(recoverable))

    def restore_selected(self) -> None:
        entry = self.selected()
        if not entry:
            return
        try:
            actions.restore(entry)
        except OSError as err:
            QMessageBox.warning(self, tr("log.restore"), tr("log.restore_failed", err=err))
        else:
            QMessageBox.information(self, tr("log.restore"), tr("log.restored", path=entry["path"]))
        self.reload()
