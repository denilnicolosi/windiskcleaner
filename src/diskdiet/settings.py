"""User preferences, stored as JSON in %LOCALAPPDATA%\\DiskDiet. No Qt here."""

from __future__ import annotations

import json
import os

DEFAULTS = {
    "theme": "system",  # system | light | dark
    "language": "auto",  # auto | en | it
    "check_updates": True,
    "old_days": 730,
    "dup_min_mb": 1,
    "exclude": [],  # folders and files DiskDiet must never propose or remove
}


def data_dir() -> str:
    """Folder for settings and the deletion log. DISKDIET_HOME overrides it (tests)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.environ.get("DISKDIET_HOME") or os.path.join(base, "DiskDiet")


def _file() -> str:
    return os.path.join(data_dir(), "settings.json")


def load() -> dict:
    values = dict(DEFAULTS)
    try:
        with open(_file(), encoding="utf-8") as f:
            stored = json.load(f)
    except (OSError, ValueError):
        return values
    # Unknown keys and wrong types are ignored: a damaged file must not stop the program.
    for name, default in DEFAULTS.items():
        if type(stored.get(name)) is type(default):
            values[name] = stored[name]
    values["exclude"] = [p for p in values["exclude"] if isinstance(p, str) and p]
    return values


def save(values: dict) -> None:
    os.makedirs(data_dir(), exist_ok=True)
    with open(_file(), "w", encoding="utf-8") as f:
        json.dump({k: values[k] for k in DEFAULTS}, f, indent=2)
