"""Integrated automated acceptance checks for the v0.001a16 usable alpha."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is not installed",
)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _wait_for_idle(app, find_replace) -> None:
    from PySide6.QtTest import QTest

    for _ in range(400):
        app.processEvents()
        if not find_replace.busy:
            return
        QTest.qWait(5)
    pytest.fail("Find/Replace operation did not finish")


def _wait_for_pattern(app, find_replace) -> None:
    from PySide6.QtTest import QTest

    for _ in range(400):
        app.processEvents()
        if find_replace.compile_current() is not None:
            return
        QTest.qWait(5)
    pytest.fail("Find/Replace pattern analysis did not finish")


def _text(view) -> str:
    return view.document.read(0, view.document.total_chars())


def test_replace_all_is_one_atomic_undo(tmp_path: Path):
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "replace-all.txt"
    source.write_text("one one one", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    panel = window._find_replace
    panel.find_input.set_text("one")
    panel.replace_input.set_text("two")
    _wait_for_pattern(app, panel)
    panel.replace_all()
    _wait_for_idle(app, panel)

    assert _text(view) == "two two two"
    assert view.document.can_undo is True
    view.state.undo()
    assert _text(view) == "one one one"
    assert view.document.can_undo is False
    window.close_all_documents(force=True)
    window.close()


def test_editor_and_hotkey_settings_survive_while_panel_uses_defaults(
    tmp_path: Path,
):
    from PySide6.QtWidgets import QApplication, QLabel

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "state.txt"
    source.write_text("Привет Western", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])

    first = UNITIMainWindow(settings_store=store)
    first.open_path(source)
    first.zoom_in_editor()
    first.zoom_in_editor()
    first.zoom_in_editor()
    first.set_editor_wrap(True)
    first._find_replace.set_zoom_percent(120)
    first._find_replace.set_report_location("Hidden")
    first._command_registry.assign("navigation.go_to_line", "Ctrl+Shift+L")
    first.close_all_documents(force=True)
    first.close()

    second = UNITIMainWindow(settings_store=store)
    view = second.open_path(source)
    status = {label.text() for label in second.statusBar().findChildren(QLabel)}

    assert view.zoom_percent == 130
    assert view.soft_wrap is True
    assert second._find_replace.zoom_percent == 100
    assert second._find_replace.report_location == "Right"
    assert second._command_registry.current("navigation.go_to_line") == (
        "Ctrl+Shift+L"
    )
    assert {"130%", "Wrap"} <= status
    second.close_all_documents(force=True)
    second.close()


def test_focused_find_input_owns_editing_commands_without_touching_document(
    tmp_path: Path,
):
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "focus.txt"
    source.write_text("document", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    view.state.move_document_end()
    view.state.insert_text("!")
    window.show_find()
    field = window._find_replace.find_input
    field.setFocus()
    QTest.keyClicks(field, "abc")
    app.processEvents()

    window.undo_current()
    assert field.text() == "ab"
    assert _text(view) == "document!"
    window.redo_current()
    assert field.text() == "abc"
    assert _text(view) == "document!"
    window.close_all_documents(force=True)
    window.close()
