"""Transparent NTFS compression (Windows' own compact.exe, WOF): what is worth compressing
and how much it would save. Read-only: compressing itself is actions.compress.

Compressed files stay where they are and open as usual; Windows decompresses them in
memory. Best for folders that are read a lot and rarely written: programs, SDKs, games.
A file a program rewrites is stored uncompressed again.
"""

from __future__ import annotations

import os
import stat
import sys
import zlib
from collections.abc import Iterable

from windiskcleaner.scanner import key, under

ALGORITHMS = ("XPRESS4K", "XPRESS8K", "XPRESS16K", "LZX")  # faster ... smaller
DEFAULT = "XPRESS8K"
# Already compressed: compact gains nothing on these, the estimate counts them as 1:1.
PACKED = {
    ".zip", ".7z", ".rar", ".gz", ".xz", ".bz2", ".zst", ".cab", ".msi", ".jar", ".apk",
    ".nupkg", ".whl", ".jpg", ".jpeg", ".png", ".gif", ".webp", ".mp3", ".mp4", ".mkv",
    ".avi", ".mov", ".webm", ".ogg", ".flac", ".m4a", ".pak", ".bk2", ".bik", ".usm",
}
MIN_FILE = 4096  # WOF leaves files this small as they are
SAMPLE = 64 * 1024  # bytes read from the start of each file for the estimate
SAMPLE_BUDGET = 64 << 20  # total bytes read for one estimate
CANDIDATE_MIN = 300 << 20

# Folders proposed for compression when they exist: installed tools that are read, not
# written. Program Files is left to the user (right-click any folder → Compress).
CANDIDATES = (
    r"%LOCALAPPDATA%\Programs\*",
    r"%LOCALAPPDATA%\Android\Sdk",
    r"%LOCALAPPDATA%\Arduino15\packages",
    r"%LOCALAPPDATA%\nvm\v*",
    r"%LOCALAPPDATA%\JetBrains\Toolbox\apps\*",
    r"%USERPROFILE%\.vscode\extensions",
    r"%USERPROFILE%\.gradle\caches",
    r"%USERPROFILE%\.m2\repository",
    r"%USERPROFILE%\scoop\apps",
)


def allocated(path: str) -> int:
    """Bytes a file really takes, compression included (logical size off Windows)."""
    if sys.platform != "win32":
        return os.lstat(path).st_size
    import ctypes

    kernel32 = ctypes.windll.kernel32
    kernel32.GetCompressedFileSizeW.restype = ctypes.c_ulong
    high = ctypes.c_ulong(0)
    low = kernel32.GetCompressedFileSizeW(path, ctypes.byref(high))
    if low == 0xFFFFFFFF and ctypes.GetLastError():
        return os.lstat(path).st_size
    return (high.value << 32) + low


def _files(root: str) -> Iterable[tuple[str, int]]:
    """(path, size) of every regular file below `root`; links and junctions not followed."""
    stack = [root]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    attrs = getattr(st, "st_file_attributes", 0)
                    if attrs & stat.FILE_ATTRIBUTE_REPARSE_POINT or stat.S_ISLNK(st.st_mode):
                        continue
                    if stat.S_ISDIR(st.st_mode):
                        stack.append(entry.path)
                    elif stat.S_ISREG(st.st_mode):
                        yield entry.path, st.st_size
        except OSError:
            continue


def on_disk(root: str) -> tuple[int, int, int]:
    """(logical bytes, bytes really used, files) of a folder."""
    logical = used = count = 0
    for path, size in _files(root):
        try:
            used += allocated(path)
        except OSError:
            continue
        logical += size
        count += 1
    return logical, used, count


def estimate(root: str) -> float:
    """Expected size after compression as a fraction of today's (0.4 = saves 60 %).

    ponytail: zlib on the first 64 KB of each file stands in for XPRESS/LZX; real ratios
    are close (LZX a little better). Compress one folder and compare to calibrate.
    """
    total = after = budget = 0
    for path, size in _files(root):
        total += size
        if size < MIN_FILE or os.path.splitext(path)[1].lower() in PACKED:
            after += size
            continue
        if budget >= SAMPLE_BUDGET:
            after += size * 0.6  # typical for programs once the sample budget is spent
            continue
        try:
            with open(path, "rb") as f:
                chunk = f.read(SAMPLE)
        except OSError:
            after += size
            continue
        budget += len(chunk)
        ratio = len(zlib.compress(chunk, 6)) / len(chunk) if chunk else 1.0
        after += size * min(1.0, ratio)
    return after / total if total else 1.0


def candidates(result, exclude: Iterable[str] = ()) -> list[tuple[str, int]]:
    """(folder, size) of catalogue folders inside the scan worth compressing, biggest first."""
    import glob

    from windiskcleaner.advisor import measure

    root, keys = key(result.root.path), [key(p) for p in exclude]
    found = []
    for pattern in CANDIDATES:
        expanded = os.path.expandvars(pattern)
        if "%" in expanded:
            continue
        for path in glob.glob(expanded):
            k = key(path)
            if not os.path.isdir(path) or not under(k, root):
                continue
            if any(k == e or under(k, e) or under(e, k) for e in keys):
                continue
            size = measure(path, result)
            if size >= CANDIDATE_MIN:
                found.append((path, size))
    return sorted(found, key=lambda pair: -pair[1])
