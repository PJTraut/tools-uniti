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


def group_palette(base: QColor) -> tuple[QColor, ...]:
    """Per-capture-group colors, shared by the Find input and Match Report."""

    return tuple(_group_color(base, index) for index in range(1, len(_GROUP_HUES) + 1))


def bracket_color(base: QColor) -> QColor:
    """One distinct, neutral (desaturated) color for capturing-group parentheses.

    Deliberately not one of the per-group hues in `_GROUP_HUES`, so a group's
    own color (used for its `\\N :` label in the Match Report, and for its
    backreferences here) never doubles as the bracket color.
    """

    dark_base = base.lightnessF() < 0.5
    lightness = 200 if dark_base else 70
    direction = 8 if dark_base else -8
    color = QColor.fromHsl(0, 0, lightness)
    while _contrast_ratio(color, base) < 4.5 and 8 <= lightness <= 247:
        lightness += direction
        color = QColor.fromHsl(0, 0, max(0, min(255, lightness)))
    return color


def non_capturing_bracket_color(base: QColor) -> QColor:
    """A distinct neutral shade for non-capturing/lookaround/atomic group
    parentheses (BF-052) — the same desaturated "structural, not content"
    family as `bracket_color`, so it still visually reads as a bracket, but
    at a different lightness so it never paints identically to a real
    capturing group's parens.
    """

    capturing = bracket_color(base)
    dark_base = base.lightnessF() < 0.5
    lightness = 140 if dark_base else 115
    direction = 8 if dark_base else -8
    color = QColor.fromHsl(0, 0, lightness)
    while (
        (_contrast_ratio(color, base) < 4.5 or _contrast_ratio(color, capturing) < 1.5)
        and 8 <= lightness <= 247
    ):
        lightness += direction
        color = QColor.fromHsl(0, 0, max(0, min(255, lightness)))
    return color


# Hues chosen to maximize angular separation from every `_GROUP_HUES` value
# (minimum 15 degrees) and from each other (minimum 21 degrees), so no
# regex-syntax category can be mistaken for an actual capturing group's
# color (BF-052) — unlike the previous design, which reused
# `_group_color(base, 2)`/`_group_color(base, 3)` (literally Group 2's and
# Group 3's own colors) for most non-group token kinds.
_CATEGORY_HUES = {
    "escape": 90,
    "unicode_property": 111,
    "unicode_escape": 234,
    "char_class": 308,
    "anchor": 33,
    "quantifier": 69,
    "alternation": 192,
    "backreference": 354,
    "invalid": 153,
}


def _category_color(base: QColor, hue: int) -> QColor:
    dark_base = base.lightnessF() < 0.5
    lightness = 170 if dark_base else 95
    direction = 8 if dark_base else -8
    # Lower saturation than `_group_color`'s 190: category colors are a
    # deliberately muted "syntax" family, visually distinct from the vivid
    # capture-group identity colors even before considering hue.
    color = QColor.fromHsl(hue, 130, lightness)
    while _contrast_ratio(color, base) < 4.5 and 8 <= lightness <= 247:
        lightness += direction
        color = QColor.fromHsl(hue, 130, max(0, min(255, lightness)))
    return color


def category_palette(base: QColor) -> dict[str, QColor]:
    """Distinct, non-group colors for regex syntax categories (BF-052),
    keyed by `RegexToken.kind` (plus `"invalid"` for the underline color) —
    reviewed and given a unique color per type, replacing the previous
    design where most non-group kinds shared just two colors, both
    borrowed from the group palette itself.
    """

    return {kind: _category_color(base, hue) for kind, hue in _CATEGORY_HUES.items()}


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
        self.group_palette = group_palette(base)
        self.bracket_color = bracket_color(base)
        self.non_capturing_bracket_color = non_capturing_bracket_color(base)
        categories = category_palette(base)
        self._formats = {
            "literal": _format(text),
            "escape": _format(categories["escape"]),
            "unicode_escape": _format(categories["unicode_escape"], bold=True),
            "unicode_property": _format(categories["unicode_property"]),
            "char_class": _format(categories["char_class"]),
            "anchor": _format(categories["anchor"], bold=True),
            "quantifier": _format(categories["quantifier"], bold=True),
            "alternation": _format(categories["alternation"], bold=True),
            "group_open": _format(self.bracket_color, bold=True),
            "group_close": _format(self.bracket_color, bold=True),
            "group_name": _format(self.bracket_color, bold=True),
            "flag": _format(text),
            "special": _format(text),
            "backreference": _format(categories["backreference"], bold=True),
        }
        self._non_capturing_bracket_format = _format(
            self.non_capturing_bracket_color, bold=True
        )
        self._invalid_color = categories["invalid"]
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
            if (
                token.kind in ("group_open", "group_close")
                and token.group_number is None
            ):
                # A non-capturing/lookaround/atomic group's brackets have no
                # group identity to color with — use the dedicated neutral
                # non-capturing color (BF-052) so they still read as
                # distinct from every capturing group's own color below.
                fmt = self._non_capturing_bracket_format
            elif token.color_key is not None:
                # A capturing group's own brackets/name paint in that
                # group's own color too, same as its backreferences — users
                # rely on this to visually trace which parens belong to
                # which group at a glance (confirmed directly: reverting
                # this to a neutral bracket color, as an earlier pass here
                # mistakenly did reading BF-020's own wording too literally,
                # regressed the visible bug "capturing groups all white").
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
