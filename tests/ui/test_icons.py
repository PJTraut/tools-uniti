import importlib.util
import os

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None, reason="PySide6 is not installed"
)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _opaque_colors(image):
    return {
        image.pixelColor(x, y).name()
        for y in range(image.height())
        for x in range(image.width())
        if image.pixelColor(x, y).alpha() == 255
    }


def test_lucide_icons_render_packaged_assets_at_high_dpi(app):
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QIcon

    from uniti.ui.icons import LUCIDE_ICONS, lucide_icon

    for name in LUCIDE_ICONS:
        icon = lucide_icon(name)
        assert not icon.isNull(), name
        for scale in (1.0, 1.5, 2.0):
            pixmap = icon.pixmap(QSize(24, 24), scale, QIcon.Mode.Normal)
            assert pixmap.size() == QSize(round(24 * scale), round(24 * scale))
            assert pixmap.devicePixelRatio() == scale
            image = pixmap.toImage()
            assert any(
                image.pixelColor(x, y).alpha() > 0
                for y in range(image.height())
                for x in range(image.width())
            ), name


def test_existing_icon_follows_palette_and_disabled_selected_states(app):
    from PySide6.QtGui import QColor, QIcon, QPalette

    from uniti.ui.icons import lucide_icon

    before = QPalette(app.palette())
    icon = lucide_icon("search-check")
    try:
        for normal in ("#171717", "#eeeeee"):
            palette = QPalette(before)
            palette.setColor(
                QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText, QColor(normal)
            )
            palette.setColor(
                QPalette.ColorGroup.Disabled,
                QPalette.ColorRole.ButtonText,
                QColor("#778899"),
            )
            palette.setColor(
                QPalette.ColorGroup.Active,
                QPalette.ColorRole.HighlightedText,
                QColor("#ffff00"),
            )
            app.setPalette(palette)
            for mode, color in (
                (QIcon.Mode.Normal, normal),
                (QIcon.Mode.Disabled, "#778899"),
                (QIcon.Mode.Selected, "#ffff00"),
            ):
                assert _opaque_colors(icon.pixmap(24, 24, mode).toImage()) == {color}
    finally:
        app.setPalette(before)


def test_find_replace_controls_have_icons_and_keep_accessible_names(app):
    from uniti.ui.find_replace import FindReplacePanel

    panel = FindReplacePanel(lambda: None)
    try:
        for button, label in (
            (panel.find_all_button, "Find All"),
            (panel.replace_all_button, "Replace All"),
            (panel.previous_button, "Previous Match"),
            (panel.next_button, "Next Match"),
            (panel.replace_button, "Replace Current Match"),
            (panel.find_clear_button, "Clear Find"),
            (panel.replace_clear_button, "Clear Replace"),
            (panel.report_toggle_button, "Hide Match Report"),
        ):
            assert not button.icon().isNull(), label
            assert button.accessibleName() == label
            assert button.toolTip() == label
        assert not panel.cancel_button.icon().isNull()
        assert panel.cancel_button.text() == "Cancel"
        opened = panel.report_toggle_button.icon().pixmap(24, 24).toImage()
        panel.report_toggle_button.click()
        assert panel.report_location == "Hidden"
        assert panel.report_toggle_button.accessibleName() == "Show Match Report"
        assert panel.report_toggle_button.icon().pixmap(24, 24).toImage() != opened
        panel.report_toggle_button.click()
        assert panel.report_location == "Right"
        assert panel.report_toggle_button.icon().pixmap(24, 24).toImage() == opened
    finally:
        panel.shutdown()
        panel.close()


def test_icons_preserve_native_palette_opacity_for_disabled_controls(app):
    from PySide6.QtGui import QColor, QIcon, QPalette

    from uniti.ui.icons import lucide_icon

    before = QPalette(app.palette())
    try:
        palette = QPalette(before)
        palette.setColor(
            QPalette.ColorGroup.Active,
            QPalette.ColorRole.ButtonText,
            QColor(255, 255, 255, 216),
        )
        palette.setColor(
            QPalette.ColorGroup.Disabled,
            QPalette.ColorRole.ButtonText,
            QColor(255, 255, 255, 63),
        )
        app.setPalette(palette)
        icon = lucide_icon("search-check")
        for mode, alpha in ((QIcon.Mode.Normal, 216), (QIcon.Mode.Disabled, 63)):
            image = icon.pixmap(24, 24, mode).toImage()
            assert max(
                image.pixelColor(x, y).alpha()
                for y in range(image.height())
                for x in range(image.width())
            ) == alpha
    finally:
        app.setPalette(before)
