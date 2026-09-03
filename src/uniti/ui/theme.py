"""Application-wide native palettes for UNITI."""

from __future__ import annotations

import weakref

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication


THEME_MODES = ("System", "Light", "Dark")

_system_app: weakref.ReferenceType[QApplication] | None = None
_system_palette: QPalette | None = None
_active_mode: str | None = None


def _remember_system_palette(app: QApplication) -> QPalette:
    global _system_app, _system_palette
    remembered_app = _system_app() if _system_app is not None else None
    if (
        remembered_app is not app
        or _system_palette is None
        or _active_mode in {None, "System"}
    ):
        _system_app = weakref.ref(app)
        _system_palette = QPalette(app.palette())
    return QPalette(_system_palette)


def _set_colors(palette: QPalette, colors: dict[QPalette.ColorRole, str]) -> None:
    for role, color in colors.items():
        palette.setColor(role, QColor(color))


def _light_palette(system_palette: QPalette) -> QPalette:
    palette = QPalette(system_palette)
    _set_colors(
        palette,
        {
            QPalette.ColorRole.Window: "#f4f7fb",
            QPalette.ColorRole.WindowText: "#111827",
            QPalette.ColorRole.Base: "#ffffff",
            QPalette.ColorRole.AlternateBase: "#e8eef7",
            QPalette.ColorRole.ToolTipBase: "#ffffff",
            QPalette.ColorRole.ToolTipText: "#111827",
            QPalette.ColorRole.Text: "#111827",
            QPalette.ColorRole.Button: "#e4ebf5",
            QPalette.ColorRole.ButtonText: "#111827",
            QPalette.ColorRole.BrightText: "#b42318",
            QPalette.ColorRole.Highlight: "#2563eb",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.Link: "#075fd8",
            QPalette.ColorRole.PlaceholderText: "#667085",
        },
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#8a94a3"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor("#8a94a3"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#8a94a3"),
    )
    return palette


def _dark_palette(system_palette: QPalette) -> QPalette:
    palette = QPalette(system_palette)
    _set_colors(
        palette,
        {
            QPalette.ColorRole.Window: "#161b22",
            QPalette.ColorRole.WindowText: "#f0f4f8",
            QPalette.ColorRole.Base: "#0d1117",
            QPalette.ColorRole.AlternateBase: "#21262d",
            QPalette.ColorRole.ToolTipBase: "#27313d",
            QPalette.ColorRole.ToolTipText: "#f0f4f8",
            QPalette.ColorRole.Text: "#f0f4f8",
            QPalette.ColorRole.Button: "#27313d",
            QPalette.ColorRole.ButtonText: "#f0f4f8",
            QPalette.ColorRole.BrightText: "#ff7b72",
            QPalette.ColorRole.Highlight: "#58a6ff",
            QPalette.ColorRole.HighlightedText: "#06121f",
            QPalette.ColorRole.Link: "#79c0ff",
            QPalette.ColorRole.PlaceholderText: "#8b949e",
        },
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Text,
        QColor("#768390"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.WindowText,
        QColor("#768390"),
    )
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.ButtonText,
        QColor("#768390"),
    )
    return palette


def apply_theme(app: QApplication, mode: str) -> None:
    """Apply one of UNITI's supported palettes to the whole application."""

    global _active_mode
    if mode not in THEME_MODES:
        mode = "System"
    system_palette = _remember_system_palette(app)
    if mode == "Light":
        app.setPalette(_light_palette(system_palette))
    elif mode == "Dark":
        app.setPalette(_dark_palette(system_palette))
    else:
        app.setPalette(system_palette)
    _active_mode = mode
