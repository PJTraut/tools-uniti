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


def _pump_until(app, predicate, *, timeout: float = 5.0) -> None:
    deadline = time.perf_counter() + timeout
    while not predicate() and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.001)
    assert predicate()


def _delay_full_analysis(monkeypatch):
    from uniti.ui import main_window

    real = main_window.analyze_eol
    started = threading.Event()
    release = threading.Event()

    def delayed(source, *args, **kwargs):
        if kwargs.get("end") is None:
            started.set()
            release.wait(5.0)
        return real(source, *args, **kwargs)

    monkeypatch.setattr(main_window, "analyze_eol", delayed)
    return started, release


def test_open_paints_with_analyzing_status_then_publishes_full_eol(
    app,
    tmp_path: Path,
    monkeypatch,
):
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "large.txt"
    path.write_bytes((b"ordinary line\n" * 100_000) + b"tail\r\n")
    started, release = _delay_full_analysis(monkeypatch)
    window = UNITIMainWindow()
    try:
        began = time.perf_counter()
        view = window.open_path(path)

        assert view is not None
        assert time.perf_counter() - began < 1.0
        assert window.statusBar().format_label.text().endswith("Analyzing…")
        assert started.wait(1.0)
        release.set()
        _pump_until(app, lambda: id(view) in window._eol_reports)
        assert view.document.source_eol_report is window._eol_reports[id(view)]
        assert window.statusBar().format_label.text().endswith("Mixed")
    finally:
        release.set()
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_closed_tab_cancels_full_eol_without_publishing(
    app,
    tmp_path: Path,
    monkeypatch,
):
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "closing.txt"
    path.write_bytes(b"line\n" * 100_000)
    started, release = _delay_full_analysis(monkeypatch)
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        assert view is not None
        assert started.wait(1.0)
        assert window._close_tab(window._tabs.indexOf(view), force=True)
        release.set()
        _pump_until(app, lambda: not window._eol_jobs)

        assert id(view) not in window._eol_reports
        assert id(view) not in window._eol_dialogs
    finally:
        release.set()
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_replaced_path_cannot_publish_stale_full_eol(
    app,
    tmp_path: Path,
    monkeypatch,
):
    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "identity.txt"
    path.write_bytes(b"line\n" * 100_000)
    started, release = _delay_full_analysis(monkeypatch)
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        assert view is not None
        assert started.wait(1.0)
        replacement = tmp_path / "replacement.txt"
        replacement.write_bytes(b"different\r\n")
        replacement.replace(path)
        release.set()
        _pump_until(app, lambda: not window._eol_jobs)

        assert id(view) not in window._eol_reports
        assert window.statusBar().format_label.text().endswith("Analyzing…")
    finally:
        release.set()
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()
