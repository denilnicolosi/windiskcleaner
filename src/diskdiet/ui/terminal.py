"""Built-in terminal: runs commands from the catalogue one after another, output live."""

from __future__ import annotations

import re
import subprocess

from PySide6.QtCore import QProcess, QProcessEnvironment
from PySide6.QtGui import QFontDatabase, QTextCursor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout

from diskdiet.log import logger
from diskdiet.strings import tr

# "Go to column 1" and "erase line" are what progress bars and spinners use to redraw
# themselves: treated as a carriage return. Every other escape sequence is dropped.
_REDRAW = re.compile(r"\x1b\[\d*G|\x1b\[[012]?K")
_ESCAPES = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)|\x1b[@-_]")
_BREAKS = re.compile(r"(\r\n|\n|\r)")


def decode(data: bytes) -> str:
    """Console tools answer in UTF-8 or in the OEM code page, depending on the tool."""
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return data.decode("oem", "replace")
        except LookupError:  # not on Windows
            return data.decode("latin-1")


def plain(text: str) -> str:
    """Terminal control sequences removed; redraws become carriage returns."""
    return _ESCAPES.sub("", _REDRAW.sub("\r", text))


class Terminal(QDialog):
    def __init__(self, parent, title: str, commands: list[list[str]]):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(780, 460)
        self.commands, self.step = commands, -1
        self.failed_step = False
        self.overwrite = False  # the next text replaces the current line (after a lone \r)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.status = QLabel(tr("term.running"))
        self.stop = QPushButton(tr("term.stop"))
        self.close_button = QPushButton(tr("ui.close"))
        self.close_button.setEnabled(False)
        self.close_button.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addWidget(self.status, 1)
        row.addWidget(self.stop)
        row.addWidget(self.close_button)
        layout = QVBoxLayout(self)
        layout.addWidget(self.output, 1)
        layout.addLayout(row)

        self.process = QProcess(self)
        self.process.setProcessChannelMode(QProcess.ProcessChannelMode.MergedChannels)
        env = QProcessEnvironment.systemEnvironment()
        env.insert("NO_COLOR", "1")  # honoured by many tools; the rest is filtered by plain()
        self.process.setProcessEnvironment(env)
        self.process.readyRead.connect(
            lambda: self.write(decode(bytes(self.process.readAll().data())))
        )
        self.process.finished.connect(self.on_exit)
        self.process.errorOccurred.connect(self.on_error)
        self.stop.clicked.connect(self.process.kill)
        self.next_command()

    def next_command(self) -> None:
        self.step += 1
        argv = self.commands[self.step]
        logger.info("command start: %s", subprocess.list2cmdline(argv))
        self.write(f"> {subprocess.list2cmdline(argv)}\n")
        self.process.start(argv[0], argv[1:])

    # ---- output ----------------------------------------------------------------------
    def write(self, text: str) -> None:
        cursor = self.output.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        for part in _BREAKS.split(plain(text)):
            if part == "\r":
                self.overwrite = True
            elif part in ("\n", "\r\n"):
                cursor.insertText("\n")
                self.overwrite = False
            elif part:
                if self.overwrite:  # redraw of a progress line: replace, do not append
                    cursor.movePosition(QTextCursor.MoveOperation.StartOfBlock,
                                        QTextCursor.MoveMode.KeepAnchor)
                    cursor.removeSelectedText()
                    self.overwrite = False
                cursor.insertText(part)
        self.output.setTextCursor(cursor)
        self.output.ensureCursorVisible()

    def done_running(self, status: str) -> None:
        self.status.setText(status)
        self.stop.setEnabled(False)
        self.close_button.setEnabled(True)

    def on_exit(self, code: int, _status=None) -> None:
        tail = self.output.toPlainText().strip().splitlines()[-15:]
        logger.info("command exit %s: %s | output tail: %s", code,
                    subprocess.list2cmdline(self.commands[self.step]), " / ".join(tail))
        self.write("\n")
        last = self.step == len(self.commands) - 1
        if code == 0 and not last:
            self.write("\n")
            self.next_command()
            return
        self.failed_step = code != 0
        if code != 0 and not last:
            self.write(tr("term.aborted") + "\n")
        self.done_running(tr("term.exit", code=code))

    def on_error(self, error) -> None:
        if error == QProcess.ProcessError.FailedToStart:
            logger.warning("command not found: %s", self.commands[self.step][0])
            self.failed_step = True
            self.write(tr("term.not_found") + "\n")
            self.done_running(tr("term.not_found"))

    def reject(self) -> None:
        # Closing the window must not kill a command half-way: Stop is the explicit way.
        if self.process.state() == QProcess.ProcessState.NotRunning:
            super().reject()
