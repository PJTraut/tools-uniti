"""Shared WCAG relative-luminance/contrast helpers for theme-aware colors."""

from __future__ import annotations

from PySide6.QtGui import QColor


def relative_luminance(color: QColor) -> float:
    channels: list[float] = []
    for value in color.getRgbF()[:3]:
        channels.append(
            value / 12.92 if value <= 0.04045 else ((value + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: QColor, second: QColor) -> float:
    high, low = sorted(
        (relative_luminance(first), relative_luminance(second)),
        reverse=True,
    )
    return (high + 0.05) / (low + 0.05)
