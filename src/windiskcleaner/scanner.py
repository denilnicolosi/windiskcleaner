"""Filesystem scanner. Pure stdlib: no Qt imports in this module (see CLAUDE.md).

Single-threaded on purpose. A thread-pool version was measured on a 360 GB system drive
(2.2 M files): 105 s with one thread, 867 s with two, 586 s with six. The walk is millions
of very short calls, and Python threads spend their time handing the interpreter lock to
each other. Going faster would take processes or native code, not threads.

`scan(workers=N)` is the process version (the window uses it for full scans): the parent walks the
top SPLIT_DEPTH levels, worker processes walk the folders below, and the parent walks the
top again using their results.
"""

from __future__ import annotations

import multiprocessing
import os
import stat
import time
from collections import defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import NamedTuple

REPARSE_POINT = 0x400  # junctions, symlinks: skipped, their target is counted where it lives
CLOUD_PLACEHOLDER = 0x400000 | 0x1000  # OneDrive files that are not on disk
MIN_TRACKED_FILE = 1 << 20  # files at least this big are listed individually
PROGRESS_EVERY = 5000
# ponytail: fixed split depth. A single huge folder at this depth (one user's AppData) is one
# job and caps the speed-up; split big jobs further if the benchmark shows one worker lagging.
SPLIT_DEPTH = 3
# Processes for a full scan from the window. Measured on a 374 GB system drive (2.2 M files,
# 6 cores, SSD): 80 s with one, 48 s with four, no gain beyond.
# ponytail: same number on every disk. A spinning disk gains nothing from it and may lose;
# detect the media type (or add a setting) if someone reports a slower scan.
DEFAULT_WORKERS = min(4, os.cpu_count() or 1)


class ScanCancelled(Exception):
    pass


def key(path: str) -> str:
    """Canonical form for comparing paths."""
    return os.path.normcase(os.path.normpath(path))


def under(path: str, root: str) -> bool:
    """True if `path` is strictly inside `root` (both already passed through key())."""
    return path.startswith(root.rstrip(os.sep) + os.sep)


@dataclass(slots=True)
class Node:
    path: str
    size: int = 0
    files: int = 0
    newest: float = 0.0  # most recent modification time of any file below
    children: list[Node] = field(default_factory=list)

    @property
    def name(self) -> str:
        return os.path.basename(self.path.rstrip("\\/")) or self.path


class FileInfo(NamedTuple):
    size: int
    mtime: float
    path: str


@dataclass
class ScanResult:
    root: Node
    big_files: list[FileInfo] = field(default_factory=list)  # every file >= MIN_TRACKED_FILE
    ext_sizes: dict[str, int] = field(default_factory=dict)
    watched: dict[str, int] = field(default_factory=dict)  # key(path) -> size
    named: list[Node] = field(default_factory=list)  # directories matching watch_names
    denied: int = 0
    cloud_bytes: int = 0
    seconds: float = 0.0

    def find(self, path: str) -> Node | None:
        """Node for `path`, if it is within the retained depth of the tree."""
        target = key(path)
        node = self.root
        while key(node.path) != target:
            for child in node.children:
                k = key(child.path)
                if target == k or under(target, k):
                    node = child
                    break
            else:
                return None
        return node


class _Walk:
    """One walk of a tree, with its counters."""

    def __init__(self, watch, names, max_depth, progress, cancelled):
        self.watch, self.names, self.max_depth = watch, names, max_depth
        self.progress, self.cancelled = progress, cancelled
        self.big: list[FileInfo] = []
        self.ext: dict[str, int] = defaultdict(int)
        self.watched: dict[str, int] = {}
        self.named: list[Node] = []
        self.denied = self.cloud = 0
        self.files = self.bytes = 0
        self.split = -1  # parallel scan only: depth at which folders go to worker processes
        self.jobs: list[tuple[str, int, bool]] | None = None  # first pass: collect them
        self.done: dict[str, Node] = {}  # second pass: their results

    def subtree(self, path: str, depth: int, in_named: bool) -> Node:
        if depth == self.split:
            if self.jobs is not None:
                self.jobs.append((path, depth, in_named))
                return Node(path)
            if path in self.done:  # absent: the folder appeared between the two passes
                return self.done[path]
        return self.walk(path, depth, in_named)

    def tick(self, path: str) -> None:
        if self.cancelled and self.cancelled():
            raise ScanCancelled
        if self.progress:
            self.progress(self.files, path, self.bytes)

    # ponytail: plain recursion, one frame per directory level. Real trees are < 100 deep;
    # switch to an explicit stack if RecursionError ever shows up.
    def walk(self, path: str, depth: int, in_named: bool) -> Node:
        node = Node(path)
        try:
            entries = os.scandir(path)
        except OSError:
            self.denied += 1
            return node
        with entries:
            while True:
                try:
                    entry = next(entries)
                except StopIteration:
                    break
                except OSError:
                    self.denied += 1
                    break
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    self.denied += 1
                    continue
                attrs = getattr(st, "st_file_attributes", 0)
                is_dir = stat.S_ISDIR(st.st_mode)
                if not is_dir and attrs & CLOUD_PLACEHOLDER:
                    self.cloud += st.st_size
                    continue
                if attrs & REPARSE_POINT or stat.S_ISLNK(st.st_mode):
                    continue
                if is_dir:
                    hit = not in_named and entry.name.lower() in self.names
                    child = self.subtree(entry.path, depth + 1, in_named or hit)
                    node.size += child.size
                    node.files += child.files
                    node.newest = max(node.newest, child.newest)
                    if depth < self.max_depth:
                        node.children.append(child)
                    if hit:
                        self.named.append(child)
                    if self.watch:
                        k = key(child.path)
                        if k in self.watch:
                            self.watched[k] = child.size
                    continue
                size = st.st_size
                node.size += size
                node.files += 1
                if st.st_mtime > node.newest:
                    node.newest = st.st_mtime
                self.ext[os.path.splitext(entry.name)[1].lower()] += size
                if size >= MIN_TRACKED_FILE:
                    self.big.append(FileInfo(size, st.st_mtime, entry.path))
                self.files += 1
                self.bytes += size
                if self.files % PROGRESS_EVERY == 0:
                    self.tick(path)
        return node


_worker_args: tuple = ()


def _init_worker(*args) -> None:
    global _worker_args
    _worker_args = args


def _job(job: tuple[str, int, bool]) -> tuple[str, Node, _Walk]:
    walk = _Walk(*_worker_args, None, None)
    node = walk.walk(*job)
    walk.watch = walk.names = None  # not needed back; keeps the pickled result small
    return job[0], node, walk


def _parallel(root: str, walk: _Walk, workers: int) -> Node:
    """Fill `walk` like walk.walk(root, 0, False) would, using worker processes."""
    args = (walk.watch, walk.names, walk.max_depth)
    first = _Walk(*args, None, None)
    first.split, first.jobs = SPLIT_DEPTH, []
    first.walk(root, 0, False)
    if not first.jobs:  # shallow tree: nothing worth starting processes for
        return walk.walk(root, 0, False)
    # ponytail: progress moves once per finished folder, not every PROGRESS_EVERY files.
    with multiprocessing.Pool(workers, _init_worker, args) as pool:  # exit terminates it
        results = pool.imap_unordered(_job, first.jobs)
        while True:
            try:
                path, node, part = results.next(timeout=0.2)
            except StopIteration:
                break
            except multiprocessing.TimeoutError:
                walk.tick(root)  # lets a cancel through while a big folder is running
                continue
            walk.done[path] = node
            walk.big += part.big
            for ext, size in part.ext.items():
                walk.ext[ext] += size
            walk.watched.update(part.watched)
            walk.named += part.named
            walk.denied += part.denied
            walk.cloud += part.cloud
            walk.files += part.files
            walk.bytes += part.bytes
            walk.tick(path)
    walk.split = SPLIT_DEPTH
    return walk.walk(root, 0, False)


def scan(
    root: str,
    *,
    watch_paths: Iterable[str] = (),
    watch_names: Iterable[str] = (),
    max_depth: int = 6,
    progress: Callable[[int, str, int], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
    workers: int = 1,
) -> ScanResult:
    """Walk `root` and return sizes.

    watch_paths: directories whose total size is recorded even below max_depth.
    watch_names: directory names (e.g. node_modules) whose every occurrence is recorded.
    progress(files, current_path, bytes): running totals, every PROGRESS_EVERY files.
    workers: more than 1 walks with that many processes (no gain expected on spinning disks).
    """
    started = time.monotonic()
    root = os.path.abspath(root)
    walk = _Walk({key(p) for p in watch_paths}, {n.lower() for n in watch_names}, max_depth,
                 progress, cancelled)
    node = _parallel(root, walk, workers) if workers > 1 else walk.walk(root, 0, False)
    walk.tick(root)  # final totals
    return ScanResult(
        root=node, big_files=walk.big, ext_sizes=dict(walk.ext), watched=walk.watched,
        named=walk.named, denied=walk.denied, cloud_bytes=walk.cloud,
        seconds=time.monotonic() - started,
    )
