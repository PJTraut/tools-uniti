"""Small transparent whitespace marks drawn independently of font coverage."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPen


def paint_compact_marker(painter, label: str, rect: QRectF) -> None:
    """Draw one reference-inspired marker without changing the text layout."""
    painter.save()
    try:
        painter.setRenderHint(painter.RenderHint.Antialiasing, True)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        pen = QPen(painter.pen())
        pen.setWidthF(max(1.0, rect.height() / 18))
        painter.setPen(pen)

        def point(x, y):
            return QPointF(rect.center().x() + x * rect.width() / 10,
                rect.top() + y * rect.height() / 14)

        def line(x1, y1, x2, y2):
            painter.drawLine(point(x1, y1), point(x2, y2))

        def dot(x, y):
            painter.drawPoint(point(x, y))

        def ring(x, y):
            painter.drawEllipse(point(x, y), rect.width() / 15, rect.height() / 24)

        name = label.partition("×")[0]
        if " / " in label:
            line(-1.5, 2, -1.5, 12)
            line(1.5, 2, 1.5, 12)
            dot(0, 7)
        elif name in {"EMSP", "ENSP"}:
            width = 4 if name == "EMSP" else 2
            line(-width, 4, width, 4)
            dot(0, 7)
        elif name in {"NBSP", "NNBSP"}:
            line(-2, 5, 0, 2)
            line(0, 2, 2, 5)
            if name == "NNBSP":
                dot(0, 9)
        elif name == "THINSP":
            line(-2, 3, 0, 6)
            line(0, 6, 2, 3)
            dot(0, 10)
        elif name == "HAIRSP":
            dot(0, 4)
            dot(0, 8)
        elif name == "IDSP":
            painter.drawRect(QRectF(point(-4, 2), point(4, 12)))
            dot(0, 7)
        elif name in {"ZWSP", "ZWNJ", "ZWJ", "WJ", "LRM", "RLM"}:
            line(0, 2, 0, 12)
            if name == "ZWSP":
                ring(0, 2)
                ring(0, 12)
            elif name == "ZWNJ":
                for direction in (-1, 1):
                    line(direction, 4, direction * 4, 4)
                    line(direction * 2.5, 2, direction * 4, 4)
                    line(direction * 2.5, 6, direction * 4, 4)
            elif name == "ZWJ":
                path = QPainterPath(point(-3, 5))
                path.quadTo(point(-3, -1), point(0, 1))
                path.quadTo(point(3, -1), point(3, 5))
                painter.drawPath(path)
            elif name == "WJ":
                line(-3, 2, 3, 2)
                line(-3, 12, 3, 12)
            else:
                direction = 1 if name == "LRM" else -1
                line(0, 2, direction * 4, 2)
                line(direction * 2, 0, direction * 4, 2)
                line(direction * 2, 4, direction * 4, 2)
        else:
            path = QPainterPath(point(0, 2))
            for x, y in ((3, 7), (0, 12), (-3, 7)):
                path.lineTo(point(x, y))
            path.closeSubpath()
            painter.drawPath(path)
            if name == "BOM":
                dot(0, 7)
    finally:
        painter.restore()
