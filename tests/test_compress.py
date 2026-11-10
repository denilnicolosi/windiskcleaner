import os
import subprocess
import sys

import pytest

from diskdiet import actions, compress, journal, settings
from diskdiet.scanner import scan

MB = 1 << 20


def test_estimate_tells_compressible_from_packed(tmp_path, make):
    make("tool/zeros.dll", content=b"\0" * MB)
    make("noise/random.bin", content=os.urandom(MB))
    make("noise/movie.mp4", content=b"\0" * MB)  # counted as already compressed
    assert compress.estimate(str(tmp_path / "tool")) < 0.05
    assert compress.estimate(str(tmp_path / "noise")) > 0.95
    assert compress.estimate(str(tmp_path / "empty")) == 1.0


def test_on_disk_counts_logical_size_and_files(tmp_path, make):
    make("app/a.bin", 1000)
    make("app/sub/b.bin", 2000)
    logical, used, files = compress.on_disk(str(tmp_path / "app"))
    assert (logical, files) == (3000, 2) and used > 0


def test_candidates_are_big_catalogue_folders_inside_the_scan(tmp_path, make, monkeypatch):
    monkeypatch.setattr(compress, "CANDIDATE_MIN", 1000)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    monkeypatch.setenv("USERPROFILE", str(tmp_path / "me"))
    make("Local/Programs/Editor/editor.exe", 5000)
    make("Local/Programs/Tiny/tiny.exe", 10)
    make("Local/Android/Sdk/platforms/android.jar", 3000)
    sdk = str(tmp_path / "Local" / "Android" / "Sdk")
    result = scan(str(tmp_path))
    found = compress.candidates(result)
    assert [p for p, _ in found] == [str(tmp_path / "Local" / "Programs" / "Editor"), sdk]
    assert sdk not in [p for p, _ in compress.candidates(result, exclude=[sdk])]


def test_compress_refuses_windows_roots_and_exclusions(tmp_path, make, monkeypatch):
    calls = []
    monkeypatch.setattr(actions, "_compact", lambda folder, sw: calls.append(sw))
    monkeypatch.setenv("WINDIR", str(tmp_path / "Windows"))
    make("Windows/System32/x.dll", 10)
    make("mine/a.bin", 10)
    values = settings.load()
    values["exclude"] = [str(tmp_path / "mine")]
    settings.save(values)
    for folder in (tmp_path / "Windows" / "System32", tmp_path / "mine", tmp_path / "none"):
        report = actions.compress(str(folder))
        assert report.skipped and not report.compressed
    assert calls == []
    with pytest.raises(ValueError):
        actions.compress(str(tmp_path), "ZIP")


def test_compressed_entry_is_restored_by_decompressing(tmp_path, make, monkeypatch):
    calls = []

    def fake(folder, switches):
        calls.append(switches)
        return subprocess.CompletedProcess([], 0, "", "")

    monkeypatch.setattr(actions, "_compact", fake)
    make("app/a.bin", 10)
    actions.compress(str(tmp_path / "app"), "LZX")
    entry = journal.load()[-1]
    assert (entry["mode"], entry["location"]) == (journal.COMPRESSED, "LZX")
    actions.restore(entry)
    assert calls == [["/C", "/EXE:LZX"], ["/U", "/EXE"]]
    assert journal.load()[-1]["state"] == "restored"


@pytest.mark.skipif(sys.platform != "win32", reason="compact.exe")
def test_real_compression_round_trip(tmp_path, make):
    """Our own small folder is compressed for real, then decompressed."""
    make("app/zeros.dll", content=b"\0" * (2 * MB))
    folder = str(tmp_path / "app")
    report = actions.compress(folder, "XPRESS4K")
    if not report.compressed:
        pytest.skip(f"compression not available here: {report.skipped}")
    assert compress.on_disk(folder)[1] < MB
    actions.uncompress(folder)
    assert compress.on_disk(folder)[1] >= 2 * MB
