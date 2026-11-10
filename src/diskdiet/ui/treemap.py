"""Clickable treemap (squarified, two levels), drawn with QPainter like the pie chart."""

from __future__ import annotations

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QToolTip, QWidget

from diskdiet.strings import fmt_size

Rect = tuple[float, float, float, float]  # x, y, width, height
INNER_MIN = 40  # boxes smaller than this (px) are not split into their own children
LABEL_MIN = 46


def squarify(values: list[float], rect: Rect) -> list[Rect]:
    """Rectangles for `values` (biggest first) filling `rect`, kept close to squares
    (Bruls, Huizing, van Wijk). Same order as `values`; zero values get empty boxes."""
    x, y, w, h = rect
    total = sum(values)
    if total <= 0 or w <= 0 or h <= 0:
        return [(x, y, 0.0, 0.0) for _ in values]
    scale = w * h / total
    areas = [v * scale for v in values]
    out: list[Rect] = []
    i = 0
    while i < len(areas):
        side = min(w, h)
        row = [areas[i]]
        i += 1
        while i < len(areas) and _worst(row + [areas[i]], side) <= _worst(row, side):
            row.append(areas[i])
            i += 1
        thick = sum(row) / side if side else 0
        pos = 0.0
        for area in row:
            length = area / thick if thick else 0
            if w >= h:  # lay the row as a column on the left
                out.append((x, y + pos, thick, length))
            else:  # as a row on top
                out.append((x + pos, y, length, thick))
            pos += length
        if w >= h:
            x, w = x + thick, w - thick
        else:
            y, h = y + thick, h - thick
    return out


def _worst(row: list[float], side: float) -> float:
    """Worst aspect ratio in `row` laid along `side` (1 = all squares)."""
    total, filled = sum(row), [a for a in row if a > 0]
    if not filled or not side:
        return float("inf")
    return max(max(side * side * a / (total * total), total * total / (side * side * a))
               for a in filled)


class TreemapWidget(QWidget):
    clicked = Signal(int)  # index of the box (same order as set_items)
    context = Signal(int, object)  # index, global position of a right click

    def __init__(self):
        super().__init__()
        self.items: list[tuple[str, int, str, list[int]]] = []  # label, size, colour, children
        self.boxes: list[QRectF] = []
        self.setMinimumSize(520, 300)
        self.setMouseTracking(True)

    def set_items(self, items: list[tuple[str, int, str, list[int]]]) -> None:
        """(label, size, colour, sizes of its own children) — biggest first."""
        self.items = [it for it in items if it[1] > 0]
        self.boxes = []
        self.update()

    def resizeEvent(self, _event) -> None:
        self.boxes = []

    def _layout(self) -> list[QRectF]:
        if not self.boxes and self.items:
            rects = squarify([it[1] for it in self.items],
                             (2.0, 2.0, self.width() - 4.0, self.height() - 4.0))
            self.boxes = [QRectF(*r) for r in rects]
        return self.boxes

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        border = self.palette().window().color()
        for (label, size, colour, children), box in zip(self.items, self._layout(), strict=True):
            base = QColor(colour)
            painter.fillRect(box, base)
            if children and box.width() > INNER_MIN and box.height() > INNER_MIN:
                inner = box.adjusted(3, 18, -3, -3)
                rects = squarify(sorted(children, reverse=True),
                                 (inner.x(), inner.y(), inner.width(), inner.height()))
                painter.setPen(QPen(base.darker(125), 1))
                for r in rects:
                    if r[2] >= 2 and r[3] >= 2:
                        painter.fillRect(QRectF(*r), base.lighter(112))
                        painter.drawRect(QRectF(*r))
            painter.setPen(QPen(border, 2))
            painter.drawRect(box)
            if box.width() > LABEL_MIN and box.height() > 16:
                painter.setPen(QColor("#ffffff") if base.lightness() < 150 else QColor("#000000"))
                text = painter.fontMetrics().elidedText(
                    f"{label}  {fmt_size(size)}", Qt.TextElideMode.ElideRight,
                    int(box.width()) - 8)
                painter.drawText(box.adjusted(4, 2, -4, 0),
                                 Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, text)

    def box_at(self, pos) -> int:
        for i, box in enumerate(self._layout()):
            if box.contains(pos):
                return i
        return -1

    def mouseMoveEvent(self, event) -> None:
        i = self.box_at(event.position())
        if i >= 0:
            label, size, _c, _k = self.items[i]
            QToolTip.showText(event.globalPosition().toPoint(), f"{label}\n{fmt_size(size)}", self)
        else:
            QToolTip.hideText()

    def mousePressEvent(self, event) -> None:
        i = self.box_at(event.position())
        if i < 0:
            return
        if event.button() == Qt.MouseButton.RightButton:
            self.context.emit(i, event.globalPosition().toPoint())
        elif event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(i)
