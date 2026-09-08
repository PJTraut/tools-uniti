"""Analysis-backed miniature editors for regex and replacement expressions."""

from __future__ import annotations

from PySide6.QtCore import QEvent
from PySide6.QtGui import QColor, QSyntaxHighlighter, QTextCharFormat

from uniti.regex.analysis import RegexAnalysis
from uniti.ui.font_policy import resolve_editor_font
from uniti.ui.text_layout import Utf16Map, ShapedWindow
from uniti.ui.bounded_text_edit import BoundedSingleLineTextEdit


_GROUP_HUES = (210, 18, 132, 286, 48, 174, 330, 258)


def _relative_luminance(color: QColor) -> float:
    channels: list[float] = []
    for value in color.getRgbF()[:3]:
        channels.append(
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _contrast_ratio(first: QColor, second: QColor) -> float:
    high, low = sorted(
        (_relative_luminance(first), _relative_luminance(second)),
        reverse=True,
    )
    return (high + 0.05) / (low + 0.05)


def _group_color(base: QColor, key: int) -> QColor:
    hue = _GROUP_HUES[(key - 1) % len(_GROUP_HUES)]
    dark_base = base.lightnessF() < 0.5
    lightness = 184 if dark_base else 86
    direction = 8 if dark_base else -8
    color = QColor.fromHsl(hue, 190, lightness)
    while _contrast_ratio(color, base) < 4.5 and 8 <= lightness <= 247:
        lightness += direction
        color = QColor.fromHsl(hue, 190, max(0, min(255, lightness)))
    return color


def _format(color: QColor, *, bold: bool = False) -> QTextCharFormat:
    result = QTextCharFormat()
    result.setForeground(color)
    if bold:
        result.setFontWeight(700)
    return result


class _AnalysisHighlighter(QSyntaxHighlighter):
    def __init__(self, document, owner: BoundedSingleLineTextEdit) -> None:
        super().__init__(document)
        self._owner = owner
        self.analysis: RegexAnalysis | None = None
        self.group_palette: tuple[QColor, ...] = ()
        self._formats: dict[str, QTextCharFormat] = {}
        self._invalid_color = QColor()
        self.rebuild_formats()

    def rebuild_formats(self) -> None:
        palette = self._owner.palette()
        base = palette.base().color()
        text = palette.text().color()
        self.group_palette = tuple(
            _group_color(base, index) for index in range(1, len(_GROUP_HUES) + 1)
        )
        structural = _group_color(base, 1)
        secondary = _group_color(base, 2)
        tertiary = _group_color(base, 3)
        self._formats = {
            "literal": _format(text),
            "escape": _format(secondary),
            "unicode_property": _format(tertiary),
            "char_class": _format(tertiary),
            "anchor": _format(secondary, bold=True),
            "quantifier": _format(secondary, bold=True),
            "alternation": _format(tertiary, bold=True),
            "group_open": _format(structural, bold=True),
            "group_close": _format(structural, bold=True),
            "group_name": _format(structural, bold=True),
            "flag": _format(text),
            "special": _format(text),
            "backreference": _format(tertiary, bold=True),
        }
        self._invalid_color = _group_color(base, 2)
        self.rehighlight()

    def set_analysis(self, analysis: RegexAnalysis) -> None:
        self.analysis = analysis
        self._update_accessibility()
        self.rehighlight()

    def _update_accessibility(self) -> None:
        analysis = self.analysis
        if analysis is None:
            self._owner.setAccessibleDescription("")
            self._owner.setToolTip("")
            return
        lines: list[str] = []
        for group in analysis.groups:
            label = f"Group {group.number}"
            if group.names:
                label += " " + ", ".join(group.names)
            lines.append(label)
        reference_labels: set[str] = set()
        for token in analysis.tokens:
            if (
                token.kind != "backreference"
                or not token.valid
                or token.group_number is None
            ):
                continue
            label = f"Reference to Group {token.group_number}"
            if token.group_name:
                label += f" {token.group_name}"
            reference_labels.add(label)
        lines.extend(sorted(reference_labels))
        lines.extend(diagnostic.message for diagnostic in analysis.diagnostics)
        description = "\n".join(lines)
        self._owner.setAccessibleDescription(description)
        self._owner.setToolTip(description)

    def _invalid_format(self, base: QTextCharFormat) -> QTextCharFormat:
        result = QTextCharFormat(base)
        result.setUnderlineColor(self._invalid_color)
        result.setUnderlineStyle(QTextCharFormat.UnderlineStyle.WaveUnderline)
        return result

    def highlightBlock(self, text: str) -> None:
        analysis = self.analysis
        if analysis is None or analysis.expression != text:
            return
        mapping = Utf16Map(text)
        for token in analysis.tokens:
            if token.end <= token.start or token.start >= len(text):
                continue
            length = min(len(text), token.end) - token.start
            if token.color_key is not None:
                color = self.group_palette[
                    (token.color_key - 1) % len(self.group_palette)
                ]
                fmt = _format(color, bold=True)
            else:
                fmt = self._formats.get(token.kind, self._formats["literal"])
            if not token.valid or token.kind == "invalid":
                fmt = self._invalid_format(fmt)
            start_unit = mapping.cp_to_u16(token.start)
            self.setFormat(
                start_unit, mapping.cp_to_u16(token.start + length) - start_unit, fmt
            )

        for diagnostic in analysis.diagnostics:
            start = max(0, min(len(text), diagnostic.start))
            end = max(start, min(len(text), diagnostic.end))
            if start == end:
                if not text:
                    continue
                start = max(0, start - 1)
                end = start + 1
            start_unit = mapping.cp_to_u16(start)
            fmt = self._invalid_format(self.format(start_unit))
            self.setFormat(start_unit, mapping.cp_to_u16(end) - start_unit, fmt)


class PatternHighlighter(_AnalysisHighlighter):
    pass


class ReplacementHighlighter(_AnalysisHighlighter):
    pass


class _FallbackTextInput(BoundedSingleLineTextEdit):
    def minimum_content_height(self) -> int:
        shape = ShapedWindow("क्षि ক্কি 中文 한국어", self.font())
        return max(28, int(max(line.height() for line in shape.lines)) + 12)


class RegexInput(_FallbackTextInput):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFont(resolve_editor_font().font)
        self.setMinimumHeight(self.minimum_content_height())
        self.highlighter = PatternHighlighter(self.document(), self)

    def set_analysis(self, analysis: RegexAnalysis) -> None:
        blocked = self.blockSignals(True)
        try:
            self.highlighter.set_analysis(analysis)
        finally:
            self.blockSignals(blocked)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            blocked = self.blockSignals(True)
            try:
                self.highlighter.rebuild_formats()
            finally:
                self.blockSignals(blocked)


class ReplacementInput(_FallbackTextInput):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFont(resolve_editor_font().font)
        self.setMinimumHeight(self.minimum_content_height())
        self.highlighter = ReplacementHighlighter(self.document(), self)

    def set_analysis(self, analysis: RegexAnalysis) -> None:
        blocked = self.blockSignals(True)
        try:
            self.highlighter.set_analysis(analysis)
        finally:
            self.blockSignals(blocked)

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.Type.PaletteChange:
            blocked = self.blockSignals(True)
            try:
                self.highlighter.rebuild_formats()
            finally:
                self.blockSignals(blocked)
