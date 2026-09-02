from __future__ import annotations

import importlib.util
import os
import threading
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


def _pump_until(app, predicate, *, timeout: float = 10.0) -> None:
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()


def _delay_navigation(monkeypatch):
    from uniti.ui import main_window

    real = main_window.build_line_index_batch
    started = threading.Event()
    release = threading.Event()

    def delayed(*args, **kwargs):
        started.set()
        release.wait(10.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(main_window, "build_line_index_batch", delayed)
    return started, release


def test_far_go_to_line_returns_pending_without_blocking(
    app,
    tmp_path: Path,
    monkeypatch,
):
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "million-lines.txt"
    path.write_bytes(b"x\n" * 1_000_000)
    started, release = _delay_navigation(monkeypatch)
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        assert view is not None
        began = time.perf_counter()

        assert window.go_to_line(900_000)
        assert time.perf_counter() - began < 0.1
        assert view.state.cursor == 0
        assert started.wait(1.0)

        release.set()
        _pump_until(
            app,
            lambda: view.document.line_for_char(view.state.cursor) == 899_999,
        )
        assert view.document.offset_mapper.complete
    finally:
        release.set()
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_edit_prevents_stale_navigation_from_moving_cursor(
    app,
    tmp_path: Path,
    monkeypatch,
):
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "stale-navigation.txt"
    path.write_bytes(b"x\n" * 600_000)
    started, release = _delay_navigation(monkeypatch)
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        assert view is not None
        assert window.go_to_line(580_000)
        assert started.wait(1.0)

        view.document.insert(0, "edit\n")
        view._state_changed()
        release.set()
        _pump_until(app, lambda: not window._navigation_jobs)

        assert view.state.cursor == 0
    finally:
        release.set()
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()
