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


def test_main_window_reloads_document_after_streamed_replace_all():
    source = MAIN.read_text()
    assert "_reload_after_stream_replace" in source
    assert "streamReplaceCommitted.connect" in source
    assert "Document.open(path" in source


def test_main_window_uses_shared_resource_manager_for_workers_and_tab_priority():
    source = MAIN.read_text()
    assert "ResourceManager" in source
    assert "resource_manager" in source
    assert "self._resources.workers" in source
    assert "set_resource_active" in source


def test_main_window_flushes_and_shuts_down_recovery_manager_on_application_close():
    source = MAIN.read_text()
    assert "self._recovery_manager.shutdown()" in source


def test_main_window_periodically_observes_resource_memory_pressure():
    source = MAIN.read_text()
    assert "_resource_timer" in source
    assert "observe_memory" in source


def test_main_window_accepts_completed_startup_snapshot_for_diagnostics():
    source = MAIN.read_text()
    assert "startup_snapshot" in source
    assert "set_startup_snapshot" in source
