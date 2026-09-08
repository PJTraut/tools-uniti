"""One bounded Qt layout supplies LTR painting, UTF-16 formats and caret geometry."""

from bisect import bisect_left, bisect_right
import regex
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QTextLayout, QTextOption


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
    ):
        if len(text) > 8192:
            raise ValueError("layout window exceeds 8192 code points")
        self.text = text
        self.document_start = document_start
        self.preedit = preedit
        display = (
            text
            if preedit is None
            else text[: preedit[0]] + preedit[1] + text[preedit[0] :]
        )
        self.mapping = Utf16Map(display)
        self.boundaries = tuple([0, *[m.end() for m in regex.finditer(r"\X", text)]])
        self.layout = QTextLayout(display, font)
        option = QTextOption()
        option.setTextDirection(Qt.LayoutDirection.LeftToRight)
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
        while len(self.lines) < max_lines:
            line = self.layout.createLine()
            if not line.isValid():
                break
            line.setLineWidth(1e12 if width_px is None else max(1.0, width_px))
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

    def row_span(self, row=0):
        line = self.lines[row]
        return (
            self.mapping.u16_to_cp(line.textStart()),
            self.mapping.u16_to_cp(line.textStart() + line.textLength()),
        )

    @property
    def width(self):
        return max((line.naturalTextWidth() for line in self.lines), default=0.0)
