import os
import sys

import pytest

from windiskcleaner import actions


def test_preview_lists_contents_of_folders_and_file_targets(tmp_path, make):
    a = make("cache/a.bin", 1)
    make("cache/sub/b.bin", 1)
    lone = make("dump.hprof", 1)
    items = actions.preview([str(tmp_path / "cache"), lone, str(tmp_path / "missing")])
    assert sorted(items) == sorted([a, str(tmp_path / "cache" / "sub"), lone])


def test_permanent_delete_empties_folder_but_keeps_it(tmp_path, make):
    make("cache/a.bin", 100)
    make("cache/sub/b.bin", 50)
    root = str(tmp_path / "cache")
    report = actions.delete(actions.preview([root]), [root], permanent=True)
    assert (report.freed, report.deleted, report.skipped) == (150, 2, [])
    assert os.path.isdir(root) and not os.listdir(root)


def test_refuses_items_outside_the_root(tmp_path, make):
    make("cache/a.bin", 1)
    outside = make("precious.doc", 10)
    report = actions.delete([outside], [str(tmp_path / "cache")], permanent=True)
    assert report.deleted == 0 and report.skipped[0][0] == outside
    assert os.path.exists(outside)


def test_refuses_the_root_folder_itself(tmp_path, make):
    make("cache/a.bin", 1)
    root = str(tmp_path / "cache")
    assert actions.delete([root], [root], permanent=True).deleted == 0
    assert os.path.exists(root)


def test_default_goes_to_the_recycle_bin_not_permanent(tmp_path, make):
    path = make("cache/a.bin", 30)
    trashed = []

    def fake_trash(p):
        trashed.append(p)
        os.remove(p)

    report = actions.delete([path], [str(tmp_path / "cache")], trash=fake_trash)
    assert trashed == [path] and report.freed == 30


def test_trash_failure_is_reported_not_raised(tmp_path, make):
    path = make("cache/a.bin", 30)

    def broken(_p):
        raise OSError("bin unavailable")

    report = actions.delete([path], [str(tmp_path / "cache")], trash=broken)
    assert report.skipped == [(path, "bin unavailable")] and os.path.exists(path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows locks open files")
def test_file_in_use_is_skipped(tmp_path, make):
    path = make("cache/locked.bin", 10)
    with open(path, "rb"):
        report = actions.delete([path], [str(tmp_path / "cache")], permanent=True)
    assert report.deleted == 0 and len(report.skipped) == 1


@pytest.mark.skipif(sys.platform != "win32", reason="Windows paths")
def test_never_touch_list(monkeypatch):
    monkeypatch.setenv("WINDIR", r"C:\Windows")
    monkeypatch.setenv("ProgramFiles", r"C:\Program Files")
    monkeypatch.setenv("USERPROFILE", r"C:\Users\me")
    protected = [
        "C:\\", r"C:\Windows", r"C:\Windows\System32\drivers", r"C:\Windows\Temp",
        r"C:\Program Files\App\app.exe", r"C:\Users\me", r"C:\Users\other\Documents\x",
    ]
    free = [r"C:\Windows\Temp\x.tmp", r"C:\Users\me\AppData\Local\Temp\x", r"D:\stuff\x"]
    assert all(actions.is_protected(p) for p in protected)
    assert not any(actions.is_protected(p) for p in free)


@pytest.mark.skipif(sys.platform != "win32", reason="junctions")
def test_profile_under_another_name_is_not_someone_elses(monkeypatch, tmp_path, make):
    import _winapi

    me = tmp_path / "Users" / "me"
    item = make("Users/me/AppData/Local/Temp/x.tmp", 1)
    make("Users/other/doc.txt", 1)
    alias = tmp_path / "Users" / "ME~1"  # stands in for an 8.3 short name
    try:
        _winapi.CreateJunction(str(me), str(alias))
    except OSError:
        pytest.skip("cannot create junctions here")
    monkeypatch.setenv("USERPROFILE", str(me))
    assert not actions.is_protected(item)
    assert not actions.is_protected(str(alias / "AppData" / "Local" / "Temp" / "x.tmp"))
    assert actions.is_protected(str(alias))  # the profile itself, by its other name
    assert actions.is_protected(str(tmp_path / "Users" / "other" / "doc.txt"))


def test_protected_items_are_refused_even_inside_the_root(monkeypatch, tmp_path, make):
    path = make("profile/file.bin", 5)
    monkeypatch.setenv("USERPROFILE", path)  # pretend this file is the profile itself
    report = actions.delete([path], [str(tmp_path / "profile")], permanent=True)
    assert report.deleted == 0 and os.path.exists(path)


def test_user_exclusions_are_never_removed_nor_proposed(tmp_path, make, monkeypatch):
    from windiskcleaner import advisor, rules, settings
    from windiskcleaner.scanner import scan

    keep = make("temp/keep/notes.txt", 5)
    gone = make("temp/old.tmp", 5)
    inner = make("temp/box/inner/keep.txt", 5)  # deleting "box" would take it along
    values = settings.load()
    values["exclude"] = [os.path.dirname(keep), os.path.dirname(inner)]
    settings.save(values)
    root = str(tmp_path / "temp")
    report = actions.delete(actions.preview([root]), [root], permanent=True)
    assert os.path.exists(keep) and os.path.exists(inner) and not os.path.exists(gone)
    assert {why for _p, why in report.skipped} == {"excluded in Settings"}
    assert actions.is_protected(keep)

    monkeypatch.setenv("TEMP", root)
    result = scan(str(tmp_path), watch_paths=rules.watch_paths())
    recs = {r.id: r for r in advisor.build(result, exclude=[root])}
    assert "user_temp" not in recs
