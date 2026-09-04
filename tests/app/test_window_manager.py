from dataclasses import dataclass

import pytest

import uniti.app.window_manager as window_manager_module
from uniti.app.window_manager import WindowManager


@dataclass
class FakeView:
    view_id: str


class FakeWindow:
    def __init__(self, *view_ids: str) -> None:
        self.view_ids = tuple(view_ids)
        self._views = {view_id: FakeView(view_id) for view_id in view_ids}

    def view_for_id(self, view_id: str):
        return self._views.get(view_id)


@pytest.mark.parametrize(
    "values",
    [
        ("", "pane", 0),
        ("window", "", 0),
        ("window", "pane", -1),
        ("window", "pane", True),
    ],
)
def test_view_location_rejects_untrusted_values(values):
    with pytest.raises(ValueError):
        window_manager_module.ViewLocation(*values)


def test_windows_remain_in_registration_order_while_activation_changes():
    manager = WindowManager()
    first = FakeWindow("view-a")
    second = FakeWindow("view-b")
    manager.register("window-a", first)
    manager.register("window-b", second)

    manager.activate("window-b", "view-b")

    assert manager.windows == (first, second)
    assert manager.active_window is second
    assert manager.active_window_id == "window-b"
    assert manager.active_view_id == "view-b"


def test_unregistering_active_window_falls_back_to_most_recent_live_window():
    manager = WindowManager()
    first = FakeWindow("view-a")
    second = FakeWindow("view-b")
    third = FakeWindow("view-c")
    manager.register("window-a", first)
    manager.register("window-b", second)
    manager.register("window-c", third)
    manager.activate("window-a", "view-a")
    manager.activate("window-b", "view-b")

    assert manager.unregister("window-b") is second
    assert manager.active_window is first
    assert manager.active_view_id == "view-a"
    assert manager.windows == (first, third)


def test_fallback_restores_the_last_active_view_for_that_window():
    manager = WindowManager()
    first = FakeWindow("view-a", "view-b")
    second = FakeWindow("view-c")
    manager.register("window-a", first)
    manager.register("window-b", second)
    manager.activate("window-a", "view-b")
    manager.activate("window-b", "view-c")

    manager.unregister("window-b")

    assert manager.active_window is first
    assert manager.active_view_id == "view-b"


def test_window_ids_are_unique_and_activation_requires_a_registered_window():
    manager = WindowManager()
    manager.register("window-a", FakeWindow("view-a"))

    with pytest.raises(ValueError, match="already registered"):
        manager.register("window-a", FakeWindow("view-b"))
    with pytest.raises(KeyError, match="missing"):
        manager.activate("missing", None)


def test_activation_rejects_a_view_owned_by_another_window():
    manager = WindowManager()
    manager.register("window-a", FakeWindow("view-a"))
    manager.register("window-b", FakeWindow("view-b"))

    with pytest.raises(ValueError, match="does not belong"):
        manager.activate("window-a", "view-b")

    assert manager.active_window is None
    assert manager.active_view_id is None


def test_view_order_follows_stable_window_then_window_local_order():
    manager = WindowManager()
    manager.register("window-a", FakeWindow("view-b", "view-a"))
    manager.register("window-b", FakeWindow("view-c", "view-a"))

    assert manager.ordered_view_ids == ("view-b", "view-a", "view-c")


def test_most_recent_window_and_view_lookup_follow_activation():
    manager = WindowManager()
    first = FakeWindow("view-a")
    second = FakeWindow("view-b")
    manager.register("window-a", first)
    manager.register("window-b", second)

    assert manager.most_recent_window is second
    assert manager.window_id_for_view("view-a") == "window-a"
    assert manager.window_for_view("view-b") is second

    manager.activate("window-a", "view-a")

    assert manager.most_recent_window is first
    assert manager.window_id_for_view("missing") is None
    assert manager.window_for_view("missing") is None


def test_windows_by_recency_preserves_activation_then_registration_fallback():
    manager = WindowManager()
    first = FakeWindow("view-a")
    second = FakeWindow("view-b")
    third = FakeWindow("view-c")
    manager.register("window-a", first)
    manager.register("window-b", second)
    manager.register("window-c", third)
    manager.activate("window-a", "view-a")
    manager.activate("window-b", "view-b")

    assert manager.windows_by_recency == (second, first, third)
