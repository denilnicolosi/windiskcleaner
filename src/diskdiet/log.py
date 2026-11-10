"""Log file for operations and errors: %LOCALAPPDATA%\\DiskDiet\\diskdiet.log.

Everything logs through logging.getLogger("diskdiet"). Until setup() is called (tests,
library use) that logger has only a NullHandler and nothing is written anywhere.
"""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler

from diskdiet import settings

logger = logging.getLogger("diskdiet")
logger.addHandler(logging.NullHandler())


def path() -> str:
    return os.path.join(settings.data_dir(), "diskdiet.log")


def setup() -> None:
    """Start writing to the log file (1 MB, two older files kept) and catch crashes."""
    try:
        os.makedirs(settings.data_dir(), exist_ok=True)
        handler = RotatingFileHandler(path(), maxBytes=1 << 20, backupCount=2, encoding="utf-8")
    except OSError:
        return  # no log is better than no program
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)

    def crashed(kind, value, trace):
        logger.critical("uncaught exception", exc_info=(kind, value, trace))
        sys.__excepthook__(kind, value, trace)

    sys.excepthook = crashed
    threading.excepthook = lambda args: logger.critical(
        "uncaught exception in thread %s", args.thread,
        exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
    )
