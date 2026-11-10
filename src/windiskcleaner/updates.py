"""Update check against GitHub Releases. The only network access in WinDiskCleaner.

Nothing about the user or the machine is sent: these are plain anonymous GET requests.
No Qt here.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

from windiskcleaner import __version__

REPO = "denilnicolosi/windiskcleaner"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOADS = f"https://github.com/{REPO}/releases/download/"


@dataclass(frozen=True)
class Release:
    version: str
    notes: str
    page: str
    exe_url: str
    sha_url: str


def _fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "WinDiskCleaner"})
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read()


def parse_version(text: str) -> tuple[int, ...]:
    """'v1.2.3' -> (1, 2, 3). Raises ValueError on anything else."""
    return tuple(int(part) for part in text.strip().lstrip("vV").split("."))


def is_newer(candidate: str, current: str = __version__) -> bool:
    try:
        return parse_version(candidate) > parse_version(current)
    except ValueError:
        return False


def latest(fetch: Callable[[str], bytes] = _fetch) -> Release | None:
    """The latest published release, or None if the repository has none yet."""
    try:
        data = json.loads(fetch(API))
    except urllib.error.HTTPError as err:
        if err.code == 404:
            return None
        raise
    assets = {a["name"]: a["browser_download_url"] for a in data.get("assets", [])}
    exe = next((url for name, url in assets.items() if name.lower().endswith(".exe")), "")
    return Release(
        version=str(data.get("tag_name", "")).lstrip("vV"),
        notes=str(data.get("body") or ""),
        page=str(data.get("html_url", "")),
        exe_url=exe,
        sha_url=next((u for n, u in assets.items() if n.lower().endswith(".sha256")), ""),
    )


def download(release: Release, dest: str, fetch: Callable[[str], bytes] = _fetch) -> str:
    """Download the release exe to `dest` after checking where it comes from and its SHA-256."""
    for url in (release.exe_url, release.sha_url):
        if not url.startswith(DOWNLOADS):
            raise ValueError(f"not a download of {REPO}: {url!r}")
    expected = fetch(release.sha_url).decode("ascii", "replace").split()[0].lower()
    data = fetch(release.exe_url)
    if hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("the downloaded file does not match its published SHA-256")
    with open(dest, "wb") as f:
        f.write(data)
    return dest


def can_self_update() -> bool:
    """Only the packaged exe replaces itself; a source checkout is updated with git."""
    return bool(getattr(sys, "frozen", False))


def swap(new_exe: str, current: str | None = None, start: bool = True) -> None:
    """Put `new_exe` in place of the running exe and start it. The caller then quits.

    Windows lets a running exe be renamed but not deleted, so the old one is parked as
    *.old and removed by cleanup() at the next start.
    """
    current = current or sys.executable
    old = current + ".old"
    if os.path.exists(old):
        os.remove(old)
    os.rename(current, old)
    try:
        os.rename(new_exe, current)
    except OSError:
        os.rename(old, current)  # put the working exe back
        raise
    if start:
        subprocess.Popen([current])


def cleanup(current: str | None = None) -> None:
    """Remove the exe left behind by a previous swap()."""
    try:
        os.remove((current or sys.executable) + ".old")
    except OSError:
        pass
