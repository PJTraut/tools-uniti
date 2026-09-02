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
    view = window.open_path(source)
    view.state.move_to(3)
    view.state.insert_text("X")
    window.save_current_as(output)
    app.processEvents()
    assert output.read_text(encoding="utf-8") == "abcX\n"
    window.close_all_documents(force=True)
    window.close()


def test_main_window_wires_recovery_manager_and_startup_recovery_flow():
    source = MAIN.read_text()
    assert "RecoveryManager" in source
    assert "recover_startup_sessions" in source
    assert "recovery_manager.attach" in source
    assert "recovery_manager.detach" in source
    application = APPLICATION.read_text()
    assert "RecoveryManager" in application
    assert "recover_startup_sessions" in application


def test_application_uses_app_paths_and_settings_store():
    source = MAIN.read_text()
    application = APPLICATION.read_text()
    assert "SettingsStore" in source
    assert "last_directory" in source
    assert "AppPaths.current" in application
    assert "SettingsStore" in application
    assert "paths.recovery_dir" in application


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
    before = window._tabs.count()

    assert window.open_path(source) is None
    assert window._tabs.count() == before
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
