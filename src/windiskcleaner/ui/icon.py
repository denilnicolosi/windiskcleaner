"""The application icon: a four-slice pie, drawn in code so there is one source for it.

scripts/make_icon.py saves the same drawing as assets/windiskcleaner.ico for the exe file.
"""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap

SLICES = [(0.42, "#4e79a7"), (0.27, "#f28e2b"), (0.19, "#59a14f"), (0.12, "#e15759")]


def pie_pixmap(size: int = 256) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QPen(QColor("white"), max(1.0, size / 40)))
    margin = size * 0.06
    rect = QRectF(margin, margin, size - 2 * margin, size - 2 * margin)
    start = 90 * 16
    for share, colour in SLICES:
        span = -round(share * 360 * 16)
        painter.setBrush(QColor(colour))
        painter.drawPie(rect, start, span)
        start += span
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    icon = QIcon()
    for size in (16, 24, 32, 48, 256):
        icon.addPixmap(pie_pixmap(size))
    return icon
