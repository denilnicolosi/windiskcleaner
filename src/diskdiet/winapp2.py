"""Community cleaning rules in the winapp2.ini format (CCleaner / BleachBit). Read-only.

The user imports a winapp2.ini they downloaded (Settings → Exclusions tab); DiskDiet
never downloads it. Its entries are not checked like the catalogue, so they only become
suggestions for the guided check, one folder at a time, never a one-click cleanup.

Only the simplest, safest part of the format is used: FileKeys that empty a whole folder
("folder|*.*"). Entries with exclusions or warnings are skipped.
"""

from __future__ import annotations

import glob
import os
import re
from dataclasses import dataclass

from diskdiet import rules, settings

FILE_NAME = "winapp2.ini"
WHOLE_FOLDER = {"*", "*.*"}


@dataclass(frozen=True)
class Entry:
    name: str
    folders: tuple[str, ...]  # as written, with %Variables%


def path() -> str:
    """Where the imported copy lives."""
    return os.path.join(settings.data_dir(), FILE_NAME)


def parse(text: str) -> list[Entry]:
    entries = []
    name, keys = None, []

    def close() -> None:
        if name is None:
            return
        if any(k in ("excludekey", "warning") for k, _v in keys):
            return  # needs care DiskDiet cannot give it
        folders = []
        for k, value in keys:
            if not k.startswith("filekey"):
                continue
            parts = value.split("|")
            if len(parts) >= 2 and parts[1].strip() in WHOLE_FOLDER and "\\" in parts[0]:
                folders.append(parts[0].strip().rstrip("\\"))
        if folders:
            entries.append(Entry(name, tuple(folders)))

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(";"):
            continue
        if line.startswith("[") and line.endswith("]"):
            close()
            name, keys = line[1:-1].strip(), []
        elif "=" in line and name is not None:
            k, value = line.split("=", 1)
            keys.append((re.sub(r"\d+$", "", k.strip().lower()), value.strip()))
    close()
    return entries


def _variables() -> dict[str, str]:
    env, profile = os.environ, os.environ.get("USERPROFILE", "")
    found = {
        "localappdata": env.get("LOCALAPPDATA", ""),
        "appdata": env.get("APPDATA", ""),
        "userprofile": profile,
        "commonappdata": env.get("PROGRAMDATA", ""),
        "programdata": env.get("PROGRAMDATA", ""),
        "temp": env.get("TEMP", ""),
        "tmp": env.get("TEMP", ""),
        "locallowappdata": os.path.join(profile, "AppData", "LocalLow") if profile else "",
        "documents": os.path.join(profile, "Documents") if profile else "",
    }
    return {k: v for k, v in found.items() if v}


def expand(folder: str, variables: dict[str, str] | None = None) -> str | None:
    """`folder` with its %Variables% replaced; None if one is unknown (e.g. %WinDir%,
    %ProgramFiles%: places DiskDiet never cleans)."""
    variables = _variables() if variables is None else variables
    missing = False

    def swap(match: re.Match) -> str:
        nonlocal missing
        value = variables.get(match[1].lower())
        if value is None:
            missing = True
            return ""
        return value

    result = re.sub(r"%([^%]+)%", swap, folder)
    return None if missing or "%" in result else os.path.normpath(result)


def folders(entries: list[Entry]) -> list[tuple[str, str]]:
    """(entry name, existing folder) for every whole-folder key that exists here."""
    variables = _variables()
    found = []
    for entry in entries:
        for folder in entry.folders:
            pattern = expand(folder, variables)
            if pattern is None:
                continue
            for match in glob.glob(pattern):
                if os.path.isdir(match) and not rules.through_link(match, pattern):
                    found.append((entry.name, match))
    return found


def load() -> list[tuple[str, str]]:
    """Folders of the imported winapp2.ini that exist on this machine ([] if none)."""
    try:
        with open(path(), encoding="utf-8", errors="replace") as f:
            return folders(parse(f.read()))
    except OSError:
        return []
