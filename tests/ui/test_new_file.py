from __future__ import annotations

import importlib.util
import os
import time
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is not installed",
)


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    from uniti.ui.main_window import UNITIMainWindow

    instance = UNITIMainWindow()
    yield instance
    instance.close_all_documents(force=True)
    instance.close()
    app.processEvents()


def _wait(app, predicate, timeout: float = 5.0) -> None:
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()


def _desktop_service(tmp_path: Path):
    from uniti.app.recovery_manager import RecoveryManager
    from uniti.app.service import UNITIService
    from uniti.app.session_store import SessionStore
    from uniti.app.settings import SettingsStore
    from uniti.resources import ResourceManager

    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=SessionStore(tmp_path / "sessions"),
        recovery_manager=RecoveryManager(tmp_path / "recovery"),
        session_capture=lambda clean: ("snapshot", clean),
    )
    return service


def _stop_desktop_service(app, service) -> None:
    for _window_id, open_window in service.windows.items:
        open_window.close_all_documents(force=True)
        open_window.close()
    app.processEvents()
    from uniti.app.service import QuitChoice

    if service.is_running:
        service.request_quit(lambda _entry: QuitChoice.DISCARD)
    app.processEvents()


def test_new_file_opens_a_blank_editable_tab(window):
    before = window.panes.active_leaf.tabs.count()

    window.new_file()

    assert window.panes.active_leaf.tabs.count() == before + 1
    view = window.current_view
    assert view is not None
    assert view.document.total_chars() == 0
    assert view.document.path.name == "Untitled.txt"
    assert view.document.modified is False

    view.state.insert_text("hello")
    assert view.document.modified is True


def test_new_file_twice_numbers_untitled_documents(tmp_path: Path, app):
    service = _desktop_service(tmp_path)
    window = service.new_window()
    try:
        window.new_file()
        window.new_file()
        names = sorted(
            entry.document.path.name for entry in service.documents.entries
        )
        assert names == ["Untitled 2.txt", "Untitled.txt"]
        assert all(entry.is_untitled for entry in service.documents.entries)
    finally:
        _stop_desktop_service(app, service)


def test_new_file_is_untitled_and_ctrl_s_redirects_to_save_as(
    tmp_path: Path, app, monkeypatch
):
    service = _desktop_service(tmp_path)
    window = service.new_window()
    try:
        window.new_file()
        view = window.current_view
        assert window._is_untitled_view(view) is True

        calls = []
        monkeypatch.setattr(
            window,
            "start_save_current_as",
            lambda *a, **k: calls.append((a, k)) or None,
        )
        window.start_save_current()
        assert calls == [((), {})]
    finally:
        _stop_desktop_service(app, service)


def test_normal_document_ctrl_s_does_not_redirect_to_save_as(
    tmp_path: Path, app, monkeypatch
):
    service = _desktop_service(tmp_path)
    window = service.new_window()
    path = tmp_path / "real.txt"
    path.write_text("abc", encoding="utf-8", newline="")
    try:
        view = window.open_path(path)
        assert window._is_untitled_view(view) is False
        calls = []
        monkeypatch.setattr(
            window,
            "start_save_current_as",
            lambda *a, **k: calls.append((a, k)) or None,
        )
        window.start_save_current()
        assert calls == []
    finally:
        _stop_desktop_service(app, service)


def test_saving_an_untitled_document_reuses_its_tab_and_cleans_up_scratch_dir(
    tmp_path: Path, app
):
    service = _desktop_service(tmp_path)
    window = service.new_window()
    try:
        window.new_file()
        view = window.current_view
        view.state.insert_text("hello world")
        scratch_dir = view.document.path.parent
        assert scratch_dir.exists()
        destination = tmp_path / "saved.txt"
        tab_count_before = window.panes.active_leaf.tabs.count()

        handle = window.start_save_current_as(
            destination, view.document.output_format
        )
        assert handle is not None
        _wait(app, lambda: handle.done)
        _wait(app, lambda: window.current_view.document.path == destination)

        assert window.panes.active_leaf.tabs.count() == tab_count_before
        assert window.current_view is view
        assert view.document.path == destination
        assert destination.read_text(encoding="utf-8") == "hello world"
        assert window._is_untitled_view(view) is False
        assert not scratch_dir.exists()
    finally:
        _stop_desktop_service(app, service)


def test_discarding_an_untitled_document_removes_its_scratch_file(
    tmp_path: Path, app, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    service = _desktop_service(tmp_path)
    window = service.new_window()
    try:
        window.new_file()
        view = window.current_view
        view.state.insert_text("throwaway")
        scratch_dir = view.document.path.parent
        assert scratch_dir.exists()

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *a, **k: QMessageBox.StandardButton.Discard,
        )
        index = window.panes.active_leaf.tabs.indexOf(view)
        assert window._close_tab(index) is True
        assert not scratch_dir.exists()
    finally:
        _stop_desktop_service(app, service)


def test_closing_an_untitled_document_with_save_choice_forces_save_as(
    tmp_path: Path, app, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    service = _desktop_service(tmp_path)
    window = service.new_window()
    try:
        window.new_file()
        view = window.current_view
        view.state.insert_text("please save me")

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *a, **k: QMessageBox.StandardButton.Save,
        )
        calls = []

        def fake_save_current_as():
            calls.append(True)
            return None

        monkeypatch.setattr(window, "save_current_as", fake_save_current_as)

        assert window._confirm_close(view) is False
        assert calls == [True]
    finally:
        _stop_desktop_service(app, service)
