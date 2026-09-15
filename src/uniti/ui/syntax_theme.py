"""Theme-aware colors for file-type syntax-highlighting categories (BF-027).

Colors are derived algorithmically from the editor's base color, the same
approach already used for the Find/Replace regex palette
(`uniti.ui.regex_input.category_palette`) — so every category is
automatically contrast-safe (including in High Contrast, by construction)
without needing hand-tuned entries in every packaged or custom theme.
"""

from __future__ import annotations

from PySide6.QtGui import QColor

from uniti.ui.color_contrast import contrast_ratio


_CATEGORY_HUES = {
    "keyword": 260,
    "string": 130,
    "number": 30,
    "tag": 210,
    "attribute": 320,
    "heading": 0,
}
_NEUTRAL_CATEGORIES = ("comment", "punctuation")


def _hued_color(base: QColor, hue: int) -> QColor:
    dark_base = base.lightnessF() < 0.5
    lightness = 175 if dark_base else 90
    direction = 8 if dark_base else -8
    color = QColor.fromHsl(hue, 140, lightness)
    while contrast_ratio(color, base) < 4.5 and 8 <= lightness <= 247:
        lightness += direction
        color = QColor.fromHsl(hue, 140, max(0, min(255, lightness)))
    return color


def _neutral_color(base: QColor, *, start_lightness: int) -> QColor:
    dark_base = base.lightnessF() < 0.5
    lightness = start_lightness if dark_base else 255 - start_lightness
    direction = 8 if dark_base else -8
    color = QColor.fromHsl(0, 0, lightness)
    while contrast_ratio(color, base) < 4.5 and 8 <= lightness <= 247:
        lightness += direction
        color = QColor.fromHsl(0, 0, max(0, min(255, lightness)))
    return color


def syntax_category_palette(base: QColor) -> dict[str, QColor]:
    """One theme-safe color per syntax category, keyed by `SyntaxToken.category`.

    `comment` and `punctuation` are deliberately desaturated (de-emphasized,
    structural) rather than given a hue, matching how most syntax themes
    treat them.
    """

    colors = {category: _hued_color(base, hue) for category, hue in _CATEGORY_HUES.items()}
    colors["comment"] = _neutral_color(base, start_lightness=150)
    colors["punctuation"] = _neutral_color(base, start_lightness=190)
    return colors
