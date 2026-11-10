"""Clickable pie chart with outside labels, drawn with QPainter (no QtCharts in the exe)."""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from windiskcleaner.strings import fmt_size

LABEL_MIN = 0.03  # slices smaller than this get no label (the tooltip still works)
LABEL_WIDTH = 150
ELBOW = 14


class PieWidget(QWidget):
    clicked = Signal(int)  # index of the slice
    context = Signal(int, object)  # index, global position of a right click

    def __init__(self):
        super().__init__()
        self.slices: list[tuple[str, int, str]] = []  # label, value, colour
        self.setMinimumSize(520, 300)
        self.setMouseTracking(True)

    def set_slices(self, slices: list[tuple[str, int, str]]) -> None:
        self.slices = [s for s in slices if s[1] > 0]
        self.update()

    def _rect(self) -> QRectF:
        room = self.width() - 2 * (LABEL_WIDTH + ELBOW + 16)
        side = max(120, min(room, self.height() - 40))
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def label_slots(self) -> list[tuple[int, QPointF, QPointF, float, bool]]:
        """(slice index, point on the rim, elbow, label y, on the right) for labelled slices.

        Labels on each side are pushed apart vertically so that they never overlap.
        """
        total = sum(s[1] for s in self.slices)
        if not total:
            return []
        rect = self._rect()
        centre, radius = rect.center(), rect.width() / 2
        gap = QFontMetrics(self.font()).lineSpacing() * 2 + 6
        sides: dict[bool, list[list]] = {True: [], False: []}
        reached = 0.0
        for i, (_label, value, _colour) in enumerate(self.slices):
            share = value / total
            angle = math.radians((reached + share / 2) * 360)  # clockwise from 12 o'clock
            reached += share
            if share < LABEL_MIN:
                continue
            ux, uy = math.sin(angle), -math.cos(angle)
            rim = QPointF(centre.x() + radius * ux, centre.y() + radius * uy)
            elbow = QPointF(centre.x() + (radius + ELBOW) * ux, centre.y() + (radius + ELBOW) * uy)
            sides[ux >= 0].append([i, rim, elbow, elbow.y()])
        slots = []
        for right, entries in sides.items():
            entries.sort(key=lambda e: e[3])
            for prev, entry in zip(entries, entries[1:], strict=False):
                entry[3] = max(entry[3], prev[3] + gap)
            overflow = entries[-1][3] + gap / 2 - self.height() if entries else 0
            for entry in entries:
                y = entry[3] - max(0.0, overflow)
                slots.append((entry[0], entry[1], entry[2], max(gap / 2, y), right))
        return slots

    def paintEvent(self, _event) -> None:
        total = sum(s[1] for s in self.slices)
        if not total:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = self._rect()
        painter.setPen(QPen(self.palette().window().color(), 1.5))
        start = 90 * 16  # Qt angles are in 1/16 of a degree, counter-clockwise
        for _label, value, colour in self.slices:
            span = -round(value / total * 360 * 16)
            painter.setBrush(QColor(colour))
            painter.drawPie(rect, start, span)
            start += span

        metrics = QFontMetrics(self.font())
        gap = metrics.lineSpacing() * 2 + 6
        text_colour = self.palette().windowText().color()
        for i, rim, elbow, y, right in self.label_slots():
            label, value, colour = self.slices[i]
            x = rect.right() + ELBOW + 12 if right else rect.left() - ELBOW - 12
            painter.setPen(QPen(QColor(colour), 1.4))
            painter.drawPolyline([rim, elbow, QPointF(x - 4 if right else x + 4, y)])
            name = metrics.elidedText(label, Qt.TextElideMode.ElideMiddle, LABEL_WIDTH)
            text = f"{name}\n{fmt_size(value)} · {value / total:.0%}"
            box = QRectF(x if right else x - LABEL_WIDTH, y - gap / 2, LABEL_WIDTH, gap)
            side = Qt.AlignmentFlag.AlignLeft if right else Qt.AlignmentFlag.AlignRight
            painter.setPen(text_colour)
            painter.drawText(box, side | Qt.AlignmentFlag.AlignVCenter, text)
        painter.end()

    def slice_at(self, pos) -> int:
        rect = self._rect()
        dx, dy = pos.x() - rect.center().x(), pos.y() - rect.center().y()
        if math.hypot(dx, dy) > rect.width() / 2:
            return -1
        angle = math.degrees(math.atan2(dx, -dy)) % 360  # clockwise from 12 o'clock
        total = sum(s[1] for s in self.slices)
        reached = 0.0
        for i, (_label, value, _colour) in enumerate(self.slices):
            reached += value / total * 360
            if angle <= reached:
                return i
        return len(self.slices) - 1

    def mouseMoveEvent(self, event) -> None:
        i = self.slice_at(event.position())
        if i < 0:
            QToolTip.hideText()
            return
        label, value, _colour = self.slices[i]
        QToolTip.showText(event.globalPosition().toPoint(), f"{label}\n{fmt_size(value)}", self)

    def mousePressEvent(self, event) -> None:
        i = self.slice_at(event.position())
        if i < 0:
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(i)
        elif event.button() == Qt.MouseButton.RightButton:
            self.context.emit(i, event.globalPosition().toPoint())
