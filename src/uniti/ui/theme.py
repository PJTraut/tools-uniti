"""Application-wide native palettes for UNITI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
import weakref

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from uniti.ui.syntax_theme import syntax_category_palette


THEME_MODES = ("System", "Light", "Dark")
THEME_CONTRASTS = ("Standard", "High Contrast")


@dataclass(frozen=True, slots=True)
class EditorThemeTokens:
    base: QColor
    text: QColor
    gutter_base: QColor
    gutter_text: QColor
    selection: QColor
    selected_text: QColor
    match: QColor
    current_match: QColor
    invalid_byte: QColor
    space_marker: QColor
    tab_marker: QColor
    eol_marker: QColor
    invisible_marker: QColor
    invisible_background: QColor
    invisible_border: QColor
    current_line: QColor
    syntax: Mapping[str, QColor]


@dataclass(frozen=True, slots=True)
class ThemeSpec:
    mode: str
    contrast: str
    palette: QPalette
    editor: EditorThemeTokens

_system_app: weakref.ReferenceType[QApplication] | None = None
_system_palette: QPalette | None = None
_active_mode: str | None = None
_active_contrast: str | None = None
_active_spec: ThemeSpec | None = None


def _remember_system_palette(app: QApplication) -> QPalette:
    global _system_app, _system_palette
    remembered_app = _system_app() if _system_app is not None else None
    if (
        remembered_app is not app
        or _system_palette is None
        or _active_mode is None
        or (_active_mode == "System" and _active_contrast == "Standard")
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


def _high_contrast_palette(system_palette: QPalette, *, dark: bool) -> QPalette:
    palette = QPalette(system_palette)
    colors = (
        {
            QPalette.ColorRole.Window: "#000000",
            QPalette.ColorRole.WindowText: "#ffffff",
            QPalette.ColorRole.Base: "#000000",
            QPalette.ColorRole.AlternateBase: "#101010",
            QPalette.ColorRole.ToolTipBase: "#000000",
            QPalette.ColorRole.ToolTipText: "#ffffff",
            QPalette.ColorRole.Text: "#ffffff",
            QPalette.ColorRole.Button: "#000000",
            QPalette.ColorRole.ButtonText: "#ffffff",
            QPalette.ColorRole.BrightText: "#ff8080",
            QPalette.ColorRole.Highlight: "#66ccff",
            QPalette.ColorRole.HighlightedText: "#000000",
            QPalette.ColorRole.Link: "#66ccff",
            QPalette.ColorRole.PlaceholderText: "#cfcfcf",
        }
        if dark
        else {
            QPalette.ColorRole.Window: "#ffffff",
            QPalette.ColorRole.WindowText: "#000000",
            QPalette.ColorRole.Base: "#ffffff",
            QPalette.ColorRole.AlternateBase: "#f2f2f2",
            QPalette.ColorRole.ToolTipBase: "#ffffff",
            QPalette.ColorRole.ToolTipText: "#000000",
            QPalette.ColorRole.Text: "#000000",
            QPalette.ColorRole.Button: "#ffffff",
            QPalette.ColorRole.ButtonText: "#000000",
            QPalette.ColorRole.BrightText: "#8b0000",
            QPalette.ColorRole.Highlight: "#003b80",
            QPalette.ColorRole.HighlightedText: "#ffffff",
            QPalette.ColorRole.Link: "#004c99",
            QPalette.ColorRole.PlaceholderText: "#404040",
        }
    )
    _set_colors(palette, colors)
    disabled = "#b3b3b3" if dark else "#595959"
    for role in (
        QPalette.ColorRole.Text,
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            role,
            QColor(disabled),
        )
    return palette


def _relative_luminance(color: QColor) -> float:
    channels = []
    for value in color.getRgbF()[:3]:
        channels.append(
            value / 12.92
            if value <= 0.04045
            else ((value + 0.055) / 1.055) ** 2.4
        )
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def _current_line_tint(base: QColor, text: QColor) -> QColor:
    """A slight background tint for the current-line highlight (BF-060),
    derived algorithmically (like `syntax_category_palette`) rather than
    stored per-profile, so no theme schema/migration is needed for it: an
    alpha-blended `text` tone lightens a dark base and darkens a light one
    by construction, and stays subordinate to selection/match highlighting
    which are painted on top of it.
    """

    tint = QColor(text)
    tint.setAlpha(16)
    return tint


def _editor_tokens(
    palette: QPalette,
    *,
    dark: bool,
    high_contrast: bool,
) -> EditorThemeTokens:
    def role(selected: QPalette.ColorRole) -> QColor:
        return QColor(palette.color(selected))

    if high_contrast and dark:
        markers = ("#cfcfcf", "#ffffff", "#66ccff", "#ff80ff")
        invisible_background = QColor("#240024")
    elif high_contrast:
        markers = ("#595959", "#404040", "#004c99", "#700070")
        invisible_background = QColor("#fff2cc")
    elif dark:
        markers = ("#8b949e", "#a5b4c3", "#79c0ff", "#ffa198")
        invisible_background = QColor("#2d1b20")
    else:
        markers = ("#667085", "#475467", "#075fd8", "#7a271a")
        invisible_background = QColor("#fffaeb")
    match = role(QPalette.ColorRole.Highlight)
    match.setAlpha(120)
    current_match = QColor("#ffbf00" if dark else "#b54708")
    base_color = role(QPalette.ColorRole.Base)
    text_color = role(QPalette.ColorRole.Text)
    return EditorThemeTokens(
        base=base_color,
        text=text_color,
        gutter_base=role(QPalette.ColorRole.AlternateBase),
        gutter_text=role(QPalette.ColorRole.PlaceholderText),
        selection=role(QPalette.ColorRole.Highlight),
        selected_text=role(QPalette.ColorRole.HighlightedText),
        match=match,
        current_match=current_match,
        invalid_byte=role(QPalette.ColorRole.BrightText),
        space_marker=QColor(markers[0]),
        tab_marker=QColor(markers[1]),
        eol_marker=QColor(markers[2]),
        invisible_marker=QColor(markers[3]),
        invisible_background=invisible_background,
        invisible_border=QColor(markers[3]),
        current_line=_current_line_tint(base_color, text_color),
        syntax=MappingProxyType(syntax_category_palette(base_color)),
    )


def build_theme(
    system_palette: QPalette,
    mode: str,
    contrast: str,
) -> ThemeSpec:
    selected_mode = mode if mode in THEME_MODES else "System"
    selected_contrast = (
        contrast if contrast in THEME_CONTRASTS else "Standard"
    )
    system = QPalette(system_palette)
    if selected_contrast == "High Contrast":
        dark = selected_mode == "Dark" or (
            selected_mode == "System"
            and _relative_luminance(
                system.color(QPalette.ColorRole.Base)
            ) < 0.5
        )
        palette = _high_contrast_palette(system, dark=dark)
    elif selected_mode == "Light":
        dark = False
        palette = _light_palette(system)
    elif selected_mode == "Dark":
        dark = True
        palette = _dark_palette(system)
    else:
        palette = system
        dark = _relative_luminance(
            palette.color(QPalette.ColorRole.Base)
        ) < 0.5
    return ThemeSpec(
        mode=selected_mode,
        contrast=selected_contrast,
        palette=palette,
        editor=_editor_tokens(
            palette,
            dark=dark,
            high_contrast=selected_contrast == "High Contrast",
        ),
    )


def apply_theme(
    app: QApplication,
    mode: str,
    contrast: str = "Standard",
) -> ThemeSpec:
    """Apply one complete UNITI theme specification to the application."""

    global _active_mode, _active_contrast, _active_spec
    system_palette = _remember_system_palette(app)
    spec = build_theme(system_palette, mode, contrast)
    return install_theme(app, spec)


def active_theme(app: QApplication) -> ThemeSpec:
    active_app = _system_app() if _system_app is not None else None
    if active_app is app and _active_spec is not None:
        return _active_spec
    return build_theme(_remember_system_palette(app), "System", "Standard")


def resolve_editor_tokens(app: QApplication, mode: str, contrast: str) -> EditorThemeTokens:
    """Editor-pane tokens for a built-in theme mode, computed without
    installing anything application-wide — for a per-view theme choice
    (View > Editor Theme) that must not affect window chrome."""

    return build_theme(_remember_system_palette(app), mode, contrast).editor


def resolve_profile_editor_tokens(app: QApplication, profile, contrast: str = "Standard") -> EditorThemeTokens:
    """Editor-pane tokens for a custom theme profile, computed without
    installing anything application-wide — the per-view counterpart to
    `resolve_editor_tokens` for a user-defined profile rather than a
    built-in mode."""

    return build_profile_theme(_remember_system_palette(app), profile, contrast).editor


__all__ = [
    "EditorThemeTokens",
    "THEME_CONTRASTS",
    "THEME_MODES",
    "ThemeSpec",
    "active_theme",
    "apply_theme",
    "build_theme",
    "resolve_editor_tokens",
    "resolve_profile_editor_tokens",
]


def contrast_feedback(spec: ThemeSpec) -> tuple[tuple[str, float, float], ...]:
    """Ratios for text, selections, controls, and meaningful editor markers."""
    def ratio(a, b):
        hi, lo = sorted((_relative_luminance(a), _relative_luminance(b)), reverse=True)
        return (hi + .05) / (lo + .05)
    e = spec.editor
    text_threshold = 7.0 if spec.contrast == 'High Contrast' else 4.5
    marker_threshold = 4.5 if spec.contrast == 'High Contrast' else 3.0
    pairs = [('Editor text', e.text, e.base, text_threshold),
             ('Selected text', e.selected_text, e.selection, 4.5),
             ('Gutter text', e.gutter_text, e.gutter_base, marker_threshold)]
    for label, fg, bg in [('Window text', 'WindowText', 'Window'), ('Control text', 'ButtonText', 'Button'),
                          ('Input text', 'Text', 'Base'), ('Tooltip text', 'ToolTipText', 'ToolTipBase'),
                          ('Selection text', 'HighlightedText', 'Highlight')]:
        pairs.append((label, spec.palette.color(getattr(QPalette.ColorRole, fg)),
                      spec.palette.color(getattr(QPalette.ColorRole, bg)), 4.5))
    for role in ('space_marker', 'tab_marker', 'eol_marker', 'invisible_marker', 'invisible_border', 'invalid_byte', 'current_match'):
        pairs.append((role.replace('_', ' ').capitalize(), getattr(e, role), e.base, marker_threshold))
    for category, color in e.syntax.items():
        # Syntax highlighting is secondary color-coding, not primary body
        # text, so it's held to the same bar as the editor's other markers
        # (4.5:1 Standard / High Contrast) rather than the stricter 7:1
        # High Contrast body-text threshold — `syntax_category_palette`'s
        # own derivation loop only ever targets 4.5:1 regardless of mode.
        pairs.append(('Syntax ' + category, color, e.base, marker_threshold))
    return tuple((label, ratio(fg, bg), threshold) for label, fg, bg, threshold in pairs)


def profile_from_spec(spec: ThemeSpec, profile_id: str, name: str, base_mode: str):
    from uniti.app.theme_profiles import ThemeProfile, PALETTE_ROLES, EDITOR_ROLES, SYNTAX_ROLES
    colors = {'palette.' + r: spec.palette.color(getattr(QPalette.ColorRole, r)).name() for r in PALETTE_ROLES}
    colors.update({'disabled.' + r: spec.palette.color(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, r)).name()
                   for r in ('Text', 'WindowText', 'ButtonText')})
    colors.update({'editor.' + r: getattr(spec.editor, r).name() for r in EDITOR_ROLES})
    colors.update({'syntax.' + r: spec.editor.syntax[r].name() for r in SYNTAX_ROLES})
    return ThemeProfile(profile_id, name, base_mode, colors)


def build_profile_theme(system_palette: QPalette, profile, contrast='Standard', *, overlay=True) -> ThemeSpec:
    from uniti.app.theme_profiles import PALETTE_ROLES, EDITOR_ROLES, SYNTAX_ROLES
    palette = QPalette(system_palette)
    for role in PALETTE_ROLES:
        palette.setColor(getattr(QPalette.ColorRole, role), QColor(profile.colors['palette.' + role]))
    for role in ('Text', 'WindowText', 'ButtonText'):
        palette.setColor(QPalette.ColorGroup.Disabled, getattr(QPalette.ColorRole, role), QColor(profile.colors['disabled.' + role]))
    tokens = {r: QColor(profile.colors['editor.' + r]) for r in EDITOR_ROLES}
    tokens['match'].setAlpha(120)
    tokens['current_line'] = _current_line_tint(tokens['base'], tokens['text'])
    tokens['syntax'] = MappingProxyType({r: QColor(profile.colors['syntax.' + r]) for r in SYNTAX_ROLES})
    spec = ThemeSpec(profile.id, contrast, palette, EditorThemeTokens(**tokens))
    if contrast == 'High Contrast' and overlay and any(r < t for _, r, t in contrast_feedback(spec)):
        # Preserve the independently selected profile while supplying the validated
        # accessibility colors. Cloning in this mode starts from these visible colors.
        hc = build_theme(system_palette, profile.base_mode, contrast)
        spec = ThemeSpec(profile.id, contrast, hc.palette, hc.editor)
    return spec


def install_theme(app: QApplication, spec: ThemeSpec) -> ThemeSpec:
    """Publish tokens before palette-change events and update every open editor."""
    global _active_mode, _active_contrast, _active_spec
    _active_mode, _active_contrast, _active_spec = spec.mode, spec.contrast, spec
    app.setPalette(spec.palette)
    if app.palette() != spec.palette:
        # Cocoa may resolve unset System roles against the previous custom
        # palette (notably inactive/disabled links). Seed every original brush
        # explicitly, then restore the original resolve mask so System retains
        # its platform inheritance instead of becoming a permanent override.
        resolved = QPalette(spec.palette)
        for group in (QPalette.Active, QPalette.Inactive, QPalette.Disabled):
            for role in QPalette.ColorRole:
                if role not in (QPalette.NoRole, QPalette.NColorRoles):
                    resolved.setBrush(group, role, spec.palette.brush(group, role))
        app.setPalette(resolved)
        app.setPalette(spec.palette)
    for window in app.topLevelWidgets():
        for view in getattr(window, 'views', ()):
            setter = getattr(view, 'set_theme_tokens', None)
            if callable(setter):
                setter(spec.editor)
    return spec


def apply_profile(app: QApplication, profile, contrast='Standard') -> ThemeSpec:
    return install_theme(app, build_profile_theme(_remember_system_palette(app), profile, contrast))


def preview_active(app: QApplication) -> bool:
    return getattr(app, '_uniti_theme_editor', None) is not None


def system_theme_palette(app: QApplication) -> QPalette:
    """Capture the platform palette before any editor preview begins."""
    return _remember_system_palette(app)
