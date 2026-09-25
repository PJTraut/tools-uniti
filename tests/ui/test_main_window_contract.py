import ast
import importlib.util
import os
from pathlib import Path

import pytest


MAIN = Path("src/uniti/ui/main_window.py")
SHORTCUT_POLICY = Path("src/uniti/ui/shortcut_policy.py")
APPLICATION = Path("src/uniti/app/application.py")


def test_main_window_declares_tabs_file_edit_actions_and_status():
    assert MAIN.exists()
    source = MAIN.read_text(encoding="utf-8")
    shortcut_source = SHORTCUT_POLICY.read_text(encoding="utf-8")
    for required in ("QTabWidget", "Open", "Save", "Save As", "Undo", "Redo", "UNITIStatusBar"):
        assert required in source + shortcut_source
    assert "build_shortcut_policy" in source
    assert "QPlainTextEdit" not in source


def test_application_imports_pyside6_only_inside_runtime_function():
    assert APPLICATION.exists()
    tree = ast.parse(APPLICATION.read_text(encoding="utf-8"))
    top_level_imports = [
        node
        for node in tree.body
        if isinstance(node, (ast.Import, ast.ImportFrom))
    ]
    assert all("PySide6" not in ast.unparse(node) for node in top_level_imports)


def test_application_module_imports_without_pyside6():
    from uniti.app import application

    assert callable(application.main)


def test_main_window_offscreen_open_edit_save_when_pyside6_available(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "input.txt"
    output = tmp_path / "output.txt"
    source.write_text("abc\n", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    assert window._tabs is window.panes.active_leaf.tabs
    view = window.open_path(source)
    view.state.move_to(3)
    view.state.insert_text("X")
    window.save_current_as(output)
    app.processEvents()
    assert output.read_text(encoding="utf-8") == "abcX\n"
    window.close_all_documents(force=True)
    window.close()


def test_startup_recovery_is_not_owned_by_each_editor_window():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")

    from uniti.ui.main_window import UNITIMainWindow

    assert not hasattr(UNITIMainWindow, "recover_startup_sessions")


def test_application_uses_app_paths_and_settings_store():
    source = MAIN.read_text(encoding="utf-8")
    application = APPLICATION.read_text(encoding="utf-8")
    assert "SettingsStore" in source
    assert "last_directory" in source
    assert "AppPaths.current" in application
    assert "SettingsStore" in application
    assert "paths.recovery_dir" in application


def test_desktop_startup_creates_one_service_owned_window():
    application = APPLICATION.read_text(encoding="utf-8")
    assert "UNITIService(" in application
    assert "service.new_window()" in application
    assert 'context.data["service"] = service' in application


def test_main_window_handles_open_and_external_save_errors_in_ui():
    source = MAIN.read_text(encoding="utf-8")
    assert "ExternalFileChangedError" in source
    assert "File Changed on Disk" in source
    assert "Open Failed" in source
    assert "Save Failed" in source


def test_main_window_does_not_bypass_document_history_for_replace_all():
    source = MAIN.read_text(encoding="utf-8")
    assert "_reload_after_stream_replace" not in source
    assert "streamReplaceCommitted.connect" not in source


def test_main_window_uses_shared_resource_manager_for_workers_and_tab_priority():
    source = MAIN.read_text(encoding="utf-8")
    assert "ResourceManager" in source
    assert "resource_manager" in source
    assert "self._resources.tasks" in source
    assert "set_resource_active" in source


def test_main_window_flushes_and_shuts_down_recovery_manager_on_application_close():
    source = MAIN.read_text(encoding="utf-8")
    assert "self._recovery_manager.shutdown()" in source


def test_main_window_periodically_observes_resource_memory_pressure():
    source = MAIN.read_text(encoding="utf-8")
    assert "_resource_timer" in source
    assert "observe_resources" in source
    assert "_resource_probe_future" in source
    assert "self._resources.workers.submit" in source
    assert "sample_resources" in source


def test_pause_background_command_stays_in_existing_editor_view_category():
    source = SHORTCUT_POLICY.read_text(encoding="utf-8")
    assert '"view.pause_background"' in source
    assert "category.EDITOR_VIEW" in source


def test_main_window_accepts_completed_startup_snapshot_for_diagnostics():
    source = MAIN.read_text(encoding="utf-8")
    assert "startup_snapshot" in source
    assert "set_startup_snapshot" in source


def test_tools_menu_exports_selected_dogfood_path_and_confirms_clear(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from datetime import date

    from PySide6.QtGui import QAction
    from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox

    from uniti.app.dogfood import (
        CPUClass,
        RAMClass,
        DogfoodRecorder,
        HostFacts,
        OSFamily,
    )
    from uniti.app.dogfood_store import DogfoodStore
    from uniti.app.service import QuitChoice, UNITIService
    from uniti.app.session_store import SessionStore
    from uniti.app.settings import SettingsStore
    from uniti.resources import ResourceManager

    class Recovery:
        def shutdown(self):
            return None

    app = QApplication.instance() or QApplication([])
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=1),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=SessionStore(tmp_path / "sessions"),
        recovery_manager=Recovery(),
        dogfood_recorder=DogfoodRecorder(
            HostFacts(
                "v0.001a21",
                OSFamily.MACOS,
                CPUClass.C5_8,
                RAMClass.GIB_16_31,
            ),
            day=date(2026, 9, 5),
        ),
        dogfood_store=DogfoodStore(tmp_path / "dogfood"),
    )
    window = service.new_window()
    destination = tmp_path / "selected-dogfood.json"
    calls = []
    monkeypatch.setattr(
        QFileDialog,
        "getSaveFileName",
        lambda *_args, **_kwargs: (str(destination), "JSON (*.json)"),
    )
    monkeypatch.setattr(
        service,
        "export_dogfood_evidence",
        lambda path: calls.append(("export", Path(path))),
    )
    monkeypatch.setattr(
        service,
        "clear_dogfood_evidence",
        lambda: calls.append(("clear",)),
    )
    answers = iter(
        (
            QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Yes,
        )
    )
    monkeypatch.setattr(
        QMessageBox,
        "question",
        lambda *_args, **_kwargs: next(answers),
    )
    try:
        action_texts = {
            action.text() for action in window.findChildren(QAction)
        }
        assert "Export Dogfood Evidence…" in action_texts
        assert "Clear Dogfood Evidence…" in action_texts

        window._export_dogfood_action.trigger()
        window._clear_dogfood_action.trigger()
        window._clear_dogfood_action.trigger()

        assert calls == [("export", destination), ("clear",)]
    finally:
        monkeypatch.undo()
        service.request_quit(lambda _entry: QuitChoice.DISCARD)
        app.processEvents()


def test_main_window_applies_and_preserves_editor_view_settings(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QLabel

    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "configured.txt"
    source.write_text("Привет", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(editor_zoom_percent=130, editor_font_weight=600, soft_wrap=True))
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)

    view = window.open_path(source)
    app.processEvents()

    assert view.zoom_percent == 130
    assert view.font_weight == 600
    assert view.soft_wrap is True
    assert store.load().editor_zoom_percent == 130
    assert store.load().editor_font_weight == 600
    status_text = {label.text() for label in window.statusBar().findChildren(QLabel)}
    assert "130%" in status_text
    assert "Wrap" in status_text
    window.zoom_in_editor()
    assert view.zoom_percent == 140
    assert store.load().editor_zoom_percent == 140
    window.increase_editor_font_weight()
    assert view.font_weight == 700
    assert store.load().editor_font_weight == 700
    window.decrease_editor_font_weight()
    assert view.font_weight == 600
    window.reset_editor_font_weight()
    assert view.font_weight == 400
    assert store.load().editor_font_weight == 400
    window.set_editor_wrap(False)
    assert view.soft_wrap is False
    assert store.load().soft_wrap is False
    window.close_all_documents(force=True)
    window.close()


def test_opening_a_document_assigns_its_syntax_profile_by_extension(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import Settings, SettingsStore
    from uniti.core.syntax_profiles import JSON, PLAIN_TEXT
    from uniti.ui.main_window import UNITIMainWindow

    json_path = tmp_path / "data.json"
    json_path.write_text("{}", encoding="utf-8")
    plain_path = tmp_path / "notes.txt"
    plain_path.write_text("hello", encoding="utf-8")
    usj_path = tmp_path / "book.usj"
    usj_path.write_text("{}", encoding="utf-8")

    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(syntax_extension_overrides={"usj": "json"}))
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)

    json_view = window.open_path(json_path)
    plain_view = window.open_path(plain_path)
    usj_view = window.open_path(usj_path)
    app.processEvents()

    assert json_view.syntax_profile is JSON
    assert plain_view.syntax_profile is PLAIN_TEXT
    assert usj_view.syntax_profile is JSON

    window.close_all_documents(force=True)
    window.close()


def test_pane_split_clones_view_state_and_assignment_is_non_destructive(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.service import UNITIService
    from uniti.app.session_store import SessionStore
    from uniti.app.settings import SettingsStore
    from uniti.resources import ResourceManager

    class Recovery:
        def attach(self, _document, **_kwargs):
            return None

        def detach(self, _document, *, clean):
            return None

        def shutdown(self):
            return None

    app = QApplication.instance() or QApplication([])
    first_path = tmp_path / "first.txt"
    second_path = tmp_path / "second.txt"
    first_path.write_text("first document", encoding="utf-8")
    second_path.write_text("second document", encoding="utf-8")
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=SessionStore(tmp_path / "sessions"),
        recovery_manager=Recovery(),
    )
    window = service.new_window()
    first = window.open_path(first_path)
    assert first is not None
    first.state.move_to(2)
    first.state.move_to(7, selecting=True)
    first.set_zoom_percent(120)
    expected_editor_state = first.state.export_state()

    window.panes.first_leaf.controls.split_right_button.click()
    app.processEvents()

    clone = window.current_view
    assert clone is not None
    assert clone is not first
    assert clone.document is first.document
    assert clone.state.export_state() == expected_editor_state
    assert service.documents.count == 1
    assert window.panes.leaf_count == 2

    second = window.open_path(second_path)
    assert second is not None
    left_id = window.panes.first_leaf.pane_id
    count_before = len(window.views)

    assigned = window.assign_document_to_pane(
        service.documents.entry_for_view(second.view_id).document_id,
        left_id,
    )
    selected_again = window.assign_document_to_pane(
        service.documents.entry_for_view(second.view_id).document_id,
        left_id,
    )

    assert assigned is selected_again
    assert assigned.document is second.document
    assert len(window.views) == count_before + 1
    assert window.panes.first_leaf.selected_view_id == assigned.view_id
    assert service.documents.count == 2
    assert len(service.documents.entry_for_view(second.view_id).view_ids) == 2
    service.request_quit(lambda _entry: None)
    app.processEvents()


def test_go_to_line_moves_to_one_based_line_and_rejects_invalid_target(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "lines.txt"
    source.write_text("zero\none\ntwo\n", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)

    assert window.go_to_line(3) is True
    assert view.state.cursor == view.document.line_start(2)
    assert window.go_to_line(0) is False
    assert window.go_to_line(99) is False
    assert view.state.cursor == view.document.line_start(2)
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_right_click_in_editor_shows_a_context_menu_and_focuses_that_view(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint
    from PySide6.QtGui import QContextMenuEvent
    from PySide6.QtWidgets import QApplication, QMenu

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "context-menu.txt"
    source.write_text("abc\n", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    window.show()
    window.activateWindow()
    app.processEvents()

    captured_menus: list[QMenu] = []
    original_popup = QMenu.popup

    def capture_popup(self, _position):
        captured_menus.append(self)

    QMenu.popup = capture_popup
    try:
        event = QContextMenuEvent(
            QContextMenuEvent.Reason.Mouse, QPoint(5, 5), QPoint(100, 100)
        )
        view.contextMenuEvent(event)
    finally:
        QMenu.popup = original_popup

    assert view.hasFocus()
    assert window.current_view is view
    assert len(captured_menus) == 1
    labels = [
        action.text()
        for action in captured_menus[0].actions()
        if not action.isSeparator()
    ]
    for expected in ("Undo", "Redo", "Cut", "Copy", "Paste", "Select All"):
        assert any(label.startswith(expected) for label in labels), labels
    assert any("Go to Line" in label for label in labels)
    assert any(label.startswith("Find") for label in labels)
    window.close_all_documents(force=True)
    window.close()


def test_reload_cancel_preserves_modified_document(tmp_path: Path, monkeypatch):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "reload-cancel.txt"
    source.write_text("disk", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    view.state.move_document_end()
    view.state.insert_text(" local")
    original_document = view.document
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Cancel,
    )

    assert window.reload_current() is False
    assert view.document is original_document
    assert view.document.read(0, view.document.total_chars()) == "disk local"
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_confirmed_reload_reopens_disk_with_fresh_history(tmp_path: Path, monkeypatch):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from uniti.core.durability import NativeDurabilityAdapter
    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "reload.txt"
    replacement = tmp_path / "replacement.txt"
    source.write_text("old", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    view.state.move_document_end()
    view.state.insert_text(" local")
    original_document = view.document
    replacement.write_text("fresh Привет", encoding="utf-8")
    NativeDurabilityAdapter().replace(replacement, source)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: QMessageBox.StandardButton.Discard,
    )

    assert window.reload_current() is True
    assert view.document is not original_document
    assert view.document.read(0, view.document.total_chars()) == "fresh Привет"
    assert view.document.modified is False
    assert view.document.can_undo is False
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_focused_find_field_owns_main_window_undo_redo(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "focus-undo.txt"
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
    assert view.document.read(0, view.document.total_chars()) == "document!"
    window.redo_current()
    assert field.text() == "abc"
    assert view.document.read(0, view.document.total_chars()) == "document!"
    window.close_all_documents(force=True)
    window.close()


def test_focused_find_field_owns_clipboard_and_select_all_commands(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "focus-clipboard.txt"
    source.write_text("document", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    window.show()
    window.show_find()
    field = window._find_replace.find_input
    field.set_text("needle")
    field.setFocus()
    app.processEvents()
    window.select_all()
    window.copy_current()
    assert QGuiApplication.clipboard().text() == "needle"
    window.cut_current()
    assert field.text() == ""
    window.paste_current()
    assert field.text() == "needle"
    assert view.document.read(0, view.document.total_chars()) == "document"
    window.close_all_documents(force=True)
    window.close()


def test_high_confidence_utf8_open_does_not_show_format_confirmation(
    tmp_path: Path, monkeypatch
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    import uniti.ui.main_window as main_window

    source = tmp_path / "certain.txt"
    source.write_text("Hello, Привет\r\n", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    window = main_window.UNITIMainWindow()

    class UnexpectedDialog:
        def __init__(self, *args, **kwargs):
            raise AssertionError("high-confidence UTF-8 must not show the modal")

    monkeypatch.setattr(main_window, "OpenFormatDialog", UnexpectedDialog)
    view = window.open_path(source)

    assert view is not None
    assert view.document.source_profile.key == "utf-8"
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_low_confidence_open_requires_exact_profile_confirmation(
    tmp_path: Path, monkeypatch
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    from uniti.core.text_format import encoding_profile
    import uniti.ui.main_window as main_window

    source = tmp_path / "legacy.txt"
    source.write_bytes(b"Price \x96 10")
    app = QApplication.instance() or QApplication([])
    window = main_window.UNITIMainWindow()
    seen = {}

    class AcceptedDialog:
        def __init__(self, assessment, eol_report, *, preview_provider, parent=None):
            seen["assessment"] = assessment
            seen["preview"] = preview_provider(encoding_profile("windows-1252"))

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_profile(self):
            return encoding_profile("windows-1252")

    monkeypatch.setattr(main_window, "OpenFormatDialog", AcceptedDialog)
    view = window.open_path(source)

    assert view is not None
    assert seen["assessment"].confidence < 0.75
    assert any("confidence" in reason.lower() for reason in seen["assessment"].reasons)
    assert seen["preview"].text == "Price – 10"
    assert view.document.source_profile.key == "windows-1252"
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_cancelled_serious_open_creates_no_tab(tmp_path: Path, monkeypatch):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    import uniti.ui.main_window as main_window

    source = tmp_path / "uncertain.txt"
    source.write_bytes(b"A\xffZ")
    app = QApplication.instance() or QApplication([])
    window = main_window.UNITIMainWindow()

    class CancelledDialog:
        def __init__(self, *args, **kwargs):
            pass

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(main_window, "OpenFormatDialog", CancelledDialog)
    before = window.panes.active_leaf.tabs.count()

    assert window.open_path(source) is None
    assert window.panes.active_leaf.tabs.count() == before
    window.close()
    app.processEvents()


def test_explicit_profile_still_reports_malformed_preview(tmp_path: Path, monkeypatch):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    from uniti.core.text_format import encoding_profile
    import uniti.ui.main_window as main_window

    source = tmp_path / "malformed-utf8.txt"
    source.write_bytes(b"A\xffZ")
    app = QApplication.instance() or QApplication([])
    window = main_window.UNITIMainWindow()
    seen = {}

    class AcceptedDialog:
        def __init__(self, assessment, eol_report, *, preview_provider, parent=None):
            seen["assessment"] = assessment

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_profile(self):
            return encoding_profile("utf-8")

    monkeypatch.setattr(main_window, "OpenFormatDialog", AcceptedDialog)
    view = window.open_path(source, profile=encoding_profile("utf-8"))

    assert view is not None
    assert seen["assessment"].malformed_preview
    assert view.document.source_profile.key == "utf-8"
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_mixed_eol_report_is_modeless_and_converts_the_live_document(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.core.text_format import EOLPolicy
    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "mixed.txt"
    original = b"one\r\ntwo\nthree\r"
    source.write_bytes(original)
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    assert view is not None
    dialog = window._eol_dialogs[id(view)]

    assert dialog.isModal() is False
    assert "LF 1" in dialog.summary_label.text()
    assert "CRLF 1" in dialog.summary_label.text()
    assert "CR 1" in dialog.summary_label.text()
    dialog.select_policy(EOLPolicy.PRESERVE)
    assert view.document.modified is False

    dialog.select_policy(EOLPolicy.CRLF)
    assert view.document.output_format.eol is EOLPolicy.CRLF
    assert view.document.modified is True
    # BF-023: the dialog's chosen policy converts the live document
    # immediately too, exactly like the Editor View menu's EOL commands —
    # only the on-disk bytes remain untouched until an actual save.
    assert view.document.read(0, view.document.total_chars()) == (
        "one\r\ntwo\r\nthree\r\n"
    )
    assert source.read_bytes() == original
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_set_tab_width_persists_and_propagates_to_open_views(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "tab-width.txt"
    source.write_text("a\tb", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    assert view is not None
    assert view._tab_width_chars == 4
    assert window._tab_width_actions[4].isChecked()

    window.set_tab_width(8)

    assert window._settings.editor_tab_width == 8
    assert view._tab_width_chars == 8
    assert window._tab_width_actions[8].isChecked()

    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_convert_tabs_to_spaces_mutates_the_live_document(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "convert-tabs.txt"
    source.write_text("a\tb", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    assert view is not None
    window.set_tab_width(2)

    window.convert_tabs_to_spaces()

    assert view.document.read(0, view.document.total_chars()) == "a  b"
    assert view.document.modified is True
    view.document.undo()
    assert view.document.read(0, view.document.total_chars()) == "a\tb"

    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_set_output_eol_converts_the_live_document_immediately(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "convert-eol.txt"
    original = b"one\ntwo\nthree\n"
    source.write_bytes(original)
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    assert view is not None
    assert view.document.modified is False

    window.set_output_eol("CRLF")

    # BF-023: the visible characters change immediately, not only on save.
    assert view.document.read(0, view.document.total_chars()) == (
        "one\r\ntwo\r\nthree\r\n"
    )
    assert view.document.modified is True
    assert source.read_bytes() == original

    # A newly typed line must use the just-chosen EOL, not the stale
    # originally-detected one.
    assert view.document.insertion_eol == "CRLF"

    view.document.undo()
    assert view.document.read(0, view.document.total_chars()) == "one\ntwo\nthree\n"

    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_reinterpret_uses_an_exact_profile_and_preserves_the_view(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.core.text_format import encoding_profile
    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "reinterpret.txt"
    source.write_bytes(b"plain ASCII\n")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(source)
    assert view is not None
    old_document = view.document

    window.reinterpret_current(encoding_profile("windows-1252"))

    assert window.current_view is view
    assert view.document is not old_document
    assert view.document.source_profile.key == "windows-1252"
    assert view.document.modified is False
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def test_saved_dark_theme_applies_to_the_application_and_child_windows(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    original_palette = QPalette(app.palette())
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(theme_mode="Dark"))
    window = None
    try:
        window = UNITIMainWindow(settings_store=store)
        app.processEvents()

        assert app.palette().color(QPalette.ColorRole.Window).name() == "#161b22"
        assert app.palette().color(QPalette.ColorRole.Base).name() == "#0d1117"
        assert window.palette().color(QPalette.ColorRole.Window).name() == "#161b22"
        assert (
            window._find_replace.palette().color(QPalette.ColorRole.Window).name()
            == "#161b22"
        )
        assert window._theme_actions["Dark"].isChecked()
    finally:
        if window is not None:
            window.close()
        app.setPalette(original_palette)
        app.processEvents()


def test_theme_menu_switches_persists_and_restores_system_palette(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    original_palette = QPalette(app.palette())
    original_window = original_palette.color(QPalette.ColorRole.Window)
    original_base = original_palette.color(QPalette.ColorRole.Base)
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(theme_mode="Dark"))
    window = None
    try:
        window = UNITIMainWindow(settings_store=store)
        window._find_replace.find_input.set_text("needle")

        window._theme_actions["Light"].trigger()
        app.processEvents()
        assert app.palette().color(QPalette.ColorRole.Window).name() == "#f4f7fb"
        assert app.palette().color(QPalette.ColorRole.Base).name() == "#ffffff"
        assert (
            window._find_replace.find_clear_button.palette()
            .color(QPalette.ColorRole.ButtonText)
            .name()
            == "#111827"
        )
        assert store.load().theme_mode == "Light"

        window._theme_actions["Dark"].trigger()
        app.processEvents()
        assert app.palette().color(QPalette.ColorRole.Highlight).name() == "#58a6ff"
        assert store.load().theme_mode == "Dark"

        window._theme_actions["System"].trigger()
        app.processEvents()
        assert app.palette().color(QPalette.ColorRole.Window) == original_window
        assert app.palette().color(QPalette.ColorRole.Base) == original_base
        assert store.load().theme_mode == "System"

        window.set_theme("Dark")
        assert window._theme_actions["Dark"].isChecked()
        window.set_theme("System")
    finally:
        if window is not None:
            window.close()
        app.setPalette(original_palette)
        app.processEvents()


def test_theme_contrast_toggle_is_independent_and_persisted(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.theme import active_theme

    app = QApplication.instance() or QApplication([])
    original_palette = QPalette(app.palette())
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(theme_mode="Dark", theme_contrast="High Contrast"))
    window = None
    try:
        window = UNITIMainWindow(settings_store=store)
        assert window._theme_actions["Dark"].isChecked() is True
        assert window._high_contrast_action.isChecked() is True
        assert active_theme(app).mode == "Dark"
        assert active_theme(app).contrast == "High Contrast"

        window._high_contrast_action.trigger()
        assert store.load().theme_mode == "Dark"
        assert store.load().theme_contrast == "Standard"

        window.set_theme("Light")
        window.set_theme_contrast("High Contrast")
        assert store.load().theme_mode == "Light"
        assert store.load().theme_contrast == "High Contrast"
        assert active_theme(app).mode == "Light"
        assert active_theme(app).contrast == "High Contrast"
    finally:
        if window is not None:
            window.close()
        app.setPalette(original_palette)
        app.processEvents()


def test_whitespace_menu_persists_and_propagates_with_theme_tokens(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.theme import active_theme, apply_theme
    from uniti.ui.whitespace import WhitespaceMode

    path = tmp_path / "menu-whitespace.txt"
    path.write_text("a b", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(whitespace_mode="all"))
    app = QApplication.instance() or QApplication([])
    original_palette = QPalette(app.palette())
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        assert view is not None
        assert view.whitespace_mode is WhitespaceMode.ALL
        assert window._whitespace_actions[WhitespaceMode.ALL].isChecked() is True

        window._whitespace_actions[WhitespaceMode.EOL].trigger()
        assert view.whitespace_mode is WhitespaceMode.EOL
        assert store.load().whitespace_mode == "eol"

        window.set_theme("Dark")
        window.set_theme_contrast("High Contrast")
        assert view.theme_tokens == active_theme(app).editor
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.setPalette(original_palette)
        apply_theme(app, "System")
        app.processEvents()


def test_text_direction_menu_is_per_view_not_a_global_setting(tmp_path: Path):
    """Text Direction is per-view state, like Whitespace/Tab Width/Editor
    Theme/Syntax Profile (see the sibling tests below): switching the
    choice on one tab must not affect another tab, and switching tabs
    must resync the radio group to the newly active view's own choice."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    first_path = tmp_path / "direction-a.txt"
    second_path = tmp_path / "direction-b.txt"
    first_path.write_text("alpha", encoding="utf-8")
    second_path.write_text("beta", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        first_view = window.open_path(first_path)
        second_view = window.open_path(second_path)
        assert first_view is not None and second_view is not None
        assert window._text_direction_actions["auto"].isChecked() is True

        window._text_direction_actions["rtl"].trigger()
        assert second_view.text_direction_override == "rtl"
        assert first_view.text_direction_override == "auto"

        window.panes.activate_view(first_view.view_id)
        assert window._text_direction_actions["auto"].isChecked() is True

        window.panes.activate_view(second_view.view_id)
        assert window._text_direction_actions["rtl"].isChecked() is True
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_whitespace_tab_width_and_syntax_menus_are_per_view_not_a_global_setting(
    tmp_path: Path,
):
    """Whitespace, Tab Width, and Syntax Profile are per-view state too
    (view settings per pane) — changing one open document's setting must
    not affect another open document's, and switching tabs must resync
    every one of these radio groups to the newly active view's own
    choice. Editor Theme has its own dedicated test below since it needs
    a theme profile store."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.whitespace import WhitespaceMode

    first_path = tmp_path / "per-view-a.txt"
    second_path = tmp_path / "per-view-b.md"
    first_path.write_text("alpha", encoding="utf-8")
    second_path.write_text("# beta", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        first_view = window.open_path(first_path)
        second_view = window.open_path(second_path)
        assert first_view is not None and second_view is not None

        window._whitespace_actions[WhitespaceMode.ALL].trigger()
        window._tab_width_actions[8].trigger()
        window._syntax_choice_actions["sfm"].trigger()
        assert second_view.whitespace_mode is WhitespaceMode.ALL
        assert second_view.tab_width == 8
        assert second_view.syntax_choice_key == "sfm"
        assert first_view.whitespace_mode is WhitespaceMode.OFF
        assert first_view.tab_width == 4
        assert first_view.syntax_choice_key is None

        window.panes.activate_view(first_view.view_id)
        assert window._whitespace_actions[WhitespaceMode.OFF].isChecked() is True
        assert window._tab_width_actions[4].isChecked() is True
        assert window._syntax_choice_actions[None].isChecked() is True

        window.panes.activate_view(second_view.view_id)
        assert window._whitespace_actions[WhitespaceMode.ALL].isChecked() is True
        assert window._tab_width_actions[8].isChecked() is True
        assert window._syntax_choice_actions["sfm"].isChecked() is True

        # Changing the global extension->profile mapping re-resolves a
        # view that never took an explicit override, but leaves the
        # overridden view (second_view, forced to "sfm" above) alone.
        window._refresh_all_syntax_profiles()
        assert second_view.syntax_profile.key == "sfm"
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_editor_theme_menu_is_per_view_and_independent_of_app_chrome_theme(
    tmp_path: Path,
):
    """Editor Theme (View > Editor Theme) is a per-view override of just
    the editor pane's own colors — it must not touch the app-wide chrome
    theme (View > Theme / High Contrast), and switching back to "Follow
    App Theme" must pick up whatever the app theme currently is."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.theme import active_theme

    first_path = tmp_path / "theme-a.txt"
    second_path = tmp_path / "theme-b.txt"
    first_path.write_text("alpha", encoding="utf-8")
    second_path.write_text("beta", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        first_view = window.open_path(first_path)
        second_view = window.open_path(second_path)
        assert first_view is not None and second_view is not None
        assert window._editor_theme_actions[None].isChecked() is True

        window._editor_theme_actions["Dark"].trigger()
        assert second_view.theme_choice_id == "Dark"
        assert first_view.theme_choice_id is None
        # The window's own chrome/app-wide theme is untouched.
        assert window._settings.theme_mode == "System"

        window.panes.activate_view(first_view.view_id)
        assert window._editor_theme_actions[None].isChecked() is True

        window.panes.activate_view(second_view.view_id)
        assert window._editor_theme_actions["Dark"].isChecked() is True

        window._editor_theme_actions[None].trigger()
        assert second_view.theme_choice_id is None
        assert second_view.theme_tokens == active_theme(app).editor
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_compare_menu_opens_a_compare_pane_for_two_picked_documents(
    tmp_path: Path, monkeypatch
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    import uniti.ui.main_window as main_window

    class _StubPicker:
        def __init__(self, candidates, *, parent=None):
            self._candidates = candidates

        def exec(self):
            return QDialog.DialogCode.Accepted

        def left_choice(self):
            return self._candidates[0]

        def right_choice(self):
            return self._candidates[1]

    monkeypatch.setattr(main_window, "CompareDocumentPickerDialog", _StubPicker)

    first_path = tmp_path / "compare-a.txt"
    second_path = tmp_path / "compare-b.txt"
    first_path.write_text("alpha\nbeta", encoding="utf-8")
    second_path.write_text("alpha\nBETA", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = main_window.UNITIMainWindow()
    try:
        first_view = window.open_path(first_path)
        second_view = window.open_path(second_path)
        assert first_view is not None and second_view is not None

        window.show_compare()
        assert window._compare_pane is not None
        # Compare is its own standalone top-level window (2026-09-18
        # follow-up), not embedded in the central splitter beside the
        # pane tree.
        assert window._central_splitter.indexOf(window._compare_pane) == -1
        assert window._compare_pane.isWindow()
        assert len(window._compare_pane._changed) == 1

        window._compare_pane.close_compare()
        app.processEvents()
        assert window._compare_pane is None
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_compare_menu_requires_two_open_documents(tmp_path: Path, monkeypatch):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from uniti.ui.main_window import UNITIMainWindow

    shown = {}
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda self, title, text, *a, **k: shown.update(title=title, text=text),
    )

    path = tmp_path / "compare-only.txt"
    path.write_text("alpha", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        assert view is not None

        window.show_compare()
        assert window._compare_pane is None
        assert shown.get("title") == "Compare"
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_compare_menu_rejects_comparing_a_document_with_itself(
    tmp_path: Path, monkeypatch
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog, QMessageBox

    import uniti.ui.main_window as main_window

    class _SameChoicePicker:
        def __init__(self, candidates, *, parent=None):
            self._candidates = candidates

        def exec(self):
            return QDialog.DialogCode.Accepted

        def left_choice(self):
            return self._candidates[0]

        def right_choice(self):
            return self._candidates[0]

    monkeypatch.setattr(main_window, "CompareDocumentPickerDialog", _SameChoicePicker)
    shown = {}
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda self, title, text, *a, **k: shown.update(title=title, text=text),
    )

    first_path = tmp_path / "compare-a.txt"
    second_path = tmp_path / "compare-b.txt"
    first_path.write_text("alpha", encoding="utf-8")
    second_path.write_text("beta", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = main_window.UNITIMainWindow()
    try:
        assert window.open_path(first_path) is not None
        assert window.open_path(second_path) is not None

        window.show_compare()
        assert window._compare_pane is None
        assert shown.get("title") == "Compare"
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_compare_hotkey_toggles_open_and_closed(tmp_path: Path, monkeypatch):
    """2026-09-20 request: add a hotkey toggle for Compare, matching Find
    and Character Inspector -- pressing it again while Compare is open
    closes it instead of reopening the document picker."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    import uniti.ui.main_window as main_window

    class _StubPicker:
        def __init__(self, candidates, *, parent=None):
            self._candidates = candidates

        def exec(self):
            return QDialog.DialogCode.Accepted

        def left_choice(self):
            return self._candidates[0]

        def right_choice(self):
            return self._candidates[1]

    monkeypatch.setattr(main_window, "CompareDocumentPickerDialog", _StubPicker)

    first_path = tmp_path / "toggle-a.txt"
    second_path = tmp_path / "toggle-b.txt"
    first_path.write_text("alpha", encoding="utf-8")
    second_path.write_text("beta", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = main_window.UNITIMainWindow()
    try:
        assert window.open_path(first_path) is not None
        assert window.open_path(second_path) is not None

        assert window._compare_pane is None
        window.show_compare()
        app.processEvents()
        assert window._compare_pane is not None

        window.show_compare()
        app.processEvents()
        assert window._compare_pane is None
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_compare_asks_for_files_when_nothing_is_open(tmp_path: Path, monkeypatch):
    """2026-09-20 request: "ask for files if nothing OPEN" -- with zero
    documents open, the usual "open at least two documents" message has
    nothing useful to say; prompt for exactly two files directly, open
    them, and compare those two without a redundant picker step."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QFileDialog

    from uniti.ui.main_window import UNITIMainWindow

    first_path = tmp_path / "ask-a.txt"
    second_path = tmp_path / "ask-b.txt"
    first_path.write_text("alpha", encoding="utf-8")
    second_path.write_text("beta", encoding="utf-8")
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileNames",
        lambda *a, **k: ([str(first_path), str(second_path)], ""),
    )

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        assert not window.views
        window.show_compare()
        app.processEvents()
        assert window._compare_pane is not None
        opened_names = {view.document.path.name for view in window.views}
        assert opened_names == {"ask-a.txt", "ask-b.txt"}
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_compare_remembers_size_and_zoom_across_reopens(tmp_path: Path, monkeypatch):
    """2026-09-20 request: preserve Compare's geometry (and zoom) across
    reopens, the same generic `_toggle_window` mechanism Character
    Inspector uses."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    import uniti.ui.main_window as main_window

    class _StubPicker:
        def __init__(self, candidates, *, parent=None):
            self._candidates = candidates

        def exec(self):
            return QDialog.DialogCode.Accepted

        def left_choice(self):
            return self._candidates[0]

        def right_choice(self):
            return self._candidates[1]

    monkeypatch.setattr(main_window, "CompareDocumentPickerDialog", _StubPicker)

    first_path = tmp_path / "remember-a.txt"
    second_path = tmp_path / "remember-b.txt"
    first_path.write_text("alpha", encoding="utf-8")
    second_path.write_text("beta", encoding="utf-8")
    from uniti.app.settings import SettingsStore

    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = main_window.UNITIMainWindow(settings_store=store)
    try:
        assert window.open_path(first_path) is not None
        assert window.open_path(second_path) is not None

        window.show_compare()
        app.processEvents()
        pane = window._compare_pane
        pane.setGeometry(20, 30, 950, 620)
        pane.set_zoom_percent(130)

        window.show_compare()  # toggle closed -- saves state
        app.processEvents()
        assert window._settings.toggle_window_geometry["compare"] == (
            20,
            30,
            950,
            620,
        )
        assert window._settings.toggle_window_zoom_percent["compare"] == 130
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_zoom_shortcut_reaches_the_panel_while_find_input_has_focus(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "zoom-shortcut.txt"
    source.write_text("abc", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        window.open_path(source)
        window.show_find()
        field = window._find_replace.find_input
        field.setFocus()
        app.processEvents()
        before = window._find_replace.zoom_percent

        QTest.keySequence(field, QKeySequence(QKeySequence.StandardKey.ZoomIn))
        app.processEvents()

        assert window._find_replace.zoom_percent > before
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_font_weight_hotkeys_reach_the_focused_editor(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QKeySequence
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "weight-shortcut.txt"
    source.write_text("abc", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        view = window.open_path(source)
        view.setFocus()
        window.show()
        app.processEvents()
        assert view.font_weight == 400

        QTest.keySequence(view, QKeySequence("Ctrl+Shift+="))
        app.processEvents()
        assert view.font_weight == 500

        QTest.keySequence(view, QKeySequence("Ctrl+Shift+-"))
        app.processEvents()
        assert view.font_weight == 400

        QTest.keySequence(view, QKeySequence("Ctrl+Shift+="))
        QTest.keySequence(view, QKeySequence("Ctrl+Shift+0"))
        app.processEvents()
        assert view.font_weight == 400
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_format_document_actions_enable_only_for_recognized_syntax_types(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    json_path = tmp_path / "data.json"
    json_path.write_text('{"a": 1}', encoding="utf-8")
    md_path = tmp_path / "notes.md"
    md_path.write_text("# hi\n", encoding="utf-8")
    txt_path = tmp_path / "plain.txt"
    txt_path.write_text("hello", encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        json_view = window.open_path(json_path)
        assert window._format_document_action.isEnabled() is True
        assert window._minify_document_action.isEnabled() is True

        md_view = window.open_path(md_path)
        assert window._format_document_action.isEnabled() is True
        assert window._minify_document_action.isEnabled() is False

        window.open_path(txt_path)
        assert window._format_document_action.isEnabled() is False
        assert window._minify_document_action.isEnabled() is False

        window._select_view(json_view)
        assert window._format_document_action.isEnabled() is True
        window._select_view(md_view)
        assert window._minify_document_action.isEnabled() is False
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_format_document_applies_as_one_undo_step(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "data.json"
    original = '{"b": 1, "a": [3, 2, 1]}'
    path.write_text(original, encoding="utf-8")

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        window.format_current_document()
        formatted = view.document.read(0, view.document.total_chars())
        assert formatted != original
        assert formatted.startswith('{\n  "b": 1,')

        window.minify_current_document()
        minified = view.document.read(0, view.document.total_chars())
        assert minified == '{"b":1,"a":[3,2,1]}'

        view.document.undo()
        assert view.document.read(0, view.document.total_chars()) == formatted
        view.document.undo()
        assert view.document.read(0, view.document.total_chars()) == original
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_format_document_rejects_invalid_json_and_leaves_document_unchanged(
    tmp_path: Path, monkeypatch
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "bad.json"
    path.write_text("{invalid", encoding="utf-8")

    shown = {}
    monkeypatch.setattr(
        QMessageBox,
        "critical",
        lambda self, title, text, *a, **k: shown.update(title=title, text=text),
    )

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        window.format_current_document()

        assert shown["title"] == "Format Failed"
        assert "line 1" in shown["text"]
        assert view.document.read(0, view.document.total_chars()) == "{invalid"
        assert view.document.modified is False
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_format_document_declines_documents_over_the_size_cap(
    tmp_path: Path, monkeypatch
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    import uniti.ui.main_window as main_window_module
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "data.json"
    path.write_text('{"a": 1}', encoding="utf-8")

    monkeypatch.setattr(main_window_module, "MAX_REFORMAT_CHARS", 4)
    shown = {}
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda self, title, text, *a, **k: shown.update(title=title, text=text),
    )

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        window.format_current_document()

        assert shown["title"] == "Document Too Large"
        assert view.document.read(0, view.document.total_chars()) == '{"a": 1}'
        assert view.document.modified is False
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_status_bar_shows_and_clears_match_position_for_its_own_view(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "match-position.txt"
    path.write_text("alpha", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        assert view is not None
        assert window._status.match_label.text() == ""

        window._find_replace.matchPositionChanged.emit(view.view_id, "Match 1 of 2")
        assert window._status.match_label.text() == "Match 1 of 2"

        window._find_replace.matchPositionChanged.emit("unowned-view-id", "Match 9 of 9")
        assert window._status.match_label.text() == "Match 1 of 2"

        window._find_replace.matchPositionChanged.emit(view.view_id, None)
        assert window._status.match_label.text() == ""
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_system_theme_refreshes_when_the_platform_palette_changes():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication

    from uniti.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    original_palette = QPalette(app.palette())
    try:
        apply_theme(app, "System")
        refreshed_palette = QPalette(app.palette())
        refreshed_palette.setColor(QPalette.ColorRole.Window, QColor("#345678"))
        refreshed_palette.setColor(QPalette.ColorRole.Base, QColor("#234567"))
        app.setPalette(refreshed_palette)
        app.processEvents()

        apply_theme(app, "Dark")
        apply_theme(app, "System")

        assert app.palette().color(QPalette.ColorRole.Window).name() == "#345678"
        assert app.palette().color(QPalette.ColorRole.Base).name() == "#234567"
    finally:
        app.setPalette(original_palette)
        app.processEvents()


def test_find_replace_report_zoom_persists_independently_of_field_zoom(
    tmp_path: Path,
):
    """BF-092: the Match Report's own font size is tracked and persisted
    separately from the find/replace fields' zoom, mirroring how
    find_replace_attached_height already persists on change (not just at
    construction, unlike find_replace_zoom_percent's write-once seed)."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        window._find_replace.set_zoom_percent(140)
        window._find_replace.set_report_zoom_percent(160)
        app.processEvents()

        assert window._settings.find_replace_report_zoom_percent == 160
        # The fields' own zoom is not saved on change (a pre-existing,
        # separate gap this doesn't touch) -- only report zoom is.
        assert window._settings.find_replace_zoom_percent == 100

        second_window = UNITIMainWindow(settings_store=store)
        try:
            assert second_window._find_replace.report_zoom_percent == 160
        finally:
            second_window.close_all_documents(force=True)
            second_window.close()
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_recent_files_menu_lists_opened_files_most_recent_first(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    first_path = tmp_path / "first.txt"
    second_path = tmp_path / "second.txt"
    first_path.write_text("first", encoding="utf-8")
    second_path.write_text("second", encoding="utf-8")

    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        window.open_path(first_path)
        window.open_path(second_path)
        app.processEvents()

        assert store.recent_files.load() == (str(second_path), str(first_path))

        window._populate_recent_files_menu()
        labels = [action.text() for action in window._recent_files_menu.actions()]
        assert labels[0] == second_path.name
        assert labels[1] == first_path.name
        assert "Clear Recent Files" in labels

        window._clear_recent_files()
        assert store.recent_files.load() == ()
        window._populate_recent_files_menu()
        empty_labels = [action.text() for action in window._recent_files_menu.actions()]
        assert empty_labels == ["(No Recent Files)"]
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_recent_files_menu_disambiguates_same_named_files_by_parent_directory(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    first_dir = tmp_path / "one"
    second_dir = tmp_path / "two"
    first_dir.mkdir()
    second_dir.mkdir()
    first_path = first_dir / "notes.txt"
    second_path = second_dir / "notes.txt"
    first_path.write_text("first", encoding="utf-8")
    second_path.write_text("second", encoding="utf-8")

    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        window.open_path(first_path)
        window.open_path(second_path)
        app.processEvents()

        window._populate_recent_files_menu()
        labels = [action.text() for action in window._recent_files_menu.actions()]
        assert labels[0] == f"notes.txt  ({second_dir})"
        assert labels[1] == f"notes.txt  ({first_dir})"
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_unicode_hex_toggle_command_converts_hex_run_in_current_view(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "hex.txt"
    path.write_text("type 0048", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        assert view is not None
        view.state.move_to(view.document.total_chars())

        window.toggle_unicode_hex()

        assert view.document.read(0, view.document.total_chars()) == "type H"
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_unicode_hex_toggle_flashes_a_highlight_over_the_converted_text(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "hex.txt"
    path.write_text("type 0048", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        assert view is not None
        view.state.move_to(view.document.total_chars())

        window.toggle_unicode_hex()

        spans = view._line_span_highlights.get(0)
        assert spans is not None
        start_column, end_column, color = spans[0]
        assert (start_column, end_column) == (5, 6)
        assert color.alpha() == 120
        assert view._unicode_hex_flash_timer is not None
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_unicode_hex_toggle_reverses_a_bare_trailing_letter_instead_of_a_short_hex_run(
    tmp_path: Path,
):
    """BF-089: a bare trailing "A" used to forward-convert as hex 0x0A (a
    newline) rather than reversing to its own U+0041 -- a hex run shorter
    than 4 digits is no longer recognized at all, so this now falls
    through to the reverse (char -> U+XXXX) direction, which is what a
    user typing one letter and invoking the toggle almost always means."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "hex.txt"
    path.write_text("A", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        assert view is not None
        view.state.move_to(view.document.total_chars())

        window.toggle_unicode_hex()

        assert view.document.read(0, view.document.total_chars()) == "U+0041"
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_extension_profile_editor_updates_settings_and_refreshes_open_views(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QDialog

    from uniti.app.settings import SettingsStore
    from uniti.core.syntax_profiles import JSON, PLAIN_TEXT
    from uniti.ui.main_window import UNITIMainWindow

    usj_path = tmp_path / "book.usj"
    usj_path.write_text("{}", encoding="utf-8")

    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(usj_path)
        assert view.syntax_profile is PLAIN_TEXT

        with patch(
            "uniti.ui.extension_profile_editor.ExtensionProfileEditor.exec",
            return_value=QDialog.DialogCode.Accepted,
        ), patch(
            "uniti.ui.extension_profile_editor.ExtensionProfileEditor.overrides",
            return_value={"usj": "json"},
        ):
            window.show_extension_profile_editor()

        assert view.syntax_profile is JSON
        assert store.load().syntax_extension_overrides == {"usj": "json"}
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_markdown_preview_toggle_opens_split_and_renders_current_document(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    md_path = tmp_path / "doc.md"
    md_path.write_text("# Hello", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        window.open_path(md_path)
        app.processEvents()

        assert window._markdown_preview_action.isEnabled() is True
        assert window._markdown_preview_action.isChecked() is False

        window.toggle_markdown_preview()
        app.processEvents()

        assert window._markdown_preview is not None
        assert window._markdown_preview_action.isChecked() is True
        assert "Hello" in window._markdown_preview._browser.toPlainText()

        window.toggle_markdown_preview()

        assert window._markdown_preview is None
        assert window._markdown_preview_action.isChecked() is False
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_markdown_preview_disabled_for_non_markdown_document(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "doc.txt"
    path.write_text("hello", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        window.open_path(path)
        app.processEvents()

        assert window._markdown_preview_action.isEnabled() is False
        window.toggle_markdown_preview()
        assert window._markdown_preview is None
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_markdown_preview_updates_on_edit_after_debounce(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    md_path = tmp_path / "doc.md"
    md_path.write_text("# Hello", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(md_path)
        window.toggle_markdown_preview()
        app.processEvents()

        view.state.move_to(view.document.total_chars())
        view.state.insert_text(" World")
        view._state_changed()
        assert window._markdown_preview_timer.isActive()

        window._markdown_preview_timer.timeout.emit()
        app.processEvents()

        assert "World" in window._markdown_preview._browser.toPlainText()
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_markdown_preview_retargets_on_tab_switch_and_closes_when_target_closes(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    first_path = tmp_path / "first.md"
    second_path = tmp_path / "second.md"
    first_path.write_text("# First", encoding="utf-8")
    second_path.write_text("# Second", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        first_view = window.open_path(first_path)
        window.toggle_markdown_preview()
        app.processEvents()
        assert "First" in window._markdown_preview._browser.toPlainText()

        second_view = window.open_path(second_path)
        app.processEvents()
        assert window._markdown_preview_target_view is second_view
        assert "Second" in window._markdown_preview._browser.toPlainText()

        window._select_view(second_view)
        app.processEvents()
        window.close_current()
        app.processEvents()

        assert window._markdown_preview is None
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_character_inspector_shows_selection_table_for_multi_character_selection(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from unittest.mock import patch

    from PySide6.QtWidgets import QApplication, QDialog

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "doc.txt"
    path.write_text("Hello", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        view.state.move_to(0)
        view.state.move_to(5, selecting=True)

        captured = {}

        class _RecordingDialog(QDialog):
            def __init__(
                self,
                text,
                *,
                output_encoding,
                invalid_bytes=None,
                initial_zoom_percent=100,
                initial_geometry=None,
                initial_splitter_sizes=None,
                on_refresh=None,
                parent=None,
            ):
                super().__init__(parent)
                captured["text"] = text

            def exec(self):
                return QDialog.DialogCode.Accepted

        with patch("uniti.ui.main_window.CharacterInspectorDialog", _RecordingDialog):
            window.show_character_inspector()

        assert captured["text"] == "Hello"
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_character_inspector_hotkey_toggles_open_and_closed(tmp_path: Path):
    """2026-09-20 request: the hotkey should toggle like Find does --
    pressing it again while the dialog is open closes it instead of
    opening a second one. Needs the dialog to be non-modal (`show()`, not
    `exec()`, which the earlier BF-073 implementation used) so a second
    press can even reach `show_character_inspector` at all."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "doc.txt"
    path.write_text("Hello", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        view.state.move_to(0)

        assert window._character_inspector_dialog is None
        window.show_character_inspector()
        app.processEvents()
        first_dialog = window._character_inspector_dialog
        assert first_dialog is not None
        assert first_dialog.isVisible()

        window.show_character_inspector()
        app.processEvents()
        assert window._character_inspector_dialog is None
        # `_on_toggle_window_closed` schedules `deleteLater()`, and
        # `processEvents()` above may already have processed that
        # deferred delete -- don't touch `first_dialog` further.
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_character_inspector_refresh_reflects_a_newer_selection(tmp_path: Path):
    """BF-076: the dialog stays open across selection changes (per its
    toggle-window/non-modal behavior), and previously had no way to pick
    up a newer selection short of closing and reopening. Refresh must
    re-read the current view's selection and repaint in place."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.character_inspector import CharacterListModel
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "doc.txt"
    path.write_text("Hello World", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        view.state.move_to(0)

        window.show_character_inspector()
        app.processEvents()
        dialog = window._character_inspector_dialog
        assert dialog.windowTitle() == "UNITI — Character Inspector"

        view.state.move_to(0)
        view.state.move_to(5, selecting=True)
        window._refresh_character_inspector()
        app.processEvents()

        # Same dialog instance, not a new one -- refresh rebuilds in
        # place rather than reopening.
        assert window._character_inspector_dialog is dialog
        assert dialog.windowTitle() == "UNITI — Inspect Selection"
        assert isinstance(dialog._character_model, CharacterListModel)
        assert dialog._character_model.rowCount() == 5
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_character_inspector_remembers_size_and_zoom_across_reopens(tmp_path: Path):
    """2026-09-20 request: remember the previous window dimensions and
    font zoom size on reopen -- resizing/zooming, closing, and reopening
    (even a fresh window sharing the same settings store, as a real
    relaunch would) must restore both."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "doc.txt"
    path.write_text("Hello", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        view.state.move_to(0)

        window.show_character_inspector()
        app.processEvents()
        dialog = window._character_inspector_dialog
        dialog.setGeometry(50, 60, 500, 550)
        dialog.zoom_in()
        dialog.zoom_in()
        expected_zoom = dialog.zoom_percent

        window.show_character_inspector()  # toggle closed -- saves state
        app.processEvents()
        assert (
            window._settings.toggle_window_zoom_percent["character_inspector"]
            == expected_zoom
        )
        assert window._settings.toggle_window_geometry["character_inspector"] == (
            50,
            60,
            500,
            550,
        )

        # A fresh window sharing the same settings store, as a real
        # relaunch would produce, must load the persisted values too.
        second_window = UNITIMainWindow(settings_store=store)
        try:
            second_view = second_window.open_path(path)
            second_view.state.move_to(0)
            second_window.show_character_inspector()
            app.processEvents()
            reopened = second_window._character_inspector_dialog
            assert reopened.zoom_percent == expected_zoom
            geometry = reopened.geometry()
            assert (geometry.x(), geometry.y()) == (50, 60)
            assert (geometry.width(), geometry.height()) == (500, 550)
        finally:
            second_window.close_all_documents(force=True)
            second_window.close()
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_character_inspector_selection_view_remembers_splitter_sizes_across_reopens(
    tmp_path: Path,
):
    """BF-087: the list/detail splitter's position persists across reopens
    the same generic way geometry/zoom already do (`toggle_window_splitter_sizes`,
    mirroring `toggle_window_geometry`/`toggle_window_zoom_percent` above).
    Single-character mode has no splitter at all -- `splitter_sizes` must
    stay `None` there and never write an entry."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "doc.txt"
    path.write_text("Hello, world!", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        view.state.move_to(0)
        view.state.move_to(5, selecting=True)

        window.show_character_inspector()
        app.processEvents()
        dialog = window._character_inspector_dialog
        assert dialog.splitter_sizes is not None
        dialog._selection_splitter.setSizes([222, 333])
        # `setSizes` alone doesn't fire `splitterMoved` -- drive the
        # tracked value the same way a real user drag would.
        dialog._on_selection_splitter_moved(0, 1)
        expected_sizes = dialog.splitter_sizes
        assert expected_sizes is not None

        window.show_character_inspector()  # toggle closed -- saves state
        app.processEvents()
        assert (
            window._settings.toggle_window_splitter_sizes["character_inspector"]
            == expected_sizes
        )

        second_window = UNITIMainWindow(settings_store=store)
        try:
            second_view = second_window.open_path(path)
            second_view.state.move_to(0)
            second_view.state.move_to(5, selecting=True)
            second_window.show_character_inspector()
            app.processEvents()
            reopened = second_window._character_inspector_dialog
            assert reopened.splitter_sizes == expected_sizes
        finally:
            second_window.close_all_documents(force=True)
            second_window.close()
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_character_inspector_single_character_mode_has_no_splitter_sizes(
    tmp_path: Path,
):
    """BF-087: a single-character dialog never builds a splitter, so its
    `splitter_sizes` must stay `None` and closing it must not write a
    stale/irrelevant entry."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "doc.txt"
    path.write_text("Hello", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        view = window.open_path(path)
        view.state.move_to(0)

        window.show_character_inspector()
        app.processEvents()
        dialog = window._character_inspector_dialog
        assert dialog.splitter_sizes is None

        window.show_character_inspector()  # toggle closed -- saves state
        app.processEvents()
        assert "character_inspector" not in window._settings.toggle_window_splitter_sizes
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_close_all_menu_action_closes_every_open_document(tmp_path: Path):
    """BF-084: there was no way to close every open document at once from
    the File menu -- only one-at-a-time Close, even though the underlying
    `close_all_documents()` (used internally for app-quit flows) already
    existed and already prompts per unsaved document, exactly like an
    ordinary Close would. This wires that existing safe method to a new
    File > Close All entry."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    store = SettingsStore(tmp_path / "settings.json")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    try:
        for name in ("a.txt", "b.txt", "c.txt"):
            path = tmp_path / name
            path.write_text("content", encoding="utf-8")
            window.open_path(path)
        assert len(window.view_ids) == 3

        action = window._command_actions["file.close_all"]
        assert action.text() == "Close All"
        action.trigger()
        app.processEvents()

        assert len(window.view_ids) == 0
    finally:
        window.close_all_documents(force=True)
        window.close()
