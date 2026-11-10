import os

import pytest

from diskdiet import vhdx
from diskdiet.duplicates import HEAD, find_duplicates
from diskdiet.scanner import FileInfo


def info(path: str) -> FileInfo:
    return FileInfo(os.path.getsize(path), 0.0, path)


def test_finds_identical_content_only(make):
    body = os.urandom(HEAD + 500)
    a = make("a.bin", content=body)
    b = make("sub/b.bin", content=body)
    same_head = make("c.bin", content=body[:-1] + b"!")  # same size, differs at the very end
    other = make("d.bin", content=os.urandom(len(body)))
    groups = find_duplicates([info(p) for p in (a, b, same_head, other)], exclude=[])
    assert len(groups) == 1
    assert groups[0].paths == sorted([a, b]) and groups[0].wasted == len(body)


def test_hard_links_are_not_duplicates(make, tmp_path):
    a = make("a.bin", 4096)
    link = str(tmp_path / "link.bin")
    try:
        os.link(a, link)
    except OSError:
        pytest.skip("cannot create hard links here")
    assert find_duplicates([info(a), info(link)], exclude=[]) == []


def test_excluded_roots_are_ignored(make, tmp_path):
    a = make("keep/a.bin", 100)
    b = make("system/b.bin", 100)
    assert find_duplicates([info(a), info(b)], exclude=[str(tmp_path / "system")]) == []


def test_groups_sorted_by_recoverable_space(make):
    small = [make(f"s{i}.bin", content=b"s" * 10) for i in range(2)]
    large = [make(f"l{i}.bin", content=b"l" * 1000) for i in range(2)]
    groups = find_duplicates([info(p) for p in small + large], exclude=[])
    assert [g.size for g in groups] == [1000, 10]


def test_vhdx_kind():
    assert vhdx.kind(r"C:\Users\me\AppData\Local\Docker\wsl\disk\docker_data.vhdx") == "docker"
    assert vhdx.kind(r"C:\Users\me\AppData\Local\Packages\Ubuntu\LocalState\ext4.vhdx") == "wsl"
    assert vhdx.kind(r"C:\Users\me\AppData\Local\Claude\vm\rootfs.vhdx") == "other"


def test_diskpart_script():
    script = vhdx.diskpart_script(r"C:\data\disk one.vhdx")
    assert script.splitlines() == [
        r'select vdisk file="C:\data\disk one.vhdx"',
        "attach vdisk readonly", "compact vdisk", "detach vdisk",
    ]


@pytest.mark.parametrize("bad", ['C:\\a".vhdx', "C:\\a\nclean.vhdx", "relative.vhdx"])
def test_diskpart_script_rejects_unsafe_paths(bad):
    with pytest.raises(ValueError):
        vhdx.diskpart_script(bad)
