"""User preferences, stored as JSON in %LOCALAPPDATA%\\WinDiskCleaner. No Qt here."""

from __future__ import annotations

import json
import os

DEFAULTS = {
    "theme": "system",  # system | light | dark
    "language": "auto",  # auto | en | it
    "check_updates": True,
    "old_days": 730,
    "dup_min_mb": 1,
    "exclude": [],  # folders and files WinDiskCleaner must never propose or remove
}


def data_dir() -> str:
    """Folder for settings and the deletion log. WINDISKCLEANER_HOME overrides it (tests)."""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    return os.environ.get("WINDISKCLEANER_HOME") or os.path.join(base, "WinDiskCleaner")


OLD_NAME = "DiskDiet"  # the program's name before 0.2.0


def migrate_old_home() -> str:
    """Rename the data folder of the former name (settings, log of removed items, scan
    history) to the current one, once. Returns the old path when it moved, else ""."""
    if os.environ.get("WINDISKCLEANER_HOME"):
        return ""
    base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    old, new = os.path.join(base, OLD_NAME), data_dir()
    if not os.path.isdir(old) or os.path.exists(new):
        return ""
    try:
        os.rename(old, new)  # same drive: instant; the old log file keeps its name
    except OSError:
        return ""  # in use (old version still open): the new folder starts empty
    return old


def write_atomic(path: str, text: str) -> None:
    """Replace a file in one step: a crash halfway leaves the old version, not half a file."""
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(temporary, path)


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
    write_atomic(_file(), json.dumps({k: values[k] for k in DEFAULTS}, indent=2))
