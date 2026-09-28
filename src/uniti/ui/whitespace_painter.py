"""Small transparent whitespace marks drawn independently of font coverage."""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QPainterPath, QPen

from uniti.ui.whitespace import WhitespaceKind


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


def end_of_text_marker_x(left: int, glyph: str, metrics, *, rtl: bool) -> int:
    """`left` is a boundary point at the true visual edge of already-
    drawn content -- the end-of-line position, or the last marker drawn
    before an overflow indicator -- not a real character's own span
    (contrast `paint_whitespace_marker`'s SPACE/TAB/INVISIBLE cases,
    which nudge into a real, already-bounded span and need no direction
    awareness). A fixed rightward nudge only lands in empty margin for
    LTR, where "further along reading direction" is also "further right
    on screen": for RTL, reading continues to the *left* of `left`, so
    the same rightward nudge draws the marker glyph back on top of the
    text it's meant to sit past. Placing the glyph's own rendered width
    entirely to the left of `left` gives real clearance instead of
    merely flipping the nudge's sign, which would still let the glyph's
    rightward extent bleed into the text.

    `metrics` is a `QFontMetrics`-like object providing `horizontalAdvance`.
    """
    if not rtl:
        return left + 3
    return left - 3 - metrics.horizontalAdvance(glyph)


def paint_whitespace_marker(
    painter,
    kind,
    label: str,
    x1: float,
    x2: float,
    y: float,
    *,
    theme_tokens,
    row_ascent: float,
    line_height: float,
    cell_width: float,
    metrics,
    rtl: bool = False,
) -> None:
    """Draw one whitespace/invisible-Unicode marker glyph for the live
    editor's per-row paint loop -- extracted out of `UNITITextView` as a
    free function (same "pull the stateless drawing logic out" pattern
    already proven by `paint_compact_marker`, which this itself calls for
    the generic/invisible-Unicode case) since it only ever reads a
    handful of narrow, read-only theme/metrics values, never document,
    selection, scroll, or cache state. `theme_tokens`/`row_ascent`/
    `line_height`/`cell_width`/`metrics` are exactly the state
    `UNITITextView._paint_whitespace_marker` used to read off `self`."""

    tokens = theme_tokens
    baseline = y + row_ascent
    # BF-064: `x1`/`x2` come from `x_for_cp`, whose ordering flips on a
    # right-to-left line (see `UNITITextView._span_rect`) -- the visual
    # left edge of the marker's span is whichever of the two is smaller,
    # not always x1 (the character's *logical* start).
    left = int(round(min(x1, x2)))
    if kind == "overflow":
        painter.setPen(tokens.invisible_marker)
        painter.drawText(
            end_of_text_marker_x(left, label, metrics, rtl=rtl), baseline, label
        )
        return
    if kind == WhitespaceKind.SPACE:
        painter.save()
        try:
            painter.setRenderHint(painter.RenderHint.Antialiasing, True)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(tokens.space_marker)
            center = QPointF((x1 + x2) / 2.0, y + line_height / 2.0)
            diameter = min(abs(x2 - x1) * 0.5, metrics.height() * 0.25)
            radius = max(0.5, diameter / 2.0)
            painter.drawEllipse(center, radius, radius)
        finally:
            painter.restore()
        return
    elif kind == WhitespaceKind.TAB:
        painter.setPen(tokens.tab_marker)
        painter.drawText(left + 1, baseline, "»")
        return
    elif kind == "eol":
        painter.setPen(tokens.eol_marker)
        glyph = {"LF": "␊", "CR": "␍", "CRLF": "␍␊"}[label]
        painter.drawText(
            end_of_text_marker_x(left, glyph, metrics, rtl=rtl), baseline, glyph
        )
        return
    else:
        painter.setPen(tokens.invisible_marker)
        width = max(4.0, cell_width * 0.8)
        center = (x1 + x2) / 2 if abs(x2 - x1) >= 0.5 else x1
        paint_compact_marker(
            painter,
            label,
            QRectF(center - width / 2, y + 1, width, line_height - 2),
        )
        return
