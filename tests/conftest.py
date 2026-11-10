import os

import pytest

from diskdiet import strings

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


@pytest.fixture(autouse=True)
def english():
    strings.LANG = "en"


@pytest.fixture(autouse=True)
def private_home(tmp_path_factory, monkeypatch):
    """Settings and the deletion log go to a throwaway folder, never the user's."""
    monkeypatch.setenv("DISKDIET_HOME", str(tmp_path_factory.mktemp("home")))


@pytest.fixture
def make(tmp_path):
    """make('a/b.bin', 1000) creates a file of that size under tmp_path and returns its path."""

    def _make(rel: str, size: int = 0, content: bytes | None = None, mtime: float | None = None):
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content if content is not None else b"x" * size)
        if mtime is not None:
            os.utime(path, (mtime, mtime))
        return str(path)

    return _make
