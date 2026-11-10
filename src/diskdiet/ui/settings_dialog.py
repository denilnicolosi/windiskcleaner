"""Settings popup: preferences on one tab, version / credits / updates on the other."""

from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from diskdiet import __version__, actions, settings, updates
from diskdiet.strings import tr
from diskdiet.ui.icon import pie_pixmap

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

        about = QWidget()
        about_layout = QVBoxLayout(about)
        logo = QLabel()
        logo.setPixmap(pie_pixmap(72))
        title = QLabel(f"<b>DiskDiet {__version__}</b>")
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
        }

    def accept(self) -> None:
        settings.save(self.values())
        super().accept()
