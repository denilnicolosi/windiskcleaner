"""Scan progress, progress callbacks, terminal clean-up, option lists, logging, tools."""

import logging
import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

from diskdiet import actions, log, rules, scanner
from diskdiet.scanner import MIN_TRACKED_FILE, scan
from diskdiet.ui.terminal import Terminal, plain


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def tree(make):
    make("a/b/c/d/e/f/g/deep.bin", 700)  # below the split depth
    make("a/b/c/d/e/f/side.bin", 60)
    make("a/b/top.txt", 5)
    make("a/proj/node_modules/x/node_modules/y.js", 9)
    make("a/big.bin", MIN_TRACKED_FILE)
    make("z/cache/blob", 42)
    make("root.txt", 1)


def summary(result):
    def flat(node):
        yield node.path, node.size, node.files
        for child in node.children:
            yield from flat(child)

    return (
        sorted(flat(result.root)), sorted(result.big_files), result.ext_sizes,
        result.watched, sorted(n.path for n in result.named), result.denied,
    )


def test_scan_at_every_depth_limit(tmp_path, make):
    tree(make)
    options = {"watch_paths": [str(tmp_path / "z" / "cache")], "watch_names": ["node_modules"]}
    serial = scan(str(tmp_path), **options)
    for depth in (0, 2, 6):  # the depth kept for the chart must not change any total
        limited = scan(str(tmp_path), max_depth=depth, **options)
        assert summary(limited)[1:] == summary(serial)[1:], depth
        assert limited.root.size == serial.root.size
    assert serial.root.size == 700 + 60 + 5 + 9 + MIN_TRACKED_FILE + 42 + 1
    assert [n.size for n in serial.named] == [9]


def test_scan_progress_reports_running_totals(tmp_path, make, monkeypatch):
    monkeypatch.setattr(scanner, "PROGRESS_EVERY", 2)
    for i in range(7):
        make(f"d{i % 2}/f{i}.bin", 10)
    seen = []
    scan(str(tmp_path), progress=lambda f, _p, b: seen.append((f, b)))
    assert max(seen) == (7, 70) and all(b == f * 10 for f, b in seen) and len(seen) >= 3


def test_delete_and_move_report_progress(tmp_path, make):
    a, b = make("cache/a.bin", 1), make("cache/b.bin", 1)
    steps = []
    actions.delete([a, b], [str(tmp_path / "cache")], permanent=True,
                   progress=lambda i, n, path: steps.append((i, n, path)))
    assert steps == [(0, 2, a), (1, 2, b)]
    c = make("Videos/c.mp4", 3)
    steps.clear()
    actions.move([c], str(tmp_path / "dest"), progress=lambda i, n, p: steps.append((i, n, p)))
    assert steps == [(0, 1, c)]


# ---- terminal ------------------------------------------------------------------------
OLLAMA_RM = (
    "\x1b[?2026h\x1b[?25l\x1b[1G⠙ \x1b[K\x1b[?25h\x1b[?2026l"
    "\x1b[?2026h\x1b[?25l\x1b[1G⠸ \x1b[K\x1b[?25h\x1b[?2026l"
    "\x1b[?25l\x1b[2K\x1b[1G\x1b[?25hdeleted 'qwen3.5:9b'\n"
)


def test_escape_sequences_are_removed():
    assert "\x1b" not in plain(OLLAMA_RM) and "[?2026h" not in plain(OLLAMA_RM)
    assert plain("\x1b[32mgreen\x1b[0m \x1b]0;title\x07ok") == "green ok"


def test_terminal_redraws_progress_lines_in_place(app):
    terminal = Terminal(None, "t", [[sys.executable, "-c", "pass"]])
    terminal.process.waitForFinished(15000)
    terminal.output.clear()
    terminal.write(OLLAMA_RM)
    assert terminal.output.toPlainText() == "deleted 'qwen3.5:9b'\n"
    terminal.output.clear()
    terminal.write("10%\r50%\r")
    terminal.write("100%\r\ndone\n")  # a redraw split across two chunks
    assert terminal.output.toPlainText() == "100%\ndone\n"


def test_terminal_runs_a_queue_and_stops_at_the_first_failure(app):
    def py(code):
        return [sys.executable, "-c", code]

    ok = Terminal(None, "t", [py("print('one')"), py("print('two')")])
    while ok.step < 1 or ok.process.state() != ok.process.ProcessState.NotRunning:
        ok.process.waitForFinished(15000)
        app.processEvents()
    text = ok.output.toPlainText()
    assert "one" in text and "two" in text and not ok.failed_step

    bad = Terminal(None, "t", [py("import sys; sys.exit(3)"), py("print('never')")])
    bad.process.waitForFinished(15000)
    app.processEvents()
    assert bad.failed_step and bad.step == 0 and "never" not in bad.output.toPlainText()
    assert bad.close_button.isEnabled()


# ---- option lists --------------------------------------------------------------------
def command(rule_id, index):
    return next(r for r in rules.RULES if r.id == rule_id).commands[index]


def test_ollama_models_are_parsed_from_ollama_list():
    output = (
        "NAME                      ID              SIZE      MODIFIED\n"
        "qwen3-coder:480b-cloud    e30e45586389    -         10 months ago\n"
        "llama3.1:8b               46e0c10c039e    4.9 GB    3 weeks ago\n"
    )
    remove = command("ollama_models", 1)
    assert [v for v, _line in remove.options(output)] == ["qwen3-coder:480b-cloud", "llama3.1:8b"]
    assert "4.9 GB" in remove.options(output)[1][1]  # the user sees the whole line
    assert remove.build("llama3.1:8b") == ["ollama", "rm", "llama3.1:8b"]


def test_nvm_versions_are_parsed_from_nvm_list():
    output = "\n  * 24.14.0 (Currently using 64-bit executable)\n    16.17.0\n"
    assert [v for v, _l in command("nvm_versions", 1).options(output)] == ["24.14.0", "16.17.0"]


def test_restore_point_is_a_fixed_admin_command():
    point = rules.RESTORE_POINT
    assert point.admin and not point.ask and point.build()[0] == "powershell"
    assert "Checkpoint-Computer" in point.build()[-1]
    assert point in next(r for r in rules.RULES if r.id == "restore_points").commands


# ---- tools and logging ---------------------------------------------------------------
def test_launch_opens_the_first_existing_candidate(tmp_path, make, monkeypatch):
    real = make("apps/Tool.exe", 1)
    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    actions.launch(f"{tmp_path}\\missing\\Tool.exe|{real}")
    assert opened == [real]
    with pytest.raises(OSError, match="not found"):
        actions.launch(f"{tmp_path}\\missing\\Tool.exe")


def test_log_file_records_operations_and_skips(tmp_path, make):
    log.setup()
    handler = log.logger.handlers[-1]
    try:
        inside = make("cache/a.bin", 10)
        outside = make("precious.doc", 10)
        actions.delete([inside, outside], [str(tmp_path / "cache")], permanent=True, source="t")
        handler.flush()
        text = open(log.path(), encoding="utf-8").read()
    finally:
        log.logger.removeHandler(handler)
        handler.close()
        sys.excepthook = sys.__excepthook__
    assert "delete [t]: 1 items, 10 bytes" in text
    assert "WARNING" in text and "precious.doc" in text
    assert isinstance(log.logger.handlers[0], logging.NullHandler)


def test_models_are_ticked_in_a_list_not_typed(app, monkeypatch):
    from types import SimpleNamespace

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QDialog, QListWidget

    from diskdiet.ui import tabs
    from diskdiet.ui.main_window import MainWindow

    listing = b"NAME  ID  SIZE\nllama3.1:8b  46e0  4.9 GB\nqwen3.5:9b  77aa  6.6 GB\n"
    monkeypatch.setattr(tabs.subprocess, "run", lambda *a, **k: SimpleNamespace(stdout=listing))

    def tick_second(dialog):
        choices = dialog.findChild(QListWidget)
        assert choices.count() == 2 and "6.6 GB" in choices.item(1).text()
        choices.item(1).setCheckState(Qt.CheckState.Checked)
        return 1

    monkeypatch.setattr(QDialog, "exec", tick_second)
    window = MainWindow()
    assert window.advice.ask_values(command("ollama_models", 1), "t") == ["qwen3.5:9b"]
    window.close()
