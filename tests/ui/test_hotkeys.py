import importlib.util
import os
from pathlib import Path

import pytest


def test_hotkeys_popup_has_horizontal_categories_and_binding_columns(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    popup = window.show_hotkeys()
    app.processEvents()

    assert [button.text() for button in popup.category_buttons] == [
        "File",
        "Editing",
        "Navigation",
        "Find/Replace",
        "Editor View",
        "F/R View",
    ]
    assert [popup.table.horizontalHeaderItem(i).text() for i in range(3)] == [
        "Command",
        "Default",
        "Current",
    ]
    assert popup.isVisible() is True
    popup.reject()
    assert popup.isVisible() is False
    window.close()


def test_binding_change_updates_shared_action_and_persists(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QKeySequence
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    store = SettingsStore(tmp_path / "settings.json")
    window = UNITIMainWindow(settings_store=store)
    popup = window.show_hotkeys()

    assert popup.assign_sequence("editor.zoom_in", "Ctrl+K") is True
    action = window._command_actions["editor.zoom_in"]
    assert action.shortcut().toString(QKeySequence.SequenceFormat.PortableText) == "Ctrl+K"
    assert store.load().shortcut_overrides["editor.zoom_in"] == "Ctrl+K"
    assert popup.clear_sequence("editor.zoom_in") is True
    assert action.shortcut().isEmpty()
    popup.reset_selected("editor.zoom_in")
    assert action.shortcut().isEmpty() is False
    window.close()


def test_popup_reports_same_scope_collision_without_reassigning():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    popup = window.show_hotkeys()
    assert popup.assign_sequence("editor.zoom_in", "Ctrl+K") is True

    assert popup.assign_sequence("editor.zoom_out", "Ctrl+K") is False
    assert "Zoom In" in popup.last_error
    assert window._command_registry.current("editor.zoom_out") != "Ctrl+K"
    window.close()


def test_disjoint_editor_and_find_shortcuts_dispatch_by_focus(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "scoped.txt"
    source.write_text("text", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    window.show()
    window._command_registry.assign("editor.zoom_in", "Ctrl+K")
    window._command_registry.assign("find.zoom_in", "Ctrl+K")
    view.setFocus()
    app.processEvents()

    QTest.keyClick(view, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier)
    assert view.zoom_percent == 110
    assert window._find_replace.zoom_percent == 100

    window.show_find()
    window._find_replace.find_input.setFocus()
    app.processEvents()
    QTest.keyClick(
        window._find_replace.find_input,
        Qt.Key.Key_K,
        Qt.KeyboardModifier.ControlModifier,
    )
    assert view.zoom_percent == 110
    assert window._find_replace.zoom_percent == 110
    window.close_all_documents(force=True)
    window.close()


def test_editing_shortcut_reaches_focused_find_field(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "field-shortcut.txt"
    source.write_text("document", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    window.open_path(source)
    window.show()
    window.show_find()
    field = window._find_replace.find_input
    field.setFocus()
    QTest.keyClicks(field, "abc")
    app.processEvents()

    QTest.keyClick(field, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)

    assert field.text() == "ab"
    window.close_all_documents(force=True)
    window.close()
