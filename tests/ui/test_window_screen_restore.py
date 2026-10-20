"""Floating-window restore positions across screen changes: the main window's
own record, and the toggle windows' persisted geometry, are pulled back onto a
connected screen (and a maximized window saves the rectangle it returns to)."""

from __future__ import annotations

import importlib.util
import os
from dataclasses import replace

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from uniti.app.session import WindowRecord  # noqa: E402
from uniti.app.settings import SettingsStore  # noqa: E402
from uniti.ui.main_window import UNITIMainWindow  # noqa: E402

_APP = QApplication.instance() or QApplication([])


def _screen() -> tuple[int, int, int, int]:
    rect = QGuiApplication.primaryScreen().availableGeometry()
    return rect.x(), rect.y(), rect.width(), rect.height()


def _inside_screen(rect) -> bool:
    screen_x, screen_y, screen_width, screen_height = _screen()
    return (
        rect.x() >= screen_x
        and rect.y() >= screen_y
        and rect.x() + rect.width() <= screen_x + screen_width
        and rect.y() + rect.height() <= screen_y + screen_height
    )


@pytest.fixture
def window(tmp_path):
    window = UNITIMainWindow(settings_store=SettingsStore(tmp_path / "settings.json"))
    try:
        yield window
    finally:
        window.close()
        _APP.processEvents()


def _record(window, geometry, state="normal") -> WindowRecord:
    return WindowRecord(window.window_id, geometry, state, window.panes.export_state())


def test_restoring_a_window_saved_on_a_removed_monitor_lands_on_a_connected_screen(window):
    window.restore_window_record(_record(window, (9000, 400, 700, 500)))
    assert _inside_screen(window.geometry())
    assert (window.width(), window.height()) == (700, 500)


def test_restoring_a_window_larger_than_the_screen_caps_it(window):
    screen_x, screen_y, screen_width, screen_height = _screen()
    window.restore_window_record(
        _record(window, (screen_x + 10, screen_y + 40, screen_width + 1500, screen_height + 1500))
    )
    assert window.width() <= screen_width
    assert window.height() <= screen_height
    assert _inside_screen(window.geometry())


def test_restoring_an_on_screen_window_leaves_it_where_it_was(window):
    screen_x, screen_y, _, _ = _screen()
    geometry = (screen_x + 60, screen_y + 80, 500, 400)
    window.restore_window_record(_record(window, geometry))
    rect = window.geometry()
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == geometry


def test_a_maximized_window_records_the_rectangle_it_returns_to(window):
    screen_x, screen_y, _, _ = _screen()
    geometry = (screen_x + 60, screen_y + 80, 500, 400)
    window.setGeometry(*geometry)
    window.show()
    _APP.processEvents()
    window.showMaximized()
    _APP.processEvents()
    assert window.isMaximized()
    record = window.export_window_record()
    assert record.window_state == "maximized"
    assert record.geometry == geometry


def test_a_normal_window_records_its_current_geometry(window):
    screen_x, screen_y, _, _ = _screen()
    window.setGeometry(screen_x + 40, screen_y + 60, 600, 450)
    window.show()
    _APP.processEvents()
    record = window.export_window_record()
    assert record.window_state == "normal"
    rect = window.geometry()
    assert record.geometry == (rect.x(), rect.y(), rect.width(), rect.height())


def test_toggle_window_saved_on_a_removed_monitor_reopens_on_a_connected_screen(window):
    window._settings = replace(
        window._settings,
        toggle_window_geometry={"whitespace_legend": (9000, 9000, 340, 460)},
    )
    window.show_whitespace_legend()
    _APP.processEvents()
    legend = window._whitespace_legend_window
    try:
        assert legend is not None
        assert _inside_screen(legend.geometry())
        assert (legend.width(), legend.height()) == (340, 460)
    finally:
        window.show_whitespace_legend()  # toggle closed
        _APP.processEvents()


def test_toggle_window_on_screen_reopens_exactly_where_it_was_closed(window):
    screen_x, screen_y, _, _ = _screen()
    geometry = (screen_x + 120, screen_y + 90, 340, 460)
    window._settings = replace(
        window._settings, toggle_window_geometry={"whitespace_legend": geometry}
    )
    window.show_whitespace_legend()
    _APP.processEvents()
    legend = window._whitespace_legend_window
    try:
        rect = legend.geometry()
        assert (rect.x(), rect.y(), rect.width(), rect.height()) == geometry
    finally:
        window.show_whitespace_legend()
        _APP.processEvents()


def test_apply_window_placement_moves_a_live_window_onto_the_screen(window):
    window.show()
    _APP.processEvents()
    window.apply_window_placement((9000, 400, 700, 500), "normal")
    assert _inside_screen(window.geometry())
    assert not window.isMaximized()


def test_apply_window_placement_returns_a_maximized_window_to_normal_first(window):
    screen_x, screen_y, _, _ = _screen()
    window.show()
    window.showMaximized()
    _APP.processEvents()
    assert window.isMaximized()
    geometry = (screen_x + 60, screen_y + 80, 500, 400)
    window.apply_window_placement(geometry, "normal")
    _APP.processEvents()
    assert not window.isMaximized()
    rect = window.geometry()
    assert (rect.x(), rect.y(), rect.width(), rect.height()) == geometry


def test_apply_window_placement_can_maximize(window):
    window.show()
    _APP.processEvents()
    screen_x, screen_y, _, _ = _screen()
    window.apply_window_placement((screen_x + 60, screen_y + 80, 500, 400), "maximized")
    _APP.processEvents()
    assert window.isMaximized()
    # The rectangle it returns to is what gets saved.
    assert window.export_window_placement()[0] == (screen_x + 60, screen_y + 80, 500, 400)


def test_toggle_window_reopens_where_the_layout_manager_says(window):
    from types import SimpleNamespace

    screen_x, screen_y, _, _ = _screen()
    wanted = (screen_x + 150, screen_y + 110, 340, 460)
    closed = []

    class Layouts:
        def toggle_geometry(self, key, fallback):
            return wanted if key == "whitespace_legend" else fallback

        def note_toggle_closed(self, key, geometry):
            closed.append((key, geometry))

    window._service = SimpleNamespace(screen_layouts=Layouts())
    try:
        window.show_whitespace_legend()
        _APP.processEvents()
        legend = window._whitespace_legend_window
        try:
            rect = legend.geometry()
            assert (rect.x(), rect.y(), rect.width(), rect.height()) == wanted
        finally:
            window.show_whitespace_legend()
            _APP.processEvents()
    finally:
        window._service = None  # the fixture closes the window as a standalone one
    assert closed and closed[0][0] == "whitespace_legend"
