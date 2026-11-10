import json
import os
import re
from pathlib import Path

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtWidgets import QApplication

from diskdiet import actions, advisor, journal, report, rules
from diskdiet.scanner import MIN_TRACKED_FILE, scan
from diskdiet.strings import S
from diskdiet.ui.main_window import MainWindow
from diskdiet.ui.pie import PieWidget
from diskdiet.ui.review_dialog import DELETE, KEEP, ReviewDialog
from diskdiet.ui.settings_dialog import SettingsDialog
from diskdiet.ui.terminal import Terminal, decode

SRC = Path(__file__).parent.parent / "src" / "diskdiet"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def scanned_window(tmp_path, make, monkeypatch):
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    make("temp/a.tmp", 2 * MIN_TRACKED_FILE)
    make("data/b.bin", MIN_TRACKED_FILE)
    make(".android/avd/Pixel.avd/userdata.img", 900)
    make(".android/avd/Old.avd/userdata.img", 100)
    result = scan(str(tmp_path), watch_paths=rules.watch_paths())
    recs = advisor.build(result)
    window = MainWindow()
    window.on_scan_done((result, [], recs))
    return window, result, recs


def test_window_shows_a_scan(app, tmp_path, make, monkeypatch):
    window, result, recs = scanned_window(tmp_path, make, monkeypatch)
    assert window.overview.table.item(0, 0).text() == "temp"
    assert window.big.rowCount() == 2
    assert window.advice.tree.topLevelItemCount() >= 2
    assert window.system_tab.recs.tree.topLevelItemCount() == 1
    assert window.tabs.count() == 9

    window.overview.enter(window.overview.row_nodes[0])  # no sub-folders: stays put
    assert len(window.overview.stack) == 1

    data = report.to_dict(result, recs)
    assert json.loads(json.dumps(data))["size"] == result.root.size
    assert "<table>" in report.to_html(data)
    window.close()
    app.processEvents()


def test_every_recommendation_can_be_selected(app, tmp_path, make, monkeypatch):
    """Selecting a row builds its detail pane and command buttons."""
    window, _result, _recs = scanned_window(tmp_path, make, monkeypatch)
    for panel in (window.advice, window.system_tab.recs, window.archive):
        for g in range(panel.tree.topLevelItemCount()):
            group = panel.tree.topLevelItem(g)
            for i in range(group.childCount()):
                panel.tree.setCurrentItem(group.child(i))
                assert panel.why.text()
    window.close()


def test_commands_become_buttons(app):
    from diskdiet.advisor import Recommendation

    rule = next(r for r in rules.RULES if r.id == "hibernation")
    rec = Recommendation(rule.id, rule.category, rule.safety, rule.action, "Hibernation", "why",
                         1, [], rule.commands)
    window = MainWindow()
    panel = window.system_tab.recs
    panel.load([rec])
    panel.tree.setCurrentItem(panel.tree.topLevelItem(0).child(0))
    labels = [panel.commands.itemAt(i).widget().text() for i in range(len(rule.commands))]
    assert len(labels) == 3 and all("🛡" in text for text in labels)  # all need admin
    panel.tree.setCurrentItem(None)
    app.processEvents()
    assert panel.commands.count() == 1  # only the stretch is left
    window.close()


def test_guided_check_collects_choices_then_deletes_once(app, tmp_path, make, monkeypatch):
    window, _result, recs = scanned_window(tmp_path, make, monkeypatch)
    rec = next(r for r in recs if r.id == "android_avd")
    dialog = ReviewDialog(window, rec, allow_move=False)
    assert [os.path.basename(i.path) for i in dialog.items] == ["Pixel.avd", "Old.avd"]
    dialog.choose(KEEP)
    dialog.choose(DELETE)
    assert dialog.pages.currentIndex() == 1  # summary page
    assert os.path.exists(dialog.items[1].path)  # nothing happened yet
    dialog.undo()
    assert dialog.pages.currentIndex() == 0 and dialog.choices == [KEEP]
    dialog.choose(DELETE)

    trashed = []
    monkeypatch.setattr(actions, "_qt_trash", lambda p: trashed.append(p) or os.rename(p, p + "~"))
    monkeypatch.setattr(window, "show_report", lambda outcome: trashed.append(outcome))
    dialog.run()
    for worker in list(window.workers):
        worker.wait(5000)
    app.processEvents()
    assert trashed[0] == dialog.items[1].path and trashed[1].deleted == 1
    assert os.path.exists(dialog.items[0].path)
    assert journal.load()[0]["source"] == "android_avd"
    window.close()


def test_overview_delete_updates_sizes(app, tmp_path, make, monkeypatch):
    window, result, _recs = scanned_window(tmp_path, make, monkeypatch)
    node = next(n for n in result.root.children if n.name == "data")
    before = result.root.size
    monkeypatch.setattr("diskdiet.ui.tabs.confirm", lambda *a, **k: True)
    monkeypatch.setattr(actions, "_qt_trash", lambda p: os.rename(p, p + "~"))
    monkeypatch.setattr(window, "show_report", lambda outcome: None)
    window.overview.delete(node)
    for worker in list(window.workers):
        worker.wait(5000)
    app.processEvents()
    assert result.root.size == before - MIN_TRACKED_FILE
    assert node not in result.root.children
    window.close()


def test_closing_summary_only_after_deletions(app, monkeypatch):
    window = MainWindow()
    shown = []
    monkeypatch.setattr(window, "closing_summary", lambda: shown.append(True))
    window.close()
    assert shown == []
    window = MainWindow()
    monkeypatch.setattr(window, "closing_summary", lambda: shown.append(True))
    window.session.merge(actions.Report(freed=10, deleted=1, trashed=10))
    window.close()
    assert shown == [True]


def test_settings_dialog_saves(app):
    window = MainWindow()
    dialog = SettingsDialog(window)
    dialog.theme.setCurrentIndex(dialog.theme.findData("dark"))
    dialog.old_days.setValue(365)
    dialog.accept()
    from diskdiet import settings

    assert settings.load()["theme"] == "dark" and settings.load()["old_days"] == 365
    window.close()


def test_terminal_runs_a_command_and_shows_output(app):
    import sys

    terminal = Terminal(None, "echo", [[sys.executable, "-c", "print('hello from child')"]])
    terminal.process.waitForFinished(15000)
    app.processEvents()
    assert "hello from child" in terminal.output.toPlainText()
    assert terminal.close_button.isEnabled()

    missing = Terminal(None, "x", [["diskdiet-no-such-program"]])
    app.processEvents()
    assert missing.close_button.isEnabled()
    assert decode("è".encode()) == "è" and decode(b"\x8a")  # falls back without raising


def test_pie_hit_testing_and_labels(app):
    pie = PieWidget()
    pie.resize(700, 300)
    pie.set_slices([("a", 25, "#f00"), ("b", 25, "#0f0"), ("c", 49, "#00f"), ("tiny", 1, "#fff")])
    c = pie._rect().center()
    # clockwise from 12 o'clock: a = 0-90°, b = 90-180°, c = 180-356°
    assert pie.slice_at(QPointF(c.x() + 40, c.y() - 40)) == 0
    assert pie.slice_at(QPointF(c.x() + 40, c.y() + 40)) == 1
    assert pie.slice_at(QPointF(c.x() - 40, c.y())) == 2
    assert pie.slice_at(QPointF(2, 2)) == -1
    slots = pie.label_slots()
    assert sorted(s[0] for s in slots) == [0, 1, 2]  # the 1% slice gets no label
    right = sorted(s[3] for s in slots if s[4])
    assert len(right) == 2 and right[1] - right[0] >= 30  # labels do not overlap
    pie.grab()  # painting runs without error


def test_every_string_key_used_in_the_code_exists():
    used = set()
    for path in SRC.rglob("*.py"):
        used |= set(re.findall(r'\btr\(\s*"([a-z_.]+)"', path.read_text(encoding="utf-8")))
    assert used and not sorted(used - set(S))
    for prefix, values in (("log.mode", ("trash", "permanent", "moved")),
                           ("log.state", ("removed", "restored")),
                           ("action", ("delete", "review", "guide")),
                           ("kind", ("docker", "wsl", "other"))):
        assert all(f"{prefix}.{v}" in S for v in values)
    assert all(len(pair) == 2 and all(pair) for pair in S.values())
