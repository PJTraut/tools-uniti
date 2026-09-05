import ast
import importlib.util
import os
from pathlib import Path

import pytest


MAIN = Path("src/uniti/ui/main_window.py")
APPLICATION = Path("src/uniti/app/application.py")


def test_main_window_declares_tabs_file_edit_actions_and_status():
    assert MAIN.exists()
    source = MAIN.read_text()
    for required in ("QTabWidget", "Open", "Save", "Save As", "Undo", "Redo", "UNITIStatusBar"):
        assert required in source
    assert "QPlainTextEdit" not in source


def test_application_imports_pyside6_only_inside_runtime_function():
    assert APPLICATION.exists()
    tree = ast.parse(APPLICATION.read_text())
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
    source.write_text("abc\n", encoding="utf-8")
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
    source = MAIN.read_text()
    application = APPLICATION.read_text()
    assert "SettingsStore" in source
    assert "last_directory" in source
    assert "AppPaths.current" in application
    assert "SettingsStore" in application
    assert "paths.recovery_dir" in application


def test_desktop_startup_creates_one_service_owned_window():
    application = APPLICATION.read_text()
    assert "UNITIService(" in application
    assert "service.new_window()" in application
    assert 'context.data["service"] = service' in application


def test_main_window_handles_open_and_external_save_errors_in_ui():
    source = MAIN.read_text()
    assert "ExternalFileChangedError" in source
    assert "File Changed on Disk" in source
    assert "Open Failed" in source
    assert "Save Failed" in source


def test_main_window_does_not_bypass_document_history_for_replace_all():
    source = MAIN.read_text()
    assert "_reload_after_stream_replace" not in source
    assert "streamReplaceCommitted.connect" not in source


def test_main_window_uses_shared_resource_manager_for_workers_and_tab_priority():
    source = MAIN.read_text()
    assert "ResourceManager" in source
    assert "resource_manager" in source
    assert "self._resources.tasks" in source
    assert "set_resource_active" in source


def test_main_window_flushes_and_shuts_down_recovery_manager_on_application_close():
    source = MAIN.read_text()
    assert "self._recovery_manager.shutdown()" in source


def test_main_window_periodically_observes_resource_memory_pressure():
    source = MAIN.read_text()
    assert "_resource_timer" in source
    assert "observe_resources" in source
    assert "_resource_probe_future" in source
    assert "self._resources.workers.submit" in source
    assert "sample_resources" in source


def test_pause_background_command_stays_in_existing_editor_view_category():
    source = MAIN.read_text()
    assert '"view.pause_background"' in source
    assert "CommandCategory.EDITOR_VIEW" in source


def test_main_window_accepts_completed_startup_snapshot_for_diagnostics():
    source = MAIN.read_text()
    assert "startup_snapshot" in source
    assert "set_startup_snapshot" in source


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
    store.save(Settings(editor_zoom_percent=130, soft_wrap=True))
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)

    view = window.open_path(source)
    app.processEvents()

    assert view.zoom_percent == 130
    assert view.soft_wrap is True
    assert store.load().editor_zoom_percent == 130
    status_text = {label.text() for label in window.statusBar().findChildren(QLabel)}
    assert "130%" in status_text
    assert "Wrap" in status_text
    window.zoom_in_editor()
    assert view.zoom_percent == 140
    assert store.load().editor_zoom_percent == 140
    window.set_editor_wrap(False)
    assert view.soft_wrap is False
    assert store.load().soft_wrap is False
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
    source.write_text("zero\none\ntwo\n", encoding="utf-8")
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
    replacement.replace(source)
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
    source.write_text("Hello, Привет\r\n", encoding="utf-8")
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


def test_mixed_eol_report_is_modeless_and_only_changes_pending_metadata(tmp_path: Path):
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
    assert source.read_bytes() == original
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
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.theme import active_theme
    from uniti.ui.whitespace import WhitespaceMode

    path = tmp_path / "menu-whitespace.txt"
    path.write_text("a b", encoding="utf-8")
    store = SettingsStore(tmp_path / "settings.json")
    store.save(Settings(whitespace_mode="all"))
    app = QApplication.instance() or QApplication([])
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
