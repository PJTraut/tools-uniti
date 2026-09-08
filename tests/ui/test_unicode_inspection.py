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


def _key(app, target, pressed, key, modifiers):
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QKeyEvent

    app.sendEvent(target, QKeyEvent(
        QEvent.Type.KeyPress if pressed else QEvent.Type.KeyRelease, key, modifiers
    ))


@pytest.mark.parametrize("mode", ["off", "eol", "spaces_tabs", "invisible_unicode", "all"])
def test_hold_inspection_respects_mode_and_ends_on_release_or_deactivation(app, tmp_path, mode):
    from PySide6.QtCore import QEvent, Qt
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "hold.txt"
    path.write_text("a\u00a0b\u200b\n", encoding="utf-8")
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.set_whitespace_mode(mode)
        before = (document.revision, view.state.cursor, view.state.anchor)
        modifiers = Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier
        try:
            assert not view.whitespace_details_visible
            for released in (Qt.Key.Key_Control, Qt.Key.Key_Alt):
                _key(app, view, True, Qt.Key.Key_Alt, modifiers)
                assert view.whitespace_details_visible == (mode != "off")
                _key(app, view, False, released, modifiers)
                assert not view.whitespace_details_visible
            _key(app, view, True, Qt.Key.Key_Alt, modifiers)
            app.sendEvent(app, QEvent(QEvent.Type.ApplicationDeactivate))
            assert not view.whitespace_details_visible
            assert view.whitespace_mode.value == mode
            assert (document.revision, view.state.cursor, view.state.anchor) == before
        finally:
            app.sendEvent(app, QEvent(QEvent.Type.ApplicationDeactivate))
            view.close()


@pytest.mark.parametrize("height", [90, 400])
def test_single_selected_codepoint_inspection_works_with_whitespace_off(app, tmp_path, height):
    from PySide6.QtCore import QEvent, Qt
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "selected.txt"
    path.write_text("A\U0001f642\u200d", encoding="utf-8")
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.resize(500, height)
        view.show()
        view.setFocus()
        app.processEvents()
        view.state.anchor, view.state.cursor = 1, 2
        try:
            before = view.viewport().grab().toImage()
            _key(app, view, True, Qt.Key.Key_Alt,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
            assert "U+1F642" in view.selected_character_detail
            assert "SLIGHTLY SMILING FACE" in view.selected_character_detail
            assert not view.whitespace_details_visible
            assert view.viewport().grab().toImage() != before
            view.state.anchor = 0
            assert view.selected_character_detail is None
            app.sendEvent(app, QEvent(QEvent.Type.ApplicationDeactivate))
            assert view.selected_character_detail is None
            assert document.revision == 0
        finally:
            app.sendEvent(app, QEvent(QEvent.Type.ApplicationDeactivate))
            view.close()


def test_hotkeys_panel_configures_and_persists_inspection(app, tmp_path):
    from PySide6.QtWidgets import QPushButton
    from uniti.app.commands import CommandCategory
    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    store = SettingsStore(tmp_path / "settings.json")
    window = UNITIMainWindow(settings_store=store)
    try:
        assert window._command_actions["file.quit"].text() == "Quit"
        assert any(a.text().replace("&", "") == "Hotkeys"
            for a in window.menuBar().actions())
        popup = window.show_hotkeys()
        popup.select_category(CommandCategory.EDITOR_VIEW)
        assert popup.inspection_group.isVisible()
        for name, checkbox in popup.inspection_checks.items():
            checkbox.setChecked(name in {"Alt", "Shift"})
        next(b for b in popup.findChildren(QPushButton)
            if b.text() == "Apply Hold Shortcut").click()
        assert store.load().whitespace_inspect_modifiers == "Alt+Shift"
        for name, checkbox in popup.inspection_checks.items():
            checkbox.setChecked(name == "Alt")
        next(b for b in popup.findChildren(QPushButton)
            if b.text() == "Apply Hold Shortcut").click()
        assert popup.last_error
        assert store.load().whitespace_inspect_modifiers == "Alt+Shift"
        next(b for b in popup.findChildren(QPushButton)
            if b.text() == "Reset Hold Shortcut").click()
        assert store.load().whitespace_inspect_modifiers == "Ctrl+Alt"
    finally:
        window.close()


def test_compact_markers_are_distinct_and_transparent(app):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    from uniti.ui.whitespace_painter import paint_compact_marker

    labels = ["EMSP", "ENSP", "NBSP", "NNBSP", "THINSP", "HAIRSP", "IDSP",
        "ZWSP", "ZWNJ", "ZWJ", "WJ", "LRM", "RLM", "BOM"]
    images = []
    for label in labels:
        image = QImage(24, 32, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setPen(QColor("#ff00ff"))
        paint_compact_marker(painter, label, QRectF(4, 4, 16, 24))
        painter.end()
        assert any(image.pixelColor(x, y).alpha()
            for x in range(24) for y in range(32)), label
        assert all(image != earlier for earlier in images), label
        assert image.pixelColor(0, 0).alpha() == 0
        images.append(image)


def test_held_detail_lists_adjacent_marker_types_readably(app, tmp_path):
    from PySide6.QtCore import QEvent, Qt
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "adjacent.txt"
    path.write_bytes(" \u00a0\u200b\u200d\t\r\n".encode())
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.set_whitespace_mode("all")
        view.resize(600, 400)
        view.show()
        app.processEvents()
        try:
            _key(app, view, True, Qt.Key.Key_Alt,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
            view.viewport().repaint()
            for name in ("SPACE", "NBSP", "ZWSP", "ZWJ", "TAB", "CRLF"):
                assert any(name in item for item in view.inspection_entries)
            assert len(view.inspection_entries) == 6
            app.sendEvent(app, QEvent(QEvent.Type.ApplicationDeactivate))
            view.viewport().repaint()
            assert not view.inspection_entries
        finally:
            app.sendEvent(app, QEvent(QEvent.Type.ApplicationDeactivate))
            view.close()


def test_whitespace_positions_after_supplementary_character(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QTextLayout
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "supplementary.txt"
    text = "\U0001f642 \u00a0"
    # Keep the synthetic LF fixture byte-exact on Windows, where text mode
    # writes otherwise translate it to CRLF.
    path.write_bytes((text + "\n").encode("utf-8"))
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.set_whitespace_mode("all")
        view.resize(600, 300)
        positions = {}
        monkeypatch.setattr(view, "_paint_whitespace_marker",
            lambda painter, kind, label, x1, x2, y: positions.update({label: x1}))
        try:
            view.show()
            app.processEvents()
            layout = QTextLayout(text, view.font())
            layout.beginLayout()
            line = layout.createLine()
            line.setLineWidth(600)
            layout.endLayout()
            for label, utf16_index in (("SPACE", 2), ("NBSP", 3), ("LF", 4)):
                expected = view._gutter_width + view._layout_cursor_x(line, utf16_index)
                assert positions[label] == pytest.approx(expected)
        finally:
            view.close()


@pytest.mark.parametrize("font_scale", [0.5, 1.0, 2.0, 3.0])
@pytest.mark.parametrize("device_scale", [1.0, 2.0])
def test_space_marker_alpha_centroid_is_centered(app, tmp_path, font_scale, device_scale):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView
    from uniti.ui.whitespace import WhitespaceKind

    path = tmp_path / "centroid.txt"
    path.write_bytes(b" ")
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        font = view.font()
        font.setPointSizeF(10.0 * font_scale)
        view.setFont(font)
        width, height = 96, 48
        image = QImage(int(width * device_scale), int(height * device_scale),
            QImage.Format.Format_ARGB32)
        image.setDevicePixelRatio(device_scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        view._paint_whitespace_marker(painter, WhitespaceKind.SPACE, "SPACE",
            21.25, 29.75, 13.25)
        painter.end()
        total = 0.0
        x_moment = 0.0
        y_moment = 0.0
        for py in range(image.height()):
            for px in range(image.width()):
                alpha = image.pixelColor(px, py).alpha()
                total += alpha
                x_moment += alpha * (px + 0.5) / device_scale
                y_moment += alpha * (py + 0.5) / device_scale
        assert total > 0
        assert x_moment / total == pytest.approx((21.25 + 29.75) / 2, abs=0.2)
        assert y_moment / total == pytest.approx(13.25 + view._line_height / 2, abs=0.2)
        view.close()


def test_custom_hold_binding_is_effective_after_reloading_settings(app, tmp_path):
    from dataclasses import replace
    from PySide6.QtCore import QEvent, Qt
    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.unicode_inspection import unicode_inspection

    store = SettingsStore(tmp_path / "settings.json")
    store.save(replace(Settings(), whitespace_inspect_modifiers="Alt+Shift"))
    window = UNITIMainWindow(settings_store=store)
    controller = unicode_inspection(app)
    try:
        _key(app, window, True, Qt.Key.Key_Alt,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
        assert not controller.active
        _key(app, window, True, Qt.Key.Key_Shift,
            Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
        assert controller.active
        window.set_inspection_modifiers("")
        assert not controller.active
        assert store.load().whitespace_inspect_modifiers == ""
        _key(app, window, True, Qt.Key.Key_Shift,
            Qt.KeyboardModifier.AltModifier | Qt.KeyboardModifier.ShiftModifier)
        assert not controller.active
    finally:
        controller.set_modifiers("Ctrl+Alt")
        app.sendEvent(app, QEvent(QEvent.Type.ApplicationDeactivate))
        window.close()
