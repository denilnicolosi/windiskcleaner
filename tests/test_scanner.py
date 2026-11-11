import os
import sys

import pytest

from windiskcleaner.scanner import MIN_TRACKED_FILE, PROGRESS_EVERY, ScanCancelled, key, scan


def test_sizes_roll_up(tmp_path, make):
    make("a/one.bin", 100)
    make("a/deep/two.bin", 250)
    make("b/three.txt", 7)
    result = scan(str(tmp_path))
    assert (result.root.size, result.root.files) == (357, 3)
    a = result.find(str(tmp_path / "a"))
    assert (a.size, a.files) == (350, 2)
    assert result.ext_sizes == {".bin": 350, ".txt": 7}


def test_depth_limit_keeps_totals(tmp_path, make):
    make("a/b/c/d/file.bin", 10)
    result = scan(str(tmp_path), max_depth=1)
    assert result.root.size == 10
    assert result.find(str(tmp_path / "a")).size == 10
    assert result.find(str(tmp_path / "a" / "b")) is None  # below the retained depth


def test_watch_paths_are_sized_below_depth_limit(tmp_path, make):
    make("a/b/c/cache/blob", 42)
    target = str(tmp_path / "a" / "b" / "c" / "cache")
    result = scan(str(tmp_path), max_depth=0, watch_paths=[target])
    assert result.watched == {key(target): 42}


def test_watch_names_do_not_nest(tmp_path, make):
    make("proj/node_modules/x/node_modules/y.js", 5)
    result = scan(str(tmp_path), watch_names=["node_modules"])
    assert [n.path for n in result.named] == [str(tmp_path / "proj" / "node_modules")]
    assert result.named[0].size == 5


def test_big_files_are_listed(tmp_path, make):
    big = make("big.bin", MIN_TRACKED_FILE)
    make("small.bin", MIN_TRACKED_FILE - 1)
    assert [f.path for f in scan(str(tmp_path)).big_files] == [big]


def test_links_are_not_followed(tmp_path, make):
    make("real/data.bin", 1000)
    link = tmp_path / "link"
    try:
        if sys.platform == "win32":
            import _winapi

            _winapi.CreateJunction(str(tmp_path / "real"), str(link))
        else:
            os.symlink(tmp_path / "real", link)
    except OSError:
        pytest.skip("cannot create links here")
    assert scan(str(tmp_path)).root.size == 1000


def test_unreadable_folder_is_counted_not_fatal(tmp_path):
    result = scan(str(tmp_path / "does-not-exist"))
    assert (result.root.size, result.denied) == (0, 1)


def test_cancel(tmp_path, make):
    for i in range(PROGRESS_EVERY):
        make(f"f{i}")
    with pytest.raises(ScanCancelled):
        scan(str(tmp_path), cancelled=lambda: True)


def test_worker_processes_give_the_same_result(tmp_path, make):
    make("top.bin", 3)
    make("a/b/shallow.txt", 7)
    make("a/b/c/d/e/deep.bin", MIN_TRACKED_FILE)
    make("a/b/c/node_modules/x/node_modules/pkg.js", 5)  # name found below the split
    make("node_modules/q/r/s/t.js", 9)  # name found above it
    make("w/x/y/z/cache/blob", 42)
    watch = [str(tmp_path / "w" / "x" / "y" / "z" / "cache"), str(tmp_path / "a" / "b" / "c")]
    kwargs = dict(watch_paths=watch, watch_names=["node_modules"], max_depth=4)
    one = scan(str(tmp_path), **kwargs)
    two = scan(str(tmp_path), workers=2, **kwargs)
    assert two.root == one.root
    assert sorted(two.big_files) == sorted(one.big_files)
    assert (two.ext_sizes, two.watched) == (one.ext_sizes, one.watched)
    assert sorted(n.path for n in two.named) == sorted(n.path for n in one.named)
    assert two.find(two.named[0].path) is not None


def test_cancel_with_worker_processes(tmp_path, make):
    make("a/b/c/d/file.bin", 1)
    with pytest.raises(ScanCancelled):
        scan(str(tmp_path), workers=2, cancelled=lambda: True)
