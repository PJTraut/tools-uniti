import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _contrast_ratio(first, second) -> float:
    def luminance(color):
        channels = []
        for value in color.getRgbF()[:3]:
            channels.append(
                value / 12.92
                if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
            )
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


@pytest.mark.parametrize("mode", ("System", "Light", "Dark"))
def test_high_contrast_specs_meet_text_and_marker_ratios(mode: str):
    from PySide6.QtWidgets import QApplication

    from uniti.ui.theme import THEME_CONTRASTS, THEME_MODES, build_theme

    app = QApplication.instance() or QApplication([])
    spec = build_theme(app.palette(), mode, "High Contrast")

    assert mode in THEME_MODES
    assert THEME_CONTRASTS == ("Standard", "High Contrast")
    assert spec.mode == mode
    assert spec.contrast == "High Contrast"
    assert _contrast_ratio(spec.editor.text, spec.editor.base) >= 7.0
    for color in (
        spec.editor.space_marker,
        spec.editor.tab_marker,
        spec.editor.eol_marker,
        spec.editor.invisible_marker,
        spec.editor.invisible_border,
    ):
        assert _contrast_ratio(color, spec.editor.base) >= 4.5


@pytest.mark.parametrize("mode", ("System", "Light", "Dark"))
@pytest.mark.parametrize("contrast", ("Standard", "High Contrast"))
def test_every_theme_combination_has_complete_editor_tokens(mode: str, contrast: str):
    from dataclasses import fields

    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from uniti.ui.theme import EditorThemeTokens, build_theme

    app = QApplication.instance() or QApplication([])
    spec = build_theme(app.palette(), mode, contrast)

    assert all(
        isinstance(getattr(spec.editor, field.name), QColor)
        and getattr(spec.editor, field.name).isValid()
        for field in fields(EditorThemeTokens)
    )


def test_apply_and_active_theme_retain_both_independent_axes():
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from uniti.ui.theme import active_theme, apply_theme

    app = QApplication.instance() or QApplication([])
    original = QPalette(app.palette())
    try:
        applied = apply_theme(app, "Dark", "High Contrast")
        assert active_theme(app) == applied
        assert applied.mode == "Dark"
        assert applied.contrast == "High Contrast"

        standard = apply_theme(app, "Light")
        assert standard.mode == "Light"
        assert standard.contrast == "Standard"
    finally:
        app.setPalette(original)
        apply_theme(app, "System")


def test_profile_applies_every_palette_editor_and_disabled_role():
    from dataclasses import replace
    from PySide6.QtWidgets import QApplication
    from PySide6.QtGui import QPalette
    from uniti.app.theme_profiles import packaged_profiles
    from uniti.ui.theme import build_profile_theme
    app = QApplication.instance() or QApplication([])
    profile = packaged_profiles()[0]
    colors = dict(profile.colors, **{'editor.text': '#123456', 'disabled.Text': '#456789'})
    spec = build_profile_theme(app.palette(), replace(profile, colors=colors), 'Standard')
    assert spec.palette.color(QPalette.ColorRole.Base).name() == '#fbf7ef'
    assert spec.editor.text.name() == '#123456'
    assert spec.editor.match.alpha() == 120
    assert spec.palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).name() == '#456789'


def test_profile_high_contrast_overlay_retains_thresholds():
    from PySide6.QtWidgets import QApplication
    from uniti.app.theme_profiles import packaged_profiles
    from uniti.ui.theme import build_profile_theme, contrast_feedback
    app = QApplication.instance() or QApplication([])
    for profile in packaged_profiles():
        spec = build_profile_theme(app.palette(), profile, 'High Contrast')
        assert spec.mode == profile.id
        assert all(ratio >= threshold for _, ratio, threshold in contrast_feedback(spec))
