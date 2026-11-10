import os

import pytest

from diskdiet import actions, advisor, rules, settings, winapp2
from diskdiet.scanner import scan

SAMPLE = r"""
; comment
[SomeApp Cache *]
Detect=HKCU\Software\SomeApp
FileKey1=%LocalAppData%\SomeApp\Cache|*.*|RECURSE
FileKey2=%LocalAppData%\SomeApp\Logs|*.log

[Risky *]
FileKey1=%AppData%\Risky\Data|*.*
ExcludeKey1=FILE|%AppData%\Risky\Data\|keep.db

[Windows Stuff *]
FileKey1=%WinDir%\Temp|*.*

[Covered *]
FileKey1=%LocalAppData%\uv\cache|*.*
"""


def test_parse_keeps_only_whole_folder_keys_without_exclusions():
    entries = winapp2.parse(SAMPLE)
    assert [e.name for e in entries] == ["SomeApp Cache *", "Windows Stuff *", "Covered *"]
    assert entries[0].folders == (r"%LocalAppData%\SomeApp\Cache",)


def test_expand_refuses_unknown_variables(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\L")
    assert winapp2.expand(r"%LocalAppData%\X") == os.path.normpath(r"C:\L\X")
    assert winapp2.expand(r"%WinDir%\Temp") is None


def test_imported_rules_become_suggestions_to_review(tmp_path, make, monkeypatch):
    local = tmp_path / "me" / "AppData" / "Local"
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "me"))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    make("me/AppData/Local/SomeApp/Cache/blob", 300)
    make("me/AppData/Local/uv/cache/wheel", 100)  # already a catalogue rule
    os.makedirs(settings.data_dir(), exist_ok=True)
    with open(winapp2.path(), "w", encoding="utf-8") as f:
        f.write(SAMPLE)
    result = scan(str(tmp_path), watch_paths=rules.watch_paths())
    recs = {r.id: r for r in advisor.build(result)}
    rec = recs["winapp2"]
    assert rec.paths == [str(local / "SomeApp" / "Cache")] and rec.size == 300
    assert rec.action is rules.Action.REVIEW  # never a one-click cleanup
    actions.remove_own_file(winapp2.FILE_NAME)
    assert not os.path.exists(winapp2.path())
    with pytest.raises(ValueError):
        actions.remove_own_file(r"..\settings.json")
