"""Duplicate finder: same size, then same first 64 KB, then same full content.

Hashing runs on a thread pool: the work is disk reads and hashlib, both of which release
the GIL. Expect a clear gain on SSDs and little on spinning disks.
"""

from __future__ import annotations

import hashlib
import os
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

from diskdiet.scanner import FileInfo, ScanCancelled, key, under

HEAD = 64 << 10
CHUNK = 1 << 20


@dataclass
class DupGroup:
    size: int
    paths: list[str]

    @property
    def wasted(self) -> int:
        return self.size * (len(self.paths) - 1)


def default_excludes() -> list[str]:
    """Windows and program folders: identical DLLs there are normal and must stay."""
    names = ("WINDIR", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "PROGRAMDATA")
    return [os.environ[n] for n in names if n in os.environ]


def _digest(path: str, limit: int | None, cancelled) -> bytes | None:
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            if limit is not None:
                h.update(f.read(limit))
            else:
                while chunk := f.read(CHUNK):
                    if cancelled and cancelled():
                        raise ScanCancelled
                    h.update(chunk)
    except OSError:
        return None  # locked or unreadable: cannot be proven a duplicate
    return h.digest()


def _identity(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_dev, st.st_ino


def _refine(pool, groups, limit, weight, progress, cancelled, done, total):
    """Split each (size, paths) group by a digest of its files. Returns (groups, done)."""
    flat = [(size, path) for size, paths in groups for path in paths]
    digests = pool.map(lambda sp: _digest(sp[1], limit, cancelled), flat)
    split: dict[tuple[int, bytes], list[str]] = defaultdict(list)
    for (size, path), digest in zip(flat, digests, strict=True):
        if cancelled and cancelled():
            raise ScanCancelled
        done += weight(size)
        if progress:
            progress(done, total)
        if digest is not None:
            split[size, digest].append(path)
    return [(size, paths) for (size, _d), paths in split.items() if len(paths) > 1], done


def find_duplicates(
    files: Iterable[FileInfo],
    *,
    exclude: Iterable[str] | None = None,
    min_size: int = 1,
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[DupGroup]:
    """Groups of identical files, most recoverable space first.

    progress(done, total) counts bytes to read, so it moves at the speed of the disk.
    """
    excluded = [key(p) for p in (default_excludes() if exclude is None else exclude)]
    by_size: dict[int, list[str]] = defaultdict(list)
    for f in files:
        k = key(f.path)
        if f.size >= min_size and not any(under(k, root) for root in excluded):
            by_size[f.size].append(f.path)
    groups = [(size, paths) for size, paths in by_size.items() if len(paths) > 1]

    with ThreadPoolExecutor(workers or min(8, (os.cpu_count() or 4))) as pool:
        # Hard links are one file under several names: removing one frees nothing.
        flat = [(size, path) for size, paths in groups for path in paths]
        distinct: dict[int, dict[tuple[int, int], str]] = defaultdict(dict)
        for (size, path), ident in zip(flat, pool.map(lambda sp: _identity(sp[1]), flat),
                                       strict=True):
            if ident is not None:
                distinct[size].setdefault(ident, path)
        groups = [(s, list(d.values())) for s, d in distinct.items() if len(d) > 1]

        def head(size):
            return min(size, HEAD)

        # The total is an upper bound: files eliminated by the first pass are never read whole.
        total = sum((head(s) + s) * len(p) for s, p in groups) or 1
        groups, done = _refine(pool, groups, HEAD, head, progress, cancelled, 0, total)
        total = done + sum(s * len(p) for s, p in groups) or 1
        groups, _ = _refine(pool, groups, None, lambda s: s, progress, cancelled, done, total)

    return sorted((DupGroup(s, sorted(p)) for s, p in groups), key=lambda g: -g.wasted)
