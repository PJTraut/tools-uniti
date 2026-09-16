"""One bounded Qt layout supplies painting, UTF-16 formats and caret geometry.

Callers pass an explicit `direction` (BF-064) rather than relying on Qt's
own auto-detection per window, because a window frequently starts mid
logical-line (a wrapped continuation row, a horizontal-scroll checkpoint) —
detecting from just that fragment would misjudge a paragraph whose first
strong character came earlier in the line. Direction is a paragraph-level
property; callers are expected to detect it once per logical line (see
`uniti.core.bidi.is_rtl_paragraph`) and reuse it for every window belonging
to that line.
"""

from bisect import bisect_left, bisect_right
import regex
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QTextLayout, QTextOption

from uniti.core.bidi import is_rtl_paragraph


def direction_for_text(text: str) -> Qt.LayoutDirection:
    """The base direction a logical line's `ShapedWindow`s should share."""

    return (
        Qt.LayoutDirection.RightToLeft
        if is_rtl_paragraph(text)
        else Qt.LayoutDirection.LeftToRight
    )


class Utf16Map:
    def __init__(self, text: str):
        positions = [0]
        for ch in text:
            positions.append(positions[-1] + (2 if ord(ch) > 0xFFFF else 1))
        self.positions = tuple(positions)

    def cp_to_u16(self, cp: int) -> int:
        if not 0 <= cp < len(self.positions):
            raise ValueError("code point outside bounded layout")
        return self.positions[cp]

    def u16_to_cp(self, unit: int, *, bias: str = "floor") -> int:
        if not 0 <= unit <= self.positions[-1]:
            raise ValueError("UTF-16 position outside bounded layout")
        low = bisect_right(self.positions, unit) - 1
        if bias == "floor":
            return low
        high = bisect_left(self.positions, unit)
        if bias == "ceil":
            return high
        if bias == "nearest":
            return (
                low
                if unit - self.positions[low] <= self.positions[high] - unit
                else high
            )
        raise ValueError("unknown UTF-16 bias")


class ShapedWindow:
    def __init__(
        self,
        text,
        font,
        *,
        document_start=0,
        width_px=None,
        tab_stop_px=32,
        preedit=None,
        tab_origin=0,
        max_lines=512,
        direction=Qt.LayoutDirection.LeftToRight,
        align_width_px=None,
    ):
        if len(text) > 8192:
            raise ValueError("layout window exceeds 8192 code points")
        self.text = text
        self.document_start = document_start
        self.preedit = preedit
        self.direction = direction
        display = (
            text
            if preedit is None
            else text[: preedit[0]] + preedit[1] + text[preedit[0] :]
        )
        self.mapping = Utf16Map(display)
        self.boundaries = tuple([0, *[m.end() for m in regex.finditer(r"\X", text)]])
        self.layout = QTextLayout(display, font)
        option = QTextOption()
        option.setTextDirection(direction)
        # BF-064: Qt anchors a QTextLine flush-left within its line width by
        # default, regardless of paragraph direction — text direction only
        # reorders glyphs *within* that box. For a right-to-left line that
        # keeps growing as characters are typed (or IME-composed) at its
        # logical end, the anchor stays fixed at the box's own left edge
        # and the box just widens rightward — meaning the caret, which
        # sits at the logical end, never visually moves. Reproduced
        # directly: typing five Arabic characters left the caret at the
        # exact same x every time.
        #
        # `align_width_px` lets a caller (the paint path, which already
        # knows the visible text area's width) supply a real anchor even
        # when this window isn't itself doing any wrapping (`width_px` is
        # `None`, as it is for painting an already-wrapped row's text) —
        # `width_px` alone would only be set by a caller that's also
        # wrapping at that width (`ShapedRowProvider`/`HorizontalLayouts`).
        # Only meaningful when one of the two is a real bound; the
        # unbounded 1e12 placeholder used when neither is given would make
        # right-alignment anchor somewhere useless.
        reference_width = width_px if width_px is not None else align_width_px
        if direction == Qt.LayoutDirection.RightToLeft and reference_width is not None:
            option.setAlignment(Qt.AlignmentFlag.AlignRight)
        option.setTabStopDistance(tab_stop_px)
        if tab_origin % tab_stop_px:
            first = tab_stop_px - tab_origin % tab_stop_px
            tabs = []
            for distance in (first, first + tab_stop_px):
                tab = QTextOption.Tab()
                tab.position = distance
                tabs.append(tab)
            option.setTabs(tabs)
        option.setFlags(QTextOption.Flag.IncludeTrailingSpaces)
        option.setWrapMode(
            QTextOption.WrapMode.NoWrap
            if width_px is None
            else QTextOption.WrapMode.WrapAnywhere
        )
        self.layout.setTextOption(option)
        self.layout.beginLayout()
        self.lines = []
        line_width = 1e12 if reference_width is None else max(1.0, reference_width)
        while len(self.lines) < max_lines:
            line = self.layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(line_width)
            line.setPosition(QPointF(0, 0))
            self.lines.append(line)
        self.layout.endLayout()

    def unit_for_cp(self, cp):
        if self.preedit is not None and cp >= self.preedit[0]:
            cp += len(self.preedit[1])
        return self.mapping.cp_to_u16(cp)

    def preedit_x(self, cp, row=0):
        if not self.lines:
            return 0.0
        value = self.lines[row].cursorToX(self.mapping.cp_to_u16(self.preedit[0] + cp))
        return float(value[0] if isinstance(value, tuple) else value)

    def x_for_cp(self, cp, row=0):
        if not self.lines:
            return 0.0
        value = self.lines[row].cursorToX(self.unit_for_cp(cp))
        return float(value[0] if isinstance(value, tuple) else value)

    def cp_for_x(self, x, row=0):
        if not self.lines:
            return 0
        cp = self.mapping.u16_to_cp(self.lines[row].xToCursor(x))
        if self.preedit is not None and cp > self.preedit[0]:
            cp = max(self.preedit[0], cp - len(self.preedit[1]))
        i = bisect_left(self.boundaries, cp)
        candidates = self.boundaries[max(0, i - 1) : i + 1]
        return min(candidates, key=lambda p: abs(self.x_for_cp(p, row) - x))

    def run_spans(self, a, b, row=0):
        """Horizontal (left, right) extents of each bidi/shaping run within
        logical span [a, b) on `row`, in this window's local layout
        coordinates.

        BF-064: a highlight (selection/match/invalid-byte) span given only
        as a logical `[a, b)` range can cross an embedded direction
        boundary within one line (e.g. an English word inside an Arabic
        paragraph) — its true visual extent is then more than one
        contiguous rectangle. `QTextLine.glyphRuns` is Qt's own
        authoritative shaping-run geometry — the same engine that already
        performs full bidi reordering and Arabic/Hebrew contextual shaping
        for painting — so using it here means the split is always
        consistent with what is actually rendered, with no separate bidi
        logic of our own to get subtly wrong. Callers apply their own
        uniform row height; only the horizontal extents come from here.
        """
        if not self.lines or b <= a:
            return []
        line = self.lines[row]
        start_unit = self.unit_for_cp(a)
        length_unit = self.unit_for_cp(b) - start_unit
        if length_unit <= 0:
            return []
        runs = line.glyphRuns(start_unit, length_unit)
        if not runs:
            x1, x2 = self.x_for_cp(a, row), self.x_for_cp(b, row)
            return [(min(x1, x2), max(x1, x2))]
        spans = sorted(
            (run.boundingRect().left(), run.boundingRect().right())
            for run in runs
        )
        merged: list[tuple[float, float]] = []
        for left, right in spans:
            if merged and left <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], right))
            else:
                merged.append((left, right))
        return merged

    def row_span(self, row=0):
        line = self.lines[row]
        return (
            self.mapping.u16_to_cp(line.textStart()),
            self.mapping.u16_to_cp(line.textStart() + line.textLength()),
        )

    @property
    def width(self):
        return max((line.naturalTextWidth() for line in self.lines), default=0.0)
