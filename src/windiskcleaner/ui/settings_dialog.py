"""Settings popup: preferences on one tab, version / credits / updates on the other."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from windiskcleaner import __version__, actions, settings, updates, winapp2
from windiskcleaner.log import logger
from windiskcleaner.strings import tr
from windiskcleaner.ui.icon import pie_pixmap

REPO_URL = f"https://github.com/{updates.REPO}"


def combo(options: list[tuple[str, str]], current: str) -> QComboBox:
    box = QComboBox()
    for value, label in options:
        box.addItem(label, value)
    box.setCurrentIndex(max(0, box.findData(current)))
    return box


class SettingsDialog(QDialog):
    def __init__(self, win):
        super().__init__(win)
        self.win = win
        self.setWindowTitle(tr("ui.settings"))
        self.resize(460, 340)
        values = win.settings

        self.theme = combo([("system", tr("set.theme.system")), ("light", tr("set.theme.light")),
                            ("dark", tr("set.theme.dark"))], values["theme"])
        self.language = combo([("auto", tr("set.lang.auto")), ("en", "English"),
                               ("it", "Italiano")], values["language"])
        self.old_days = QSpinBox()
        self.old_days.setRange(30, 3650)
        self.old_days.setSingleStep(30)
        self.old_days.setValue(values["old_days"])
        self.dup_min = QSpinBox()
        self.dup_min.setRange(1, 10240)
        self.dup_min.setSuffix(" MB")
        self.dup_min.setValue(values["dup_min_mb"])
        self.check_updates = QCheckBox(tr("set.check_updates"))
        self.check_updates.setChecked(values["check_updates"])
        general = QWidget()
        form = QFormLayout(general)
        form.addRow(tr("set.theme"), self.theme)
        form.addRow(tr("set.language"), self.language)
        form.addRow(tr("set.old_days"), self.old_days)
        form.addRow(tr("set.dup_min"), self.dup_min)
        form.addRow(self.check_updates)
        privacy = QLabel(tr("set.privacy"))
        privacy.setWordWrap(True)
        form.addRow(privacy)

        exclusions = QWidget()
        ex_layout = QVBoxLayout(exclusions)
        hint = QLabel(tr("set.exclude_hint"))
        hint.setWordWrap(True)
        self.exclude = QListWidget()
        self.exclude.addItems(values["exclude"])
        add_folder = QPushButton(tr("set.exclude_folder"))
        add_folder.clicked.connect(self.add_folder)
        add_file = QPushButton(tr("set.exclude_file"))
        add_file.clicked.connect(self.add_file)
        remove = QPushButton(tr("set.exclude_remove"))
        remove.clicked.connect(lambda: [self.exclude.takeItem(self.exclude.row(i))
                                        for i in self.exclude.selectedItems()])
        row = QHBoxLayout()
        for button in (add_folder, add_file, remove):
            row.addWidget(button)
        row.addStretch(1)
        ex_layout.addWidget(hint)
        ex_layout.addWidget(self.exclude)
        ex_layout.addLayout(row)
        self.community = QLabel()
        self.community.setWordWrap(True)
        load_rules = QPushButton(tr("set.winapp2_import"))
        load_rules.clicked.connect(self.import_winapp2)
        drop_rules = QPushButton(tr("set.winapp2_remove"))
        drop_rules.clicked.connect(self.remove_winapp2)
        rules_row = QHBoxLayout()
        rules_row.addWidget(load_rules)
        rules_row.addWidget(drop_rules)
        rules_row.addStretch(1)
        ex_layout.addWidget(self.community)
        ex_layout.addLayout(rules_row)
        self.show_winapp2()

        about = QWidget()
        about_layout = QVBoxLayout(about)
        logo = QLabel()
        logo.setPixmap(pie_pixmap(72))
        title = QLabel(f"<b>WinDiskCleaner {__version__}</b>")
        credits_ = QLabel(tr("about.credits", repo=REPO_URL))
        credits_.setWordWrap(True)
        credits_.setTextFormat(Qt.TextFormat.RichText)
        credits_.setOpenExternalLinks(True)
        self.update_status = QLabel()
        self.update_status.setWordWrap(True)
        check = QPushButton(tr("about.check"))
        check.clicked.connect(self.check_now)
        data = QPushButton(tr("about.open_data"))
        data.clicked.connect(self.open_data)
        for widget in (logo, title, credits_, check, self.update_status, data):
            about_layout.addWidget(widget, 0, Qt.AlignmentFlag.AlignLeft)
        about_layout.addStretch(1)

        tabs = QTabWidget()
        tabs.addTab(general, tr("set.general"))
        tabs.addTab(exclusions, tr("set.exclusions"))
        tabs.addTab(about, tr("set.about"))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)
        layout.addWidget(buttons)

    def check_now(self) -> None:
        self.update_status.setText(tr("upd.checking"))
        self.win.check_updates(report_to=self.update_status.setText)

    def _add_exclusion(self, path: str) -> None:
        path = os.path.normpath(path) if path else ""
        if path and not self.exclude.findItems(path, Qt.MatchFlag.MatchFixedString):
            self.exclude.addItem(path)

    def add_folder(self) -> None:
        self._add_exclusion(QFileDialog.getExistingDirectory(self, tr("set.exclude_folder")))

    def add_file(self) -> None:
        self._add_exclusion(QFileDialog.getOpenFileName(self, tr("set.exclude_file"))[0])

    def show_winapp2(self) -> None:
        try:
            with open(winapp2.path(), encoding="utf-8", errors="replace") as f:
                count = len(winapp2.parse(f.read()))
        except OSError:
            count = 0
        self.community.setText(tr("set.winapp2", n=count) if count else tr("set.winapp2_none"))

    def import_winapp2(self) -> None:
        source, _ = QFileDialog.getOpenFileName(self, tr("set.winapp2_import"), "",
                                                "winapp2.ini (*.ini)")
        if not source:
            return
        try:
            with open(source, encoding="utf-8", errors="replace") as f:
                text = f.read()
        except OSError as err:
            self.community.setText(tr("ui.failed", err=err))
            return
        if not winapp2.parse(text):
            self.community.setText(tr("set.winapp2_empty"))
            return
        os.makedirs(settings.data_dir(), exist_ok=True)
        with open(winapp2.path(), "w", encoding="utf-8") as f:
            f.write(text)
        logger.info("winapp2.ini imported from %s", source)
        self.show_winapp2()

    def remove_winapp2(self) -> None:
        try:
            actions.remove_own_file(winapp2.FILE_NAME)  # WinDiskCleaner's copy, not the user's
        except OSError as err:
            self.community.setText(tr("ui.failed", err=err))
            return
        self.show_winapp2()

    def open_data(self) -> None:
        os.makedirs(settings.data_dir(), exist_ok=True)
        actions.open_in_explorer(settings.data_dir())

    def values(self) -> dict:
        return {
            "theme": self.theme.currentData(),
            "language": self.language.currentData(),
            "old_days": self.old_days.value(),
            "dup_min_mb": self.dup_min.value(),
            "check_updates": self.check_updates.isChecked(),
            "exclude": [self.exclude.item(i).text() for i in range(self.exclude.count())],
        }

    def accept(self) -> None:
        settings.save(self.values())
        super().accept()
