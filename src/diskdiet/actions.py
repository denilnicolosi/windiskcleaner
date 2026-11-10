"""Everything that changes the user's machine goes through this module, and nowhere else."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from diskdiet import journal
from diskdiet.log import logger
from diskdiet.scanner import key, scan, under

# The one-file exe unpacks itself into %TEMP%: cleaning temporary files must not delete it.
_OWN_RUNTIME = key(sys._MEIPASS) if hasattr(sys, "_MEIPASS") else ""
ARCHIVE_FOLDER = "DiskDiet-Archive"


@dataclass
class Report:
    freed: int = 0  # bytes no longer where they were (trashed + permanent + moved)
    deleted: int = 0  # items
    trashed: int = 0  # bytes now in the Recycle Bin: not free until it is emptied
    permanent: int = 0
    moved: int = 0  # bytes now on another drive
    skipped: list[tuple[str, str]] = field(default_factory=list)  # (path, reason)

    def merge(self, other: Report) -> None:
        self.freed += other.freed
        self.deleted += other.deleted
        self.trashed += other.trashed
        self.permanent += other.permanent
        self.moved += other.moved
        self.skipped += other.skipped


def _logged(what: str, report: Report) -> Report:
    logger.info("%s: %d items, %d bytes (bin %d, permanent %d, moved %d), %d skipped", what,
                report.deleted, report.freed, report.trashed, report.permanent, report.moved,
                len(report.skipped))
    for path, why in report.skipped:
        logger.warning("%s skipped: %s (%s)", what, path, why)
    return report


def is_protected(path: str) -> bool:
    """Hard-wired never-touch list. Checked again right before every deletion."""
    k = key(path)
    env = os.environ
    if os.path.splitdrive(k)[1] in ("", os.sep):
        return True  # a drive root
    windir = key(env.get("WINDIR", r"C:\Windows"))
    if k == windir or under(k, windir):
        return not under(k, os.path.join(windir, "temp"))
    for var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        root = key(env[var]) if var in env else None
        if root and (k == root or under(k, root)):
            return True
    profile = key(env.get("USERPROFILE", os.path.expanduser("~")))
    if k == profile:
        return True
    if not under(k, os.path.dirname(profile)) or under(k, profile):
        return False
    # Under C:\Users but outside the profile: someone else's profile, or this one under another
    # name (8.3 short name like RUNNER~1 in %TEMP%, junction). Only this branch pays for realpath.
    return not under(key(os.path.realpath(path)), key(os.path.realpath(profile)))


def preview(targets: Iterable[str]) -> list[str]:
    """What would be removed: the contents of directory targets, and file targets themselves."""
    items: list[str] = []
    for target in targets:
        if os.path.isdir(target):
            try:
                with os.scandir(target) as entries:
                    items += [e.path for e in entries]
            except OSError:
                pass
        elif os.path.lexists(target):
            items.append(target)
    return items


def _qt_trash(path: str) -> str:
    """Move to the Recycle Bin; returns where the item now is, when Windows tells."""
    from PySide6.QtCore import QFile  # imported lazily: this module stays usable without Qt

    # The instance method (not the static one) renames the QFile to its place in the bin.
    handle = QFile(path)
    if not handle.moveToTrash():
        raise OSError("could not move to the Recycle Bin")
    where = os.path.normpath(handle.fileName())
    return where if key(where) != key(path) else ""


def _is_dir(path: str) -> bool:
    return os.path.isdir(path) and not os.path.islink(path)


def _measure(path: str) -> tuple[int, int]:
    """(bytes, files) of a file or folder; zeros when unreadable."""
    try:
        if _is_dir(path):
            node = scan(path, max_depth=0).root
            return node.size, node.files
        return os.lstat(path).st_size, 1
    except OSError:
        return 0, 0


def delete(
    items: Iterable[str],
    roots: Iterable[str],
    *,
    permanent: bool = False,
    trash: Callable[[str], str | None] | None = None,
    source: str = "",
    progress: Callable[[int, int, str], None] | None = None,
) -> Report:
    """Remove `items`, each of which must lie inside one of `roots` (or be a root file).

    Not permanent: moved to the Recycle Bin. Items in use are skipped, never forced.
    Every removed item is written to the journal.
    """
    trash = trash or _qt_trash
    allowed = [key(r) for r in roots]
    report = Report()
    items = list(items)
    for i, item in enumerate(items):
        if progress:
            progress(i, len(items), item)
        k = key(item)
        inside = any(under(k, r) or (k == r and not os.path.isdir(item)) for r in allowed)
        if not inside or is_protected(item):
            report.skipped.append((item, "outside the allowed location"))
            continue
        if _OWN_RUNTIME and (k == _OWN_RUNTIME or under(_OWN_RUNTIME, k)):
            report.skipped.append((item, "DiskDiet's own runtime files"))
            continue
        before, files = _measure(item)
        location = ""
        try:
            if not permanent:
                location = trash(item) or ""
            elif _is_dir(item):
                shutil.rmtree(item, ignore_errors=True)
            else:
                os.remove(item)
        except OSError as err:
            report.skipped.append((item, str(err)))
            continue
        if os.path.lexists(item):  # partly removed: some files were in use
            report.freed += max(0, before - _measure(item)[0])
            report.skipped.append((item, "in use"))
            continue
        report.freed += before
        report.deleted += 1
        if permanent:
            report.permanent += before
        else:
            report.trashed += before
        mode = journal.PERMANENT if permanent else journal.TRASH
        journal.add(item, before, files, mode, location, source)
    return _logged(f"delete [{source}]", report)


def _long(path: str) -> str:
    """Extended-length form of `path` on Windows, so paths past 260 characters still work.
    The archive mirrors the whole original path under the destination, which easily
    crosses that limit."""
    if sys.platform != "win32" or path.startswith("\\\\?\\"):
        return path
    path = os.path.abspath(path)
    return "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path


def archive_target(item: str, dest_root: str) -> str:
    """Where `item` lands under `dest_root`: its full original path, drive letter included."""
    drive, tail = os.path.splitdrive(os.path.abspath(item))
    return os.path.join(dest_root, ARCHIVE_FOLDER, drive.rstrip(":"), tail.lstrip("\\/"))


def move(
    items: Iterable[str],
    dest_root: str,
    *,
    source: str = "",
    progress: Callable[[int, int, str], None] | None = None,
) -> Report:
    """Move `items` to another drive: copy, verify, and only then remove the original."""
    report = Report()
    items = list(items)
    for i, item in enumerate(items):
        if progress:
            progress(i, len(items), item)
        if is_protected(item) or not os.path.lexists(item):
            report.skipped.append((item, "outside the allowed location"))
            continue
        size, files = _measure(item)
        target = archive_target(item, dest_root)
        far = _long(target)
        if os.path.lexists(far):
            report.skipped.append((item, "already present at the destination"))
            continue
        try:
            if shutil.disk_usage(dest_root).free < size + (64 << 20):
                report.skipped.append((item, "not enough space at the destination"))
                continue
            os.makedirs(os.path.dirname(far), exist_ok=True)
            if _is_dir(item):
                shutil.copytree(item, far)
            else:
                shutil.copy2(item, far)
        except OSError as err:
            shutil.rmtree(far, ignore_errors=True) if _is_dir(far) else _unlink(far)
            report.skipped.append((item, str(err)))
            continue
        if _measure(far) != (size, files):
            shutil.rmtree(far, ignore_errors=True) if _is_dir(far) else _unlink(far)
            report.skipped.append((item, "the copy did not match the original"))
            continue
        if _is_dir(item):
            shutil.rmtree(item, ignore_errors=True)
        else:
            _unlink(item)
        if os.path.lexists(item):
            report.skipped.append((item, "copied, but the original is in use and was kept"))
            continue
        report.freed += size
        report.moved += size
        report.deleted += 1
        journal.add(item, size, files, journal.MOVED, target, source)
    return _logged(f"move [{source}] to {dest_root}", report)


def _unlink(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass


def restore(entry: dict) -> None:
    """Put a journal entry back where it was. Raises OSError with the reason if it cannot."""
    location, original = entry.get("location", ""), entry["path"]
    if entry.get("state") == "restored":
        raise OSError("already restored")
    if entry["mode"] == journal.PERMANENT:
        raise OSError("deleted permanently: it cannot be recovered")
    if not location:
        raise OSError("Windows did not report its place in the Recycle Bin: restore it from there")
    if not os.path.lexists(_long(location)):
        raise OSError("no longer there: the Recycle Bin was emptied or the copy was removed")
    if os.path.lexists(original):
        raise OSError("something else is now at the original location")
    os.makedirs(os.path.dirname(original), exist_ok=True)
    shutil.move(_long(location), original)
    if entry["mode"] == journal.TRASH:
        # The bin keeps a small $I… record beside each $R… item; drop it so no ghost remains.
        folder, name = os.path.split(location)
        if name.upper().startswith("$R"):
            _unlink(os.path.join(folder, "$I" + name[2:]))
    journal.mark_restored(entry["id"])


def recycle_bin_size() -> int:
    """Bytes held by the Recycle Bin on all drives (0 when unknown)."""
    if sys.platform != "win32":
        return 0
    import ctypes

    class Info(ctypes.Structure):
        _fields_ = [("cbSize", ctypes.c_ulong), ("size", ctypes.c_int64), ("items", ctypes.c_int64)]

    info = Info()
    info.cbSize = ctypes.sizeof(info)
    if ctypes.windll.shell32.SHQueryRecycleBinW(None, ctypes.byref(info)) != 0:
        return 0
    return info.size


def empty_recycle_bin() -> bool:
    """Permanently delete everything in the Recycle Bin. The caller confirms first."""
    import ctypes

    no_ui = 0x1 | 0x2 | 0x4  # no confirmation, no progress window, no sound
    return ctypes.windll.shell32.SHEmptyRecycleBinW(None, None, no_ui) == 0


def open_in_explorer(path: str) -> None:
    if os.path.isdir(path):
        os.startfile(path)
    else:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])


def launch(tool: str) -> None:
    """Open a tool: an executable, a shell: folder or an ms-settings: URI.

    "a|b" tries each in turn and opens the first full path that exists.
    """
    candidates = [os.path.expandvars(c) for c in tool.split("|")]
    tool = next((c for c in candidates if os.sep not in c or os.path.exists(c)), None)
    if tool is None:
        raise OSError("program not found")
    logger.info("launch: %s", tool)
    if tool.startswith("shell:"):
        subprocess.Popen(["explorer", tool])
    else:
        os.startfile(tool)


def uninstall(command: str) -> None:
    """Start a program's own uninstaller (its UninstallString), which asks the user itself."""
    logger.info("uninstall: %s", command or "(Windows settings)")
    if command:
        subprocess.Popen(command)
    else:
        launch("ms-settings:appsfeatures")


def relaunch_elevated() -> bool:
    """Start a second DiskDiet as administrator (UAC prompt). True if it was started."""
    import ctypes

    args = "" if getattr(sys, "frozen", False) else "-m diskdiet"
    return ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1) > 32
