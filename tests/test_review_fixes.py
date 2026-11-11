"""Regressions found by reviewing the program in real use. Most press the actual buttons."""

import ast
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from windiskcleaner import actions, advisor, games, history, journal, report, rules, winapp2
from windiskcleaner.duplicates import DupGroup
from windiskcleaner.games import Game
from windiskcleaner.rules import Action, Safety
from windiskcleaner.scanner import FileInfo, scan
from windiskcleaner.strings import S, fmt_date, tr
from windiskcleaner.system import Program, running_images
from windiskcleaner.ui import main_window
from windiskcleaner.ui.main_window import MainWindow
from windiskcleaner.ui.widgets import ROLE

SRC = Path(__file__).parent.parent / "src" / "windiskcleaner"
TABS = "windiskcleaner.ui.tabs"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def profile(tmp_path, monkeypatch):
    """A fake user profile, so that nothing here can reach the real one."""
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "AppData" / "Local"))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    monkeypatch.setenv("TEMP", str(tmp_path / "AppData" / "Local" / "Temp"))
    return tmp_path


def window_for(tmp_path):
    result = scan(str(tmp_path), watch_paths=rules.watch_paths())
    window = MainWindow()
    window.on_scan_done((result, [], advisor.build(result)))
    return window, result


def settle(app, window):
    for worker in list(window.workers):
        worker.wait(5000)
    app.processEvents()


# ---- buttons -------------------------------------------------------------------------
def test_clean_everything_safe_ticks_only_safe_items(app, profile, make, monkeypatch):
    make("AppData/Local/Temp/a.tmp", 10)
    make("AppData/Local/Android/Sdk/platforms/a.jar", 10)
    make("AppData/Local/Programs/Python/Python39/python.exe", 10)
    make("OneDrive/thesis.docx", 10)
    window, _result = window_for(profile)
    monkeypatch.setattr(f"{TABS}.confirm", lambda *a, **k: False)  # stop at the confirmation
    monkeypatch.setattr(f"{TABS}.system.running_images", set)
    window.advice.check_all_safe()
    chosen = [item.data(0, ROLE) for item in window.advice.checked()]
    assert [r.id for r in chosen] == ["user_temp"]
    tree = window.advice.tree
    for g in range(tree.topLevelItemCount()):
        for i in range(tree.topLevelItem(g).childCount()):
            item = tree.topLevelItem(g).child(i)
            rec = item.data(0, ROLE)
            if not (rec.action is Action.DELETE and rec.safety is Safety.SAFE):
                assert item.checkState(0).value == 0, rec.id
    window.close()


def test_uninstall_button(app, profile, monkeypatch):
    window = MainWindow()
    window.program_tab.load([Program("Tool", "Acme", 0, "", "tool-uninstall.exe")])
    window.program_tab.table.setCurrentCell(0, 0)
    started, told = [], []
    monkeypatch.setattr(f"{TABS}.confirm", lambda *a, **k: True)
    monkeypatch.setattr(actions, "uninstall", started.append)
    monkeypatch.setattr(f"{TABS}.QMessageBox.information", lambda *a: told.append(a[2]))
    window.program_tab.uninstall_selected()
    assert started == ["tool-uninstall.exe"] and "Tool" in told[0]
    window.close()


def test_find_leftovers_button(app, profile, make, monkeypatch):
    make("AppData/Local/Gonetool/data.bin", 10)
    window = MainWindow()
    window.program_tab.load([Program("Gonetool", "Acme", 0, "")])
    window.program_tab.table.setCurrentCell(0, 0)
    shown = []

    class FakeDialog:
        def __init__(self, _win, rec, _allow):
            shown.append(rec)

        def exec(self):
            return 0

    monkeypatch.setattr(f"{TABS}.ReviewDialog", FakeDialog)
    monkeypatch.setattr(f"{TABS}.system.installed_programs", list)
    window.program_tab.find_leftovers()
    settle(app, window)
    assert [os.path.basename(p) for p in shown[0].paths] == ["Gonetool"]
    window.close()


def test_game_uninstall_button(app, monkeypatch):
    window = MainWindow()
    window.games_tab.load([Game("Some Game", "Steam", r"D:\Games\Some", 10, 0.0, "42")])
    window.games_tab.table.selectRow(0)
    asked = []
    monkeypatch.setattr("windiskcleaner.ui.more_tabs.confirm", lambda *a, **k: True)
    monkeypatch.setattr(actions, "uninstall_game", lambda *a: asked.append(a))
    window.games_tab.uninstall_selected()
    assert asked == [("Steam", "42")]
    window.close()


def test_every_translated_call_formats_in_both_languages():
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", "") == "tr"):
                continue
            first = node.args[0] if node.args else None
            if not isinstance(first, ast.Constant) or any(k.arg is None for k in node.keywords):
                continue
            values = {k.arg: 1 for k in node.keywords}
            for text in S[first.value]:
                text.format(**values) if values else text
    assert tr("prog.confirm", name="X")  # "name" is also tr's own parameter


# ---- damaged data --------------------------------------------------------------------
def test_dates_windows_cannot_convert(app, tmp_path, make):
    assert fmt_date(-1.0) == "" and fmt_date(0.0 + 86400)
    from windiskcleaner.strings import fmt_stamp

    assert fmt_stamp("2026-11-10T16:23:11") == "10-11-2026 16:23:11"
    assert fmt_stamp("20251104") == "04-11-2025" and fmt_stamp("odd") == "odd"
    assert len(fmt_date(1_700_000_000)) == 10 and fmt_date(1_700_000_000)[2] == "-"
    window = MainWindow()
    window.big.load([FileInfo(2 << 20, -1.0, "x.bin")])
    assert window.big.rowCount() == 1
    window.close()
    make("a/x.bin", 5)
    result = scan(str(tmp_path))
    result.big_files.append(FileInfo(2 << 20, -1.0, "x.bin"))
    assert "x.bin" in report.to_csv(result)


def test_damaged_launcher_files_do_not_stop_the_scan(tmp_path, make):
    make("S/steamapps/libraryfolders.vdf", content=b'"libraryfolders" "broken"')
    make("S/steamapps/appmanifest_1.acf",
         content=b'"AppState" { "installdir" "G" "SizeOnDisk" "abc" "LastPlayed" "x" }')
    make("S/steamapps/appmanifest_2.acf", content=b'"AppState" "broken"')
    [game] = games.steam_games(str(tmp_path / "S"))
    assert (game.size, game.last_played) == (0, 0.0)
    make("M/a.item", content=b"[1, 2]")
    make("M/b.item", content=json.dumps({"InstallLocation": "E:\\G", "InstallSize": "x"}).encode())
    [epic] = games.epic_games(str(tmp_path / "M"))
    assert epic.size == 0


def test_odd_lines_in_the_logs_are_ignored(tmp_path, make):
    make("a/x.bin", 1)
    history.save(scan(str(tmp_path / "a")))
    with open(history._file(), "a", encoding="utf-8") as f:
        f.write('5\n{"root": "x"}\n')
    assert history.previous(str(tmp_path / "a")) is not None
    journal.add("a", 1, 1, journal.TRASH)
    with open(journal._file(), "a", encoding="utf-8") as f:
        f.write('5\n{"id": "x"}\n')
    assert len(journal.load()) == 1


# ---- what is proposed ----------------------------------------------------------------
def test_an_exclusion_inside_a_folder_spares_only_that_item(profile, make, monkeypatch):
    make("AppData/Local/Temp/a.tmp", 100)
    make("AppData/Local/Temp/keep/deep/k.tmp", 7)
    keep = str(profile / "AppData" / "Local" / "Temp" / "keep" / "deep")
    result = scan(str(profile), watch_paths=rules.watch_paths())
    rec = {r.id: r for r in advisor.build(result, exclude=[keep])}["user_temp"]
    assert rec.size == 100
    monkeypatch.setattr(actions, "excluded", lambda: [os.path.normcase(keep)])
    assert [os.path.basename(i.path) for i in advisor.review_items(rec, result)] == ["a.tmp"]


def test_leftovers_respect_installed_programs_named_after_the_publisher(profile, make):
    make("AppData/Local/Microsoft/Teams/x", 5)
    classic = Program("Microsoft Teams classic", "Microsoft", 0, "")
    assert advisor.leftovers(classic, [Program("Microsoft Teams", "Microsoft", 0, "")]) is None
    assert advisor.leftovers(classic, [])  # with no new Teams installed it is a leftover


def test_winapp2_needs_recurse_to_empty_a_whole_folder():
    text = "[A *]\nFileKey1=%LocalAppData%\\A|*.*\n[B *]\nFileKey1=%LocalAppData%\\B|*.*|RECURSE\n"
    assert [e.name for e in winapp2.parse("\ufeff" + text)] == ["B *"]


def test_cache_of_desktop_apps_names_the_app_to_close(profile, make):
    make("AppData/Roaming/SomeChat/Cache/Cache_Data/f", 10)
    make("AppData/Roaming/SomeChat/Code Cache/js/x", 10)
    rec = {r.id: r for r in advisor.build(scan(str(profile)))}["app_caches"]
    assert rec.process == "SomeChat.exe"


# ---- operations ----------------------------------------------------------------------
def test_compression_that_saves_nothing_is_not_recorded(tmp_path, make, monkeypatch):
    make("app/a.bin", 10)
    monkeypatch.setattr(actions, "_compact", lambda folder, switches, cancelled=None:
                        subprocess.CompletedProcess([], 0, "", ""))
    report_ = actions.compress(str(tmp_path / "app"))
    assert "nothing saved" in report_.skipped[0][1] and journal.load() == []


def test_undo_rewrites_the_log_once(tmp_path, make, monkeypatch):
    root = str(tmp_path / "cache")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def trash(path):
        target = bin_dir / ("$R" + os.path.basename(path))
        os.rename(path, target)
        return str(target)

    batch = journal.new_batch()
    items = [make(f"cache/{i}.bin", 1) for i in range(5)]
    actions.delete(items, [root], trash=trash, batch=batch)
    writes, real = [], journal._write
    monkeypatch.setattr(journal, "_write", lambda e: (writes.append(1), real(e)))
    seen = []
    done, failed = actions.restore_last(lambda i, n, _p: seen.append((i, n)))
    assert len(done) == 5 and not failed and len(writes) == 1 and seen[-1] == (4, 5)


def test_cancel_stops_a_cleanup_between_items(tmp_path, make):
    root = str(tmp_path / "t")
    items = [make(f"t/{i}.tmp", 1) for i in range(5)]
    asked = iter([False, False, True])
    outcome = actions.delete(items, [root], permanent=True, cancelled=lambda: next(asked))
    assert outcome.deleted == 2 and sum(os.path.exists(p) for p in items) == 3


def test_purge_removes_only_what_the_cleanup_put_in_the_bin(tmp_path, make):
    root = str(tmp_path / "cache")
    bin_dir = tmp_path / "$Recycle.Bin" / "S-1-5"
    bin_dir.mkdir(parents=True)
    other = bin_dir / "$Rother.txt"
    other.write_bytes(b"not ours")

    def trash(path):
        target = bin_dir / ("$R" + os.path.basename(path))
        os.rename(path, target)
        (bin_dir / ("$I" + os.path.basename(path))).write_bytes(b"info")
        return str(target)

    batch = journal.new_batch()
    actions.delete([make("cache/a.bin", 4)], [root], trash=trash, batch=batch)
    actions.delete([make("cache/b.bin", 4)], [root], trash=trash)  # another cleanup
    journal.add("x", 1, 1, journal.TRASH, str(tmp_path / "elsewhere" / "$Rx"), "", batch)
    outcome = actions.purge_batch(batch)
    assert outcome.permanent == 4 and len(outcome.skipped) == 1
    assert sorted(p.name for p in bin_dir.iterdir()) == [
        "$Ib.bin", "$Rb.bin", "$Rother.txt"]
    assert [e["state"] for e in journal.load()][:2] == ["purged", "removed"]


def test_journal_trim_and_skip_log_are_bounded(caplog):
    for i in range(5):
        journal.add(str(i), 1, 1, journal.TRASH)
    journal.trim(keep=2)
    assert [e["path"] for e in journal.load()] == ["3", "4"]
    outcome = actions.Report(skipped=[(str(i), "why") for i in range(100)])
    with caplog.at_level("WARNING", logger="windiskcleaner"):
        actions._logged("test", outcome)
    assert len(caplog.records) == actions.MAX_LOGGED_SKIPS + 1


@pytest.mark.skipif(sys.platform != "win32", reason="tasklist")
def test_running_images_lists_this_process():
    assert os.path.basename(sys.executable).lower() in running_images()


# ---- the window ----------------------------------------------------------------------
def test_one_job_at_a_time_and_close_waits_for_it(app):
    window = MainWindow()
    release = threading.Event()
    assert window.run(lambda _p, _c: release.wait(5), lambda _r: None)
    assert not window.run(lambda _p, _c: None, lambda _r: None)  # refused while busy
    window.close()
    assert window.close_when_idle and window.workers  # asked to stop, not destroyed
    release.set()
    settle(app, window)
    assert not window.workers


def test_reopen_does_not_compare_a_scan_with_itself(app, profile, make, monkeypatch):
    monkeypatch.setattr(history, "MIN_FOLDER", 1)
    monkeypatch.setattr(history, "MIN_CHANGE", 100)
    make("data/a.bin", 10)
    history.save(scan(str(profile)))
    make("data/b.bin", 5000)
    window, _result = window_for(profile)
    rows, saved = window.growth_tab.table.rowCount(), len(history.load())
    assert rows
    before = list(main_window._WINDOWS)
    window.reopen()
    settle(app, window)
    fresh = next(w for w in main_window._WINDOWS if w not in before)
    assert fresh.growth_tab.table.rowCount() == rows and len(history.load()) == saved
    fresh.close()


def test_duplicates_that_could_not_be_removed_stay_listed(app, profile, make, monkeypatch):
    a, b, c = (make(f"d/{n}.bin", 5) for n in "abc")
    window = MainWindow()
    window.dups.load([DupGroup(5, [a, b, c])])
    head = window.dups.tree.topLevelItem(0)
    head.child(0).setCheckState(0, head.child(0).checkState(0).__class__.Checked)
    head.child(1).setCheckState(0, head.child(1).checkState(0).__class__.Checked)

    def trash(path):
        if path == b:
            raise OSError("in use")
        os.rename(path, path + "~")
        return path + "~"

    monkeypatch.setattr(actions, "_qt_trash", trash)
    monkeypatch.setattr(f"{TABS}.confirm", lambda *a, **k: True)
    monkeypatch.setattr(window, "show_report", lambda outcome, batch="": None)
    window.dups.trash_checked()
    settle(app, window)
    assert [head.child(i).text(0) for i in range(head.childCount())] == [b, c]
    window.close()


def test_going_up_during_a_delete_keeps_the_totals(app, profile, make, monkeypatch):
    make("data/sub/x.bin", 50)
    make("data/y.bin", 5)
    window, result = window_for(profile)
    data = next(n for n in result.root.children if n.name == "data")
    sub = next(n for n in data.children if n.name == "sub")
    total = result.root.size
    window.overview.enter(data)
    monkeypatch.setattr(f"{TABS}.confirm", lambda *a, **k: True)
    monkeypatch.setattr(actions, "_qt_trash", lambda p: os.rename(p, p + "~"))
    monkeypatch.setattr(window, "show_report", lambda outcome, batch="": None)
    window.overview.delete(sub)
    window.overview.go_up()  # the user moves on while the job runs
    settle(app, window)
    assert result.root.size == total - 50
    window.close()


def test_every_grid_column_fits_its_content(app, profile, make):
    """Columns must show their content without resizing by hand; one column per grid
    stretches into the remaining width."""
    from PySide6.QtWidgets import QHeaderView, QTableView, QTreeView

    from windiskcleaner.ui.widgets import MAX_FIT

    long_name = "A program with a rather long name, version 2025 (64-bit)"
    make("AppData/Local/Temp/a.tmp", 10)
    window, _result = window_for(profile)
    window.program_tab.load([Program(long_name, "A publisher with a long name", 7 << 30,
                                     "20251104")])
    window.games_tab.load([Game("A game with a long title: Definitive Edition", "Steam",
                                r"D:\Games\Some", 10, 0.0, "1")])
    journal.add(str(profile / "x"), 123456789, 1, journal.MOVED, "D:/x", "s")
    window.journal_tab.reload()
    window.resize(1180, 760)
    window.show()
    app.processEvents()
    app.processEvents()
    checked = 0
    for view in window.findChildren(QTableView) + window.findChildren(QTreeView):
        if not view.model().rowCount():
            continue
        header = view.horizontalHeader() if isinstance(view, QTableView) else view.header()
        for col in range(header.count()):
            if header.sectionResizeMode(col) == QHeaderView.ResizeMode.Stretch:
                continue
            need = max(view.sizeHintForColumn(col), header.sectionSizeHint(col))
            assert header.sectionSize(col) >= min(need, MAX_FIT), (view.parent(), col)
            checked += 1
    assert checked > 20
    window.close()


def test_a_replaced_window_is_released(app, profile, make):
    make("data/a.bin", 10)
    window, _result = window_for(profile)
    main_window._WINDOWS.append(window)
    window.reopen()
    settle(app, window)
    assert window not in main_window._WINDOWS and len(main_window._WINDOWS) >= 1
    main_window._WINDOWS[-1].close()
    assert not main_window._WINDOWS or all(w.isVisible() for w in main_window._WINDOWS)
