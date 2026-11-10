import os
import time

import pytest

from diskdiet import actions, advisor, rules
from diskdiet.rules import Action, Safety
from diskdiet.scanner import scan
from diskdiet.strings import S
from diskdiet.system import Program

MB = 1 << 20


@pytest.fixture(autouse=True)
def small_thresholds(monkeypatch):
    """Real thresholds are hundreds of MB: tests must not write that much."""
    monkeypatch.setattr(advisor, "ARCHIVE_MIN", 2 * MB)
    monkeypatch.setattr(advisor, "IDLE_PROJECT_MIN", 1000)
    monkeypatch.setattr(advisor, "ORPHAN_MIN", 1000)


def test_catalogue_is_well_formed():
    ids = [r.id for r in rules.RULES]
    assert len(ids) == len(set(ids))
    for rule in rules.RULES:
        assert f"cat.{rule.category}" in S, rule.id
        for text in (rule.title, rule.why):
            assert text if isinstance(text, str) else all(text), rule.id
        if rule.action is Action.DELETE:
            assert rule.safety is Safety.SAFE and rule.paths, rule.id
        if rule.action is Action.GUIDE:
            assert rule.commands or rule.tool, rule.id
        if rule.permanent:
            assert rule.category == "temp", rule.id


def test_deletable_rules_never_point_at_protected_places():
    for rule in rules.RULES:
        if rule.action is Action.DELETE:
            for path in rule.resolve():
                for item in actions.preview([path]):
                    assert not actions.is_protected(item), (rule.id, item)


def test_rule_becomes_recommendation(tmp_path, make, monkeypatch):
    make("temp/a.tmp", 300)
    make("temp/sub/b.tmp", 200)
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))
    result = scan(str(tmp_path), watch_paths=rules.watch_paths())
    recs = {r.id: r for r in advisor.build(result)}
    temp = recs["user_temp"]
    assert (temp.size, temp.permanent, temp.action) == (500, True, Action.DELETE)
    assert temp.paths == [str(tmp_path / "temp")]


def test_rule_absent_on_this_machine_is_dropped(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "nothing"))
    recs = {r.id for r in advisor.build(scan(str(tmp_path)))}
    assert "pip_cache" not in recs
    assert "storage_sense" in recs  # tool-only guidance is always offered


def test_archive_heuristics(tmp_path, make, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    now = time.time()
    old = now - 3 * 365 * advisor.DAY
    twin = make("Downloads/Photos.zip", MB)
    (tmp_path / "Downloads" / "Photos").mkdir()
    setup = make("Downloads/setup.exe", MB, mtime=old)
    video = make("Videos/clip.mp4", 2 * MB)
    stale = make("Documents/dataset.bin", 2 * MB, mtime=old)
    make("AppData/Local/thing/cache.bin", 2 * MB, mtime=old)  # not the user's own files
    recs = {r.id: r for r in advisor.build(scan(str(tmp_path)), now=now)}
    assert recs["archive_twins"].paths == [twin]
    assert recs["old_installers"].paths == [setup]
    assert recs["archive_videos"].paths == [video]
    assert recs["archive_old"].paths == [stale]


def test_idle_projects(tmp_path, make, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    now = time.time()
    make("code/old/node_modules/lib.js", 2000, mtime=now - 400 * advisor.DAY)
    make("code/live/node_modules/lib.js", 2000, mtime=now)
    result = scan(str(tmp_path), watch_names=advisor.REGENERABLE)
    recs = {r.id: r for r in advisor.build(result, now=now)}
    assert recs["idle_projects"].paths == [str(tmp_path / "code" / "old" / "node_modules")]


def test_orphans_need_no_matching_program(tmp_path, make, monkeypatch):
    local = tmp_path / "AppData" / "Local"
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    make("AppData/Local/Leftover/data.bin", advisor.ORPHAN_MIN)
    make("AppData/Local/Arduino15/data.bin", advisor.ORPHAN_MIN)
    make("AppData/Local/Packages/Chatty_abc123/settings.dat", 1)  # a Microsoft Store app
    make("AppData/Local/Chatty-Data/data.bin", advisor.ORPHAN_MIN)
    programs = [Program("Arduino IDE", "Arduino SA", 0, "")]
    recs = {r.id: r for r in advisor.build(scan(str(tmp_path)), programs=programs)}
    assert recs["appdata_orphans"].paths == [os.path.join(str(local), "Leftover")]
