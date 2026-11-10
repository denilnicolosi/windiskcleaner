"""Writes assets/windiskcleaner.ico from the drawing in windiskcleaner/ui/icon.py.

Run it again only if the icon drawing changes:  uv run python scripts/make_icon.py
"""

import os
import sys

from PySide6.QtGui import QGuiApplication

from windiskcleaner.ui.icon import pie_pixmap

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
app = QGuiApplication(sys.argv)
target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
os.makedirs(target, exist_ok=True)
path = os.path.join(target, "windiskcleaner.ico")
if not pie_pixmap(256).save(path, "ICO"):
    sys.exit("could not write the icon")
print(path)
