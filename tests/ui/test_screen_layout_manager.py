"""Layouts per screen configuration, driven with fake screens and windows."""

from __future__ import annotations

import importlib.util
import os
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from uniti.app.window_layouts import ScreenSpec, WindowLayoutStore  # noqa: E402
from uniti.ui.screen_layout_manager import ScreenLayoutManager  # noqa: E402

_APP = QApplication.instance() or QApplication([])

LAPTOP = ScreenSpec("laptop", (0, 0, 1440, 900), 2.0)
EXTERNAL = ScreenSpec("external", (1440, 0, 2560, 1440), 1.0)


class FakeToggle:
    def __init__(self, rect):
        self._rect = rect

    def geometry(self):
        return QRect(*self._rect)

    def setGeometry(self, x, y, width, height):
        self._rect = (x, y, width, height)


class FakeWindow:
    def __init__(self, rect, state="normal"):
        self.placement = (rect, state)
        self._toggle_windows = {}

    def export_window_placement(self):
        return self.placement

    def apply_window_placement(self, geometry, state):
        self.placement = (geometry, state)


class FakeFind:
    placement = "detached"

    def __init__(self, rect):
        self.detached_geometry = rect

    def set_detached_geometry(self, rect):
        self.detached_geometry = rect


class World:
    """The 'hardware' (connected screens) plus a service with windows."""

    def __init__(self):
        self.screens = (LAPTOP, EXTERNAL)
        self.windows = {"w1": FakeWindow((1600, 100, 1200, 800))}
        self.service = SimpleNamespace(
            windows=SimpleNamespace(items=property(lambda _self: tuple(self.windows.items()))),
            _find_replace=None,
        )
        self.service.windows = self  # exposes .items below

    @property
    def items(self):
        return tuple(self.windows.items())

    def available(self):
        return tuple((s.geometry[0], s.geometry[1], s.geometry[2], s.geometry[3]) for s in self.screens)


def _manager(world, tmp_path, **kwargs):
    manager = ScreenLayoutManager(
        world.service,
        WindowLayoutStore(tmp_path / "window-layouts.json"),
        screens_provider=lambda: world.screens,
        available_provider=world.available,
        poll_ms=10**7,
        settle_ms=10**7,
        **kwargs,
    )
    return manager


def _settled(manager):
    """Record what the windows are doing now: two identical polls."""

    manager._poll()
    manager._poll()


def _change_screens(manager, world, screens):
    world.screens = screens
    manager._begin_settle()
    manager._settle()


def test_a_stable_layout_is_recorded_only_after_two_identical_polls(tmp_path):
    world = World()
    manager = _manager(world, tmp_path)
    manager.start()
    manager._poll()
    assert manager._book.layouts == ()
    manager._poll()
    assert len(manager._book.layouts) == 1
    assert WindowLayoutStore(tmp_path / "window-layouts.json").load().layouts


def test_a_window_still_moving_is_not_recorded(tmp_path):
    world = World()
    manager = _manager(world, tmp_path)
    manager.start()
    manager._poll()
    world.windows["w1"].placement = ((1700, 100, 1200, 800), "normal")
    manager._poll()
    assert manager._book.layouts == ()


def test_unplugging_a_monitor_adapts_the_layout_and_replugging_restores_it(tmp_path):
    world = World()
    manager = _manager(world, tmp_path)
    manager.start()
    _settled(manager)

    _change_screens(manager, world, (LAPTOP,))
    geometry, _ = world.windows["w1"].placement
    x, y, width, height = geometry
    assert 0 <= x and x + width <= 1440 and 0 <= y and y + height <= 900  # on the laptop

    _change_screens(manager, world, (LAPTOP, EXTERNAL))
    assert world.windows["w1"].placement == ((1600, 100, 1200, 800), "normal")


def test_the_os_shuffling_windows_during_the_unplug_is_not_filed_under_the_old_screens(tmp_path):
    world = World()
    manager = _manager(world, tmp_path)
    manager.start()
    _settled(manager)
    # The OS drags the window onto the laptop when the monitor goes away, and a
    # poll sees it before the settle: the screens differ, so nothing is recorded.
    world.screens = (LAPTOP,)
    world.windows["w1"].placement = ((100, 100, 800, 600), "normal")
    manager._poll()
    manager._poll()
    assert manager._settling
    both = [layout for layout in manager._book.layouts if len(layout.screens) == 2][0]
    assert both.windows["w1"].geometry == (1600, 100, 1200, 800)


def test_a_new_configuration_scales_main_windows_and_keeps_tool_window_sizes(tmp_path):
    world = World()
    world.windows["w1"].placement = ((1440, 0, 1280, 720), "normal")  # left half of EXTERNAL
    world.windows["w1"]._toggle_windows["whitespace_legend"] = FakeToggle((2000, 200, 340, 460))
    manager = _manager(world, tmp_path)
    manager.start()
    _settled(manager)
    smaller = ScreenSpec("external", (1440, 0, 1280, 720), 1.0)
    _change_screens(manager, world, (LAPTOP, smaller))
    (x, y, width, height), _ = world.windows["w1"].placement
    assert (width, height) == (640, 360)  # half of the new, half-size screen
    legend = world.windows["w1"]._toggle_windows["whitespace_legend"]._rect
    assert legend[2:] == (340, 460)


def test_a_maximized_state_travels_with_the_layout(tmp_path):
    world = World()
    world.windows["w1"].placement = ((1600, 100, 1200, 800), "maximized")
    manager = _manager(world, tmp_path)
    manager.start()
    _settled(manager)
    _change_screens(manager, world, (LAPTOP,))
    assert world.windows["w1"].placement[1] == "maximized"


def test_find_panel_follows_the_configuration(tmp_path):
    world = World()
    world.service._find_replace = FakeFind((1500, 100, 820, 320))
    manager = _manager(world, tmp_path)
    manager.start()
    _settled(manager)
    _change_screens(manager, world, (LAPTOP,))
    x, _, width, _ = world.service._find_replace.detached_geometry
    assert x + width <= 1440
    _change_screens(manager, world, (LAPTOP, EXTERNAL))
    assert world.service._find_replace.detached_geometry == (1500, 100, 820, 320)
    assert manager.find_geometry(None) == (1500, 100, 820, 320)


def test_toggle_windows_reopen_where_they_were_left_on_this_configuration(tmp_path):
    world = World()
    manager = _manager(world, tmp_path)
    manager.start()
    assert manager.toggle_geometry("compare", (1, 2, 3, 4)) == (1, 2, 3, 4)
    manager.note_toggle_closed("compare", (1700, 50, 900, 600))
    assert manager.toggle_geometry("compare", (1, 2, 3, 4)) == (1700, 50, 900, 600)
    _settled(manager)
    _change_screens(manager, world, (LAPTOP,))
    laptop_value = manager.toggle_geometry("compare", None)
    assert laptop_value[0] + laptop_value[2] <= 1440
    manager.note_toggle_closed("compare", (30, 40, 900, 600))
    _settled(manager)
    _change_screens(manager, world, (LAPTOP, EXTERNAL))
    assert manager.toggle_geometry("compare", None) == (1700, 50, 900, 600)


def test_open_toggle_windows_are_moved_when_the_screens_change(tmp_path):
    world = World()
    world.windows["w1"]._toggle_windows["compare"] = FakeToggle((2000, 100, 900, 600))
    manager = _manager(world, tmp_path)
    manager.start()
    _settled(manager)
    _change_screens(manager, world, (LAPTOP,))
    x, y, width, height = world.windows["w1"]._toggle_windows["compare"]._rect
    assert x + width <= 1440 and y + height <= 900
    _change_screens(manager, world, (LAPTOP, EXTERNAL))
    assert world.windows["w1"]._toggle_windows["compare"]._rect == (2000, 100, 900, 600)


def test_startup_on_changed_screens_moves_the_restored_windows(tmp_path):
    world = World()
    first = _manager(world, tmp_path)
    first.start()
    _settled(first)
    first.shutdown()
    # Relaunched with the external monitor gone: the session's window is
    # still at its old place until the manager starts.
    world.screens = (LAPTOP,)
    second = _manager(world, tmp_path)
    second.start()
    x, _, width, _ = world.windows["w1"].placement[0]
    assert x + width <= 1440


def test_startup_on_the_same_screens_leaves_windows_alone(tmp_path):
    world = World()
    first = _manager(world, tmp_path)
    first.start()
    _settled(first)
    first.shutdown()
    world.windows["w1"].placement = ((1500, 150, 1100, 700), "normal")
    second = _manager(world, tmp_path)
    second.start()
    assert world.windows["w1"].placement == ((1500, 150, 1100, 700), "normal")


def test_shutdown_records_the_final_positions_but_not_an_empty_window_set(tmp_path):
    world = World()
    manager = _manager(world, tmp_path)
    manager.start()
    _settled(manager)
    world.windows["w1"].placement = ((1500, 150, 1100, 700), "normal")
    manager.shutdown()
    stored = WindowLayoutStore(tmp_path / "window-layouts.json").load()
    assert stored.layouts[0].windows["w1"].geometry == (1500, 150, 1100, 700)
    world.windows.clear()
    again = _manager(world, tmp_path)
    again.start()
    again.shutdown()
    assert WindowLayoutStore(tmp_path / "window-layouts.json").load().layouts[0].windows


def test_a_signature_change_without_a_signal_is_still_noticed_by_the_poll(tmp_path):
    world = World()
    manager = _manager(world, tmp_path)
    manager.start()
    _settled(manager)
    world.screens = (LAPTOP,)
    manager._poll()
    assert manager._settling


def test_startup_attaches_a_manager_next_to_the_settings_and_skips_a_store_without_a_path(tmp_path):
    from uniti.app.application import _start_screen_layouts

    cleanups = []
    service = SimpleNamespace(windows=SimpleNamespace(items=()), screen_layouts=None)
    context = SimpleNamespace(
        data={"settings_store": SimpleNamespace(path=tmp_path / "settings.json")},
        register_cleanup=cleanups.append,
    )
    _start_screen_layouts(service, context)
    try:
        assert isinstance(service.screen_layouts, ScreenLayoutManager)
        assert service.screen_layouts._store.path == tmp_path / "window-layouts.json"
        assert cleanups == [service.screen_layouts.shutdown]
    finally:
        service.screen_layouts.shutdown()

    bare = SimpleNamespace(windows=SimpleNamespace(items=()), screen_layouts=None)
    _start_screen_layouts(
        bare, SimpleNamespace(data={"settings_store": object()}, register_cleanup=cleanups.append)
    )
    assert bare.screen_layouts is None
