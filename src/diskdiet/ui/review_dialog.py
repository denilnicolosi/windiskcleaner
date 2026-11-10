"""Guided check: one question per item, choices collected, one confirmation at the end."""

from __future__ import annotations

import os
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from diskdiet import actions, advisor
from diskdiet.strings import fmt_size, tr

DELETE, MOVE, KEEP = "delete", "move", "keep"


class ReviewDialog(QDialog):
    def __init__(self, win, rec, allow_move: bool, destination: str = ""):
        super().__init__(win)
        self.win, self.rec, self.destination = win, rec, destination
        self.items = advisor.review_items(rec, win.result)
        self.choices: list[str] = []
        self.setWindowTitle(rec.title)
        self.resize(640, 380)

        why = QLabel(rec.why)
        why.setWordWrap(True)
        self.counter = QLabel()
        self.name = QLabel()
        self.name.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        self.detail.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.question = QLabel(rec.question)
        self.question.setStyleSheet("font-size: 14px;")
        self.question.setWordWrap(True)

        buttons = QHBoxLayout()
        options = [(tr("rev.delete"), DELETE), (tr("rev.keep"), KEEP)]
        if allow_move and destination:
            options.insert(1, (tr("rev.move", drive=destination), MOVE))
        for text, choice in options:
            button = QPushButton(text)
            button.clicked.connect(lambda _checked=False, c=choice: self.choose(c))
            buttons.addWidget(button)
        buttons.addStretch(1)
        show = QPushButton(tr("file.open"))
        show.clicked.connect(lambda: actions.open_in_explorer(self.items[len(self.choices)].path))
        self.back = QPushButton(tr("rev.back"))
        self.back.clicked.connect(self.undo)
        keep_rest = QPushButton(tr("rev.keep_rest"))
        keep_rest.clicked.connect(self.keep_rest)
        for button in (show, self.back, keep_rest):
            buttons.addWidget(button)

        ask = QWidget()
        ask_layout = QVBoxLayout(ask)
        for widget in (why, self.counter, self.name, self.detail, self.question):
            ask_layout.addWidget(widget)
        ask_layout.addStretch(1)
        ask_layout.addLayout(buttons)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.listing = QPlainTextEdit()
        self.listing.setReadOnly(True)
        self.execute = QPushButton(tr("rev.execute"))
        self.execute.clicked.connect(self.run)
        change = QPushButton(tr("rev.change_dest"))
        change.clicked.connect(self.change_destination)
        change.setVisible(allow_move)
        again = QPushButton(tr("rev.back"))
        again.clicked.connect(self.undo)
        cancel = QPushButton(tr("ui.cancel"))
        cancel.clicked.connect(self.reject)
        end_buttons = QHBoxLayout()
        end_buttons.addWidget(self.execute)
        end_buttons.addWidget(change)
        end_buttons.addStretch(1)
        end_buttons.addWidget(again)
        end_buttons.addWidget(cancel)
        end = QWidget()
        end_layout = QVBoxLayout(end)
        end_layout.addWidget(self.summary)
        end_layout.addWidget(self.listing, 1)
        end_layout.addLayout(end_buttons)

        self.pages = QStackedWidget()
        self.pages.addWidget(ask)
        self.pages.addWidget(end)
        QVBoxLayout(self).addWidget(self.pages)
        self.show_current()

    # ---- asking ----------------------------------------------------------------------
    def show_current(self) -> None:
        i = len(self.choices)
        if i >= len(self.items):
            self.show_summary()
            return
        item = self.items[i]
        self.pages.setCurrentIndex(0)
        self.back.setEnabled(i > 0)
        self.counter.setText(tr("rev.counter", i=i + 1, n=len(self.items)))
        self.name.setText(os.path.basename(item.path))
        modified = datetime.fromtimestamp(item.mtime).strftime("%Y-%m-%d")
        self.detail.setText(
            tr("rev.detail", size=fmt_size(item.size), modified=modified, path=item.path)
        )

    def choose(self, choice: str) -> None:
        self.choices.append(choice)
        self.show_current()

    def undo(self) -> None:
        if self.choices:
            self.choices.pop()
        self.show_current()

    def keep_rest(self) -> None:
        self.choices += [KEEP] * (len(self.items) - len(self.choices))
        self.show_current()

    # ---- summary and execution -------------------------------------------------------
    def chosen(self, choice: str):
        return [item for item, c in zip(self.items, self.choices, strict=True) if c == choice]

    def show_summary(self) -> None:
        self.pages.setCurrentIndex(1)
        delete, move = self.chosen(DELETE), self.chosen(MOVE)
        lines = [tr("rev.sum_delete", n=len(delete), size=fmt_size(sum(i.size for i in delete)))]
        if move:
            lines.append(tr("rev.sum_move", n=len(move), size=fmt_size(sum(i.size for i in move)),
                            dest=os.path.join(self.destination, actions.ARCHIVE_FOLDER)))
        lines.append(tr("rev.sum_keep", n=len(self.chosen(KEEP))))
        self.summary.setText("\n".join(lines))
        self.listing.setPlainText("\n".join(
            [f"{tr('rev.delete')}: {i.path}" for i in delete]
            + [f"{tr('rev.moving')}: {i.path}" for i in move]
        ))
        self.execute.setEnabled(bool(delete or move))

    def change_destination(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, tr("rev.change_dest"), self.destination)
        if folder:
            self.destination = os.path.normpath(folder)
            self.show_summary()

    def run(self) -> None:
        delete = [i.path for i in self.chosen(DELETE)]
        move = [i.path for i in self.chosen(MOVE)]
        # Catalogue folders: items must be inside them. Heuristic items: inside their own folder.
        roots = self.rec.paths if self.rec.expand else [os.path.dirname(p) for p in delete]
        rec_id, destination = self.rec.id, self.destination

        total = len(delete) + len(move)

        def job(progress, _cancelled):
            outcome = actions.delete(
                delete, roots, source=rec_id,
                progress=lambda i, _n, path: progress((i, total), path),
            )
            if move:
                outcome.merge(actions.move(
                    move, destination, source=rec_id,
                    progress=lambda i, _n, path: progress((len(delete) + i, total), path),
                ))
            return outcome

        self.win.run(job, self.win.show_report, self.win.item_progress)
        self.accept()
