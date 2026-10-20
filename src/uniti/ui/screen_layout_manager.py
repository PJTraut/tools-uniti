"""Keeps floating-window layouts per screen configuration.

`uniti.app.window_layouts` holds one layout per set of connected screens; this
is the Qt side that records the live windows into it and, when the screens
change, puts the windows where that configuration last had them -- or, for a
configuration never seen, adapts the previous layout to the new screens
(`screen_geometry.adapt_geometry`: main windows scale with the screen, tool
windows keep their size).

Two details make it work:

- Recording is by polling for geometry that has held still, not by watching
  every move. The OS moves windows on its own when a monitor is unplugged,
  and those moves must not be filed as the user's layout for the outgoing
  configuration; a record needs two identical polls under an unchanged
  screen signature, so a transition always reaches `_begin_settle` first.
- A change is acted on only after the screens stop signalling (`settle_ms`):
  a hot-plug emits several signals, and sleep/wake can remove and re-add the
  same monitor within seconds. Settling to the *same* configuration still
  re-applies its layout, undoing whatever the OS did to the windows meanwhile.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QObject, QTimer
from PySide6.QtGui import QGuiApplication

from uniti.app.window_layouts import (
    MAX_NAME_LENGTH,
    Layout,
    LayoutBook,
    Placement,
    ScreenSpec,
    WindowLayoutStore,
    screen_signature,
)
from uniti.ui.screen_geometry import (
    NATIVE_TITLE_BAR_HEIGHT,
    Geometry,
    adapt_geometry,
    clamp_geometry_to_screens,
    current_screen_geometries,
)

DEFAULT_SETTLE_MS = 750
DEFAULT_POLL_MS = 1000


def current_screen_specs() -> tuple[ScreenSpec, ...]:
    """Every connected screen (primary first) as a `ScreenSpec`."""

    specs = []
    for screen in QGuiApplication.screens():
        rect = screen.geometry()
        identity = "|".join(
            (screen.name(), screen.manufacturer(), screen.model(), screen.serialNumber())
        )[:MAX_NAME_LENGTH]
        try:
            specs.append(
                ScreenSpec(
                    identity,
                    (rect.x(), rect.y(), rect.width(), rect.height()),
                    screen.devicePixelRatio(),
                )
            )
        except ValueError:
            continue
    return tuple(specs)


def _rect(widget) -> Geometry | None:
    rect = widget.geometry()
    if rect.width() <= 0 or rect.height() <= 0:
        return None
    return (rect.x(), rect.y(), rect.width(), rect.height())


class ScreenLayoutManager(QObject):
    """Owned by the service (`service.screen_layouts`)."""

    def __init__(
        self,
        service,
        store: WindowLayoutStore,
        *,
        screens_provider: Callable[[], tuple[ScreenSpec, ...]] = current_screen_specs,
        available_provider: Callable[[], tuple[Geometry, ...]] = current_screen_geometries,
        settle_ms: int = DEFAULT_SETTLE_MS,
        poll_ms: int = DEFAULT_POLL_MS,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._store = store
        self._screens_provider = screens_provider
        self._available_provider = available_provider
        self._book: LayoutBook = store.load()
        self._signature: str | None = None
        self._settling = False
        self._observed: tuple | None = None
        self._toggle_notes: dict[str, Geometry] = {}
        self._connected_screens: list = []
        self._stopped = False
        self._settle_timer = QTimer(self)
        self._settle_timer.setSingleShot(True)
        self._settle_timer.setInterval(settle_ms)
        self._settle_timer.timeout.connect(self._settle)
        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(poll_ms)
        self._poll_timer.timeout.connect(self._poll)

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Begin watching. When the screens are not the ones the last
        recording was made under (they changed while UNITI was closed), the
        windows restored from the session are moved to this configuration's
        layout right away."""

        specs = self._screens_provider()
        if not specs:
            return
        self._signature = screen_signature(specs)
        app = QGuiApplication.instance()
        if app is not None:
            app.screenAdded.connect(self._on_screen_added)
            app.screenRemoved.connect(self._begin_settle)
            app.primaryScreenChanged.connect(self._begin_settle)
            for screen in QGuiApplication.screens():
                self._watch(screen)
        previous = self._book.active
        if previous is not None and previous != self._signature:
            self._apply(self._signature, previous, specs)
        self._poll_timer.start()

    def shutdown(self) -> None:
        """Stop watching and record the windows' final positions."""

        if self._stopped:
            return
        self._stopped = True
        self._poll_timer.stop()
        self._settle_timer.stop()
        app = QGuiApplication.instance()
        if app is not None:
            for signal, slot in (
                (app.screenAdded, self._on_screen_added),
                (app.screenRemoved, self._begin_settle),
                (app.primaryScreenChanged, self._begin_settle),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        for screen in self._connected_screens:
            try:
                screen.geometryChanged.disconnect(self._begin_settle)
            except (RuntimeError, TypeError):
                pass
        self._connected_screens.clear()
        specs = self._screens_provider()
        if (
            self._settling
            or not specs
            or screen_signature(specs) != self._signature
            or not self._windows()  # all closed already: nothing left to record
        ):
            return
        self._record(self._snapshot(specs))

    # -- consumers ---------------------------------------------------------

    def find_geometry(self, fallback: Geometry | None) -> Geometry | None:
        """Where the detached Find/Replace panel goes on the current screens."""

        layout = self._book.get(self._signature)
        if layout is not None and layout.find is not None:
            return layout.find
        return fallback

    def toggle_geometry(self, key: str, fallback: Geometry | None) -> Geometry | None:
        """Where toggle window `key` reopens on the current screens."""

        if key in self._toggle_notes:
            return self._toggle_notes[key]
        layout = self._book.get(self._signature)
        if layout is not None and key in layout.toggles:
            return layout.toggles[key]
        return fallback

    def note_toggle_closed(self, key: str, geometry: Geometry) -> None:
        """A toggle window closed where it was left: that is its position
        on this configuration (it is not open to be seen by the next poll)."""

        self._toggle_notes[key] = tuple(geometry)

    # -- screen changes ----------------------------------------------------

    def _watch(self, screen) -> None:
        if screen not in self._connected_screens:
            self._connected_screens.append(screen)
            screen.geometryChanged.connect(self._begin_settle)

    def _on_screen_added(self, screen) -> None:
        self._watch(screen)
        self._begin_settle()

    def _begin_settle(self, *_args) -> None:
        self._settling = True
        self._settle_timer.start()

    def _settle(self) -> None:
        specs = self._screens_provider()
        if not specs:
            self._settle_timer.start()  # no screens at all: wait for some
            return
        signature = screen_signature(specs)
        self._apply(signature, self._signature, specs)
        self._signature = signature
        self._settling = False
        self._observed = None

    # -- recording ---------------------------------------------------------

    def _windows(self) -> list:
        return list(self._service.windows.items)

    def _snapshot(self, specs: tuple[ScreenSpec, ...]) -> Layout:
        signature = screen_signature(specs)
        previous = self._book.get(signature)
        windows: dict[str, Placement] = {}
        toggles: dict[str, Geometry] = dict(previous.toggles) if previous else {}
        for window_id, window in self._windows():
            export = getattr(window, "export_window_placement", None)
            if callable(export):
                geometry, state = export()
                try:
                    windows[window_id] = Placement(geometry, state)
                except ValueError:
                    pass
            for key, widget in getattr(window, "_toggle_windows", {}).items():
                rect = _rect(widget)
                if rect is not None:
                    toggles[key] = rect
        toggles.update(self._toggle_notes)
        find = previous.find if previous else None
        panel = getattr(self._service, "_find_replace", None)
        if panel is not None and panel.placement == "detached":
            find = panel.detached_geometry
        return Layout(signature, specs, windows, find, toggles)

    @staticmethod
    def _content(layout: Layout) -> tuple:
        return (layout.windows, layout.find, layout.toggles)

    def _record(self, layout: Layout) -> None:
        current = self._book.get(layout.signature)
        if (
            current is not None
            and self._content(current) == self._content(layout)
            and self._book.active == layout.signature
        ):
            return
        self._book = self._book.with_layout(layout)
        try:
            self._store.save(self._book)
        except Exception:  # noqa: BLE001 -- never let a layout save disturb the UI
            pass

    def _poll(self) -> None:
        if self._settling:
            return
        specs = self._screens_provider()
        if not specs:
            return
        if screen_signature(specs) != self._signature:
            self._begin_settle()  # the screens changed without a signal
            return
        layout = self._snapshot(specs)
        observed = self._content(layout)
        if observed != self._observed:
            self._observed = observed  # still moving; record once it holds
            return
        self._record(layout)

    # -- applying ----------------------------------------------------------

    def _apply(
        self, signature: str, previous_signature: str | None, specs: tuple[ScreenSpec, ...]
    ) -> None:
        known = self._book.get(signature)
        source = (
            None
            if known is not None
            else self._book.get(previous_signature) or self._book.latest(exclude=signature)
        )
        target = tuple((spec.name, spec.geometry) for spec in specs)
        available = self._available_provider()

        def adapted(geometry: Geometry, *, scale_size: bool, frame_top: int = 0) -> Geometry:
            assert source is not None
            return adapt_geometry(
                geometry,
                tuple((spec.name, spec.geometry) for spec in source.screens),
                target,
                scale_size=scale_size,
                target_available=available,
                frame_top=frame_top,
            )

        windows: dict[str, Placement] = {}
        toggles: dict[str, Geometry] = dict(known.toggles) if known else {}
        if source is not None:
            for key, rect in source.toggles.items():
                toggles.setdefault(key, adapted(rect, scale_size=False))
        for window_id, window in self._windows():
            placement = None
            if known is not None:
                placement = known.windows.get(window_id)
            elif source is not None and window_id in source.windows:
                saved = source.windows[window_id]
                placement = Placement(
                    adapted(saved.geometry, scale_size=True, frame_top=NATIVE_TITLE_BAR_HEIGHT),
                    saved.state,
                )
            export = getattr(window, "export_window_placement", None)
            if placement is None and callable(export):
                geometry, state = export()
                placement = Placement(geometry, state)
            apply = getattr(window, "apply_window_placement", None)
            if placement is not None:
                if callable(apply):
                    apply(placement.geometry, placement.state)
                windows[window_id] = placement
            for key, widget in getattr(window, "_toggle_windows", {}).items():
                wanted = toggles.get(key)
                if wanted is not None:
                    wanted = clamp_geometry_to_screens(wanted, available)
                    widget.setGeometry(*wanted)
                    toggles[key] = wanted
                else:
                    rect = _rect(widget)
                    if rect is not None:
                        toggles[key] = rect
        find = known.find if known is not None else None
        if find is None and source is not None and source.find is not None:
            find = adapted(source.find, scale_size=False)
        panel = getattr(self._service, "_find_replace", None)
        if find is not None and panel is not None:
            panel.set_detached_geometry(find)
        self._toggle_notes.clear()
        self._record(Layout(signature, specs, windows, find, toggles))
