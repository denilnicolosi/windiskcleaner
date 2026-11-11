"""Log of everything WinDiskCleaner removed or moved: one JSON object per line. No Qt here.

This module only records. The operations themselves (and restoring) are in actions.py.
"""

from __future__ import annotations

import json
import os
import uuid
from collections.abc import Iterable
from datetime import datetime

from windiskcleaner import settings

TRASH, PERMANENT, MOVED = "trash", "permanent", "moved"
COMPRESSED = "compressed"  # still in place; `location` holds the algorithm
KEEP = 20000  # entries kept; the oldest go first


def _file() -> str:
    return os.path.join(settings.data_dir(), "deleted.jsonl")


def new_batch() -> str:
    """Id shared by every item of one cleanup, so the whole cleanup can be undone."""
    return uuid.uuid4().hex


def add(path: str, size: int, files: int, mode: str, location: str = "", source: str = "",
        batch: str = "") -> dict:
    """Record one removed item. `location` is where it is now (Recycle Bin or archive)."""
    entry = {
        "batch": batch,
        "id": uuid.uuid4().hex,
        "when": datetime.now().isoformat(timespec="seconds"),
        "path": path,
        "size": size,
        "files": files,
        "mode": mode,
        "location": location,
        "source": source,
        "state": "removed",
    }
    os.makedirs(settings.data_dir(), exist_ok=True)
    with open(_file(), "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def load() -> list[dict]:
    try:
        with open(_file(), encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return []
    entries = []
    for line in lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue  # a half-written line after a crash
        if isinstance(entry, dict) and {"id", "path", "mode", "state"} <= entry.keys():
            entries.append(entry)
    return entries


def _write(entries: list[dict]) -> None:
    settings.write_atomic(_file(), "".join(json.dumps(e) + "\n" for e in entries))


def trim(keep: int = KEEP) -> None:
    """Forget the oldest entries once the log has grown past `keep`."""
    entries = load()
    if len(entries) > keep:
        _write(entries[-keep:])


def mark(ids: Iterable[str], state: str) -> None:
    """Set the state of many entries with one rewrite of the file."""
    wanted = set(ids)
    if not wanted:
        return
    entries = load()
    for entry in entries:
        if entry["id"] in wanted:
            entry["state"] = state
    _write(entries)


def mark_restored(entry_id: str) -> None:
    mark([entry_id], "restored")
