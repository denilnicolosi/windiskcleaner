"""Writes docs/screenshot.png: the Overview tab filled with made-up sample data.

Sample data on purpose, so that no real folder or user name ends up in the repository.
Run:  uv run python scripts/make_screenshot.py
"""

import os
import sys
import tempfile

os.environ["WINDISKCLEANER_HOME"] = tempfile.mkdtemp()  # do not read or write real settings

from PySide6.QtWidgets import QApplication  # noqa: E402

from windiskcleaner import strings  # noqa: E402
from windiskcleaner.scanner import Node, ScanResult  # noqa: E402
from windiskcleaner.system import Volume  # noqa: E402
from windiskcleaner.ui.main_window import MainWindow  # noqa: E402

GB = 1 << 30
SAMPLE = [("Users", 212, 1_450_000), ("Windows", 48, 220_000), ("Program Files", 41, 154_000),
          ("ProgramData", 27, 61_000), ("Program Files (x86)", 10, 23_000),
          ("pagefile.sys + hiberfil.sys", 26, 2), ("Games", 58, 31_000)]

strings.LANG = "en"
app = QApplication(sys.argv)
root = Node("C:\\", children=[Node(f"C:\\{n}", int(s * GB), f) for n, s, f in SAMPLE])
root.size = sum(c.size for c in root.children)
root.files = sum(c.files for c in root.children)
window = MainWindow()
window.result = ScanResult(root=root, seconds=92)
window.overview.load(root, Volume("C:\\", 500 * GB, 62 * GB, True))
window.status.setText(strings.tr(
    "ui.done", size=strings.fmt_size(root.size), files=root.files, secs=92, denied=0))
window.show()
app.processEvents()
target = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "docs",
                      "screenshot.png")
window.grab().save(target)
print(target)
