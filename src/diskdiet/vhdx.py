"""Find Docker/WSL virtual disks and compact them with diskpart.

This is the only part of DiskDiet that asks for administrator rights (one UAC prompt).
"""

from __future__ import annotations

import os
import subprocess
import tempfile
from collections.abc import Iterable

from diskdiet.scanner import FileInfo

NO_WINDOW = 0x08000000


def kind(path: str) -> str:
    """'docker' or 'wsl' (compactable here) or 'other' (reported only)."""
    low = path.lower()
    if "\\docker\\" in low:
        return "docker"
    if low.endswith("\\ext4.vhdx") or "\\wsl\\" in low:
        return "wsl"
    return "other"


def find(files: Iterable[FileInfo]) -> list[FileInfo]:
    return sorted(f for f in files if f.path.lower().endswith(".vhdx"))[::-1]


def diskpart_script(path: str) -> str:
    if any(c in path for c in '"\r\n') or not os.path.isabs(path):
        raise ValueError(f"unsafe virtual disk path: {path!r}")
    return (
        f'select vdisk file="{path}"\n'
        "attach vdisk readonly\n"
        "compact vdisk\n"
        "detach vdisk\n"
    )


def _script_file(path: str) -> str:
    """Shut WSL down and write the diskpart script; returns the script's path."""
    script = diskpart_script(path)
    if kind(path) == "other":
        raise ValueError("only Docker and WSL disks are compacted")
    subprocess.run(["wsl", "--shutdown"], timeout=120, creationflags=NO_WINDOW)
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(script)
    return f.name


def prepare(path: str) -> list[str]:
    """For an already elevated DiskDiet: the diskpart command to run in its own terminal."""
    return ["diskpart", "/s", _script_file(path)]


def compact(path: str) -> None:
    """Shut WSL down, then run diskpart elevated. Returns once diskpart has been started."""
    import ctypes

    script = _script_file(path)
    # cmd /k keeps the window open so the user can read diskpart's outcome.
    args = f'/k diskpart /s "{script}" & del "{script}"'
    if ctypes.windll.shell32.ShellExecuteW(None, "runas", "cmd.exe", args, None, 1) <= 32:
        os.unlink(script)
        raise OSError("administrator rights were not granted")
