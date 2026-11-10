"""Read-only facts about the machine: drives and installed programs."""

from __future__ import annotations

import shutil
import string
import subprocess
import sys
from dataclasses import dataclass

UNINSTALL = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
DRIVE_FIXED = 3
NO_WINDOW = 0x08000000


@dataclass(frozen=True)
class Volume:
    root: str  # "C:\\"
    total: int
    free: int
    fixed: bool


@dataclass(frozen=True)
class Program:
    name: str
    publisher: str
    size: int  # bytes, as declared by the installer; 0 when unknown
    installed: str  # YYYYMMDD or ""
    uninstall: str = ""  # the program's own uninstaller command line


def is_admin() -> bool:
    if sys.platform != "win32":
        return False
    import ctypes

    return bool(ctypes.windll.shell32.IsUserAnAdmin())


def volumes() -> list[Volume]:
    if sys.platform != "win32":
        return []
    import ctypes

    kernel32 = ctypes.windll.kernel32
    mask = kernel32.GetLogicalDrives()
    found = []
    for i, letter in enumerate(string.ascii_uppercase):
        if not mask >> i & 1:
            continue
        root = f"{letter}:\\"
        try:
            usage = shutil.disk_usage(root)
        except OSError:  # empty card reader, disconnected network drive
            continue
        fixed = kernel32.GetDriveTypeW(root) == DRIVE_FIXED
        found.append(Volume(root, usage.total, usage.free, fixed))
    return found


def running(image: str) -> bool:
    """Whether a process with this executable name ("chrome.exe") is running."""
    if sys.platform != "win32" or not image:
        return False
    try:
        out = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {image}", "/NH"],
            capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    return image.lower() in out.lower()


def installed_programs() -> list[Program]:
    """Programs listed in “Installed apps”, biggest first."""
    if sys.platform != "win32":
        return []
    import winreg

    def value(k, name, default):
        try:
            return winreg.QueryValueEx(k, name)[0]
        except OSError:
            return default

    programs: dict[str, Program] = {}
    views = (
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_64KEY),
        (winreg.HKEY_LOCAL_MACHINE, winreg.KEY_WOW64_32KEY),
        (winreg.HKEY_CURRENT_USER, 0),
    )
    for hive, view in views:
        try:
            base = winreg.OpenKey(hive, UNINSTALL, 0, winreg.KEY_READ | view)
        except OSError:
            continue
        with base:
            for i in range(winreg.QueryInfoKey(base)[0]):
                try:
                    with winreg.OpenKey(base, winreg.EnumKey(base, i)) as k:
                        name = value(k, "DisplayName", "")
                        if not name or value(k, "SystemComponent", 0) == 1:
                            continue
                        size = value(k, "EstimatedSize", 0)
                        size = size * 1024 if isinstance(size, int) else 0
                        prog = Program(
                            str(name), str(value(k, "Publisher", "")), size,
                            str(value(k, "InstallDate", "")),
                            str(value(k, "UninstallString", "")),
                        )
                except OSError:
                    continue
                if prog.name not in programs or programs[prog.name].size < prog.size:
                    programs[prog.name] = prog
    return sorted(programs.values(), key=lambda p: -p.size)
