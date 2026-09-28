"""Generic open/close/geometry-and-zoom-persistence manager for every
"toggle window" (Character Inspector, Compare, Whitespace & Unicode
Legend, and any future one), composed onto UNITIMainWindow.

Second slice pulled out of main_window.py's god-object, after Dogfood
Evidence proved the "compose a controller object" pattern (mirroring
`theme_editor.py`, `compare_pane.py`, `whitespace_legend.py`) works
cleanly there. `self._toggle_windows` (the open-window bookkeeping dict)
and `self._settings`/`self._save_settings()` (persistence) stay owned by
`UNITIMainWindow` itself -- several read-only properties elsewhere
(`_compare_pane`, `_character_inspector_dialog`, `_whitespace_legend_window`,
`_refresh_character_inspector`) already read `self._toggle_windows`
directly and don't need to change; only the state-transition logic
(open/close/persist) moves here.
"""

from __future__ import annotations

from dataclasses import replace as dataclass_replace

from PySide6.QtWidgets import QWidget


class ToggleWindowManager:
    """Owns the open/close/persist logic for `owner._toggle_windows`.

    `owner` is the `UNITIMainWindow` this manager acts on behalf of --
    used for `owner._toggle_windows` (the dict of currently-open toggle
    windows, keyed by a short string id), `owner._settings`/
    `owner._save_settings()` (geometry/zoom/splitter-size persistence),
    exactly the same state `_toggle_window`/`_on_toggle_window_closed`
    touched before the move."""

    def __init__(self, owner) -> None:
        self._owner = owner

    def toggle(self, key: str, factory) -> QWidget | None:
        """A call while `key`'s window is already open closes it instead
        of opening another (matching Find: the hotkey toggles).
        `factory(zoom_percent, geometry)` builds a new window using the
        last-persisted values for `key` (or the defaults if none exist
        yet), or returns `None` to decline opening at all -- e.g. the
        user cancelled a document/file picker, or there was nothing to
        inspect -- in which case nothing is shown or tracked. Whatever
        closes the window (this method again, its own Close action,
        Escape, or window chrome) is caught via its `closeRequested`
        signal if it has one (`ComparePane`), else `QDialog`'s own
        `finished` (`CharacterInspectorDialog`, `WhitespaceLegendWindow`),
        and persists its final geometry (always) and `zoom_percent` (if
        the window exposes that property) back to `Settings`."""

        owner = self._owner
        existing = owner._toggle_windows.get(key)
        if existing is not None:
            existing.close()
            return None
        zoom_percent = owner._settings.toggle_window_zoom_percent.get(key, 100)
        geometry = owner._settings.toggle_window_geometry.get(key)
        window = factory(zoom_percent, geometry)
        if window is None:
            return None
        owner._toggle_windows[key] = window
        close_signal = getattr(window, "closeRequested", None)
        if close_signal is None:
            close_signal = window.finished
        close_signal.connect(
            lambda *_args, key=key, window=window: self._on_closed(key, window)
        )
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def _on_closed(self, key: str, window: QWidget) -> None:
        owner = self._owner
        if owner._toggle_windows.get(key) is not window:
            return
        del owner._toggle_windows[key]
        geometry = window.geometry()
        geometries = dict(owner._settings.toggle_window_geometry)
        geometries[key] = (
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
        )
        updates: dict[str, object] = {"toggle_window_geometry": geometries}
        zoom_percent = getattr(window, "zoom_percent", None)
        if isinstance(zoom_percent, int):
            zoom_percents = dict(owner._settings.toggle_window_zoom_percent)
            zoom_percents[key] = zoom_percent
            updates["toggle_window_zoom_percent"] = zoom_percents
        # BF-087: same optional-property pattern as zoom_percent above --
        # only a window that exposes `splitter_sizes` (Character Inspector's
        # list/detail split) gets an entry; others are left untouched.
        splitter_sizes = getattr(window, "splitter_sizes", None)
        if (
            isinstance(splitter_sizes, tuple)
            and len(splitter_sizes) == 2
            and all(isinstance(size, int) for size in splitter_sizes)
        ):
            splitter_sizes_by_key = dict(owner._settings.toggle_window_splitter_sizes)
            splitter_sizes_by_key[key] = splitter_sizes
            updates["toggle_window_splitter_sizes"] = splitter_sizes_by_key
        owner._settings = dataclass_replace(owner._settings, **updates)
        owner._save_settings()
        window.deleteLater()


__all__ = ["ToggleWindowManager"]
