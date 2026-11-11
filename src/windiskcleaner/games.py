"""Installed games of Steam and Epic, with size and last time played. Read-only.

Games are often the biggest things on a disk and the launchers know them better than
any folder scan: Steam records the size and the last launch of every game.
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
from dataclasses import dataclass

STEAM_URI = "steam://uninstall/{id}"  # Steam asks the user to confirm


@dataclass(frozen=True)
class Game:
    name: str
    launcher: str  # "Steam" | "Epic"
    path: str
    size: int
    last_played: float = 0.0  # epoch seconds, 0 = unknown / never
    app_id: str = ""


def _number(value) -> int:
    """A number from a launcher's file; 0 when it is missing or damaged."""
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


_TOKEN = re.compile(r'"((?:[^"\\]|\\.)*)"|([{}])')


def vdf(text: str) -> dict:
    """Valve's KeyValues text format ("key" "value" / "key" { ... }) as nested dicts."""
    root: dict = {}
    stack = [root]
    pending: str | None = None
    for quoted, brace in _TOKEN.findall(text):
        if brace == "{":
            child: dict = {}
            stack[-1][pending or ""] = child
            stack.append(child)
            pending = None
        elif brace == "}":
            if len(stack) > 1:
                stack.pop()
            pending = None
        elif pending is None:
            pending = quoted.replace("\\\\", "\\")
        else:
            stack[-1][pending] = quoted.replace("\\\\", "\\")
            pending = None
    return root


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read()
    except OSError:
        return ""


def steam_games(steam_root: str) -> list[Game]:
    libraries = {os.path.normpath(steam_root)}
    folders = vdf(_read(os.path.join(steam_root, "steamapps", "libraryfolders.vdf")))
    listed = folders.get("libraryfolders", {})
    for entry in listed.values() if isinstance(listed, dict) else ():
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            libraries.add(os.path.normpath(entry["path"]))
    games = []
    for library in sorted(libraries):
        apps = os.path.join(library, "steamapps")
        for manifest in glob.glob(os.path.join(glob.escape(apps), "appmanifest_*.acf")):
            state = vdf(_read(manifest)).get("AppState", {})
            if not isinstance(state, dict) or not isinstance(state.get("installdir"), str):
                continue
            games.append(Game(
                state.get("name", state["installdir"]), "Steam",
                os.path.join(apps, "common", state["installdir"]),
                _number(state.get("SizeOnDisk")),
                float(_number(state.get("LastPlayed"))),
                state.get("appid", ""),
            ))
    return games


def epic_games(manifests: str) -> list[Game]:
    games = []
    for item in glob.glob(os.path.join(glob.escape(manifests), "*.item")):
        try:
            data = json.loads(_read(item))
        except ValueError:
            continue
        if isinstance(data, dict) and isinstance(data.get("InstallLocation"), str):
            games.append(Game(
                data.get("DisplayName", data.get("AppName", "?")), "Epic",
                os.path.normpath(data["InstallLocation"]), _number(data.get("InstallSize")),
                app_id=data.get("AppName", ""),
            ))
    return games


def _steam_root() -> str:
    if sys.platform == "win32":
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                return os.path.normpath(winreg.QueryValueEx(k, "SteamPath")[0])
        except OSError:
            pass
    return os.path.expandvars(r"%ProgramFiles(x86)%\Steam")


def installed_games() -> list[Game]:
    """Every game Steam or Epic knows, biggest first; only those still on disk."""
    found = steam_games(_steam_root()) + epic_games(os.path.expandvars(
        r"%ProgramData%\Epic\EpicGamesLauncher\Data\Manifests"))
    return sorted((g for g in found if os.path.isdir(g.path)), key=lambda g: -g.size)
