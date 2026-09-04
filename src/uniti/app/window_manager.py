"""Stable process-level ownership and activation order for editor windows."""

from __future__ import annotations


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _window_view_ids(window: object) -> tuple[str, ...] | None:
    if not hasattr(window, "view_ids"):
        return None
    value = getattr(window, "view_ids")
    value = value() if callable(value) else value
    if value is None:
        return ()
    return tuple(_identifier(view_id, "view ID") for view_id in value)


class WindowManager:
    """Track top-level windows without coupling the app layer to Qt widgets."""

    def __init__(self) -> None:
        self._windows: dict[str, object] = {}
        self._activation_order: list[str] = []
        self._active_views: dict[str, str | None] = {}
        self._active_window_id: str | None = None
        self._active_view_id: str | None = None

    @property
    def windows(self) -> tuple[object, ...]:
        """Return windows in stable registration order."""

        return tuple(self._windows.values())

    @property
    def items(self) -> tuple[tuple[str, object], ...]:
        return tuple(self._windows.items())

    @property
    def count(self) -> int:
        return len(self._windows)

    @property
    def active_window_id(self) -> str | None:
        return self._active_window_id

    @property
    def active_window(self) -> object | None:
        if self._active_window_id is None:
            return None
        return self._windows.get(self._active_window_id)

    @property
    def most_recent_window(self) -> object | None:
        if self.active_window is not None:
            return self.active_window
        return next(reversed(self._windows.values()), None)

    @property
    def active_view_id(self) -> str | None:
        return self._active_view_id

    @property
    def ordered_view_ids(self) -> tuple[str, ...]:
        ordered: list[str] = []
        seen: set[str] = set()
        for window in self._windows.values():
            view_ids = _window_view_ids(window)
            if view_ids is None:
                continue
            for view_id in view_ids:
                if view_id not in seen:
                    seen.add(view_id)
                    ordered.append(view_id)
        return tuple(ordered)

    def window_id_for_view(self, view_id: str) -> str | None:
        selected_id = _identifier(view_id, "view ID")
        for window_id, window in self._windows.items():
            view_ids = _window_view_ids(window)
            if view_ids is not None and selected_id in view_ids:
                return window_id
        return None

    def window_for_view(self, view_id: str) -> object | None:
        window_id = self.window_id_for_view(view_id)
        return None if window_id is None else self._windows[window_id]

    def register(self, window_id: str, window: object) -> None:
        selected_id = _identifier(window_id, "window ID")
        if window is None:
            raise ValueError("window must not be None")
        if selected_id in self._windows:
            raise ValueError(f"window {selected_id!r} is already registered")
        if any(existing is window for existing in self._windows.values()):
            raise ValueError("window object is already registered")
        self._windows[selected_id] = window
        self._active_views[selected_id] = None

    def unregister(self, window_id: str) -> object:
        selected_id = _identifier(window_id, "window ID")
        try:
            window = self._windows.pop(selected_id)
        except KeyError as exc:
            raise KeyError(selected_id) from exc
        self._activation_order = [
            candidate for candidate in self._activation_order if candidate != selected_id
        ]
        self._active_views.pop(selected_id, None)
        if self._active_window_id == selected_id:
            self._active_window_id = (
                self._activation_order[-1] if self._activation_order else None
            )
            self._active_view_id = None
            if self._active_window_id is not None:
                retained = self._active_views[self._active_window_id]
                if retained is not None:
                    self._active_view_id = retained
                else:
                    fallback = self._windows[self._active_window_id]
                    candidate = getattr(fallback, "active_view_id", None)
                    if isinstance(candidate, str) and candidate:
                        self._active_view_id = candidate
                    else:
                        view_ids = _window_view_ids(fallback)
                        if view_ids:
                            self._active_view_id = view_ids[0]
        return window

    def activate(self, window_id: str, view_id: str | None) -> None:
        selected_id = _identifier(window_id, "window ID")
        if selected_id not in self._windows:
            raise KeyError(selected_id)
        selected_view_id = (
            None if view_id is None else _identifier(view_id, "view ID")
        )
        if selected_view_id is not None:
            view_ids = _window_view_ids(self._windows[selected_id])
            if view_ids is not None and selected_view_id not in view_ids:
                raise ValueError(
                    f"view {selected_view_id!r} does not belong to window {selected_id!r}"
                )
        self._activation_order = [
            candidate for candidate in self._activation_order if candidate != selected_id
        ]
        self._activation_order.append(selected_id)
        self._active_window_id = selected_id
        self._active_view_id = selected_view_id
        self._active_views[selected_id] = selected_view_id

    def resolve_active_view(self) -> object | None:
        window = self.active_window
        view_id = self._active_view_id
        if window is None or view_id is None:
            return None
        resolver = getattr(window, "view_for_id", None)
        if callable(resolver):
            return resolver(view_id)
        views = getattr(window, "views", None)
        if isinstance(views, dict):
            return views.get(view_id)
        current = getattr(window, "current_view", None)
        current = current() if callable(current) else current
        if current is not None and getattr(current, "view_id", view_id) == view_id:
            return current
        return None

    def clear(self) -> None:
        self._windows.clear()
        self._activation_order.clear()
        self._active_views.clear()
        self._active_window_id = None
        self._active_view_id = None


__all__ = ["WindowManager"]
