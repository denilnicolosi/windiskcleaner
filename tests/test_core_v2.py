"""Journal, move/restore, settings, updates, commands, guided-check items."""

import hashlib
import os
import shutil
import sys
import urllib.error

import pytest

from diskdiet import actions, advisor, journal, rules, settings, updates
from diskdiet.rules import Action, Command
from diskdiet.scanner import scan


def fake_bin(tmp_path):
    """A trash function that moves items into a folder and reports where, like Windows."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()

    def trash(path):
        target = bin_dir / ("$R" + os.path.basename(path))
        os.rename(path, target)
        (bin_dir / ("$I" + os.path.basename(path))).write_bytes(b"info")
        return str(target)

    return trash


# ---- journal and restore ------------------------------------------------------------
def test_deletions_are_logged(tmp_path, make):
    a = make("cache/a.bin", 30)
    b = make("cache/dir/b.bin", 20)
    root = str(tmp_path / "cache")
    actions.delete([a], [root], trash=fake_bin(tmp_path), source="pip_cache")
    actions.delete([os.path.dirname(b)], [root], permanent=True, source="user_temp")
    first, second = journal.load()
    assert (first["path"], first["size"], first["mode"], first["source"]) == (
        a, 30, journal.TRASH, "pip_cache")
    assert first["location"].endswith("$Ra.bin") and first["state"] == "removed"
    assert (second["mode"], second["size"], second["files"]) == (journal.PERMANENT, 20, 1)


def test_restore_from_bin(tmp_path, make):
    a = make("cache/a.bin", content=b"precious")
    report = actions.delete([a], [str(tmp_path / "cache")], trash=fake_bin(tmp_path))
    assert report.trashed == 8 and not os.path.exists(a)
    entry = journal.load()[0]
    actions.restore(entry)
    assert open(a, "rb").read() == b"precious"
    assert not os.path.exists(tmp_path / "bin" / "$Ia.bin")  # no ghost left in the bin
    assert journal.load()[0]["state"] == "restored"
    with pytest.raises(OSError, match="already restored"):
        actions.restore(journal.load()[0])


def test_restore_refuses_when_it_cannot_be_exact(tmp_path, make):
    root = str(tmp_path / "cache")
    a = make("cache/a.bin", 5)
    actions.delete([a], [root], trash=fake_bin(tmp_path))
    make("cache/a.bin", 1)  # something new took its place
    with pytest.raises(OSError, match="original location"):
        actions.restore(journal.load()[-1])

    b = make("cache/b.bin", 5)
    actions.delete([b], [root], permanent=True)
    with pytest.raises(OSError, match="permanently"):
        actions.restore(journal.load()[-1])

    c = make("cache/c.bin", 5)
    actions.delete([c], [root], trash=fake_bin(tmp_path / "cache"))
    os.remove(journal.load()[-1]["location"])  # the bin was emptied
    with pytest.raises(OSError, match="no longer there"):
        actions.restore(journal.load()[-1])


@pytest.mark.skipif(sys.platform != "win32", reason="real Recycle Bin")
def test_real_recycle_bin_round_trip(make):
    """One tiny file of ours goes to the real Recycle Bin and comes back."""
    pytest.importorskip("PySide6")
    path = make("cache/roundtrip.txt", content=b"diskdiet")
    report = actions.delete([path], [os.path.dirname(path)])
    if not report.deleted or not journal.load()[-1]["location"]:
        pytest.skip("no Recycle Bin available here")
    entry = journal.load()[-1]
    assert not os.path.exists(path)
    actions.restore(entry)
    assert open(path, "rb").read() == b"diskdiet"


# ---- move ---------------------------------------------------------------------------
def test_move_copies_verifies_then_removes(tmp_path, make):
    video = make("Videos/clip.mp4", content=b"v" * 500)
    make("VMs/ubuntu/disk.vmdk", 300)
    make("VMs/ubuntu/conf.vmx", 10)
    vm = str(tmp_path / "VMs" / "ubuntu")
    dest = str(tmp_path / "other-drive")
    os.mkdir(dest)
    report = actions.move([video, vm], dest, source="archive_videos")
    assert (report.moved, report.deleted, report.skipped) == (810, 2, [])
    assert not os.path.exists(video) and not os.path.exists(vm)
    target = actions.archive_target(video, dest)
    assert open(target, "rb").read() == b"v" * 500
    entry = journal.load()[0]
    assert (entry["mode"], entry["location"]) == (journal.MOVED, target)
    actions.restore(entry)  # moving back works the same way
    assert os.path.exists(video) and not os.path.exists(target)


def test_move_keeps_original_when_destination_is_taken_or_full(tmp_path, make, monkeypatch):
    video = make("Videos/clip.mp4", 100)
    dest = str(tmp_path / "other-drive")
    os.makedirs(os.path.dirname(actions.archive_target(video, dest)))
    open(actions.archive_target(video, dest), "wb").close()
    assert actions.move([video], dest).skipped[0][1] == "already present at the destination"
    os.remove(actions.archive_target(video, dest))

    monkeypatch.setattr(actions.shutil, "disk_usage", lambda _p: shutil._ntuple_diskusage(0, 0, 10))
    assert actions.move([video], dest).skipped[0][1] == "not enough space at the destination"
    assert os.path.getsize(video) == 100 and journal.load() == []


def test_move_refuses_a_bad_copy(tmp_path, make, monkeypatch):
    video = make("Videos/clip.mp4", 100)
    dest = str(tmp_path / "other-drive")
    os.mkdir(dest)
    monkeypatch.setattr(actions.shutil, "copy2", lambda _s, d: open(d, "wb").write(b"short"))
    report = actions.move([video], dest)
    assert report.skipped[0][1] == "the copy did not match the original"
    assert os.path.exists(video) and not os.path.exists(actions.archive_target(video, dest))


# ---- settings -----------------------------------------------------------------------
def test_settings_round_trip_and_tolerate_damage(tmp_path):
    assert settings.load() == settings.DEFAULTS
    settings.save({**settings.DEFAULTS, "theme": "dark", "old_days": 365})
    assert settings.load()["theme"] == "dark" and settings.load()["old_days"] == 365
    with open(os.path.join(settings.data_dir(), "settings.json"), "w") as f:
        f.write('{"theme": 5, "old_days": "many", "check_updates": false')  # truncated
    assert settings.load() == settings.DEFAULTS
    with open(os.path.join(settings.data_dir(), "settings.json"), "w") as f:
        f.write('{"theme": 5, "check_updates": false}')
    assert settings.load() == {**settings.DEFAULTS, "check_updates": False}


# ---- updates (no real network) ------------------------------------------------------
def release(exe=b"new exe", sha=None, base=updates.DOWNLOADS):
    digest = sha or hashlib.sha256(exe).hexdigest()
    pages = {
        base + "v9.0.0/DiskDiet-9.0.0.exe": exe,
        base + "v9.0.0/DiskDiet-9.0.0.exe.sha256": f"{digest}  DiskDiet-9.0.0.exe\n".encode(),
    }
    rel = updates.Release("9.0.0", "notes", "page", *pages)
    return rel, pages.__getitem__


def test_version_comparison():
    assert updates.is_newer("v0.2.0", "0.1.9") and updates.is_newer("1.0", "0.9.9")
    assert not updates.is_newer("0.1.0", "0.1.0") and not updates.is_newer("0.0.9", "0.1.0")
    assert not updates.is_newer("nightly", "0.1.0")


def test_latest_parses_the_release_and_handles_no_release():
    body = (b'{"tag_name": "v9.0.0", "body": "notes", "html_url": "page", "assets": ['
            b'{"name": "DiskDiet-9.0.0.exe", "browser_download_url": "U1"},'
            b'{"name": "DiskDiet-9.0.0.exe.sha256", "browser_download_url": "U2"}]}')
    found = updates.latest(lambda _url: body)
    assert (found.version, found.exe_url, found.sha_url) == ("9.0.0", "U1", "U2")

    def missing(url):
        raise urllib.error.HTTPError(url, 404, "Not Found", None, None)

    assert updates.latest(missing) is None


def test_download_checks_origin_and_hash(tmp_path):
    dest = str(tmp_path / "new.exe")
    rel, fetch = release()
    assert open(updates.download(rel, dest, fetch), "rb").read() == b"new exe"

    rel, fetch = release(sha="0" * 64)
    with pytest.raises(ValueError, match="SHA-256"):
        updates.download(rel, str(tmp_path / "bad.exe"), fetch)
    assert not os.path.exists(tmp_path / "bad.exe")

    rel, fetch = release(base="https://evil.example/releases/download/")
    with pytest.raises(ValueError, match="not a download"):
        updates.download(rel, str(tmp_path / "evil.exe"), fetch)


def test_swap_replaces_the_exe_and_cleanup_removes_the_old_one(tmp_path, make):
    current = make("app/DiskDiet.exe", content=b"old")
    new = make("app/DiskDiet.new.exe", content=b"new")
    updates.swap(new, current, start=False)
    assert open(current, "rb").read() == b"new"
    assert open(current + ".old", "rb").read() == b"old"
    updates.cleanup(current)
    assert os.listdir(os.path.dirname(current)) == ["DiskDiet.exe"]


# ---- commands -----------------------------------------------------------------------
def test_every_command_is_an_argument_list_with_two_languages():
    for rule in rules.RULES:
        for cmd in rule.commands:
            assert isinstance(cmd.argv, tuple) and all(isinstance(a, str) for a in cmd.argv)
            assert all(cmd.label), rule.id
            assert ("{value}" in " ".join(cmd.argv)) == bool(cmd.ask), rule.id
            if cmd.ask:
                assert cmd.changes, rule.id


@pytest.mark.parametrize("bad", ["", "a b", 'x"', "x;del", "a&b", "a|b", "-rf", "$(x)", "a\nb"])
def test_command_values_must_be_plain_names(bad):
    cmd = Command("rm", ("tool", "rm", "{value}"), ask="which")
    with pytest.raises(ValueError):
        cmd.build(bad)


def test_command_build():
    cmd = Command("rm", ("ollama", "rm", "{value}"), ask="which")
    assert cmd.build("llama3.1:8b") == ["ollama", "rm", "llama3.1:8b"]
    assert Command("df", ("docker", "system", "df")).build() == ["docker", "system", "df"]


# ---- guided check -------------------------------------------------------------------
def test_review_items_expand_catalogue_folders(tmp_path, make, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    make(".android/avd/Pixel.avd/userdata.img", 900)
    make(".android/avd/Old.avd/userdata.img", 100)
    make(".android/avd/Pixel.ini", 5)
    recs = {r.id: r for r in advisor.build(scan(str(tmp_path)))}
    rec = recs["android_avd"]
    assert rec.action is Action.REVIEW and rec.expand and "emulator" in rec.question
    items = advisor.review_items(rec)
    assert [(os.path.basename(i.path), i.size) for i in items] == [
        ("Pixel.avd", 900), ("Old.avd", 100), ("Pixel.ini", 5)]


def test_review_items_of_a_heuristic_are_its_files(tmp_path, make, monkeypatch):
    monkeypatch.setenv("USERPROFILE", str(tmp_path))
    monkeypatch.setattr(advisor, "ARCHIVE_MIN", 1 << 20)
    video = make("Videos/clip.mp4", 1 << 20)
    rec = {r.id: r for r in advisor.build(scan(str(tmp_path)))}["archive_videos"]
    assert not rec.expand and [i.path for i in advisor.review_items(rec)] == [video]


def test_every_review_question_has_two_languages():
    for text in [rules.DEFAULT_QUESTION, *rules.QUESTIONS.values()]:
        assert len(text) == 2 and all(text)


def test_move_handles_destinations_past_260_characters(tmp_path, make):
    deep = make("d" * 40 + "/" + "e" * 40 + "/" + "f" * 40 + "/clip.mp4", content=b"v" * 50)
    dest = str(tmp_path / "other-drive")
    os.mkdir(dest)
    assert len(actions.archive_target(deep, dest)) > 260
    report = actions.move([deep], dest)
    assert (report.moved, report.skipped) == (50, [])
    actions.restore(journal.load()[-1])
    assert open(deep, "rb").read() == b"v" * 50
