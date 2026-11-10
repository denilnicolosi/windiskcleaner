"""The window. Thin: all decisions are made in the Qt-free modules."""

from __future__ import annotations

import json
import os
import sys
import time

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from diskdiet import (
    __version__,
    actions,
    advisor,
    history,
    report,
    rules,
    settings,
    strings,
    system,
    updates,
)
from diskdiet.log import logger
from diskdiet.log import setup as setup_log
from diskdiet.scanner import scan
from diskdiet.strings import fmt_size, tr
from diskdiet.ui.icon import app_icon
from diskdiet.ui.more_tabs import CompressTab, GrowthTab, TypesTab
from diskdiet.ui.settings_dialog import SettingsDialog
from diskdiet.ui.tabs import (
    Duplicates,
    FileTable,
    JournalTab,
    Overview,
    ProgramsTab,
    RecPanel,
    SystemTab,
)
from diskdiet.ui.widgets import MAX_ROWS, Worker, confirm

_WINDOWS: list[QMainWindow] = []  # keeps windows alive across a language change


def apply_theme(theme: str) -> None:
    scheme = {"light": Qt.ColorScheme.Light, "dark": Qt.ColorScheme.Dark}.get(
        theme, Qt.ColorScheme.Unknown
    )
    QGuiApplication.styleHints().setColorScheme(scheme)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.settings = settings.load()
        self.admin = system.is_admin()
        suffix = f" ({tr('ui.admin')})" if self.admin else ""
        self.setWindowTitle(f"DiskDiet {__version__}{suffix}")
        self.setWindowIcon(app_icon())
        self.resize(1180, 760)
        self.result = self.programs = self.recs = self.release = None
        self.session = actions.Report()  # everything removed since the program started
        self.skip_summary = False
        self.workers: list[Worker] = []
        self.side_workers: list[Worker] = []  # update check/download: do not block scanning

        self.drive = QComboBox()
        self.volumes = system.volumes()
        for v in self.volumes:
            self.drive.addItem(f"{v.root}  ({fmt_size(v.free)} / {fmt_size(v.total)})", v.root)
        self.scan_button = QPushButton(tr("ui.scan"))
        self.scan_button.clicked.connect(lambda: self.start_scan(self.drive.currentData()))
        self.folder_button = QPushButton(tr("ui.folder"))
        self.folder_button.clicked.connect(self.choose_folder)
        self.cancel_button = QPushButton(tr("ui.cancel"))
        self.cancel_button.clicked.connect(self.cancel)
        self.cancel_button.setEnabled(False)
        self.status = QLabel(tr("ui.ready"))
        self.admin_button = QPushButton("🛡 " + tr("ui.run_admin"))
        self.admin_button.setToolTip(tr("ui.run_admin_tip"))
        self.admin_button.clicked.connect(self.relaunch_admin)
        self.admin_button.setVisible(not self.admin)
        bar = QHBoxLayout()
        for widget in (self.drive, self.scan_button, self.folder_button, self.cancel_button):
            bar.addWidget(widget)
        bar.addWidget(self.status, 1)
        bar.addWidget(self.admin_button)

        self.banner = QFrame()
        self.banner.setFrameShape(QFrame.Shape.StyledPanel)
        self.banner_text = QLabel()
        notes = QPushButton(tr("upd.notes"))
        notes.clicked.connect(self.show_notes)
        self.install_button = QPushButton()
        self.install_button.clicked.connect(self.install_update)
        dismiss = QPushButton("✕")
        dismiss.setFixedWidth(30)
        dismiss.clicked.connect(self.banner.hide)
        banner_row = QHBoxLayout(self.banner)
        banner_row.addWidget(self.banner_text, 1)
        for button in (notes, self.install_button, dismiss):
            banner_row.addWidget(button)
        self.banner.hide()

        self.overview = Overview(self)
        self.advice = RecPanel(self, None)
        self.big = FileTable(self)
        self.old = FileTable(self)
        self.program_tab = ProgramsTab(self)
        self.system_tab = SystemTab(self)
        self.archive = RecPanel(self, {"archive"})
        self.archive_hint = QLabel()
        self.dups = Duplicates(self)
        self.compress_tab = CompressTab(self)
        self.growth_tab = GrowthTab(self)
        self.types_tab = TypesTab(self)
        self.journal_tab = JournalTab(self)

        archive = QWidget()
        archive_layout = QVBoxLayout(archive)
        archive_layout.addWidget(self.archive_hint)
        archive_layout.addWidget(self.archive, 1)

        self.tabs = QTabWidget()
        for name, widget in (
            ("overview", self.overview), ("growth", self.growth_tab), ("advice", self.advice),
            ("big", self.big.holder), ("types", self.types_tab),
            ("old", self.old.holder), ("programs", self.program_tab), ("system", self.system_tab),
            ("archive", archive), ("compress", self.compress_tab), ("dups", self.dups),
            ("log", self.journal_tab),
        ):
            self.tabs.addTab(widget, tr(f"tab.{name}"))

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(bar)
        layout.addWidget(self.banner)
        layout.addWidget(self.tabs, 1)
        self.setCentralWidget(central)

        menu = self.menuBar().addMenu(tr("ui.file"))
        menu.addAction(tr("ui.export_json"), lambda: self.export("json"))
        menu.addAction(tr("ui.export_html"), lambda: self.export("html"))
        self.menuBar().addAction(tr("ui.settings"), self.open_settings)

        # bottom bar: what is being done right now, and how far along it is
        self.activity = QLabel()
        self.progress_bar = QProgressBar()
        self.progress_bar.setFixedWidth(320)
        self.progress_bar.hide()
        self.statusBar().addWidget(self.activity, 1)
        self.statusBar().addPermanentWidget(self.progress_bar)

    # ---- background work -------------------------------------------------------------
    def run(self, fn, on_done, on_progress=None) -> None:
        worker = Worker(fn)
        self.workers.append(worker)
        worker.done.connect(on_done)
        worker.failed.connect(self.failed)
        if on_progress:
            worker.progress.connect(on_progress)
        worker.finished.connect(lambda: self.finished(worker))
        self.scan_button.setEnabled(False)
        self.folder_button.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.set_progress(0, 0)  # busy until the job reports how far it is
        worker.start()

    def finished(self, worker: Worker) -> None:
        self.workers.remove(worker)
        busy = bool(self.workers)
        self.scan_button.setEnabled(not busy)
        self.folder_button.setEnabled(not busy)
        self.cancel_button.setEnabled(busy)
        if not busy:
            self.progress_bar.hide()
            self.activity.clear()

    def set_progress(self, done: int, total: int) -> None:
        """Bottom progress bar; total <= 0 shows a busy indicator."""
        if total > 0:
            self.progress_bar.setRange(0, 1000)  # scaled: byte counts overflow the widget
            self.progress_bar.setValue(min(1000, done * 1000 // total))
        else:
            self.progress_bar.setRange(0, 0)
        self.progress_bar.show()

    def item_progress(self, pair, path) -> None:
        """Progress of a removal: pair = (items done, items in all)."""
        done, total = pair
        self.set_progress(done, total)
        self.activity.setText(tr("ui.removing", i=done + 1, n=total, path=str(path)[-90:]))

    def run_aside(self, fn, on_done, on_failed) -> None:
        worker = Worker(fn)
        self.side_workers.append(worker)
        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        worker.finished.connect(lambda: self.side_workers.remove(worker))
        worker.start()

    def cancel(self) -> None:
        for worker in self.workers:
            worker.requestInterruption()

    def failed(self, err: str) -> None:
        logger.error("operation failed: %s", err) if err else logger.info("cancelled")
        self.status.setText(tr("ui.failed", err=err) if err else tr("ui.cancelled"))

    # ---- scanning --------------------------------------------------------------------
    def choose_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("ui.folder"))
        if folder:
            self.start_scan(os.path.normpath(folder))

    def start_scan(self, root: str | None) -> None:
        if not root:
            return
        old_days, exclude = self.settings["old_days"], self.settings["exclude"]
        volume = next((v for v in self.volumes if v.root.lower() == root.lower()), None)
        used = volume.total - volume.free if volume else 0  # unknown for a plain folder
        logger.info("scan start: %s", root)

        def job(progress, cancelled):
            result = scan(
                root, watch_paths=rules.watch_paths(), watch_names=advisor.REGENERABLE,
                cancelled=cancelled,
                progress=lambda files, path, size: progress((files, size), path),
            )
            programs = system.installed_programs()
            recs = advisor.build(result, programs=programs, old_days=old_days, exclude=exclude)
            return result, programs, recs

        def on_progress(pair, path):
            files, size = pair
            self.set_progress(size, used)
            pct = f"{min(99, size * 100 // used)}% — " if used else ""
            self.activity.setText(pct + tr("ui.scanning", n=files, path=path[-80:]))

        self.run(job, self.on_scan_done, on_progress)

    def on_scan_done(self, payload) -> None:
        self.result, self.programs, self.recs = result, programs, recs = payload
        logger.info("scan done: %s, %d bytes, %d files, %.0f s, %d unreadable, %d advice items",
                    result.root.path, result.root.size, result.root.files, result.seconds,
                    result.denied, len(recs))
        root = result.root
        self.volumes = system.volumes()
        volume = next((v for v in self.volumes if v.root.lower() == root.path.lower()), None)
        self.overview.load(root, volume)
        self.advice.load(recs)
        self.system_tab.load(result, recs)
        self.archive.load(recs)
        files = sorted(result.big_files, reverse=True)
        cutoff = time.time() - self.settings["old_days"] * advisor.DAY
        self.big.load(files)
        self.old.load([f for f in files if f.mtime < cutoff])
        self.program_tab.load(programs)
        self.compress_tab.load(result)
        self.types_tab.load(result.ext_sizes)
        try:
            before = history.previous(root.path)
            self.growth_tab.load(before, history.save(result))
        except OSError as err:  # a full or read-only data folder must not spoil the scan
            logger.warning("scan history not saved: %s", err)
        best = self.archive_destination()
        free = next((v.free for v in self.volumes if v.root == best), 0)
        self.archive_hint.setText(
            tr("arch.target", drive=best, free=fmt_size(free)) if best else tr("arch.no_target")
        )
        self.status.setText(tr(
            "ui.done", size=fmt_size(root.size), files=root.files,
            secs=result.seconds, denied=result.denied,
        ))

    def archive_destination(self) -> str:
        """Fixed drive with the most free space, other than the scanned one ('' if none)."""
        scanned = self.result.root.path[0].lower() if self.result else ""
        others = [v for v in self.volumes if v.fixed and v.root[0].lower() != scanned]
        best = max(others, key=lambda v: v.free, default=None)
        return best.root if best else ""

    # ---- results ---------------------------------------------------------------------
    def show_report(self, outcome: actions.Report) -> None:
        self.session.merge(outcome)
        self.journal_tab.reload()
        lines = [tr("rec.result", n=outcome.deleted, size=fmt_size(outcome.freed),
                    skipped=len(outcome.skipped))]
        if outcome.trashed:
            lines.append(tr("rec.result_bin", size=fmt_size(outcome.trashed)))
        box = QMessageBox(
            QMessageBox.Icon.Information, tr("rec.confirm_title"), "\n\n".join(lines),
            QMessageBox.StandardButton.Ok, self,
        )
        if outcome.skipped:
            box.setDetailedText("\n".join(f"{p} — {why}" for p, why in outcome.skipped[:MAX_ROWS]))
        box.exec()

    def empty_bin(self) -> None:
        size = actions.recycle_bin_size()
        if confirm(self, tr("bin.empty"), tr("bin.empty_confirm", size=fmt_size(size))):
            actions.empty_recycle_bin()
            self.journal_tab.reload()

    def export(self, kind: str) -> None:
        if not self.result:
            QMessageBox.information(self, "DiskDiet", tr("ui.no_scan"))
            return
        path, _ = QFileDialog.getSaveFileName(self, "DiskDiet", f"diskdiet-report.{kind}")
        if not path:
            return
        data = report.to_dict(self.result, self.recs, self.programs)
        text = json.dumps(data, indent=2) if kind == "json" else report.to_html(data)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)

    # ---- settings --------------------------------------------------------------------
    def open_settings(self) -> None:
        before = dict(self.settings)
        if not SettingsDialog(self).exec():
            return
        self.settings = settings.load()
        apply_theme(self.settings["theme"])
        changed = ("language", "exclude", "old_days")
        if any(self.settings[k] != before[k] for k in changed):
            self.reopen()  # rebuilds the advice with the new values

    def add_exclusion(self, path: str) -> None:
        values = settings.load()
        if path not in values["exclude"]:
            values["exclude"].append(path)
            settings.save(values)
            logger.info("exclusion added: %s", path)
        self.settings = values
        self.reopen()  # the advice no longer lists it

    def reopen(self) -> None:
        """Rebuild the window in the new language, keeping the scan and the session totals."""
        chosen = self.settings["language"]
        strings.LANG = chosen if chosen != "auto" else None
        fresh = MainWindow()
        fresh.session = self.session
        if self.result:
            recs = advisor.build(
                self.result, programs=self.programs, old_days=self.settings["old_days"],
                exclude=self.settings["exclude"],
            )
            fresh.on_scan_done((self.result, self.programs, recs))
        _WINDOWS.append(fresh)
        fresh.show()
        self.skip_summary = True
        self.close()

    def relaunch_admin(self) -> None:
        if actions.relaunch_elevated():
            self.close()

    # ---- updates ---------------------------------------------------------------------
    def check_updates(self, report_to=None) -> None:
        """Look for a newer release. `report_to(text)` gets the outcome of a manual check;
        an automatic check stays silent unless there is something new."""

        def found(release):
            self.release = release
            newer = release is not None and updates.is_newer(release.version)
            if newer:
                self.banner_text.setText(tr("upd.available", version=release.version))
                self.install_button.setText(
                    tr("upd.install") if updates.can_self_update() and release.exe_url
                    else tr("upd.open_page")
                )
                self.banner.show()
            if report_to:
                report_to(
                    tr("upd.available", version=release.version) if newer
                    else tr("upd.none") if release is None else tr("upd.current")
                )

        def failed(err):
            logger.warning("update check failed: %s", err)
            if report_to:
                report_to(tr("upd.failed", err=err))

        self.run_aside(lambda _p, _c: updates.latest(), found, failed)

    def show_notes(self) -> None:
        if self.release:
            QMessageBox.information(
                self, f"DiskDiet {self.release.version}", self.release.notes or "—"
            )

    def install_update(self) -> None:
        release = self.release
        if not release:
            return
        if not (updates.can_self_update() and release.exe_url and release.sha_url):
            QDesktopServices.openUrl(QUrl(release.page))
            return
        if not confirm(self, "DiskDiet", tr("upd.confirm", version=release.version)):
            return
        target = os.path.join(os.path.dirname(sys.executable), "DiskDiet.new.exe")
        self.banner_text.setText(tr("upd.downloading"))
        self.install_button.setEnabled(False)

        def downloaded(path):
            try:
                updates.swap(path)
            except OSError as err:
                failed(str(err))
                return
            self.skip_summary = True
            self.close()

        def failed(err):
            self.install_button.setEnabled(True)
            self.banner_text.setText(tr("upd.failed", err=err))

        self.run_aside(lambda _p, _c: updates.download(release, target), downloaded, failed)

    # ---- closing ---------------------------------------------------------------------
    def closeEvent(self, event) -> None:
        self.cancel()
        for worker in [*self.workers, *self.side_workers]:
            worker.wait(5000)
        if self.session.deleted and not self.skip_summary:
            self.closing_summary()
        event.accept()

    def closing_summary(self) -> None:
        s = self.session
        lines = [tr("close.total", n=s.deleted, size=fmt_size(s.freed))]
        if s.trashed:
            lines.append(tr("close.trashed", size=fmt_size(s.trashed)))
        if s.permanent:
            lines.append(tr("close.permanent", size=fmt_size(s.permanent)))
        if s.moved:
            lines.append(tr("close.moved", size=fmt_size(s.moved)))
        box = QMessageBox(QMessageBox.Icon.Information, "DiskDiet", "\n\n".join(lines),
                          QMessageBox.StandardButton.NoButton, self)
        role = QMessageBox.ButtonRole
        empty = open_bin = None
        if s.trashed:
            bin_size = fmt_size(actions.recycle_bin_size())
            empty = box.addButton(tr("bin.empty_now", size=bin_size), role.ActionRole)
            open_bin = box.addButton(tr("bin.open"), role.ActionRole)
        box.addButton(tr("ui.close"), role.AcceptRole)
        box.exec()
        if empty is not None and box.clickedButton() is empty:
            self.empty_bin()
        elif open_bin is not None and box.clickedButton() is open_bin:
            actions.launch("shell:RecycleBinFolder")


def run() -> int:
    app = QApplication(sys.argv)
    app.setWindowIcon(app_icon())
    setup_log()
    logger.info("start: DiskDiet %s, admin=%s, packaged=%s", __version__, system.is_admin(),
                updates.can_self_update())
    values = settings.load()
    if values["language"] != "auto":
        strings.LANG = values["language"]
    apply_theme(values["theme"])
    if updates.can_self_update():
        updates.cleanup()
    window = MainWindow()
    _WINDOWS.append(window)
    window.show()
    if values["check_updates"]:
        window.check_updates()
    code = app.exec()
    logger.info("exit")
    return code
