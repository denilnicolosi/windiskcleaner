"""Summaries of past scans, to show what grew since the last one. Records only.

One JSON line per scan in `%LOCALAPPDATA%\\DiskDiet\\history.jsonl`: the root, its total
and the size of every folder down to DEPTH levels that is at least MIN_FOLDER. Paths
stay on this machine, like the log.
"""

from __future__ import annotations

import json
import os
from datetime import datetime

from diskdiet import settings
from diskdiet.scanner import ScanResult, key, under

DEPTH = 4
MIN_FOLDER = 20 << 20
KEEP = 10  # scans kept per root
MIN_CHANGE = 100 << 20  # smaller changes are not worth a line


def _file() -> str:
    return os.path.join(settings.data_dir(), "history.jsonl")


def summary(result: ScanResult, when: str | None = None) -> dict:
    folders: dict[str, int] = {}
    stack = [(result.root, 0)]
    while stack:
        node, depth = stack.pop()
        if node.size >= MIN_FOLDER:
            folders[node.path] = node.size
        if depth < DEPTH:
            stack += [(child, depth + 1) for child in node.children]
    return {
        "when": when or datetime.now().isoformat(timespec="seconds"),
        "root": result.root.path,
        "total": result.root.size,
        "files": result.root.files,
        "folders": folders,
    }


def load() -> list[dict]:
    try:
        with open(_file(), encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entries.append(json.loads(line))
        except ValueError:
            continue
    return entries


def previous(root: str) -> dict | None:
    """The last saved scan of the same root."""
    same = [e for e in load() if key(e.get("root", "")) == key(root)]
    return same[-1] if same else None


def save(result: ScanResult) -> dict:
    """Record this scan, keeping the last KEEP scans of each root."""
    entry = summary(result)
    entries = load() + [entry]
    k = key(entry["root"])
    mine = [e for e in entries if key(e.get("root", "")) == k]
    drop = {id(e) for e in mine[:-KEEP]}
    os.makedirs(settings.data_dir(), exist_ok=True)
    with open(_file(), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(e) + "\n" for e in entries if id(e) not in drop)
    return entry


def growth(before: dict, after: dict) -> list[tuple[str, int, int]]:
    """(folder, size before, size after) of the folders that changed most, biggest change
    first. A folder is left out when its changed subfolders explain most of its change,
    so each line points at where the change really is."""
    old, new = before["folders"], after["folders"]
    changed = []
    for path in set(old) | set(new):
        a, b = old.get(path, 0), new.get(path, 0)
        if abs(b - a) >= MIN_CHANGE:
            changed.append((path, a, b))
    deltas = {key(p): b - a for p, a, b in changed}
    kept = []
    for path, a, b in changed:
        k = key(path)
        below = [c for c in deltas if under(c, k)]
        # Only the topmost changed subfolders: deeper ones are already inside them.
        top = [c for c in below if not any(under(c, o) for o in below)]
        if abs(sum(deltas[c] for c in top)) < abs(b - a) * 0.8:
            kept.append((path, a, b))
    return sorted(kept, key=lambda row: -abs(row[2] - row[1]))
