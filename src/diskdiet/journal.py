"""Log of everything DiskDiet removed or moved: one JSON object per line. No Qt here.

This module only records. The operations themselves (and restoring) are in actions.py.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime

from diskdiet import settings

TRASH, PERMANENT, MOVED = "trash", "permanent", "moved"


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
            entries.append(json.loads(line))
        except ValueError:
            continue  # a half-written line after a crash
    return entries


def mark_restored(entry_id: str) -> None:
    entries = load()
    for entry in entries:
        if entry["id"] == entry_id:
            entry["state"] = "restored"
    with open(_file(), "w", encoding="utf-8") as f:
        f.writelines(json.dumps(e) + "\n" for e in entries)
