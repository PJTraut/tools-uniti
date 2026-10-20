"""Qt-free window layouts per screen configuration, and their atomic storage.

A saved window position is only meaningful for the screens it was saved on.
This keeps one `Layout` per screen configuration (the set of connected
screens with their sizes, origins and scale), so reconnecting a known set of
monitors can put every floating window back where it was, and a new set can
start from the most recent layout adapted to it (`screen_geometry.adapt_geometry`).

At most `MAX_LAYOUTS` configurations are kept, least recently recorded
dropped first: virtual screens (screen sharing, remote desktop, Sidecar) show
up as extra screens and would otherwise pile up.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

from .atomic_json import atomic_write_json

Geometry = tuple[int, int, int, int]

SCHEMA = 1
MAX_LAYOUTS = 8
MAX_SCREENS = 16
MAX_WINDOWS = 64
MAX_TOGGLES = 32
MAX_NAME_LENGTH = 256
MAX_BYTES = 256 * 1024
_COORDINATE_LIMIT = 10_000_000
WINDOW_STATES = frozenset({"normal", "maximized", "fullscreen", "minimized"})


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


def _geometry(value: object) -> Geometry:
    if (
        not isinstance(value, (list, tuple))
        or len(value) != 4
        or any(type(item) is not int for item in value)
    ):
        raise ValueError("geometry must be four integers")
    x, y, width, height = value
    if width <= 0 or height <= 0:
        raise ValueError("geometry width and height must be positive")
    if abs(x) > _COORDINATE_LIMIT or abs(y) > _COORDINATE_LIMIT:
        raise ValueError("geometry origin is outside the supported range")
    if width > _COORDINATE_LIMIT or height > _COORDINATE_LIMIT:
        raise ValueError("geometry size is outside the supported range")
    return (x, y, width, height)


@dataclass(frozen=True, slots=True)
class ScreenSpec:
    """One connected screen: an identity string (name, maker, model and
    serial where the platform gives them), its full geometry and its scale."""

    name: str
    geometry: Geometry
    scale: float = 1.0

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or len(self.name) > MAX_NAME_LENGTH:
            raise ValueError("screen name must be a short string")
        object.__setattr__(self, "geometry", _geometry(self.geometry))
        if (
            isinstance(self.scale, bool)
            or not isinstance(self.scale, (int, float))
            or not 0.1 <= self.scale <= 16
        ):
            raise ValueError("screen scale is out of range")
        object.__setattr__(self, "scale", float(self.scale))

    def as_dict(self) -> dict:
        return dict(name=self.name, geometry=list(self.geometry), scale=self.scale)

    @classmethod
    def from_payload(cls, payload: object) -> "ScreenSpec":
        if not isinstance(payload, dict) or set(payload) != {"name", "geometry", "scale"}:
            raise ValueError("invalid screen entry")
        return cls(payload["name"], _geometry(payload["geometry"]), payload["scale"])


def screen_signature(screens: tuple[ScreenSpec, ...]) -> str:
    """A stable identifier of a screen configuration: independent of the
    order the platform lists the screens in, different when any screen's
    identity, origin, size or scale differs (saved coordinates are absolute,
    so a rearranged or rescaled setup is a different configuration)."""

    parts = sorted(
        (spec.name, *spec.geometry, round(spec.scale, 3)) for spec in screens
    )
    return hashlib.sha1(repr(parts).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class Placement:
    """A main window's saved rectangle (its normal one, even when the window
    is maximized) and window state."""

    geometry: Geometry
    state: str = "normal"

    def __post_init__(self) -> None:
        object.__setattr__(self, "geometry", _geometry(self.geometry))
        if self.state not in WINDOW_STATES:
            raise ValueError("window state is invalid")

    def as_dict(self) -> dict:
        return dict(geometry=list(self.geometry), state=self.state)

    @classmethod
    def from_payload(cls, payload: object) -> "Placement":
        if not isinstance(payload, dict) or set(payload) != {"geometry", "state"}:
            raise ValueError("invalid window placement")
        return cls(_geometry(payload["geometry"]), payload["state"])


@dataclass(frozen=True, slots=True)
class Layout:
    """Where everything floating was on one screen configuration."""

    signature: str
    screens: tuple[ScreenSpec, ...]
    windows: dict[str, Placement] = field(default_factory=dict)
    find: Geometry | None = None
    toggles: dict[str, Geometry] = field(default_factory=dict)
    serial: int = 0

    def __post_init__(self) -> None:
        if not isinstance(self.signature, str) or not self.signature:
            raise ValueError("layout signature must be a non-empty string")
        if not self.screens or len(self.screens) > MAX_SCREENS:
            raise ValueError("layout needs between one and sixteen screens")
        if len(self.windows) > MAX_WINDOWS or len(self.toggles) > MAX_TOGGLES:
            raise ValueError("layout has too many windows")
        for window_id, placement in self.windows.items():
            if not isinstance(window_id, str) or not window_id or len(window_id) > MAX_NAME_LENGTH:
                raise ValueError("window ID must be a short non-empty string")
            if not isinstance(placement, Placement):
                raise TypeError("windows must map to Placement values")
        for key, geometry in self.toggles.items():
            if not isinstance(key, str) or not key or len(key) > MAX_NAME_LENGTH:
                raise ValueError("toggle window key must be a short non-empty string")
            _geometry(geometry)
        if self.find is not None:
            _geometry(self.find)
        if type(self.serial) is not int or self.serial < 0:
            raise ValueError("layout serial must be a non-negative integer")

    def as_dict(self) -> dict:
        return dict(
            signature=self.signature,
            serial=self.serial,
            screens=[screen.as_dict() for screen in self.screens],
            windows={key: value.as_dict() for key, value in self.windows.items()},
            find=None if self.find is None else list(self.find),
            toggles={key: list(value) for key, value in self.toggles.items()},
        )

    @classmethod
    def from_payload(cls, payload: object) -> "Layout":
        fields = {"signature", "serial", "screens", "windows", "find", "toggles"}
        if not isinstance(payload, dict) or set(payload) != fields:
            raise ValueError("invalid layout entry")
        if not isinstance(payload["screens"], list):
            raise ValueError("invalid layout screens")
        if not isinstance(payload["windows"], dict) or not isinstance(payload["toggles"], dict):
            raise ValueError("invalid layout windows")
        return cls(
            signature=payload["signature"],
            serial=payload["serial"],
            screens=tuple(ScreenSpec.from_payload(item) for item in payload["screens"]),
            windows={
                key: Placement.from_payload(value) for key, value in payload["windows"].items()
            },
            find=None if payload["find"] is None else _geometry(payload["find"]),
            toggles={key: _geometry(value) for key, value in payload["toggles"].items()},
        )


@dataclass(frozen=True, slots=True)
class LayoutBook:
    """The remembered layouts, plus the configuration the last recording was
    made under (`active`): at startup, a different current configuration
    means the screens changed while UNITI was closed."""

    layouts: tuple[Layout, ...] = ()
    active: str | None = None

    def get(self, signature: str | None) -> Layout | None:
        return next((item for item in self.layouts if item.signature == signature), None)

    def latest(self, exclude: str | None = None) -> Layout | None:
        candidates = [item for item in self.layouts if item.signature != exclude]
        return max(candidates, key=lambda item: item.serial, default=None)

    @property
    def serial(self) -> int:
        return max((item.serial for item in self.layouts), default=0)

    def with_layout(self, layout: Layout) -> "LayoutBook":
        """Record `layout` as the newest for its configuration and make that
        configuration the active one, dropping the oldest layouts past
        `MAX_LAYOUTS`."""

        stamped = replace(layout, serial=self.serial + 1)
        kept = [item for item in self.layouts if item.signature != layout.signature]
        kept.append(stamped)
        kept.sort(key=lambda item: item.serial)
        return LayoutBook(tuple(kept[-MAX_LAYOUTS:]), layout.signature)

    def with_active(self, signature: str | None) -> "LayoutBook":
        return replace(self, active=signature)


class WindowLayoutStore:
    """Published in ONE atomic JSON replacement. Loading never repairs or
    writes a damaged file; it reads as an empty book."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> LayoutBook:
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Window layouts file is too large")
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if (
                not isinstance(payload, dict)
                or set(payload) != {"schema", "active", "layouts"}
                or type(payload["schema"]) is not int
                or payload["schema"] != SCHEMA
                or not isinstance(payload["layouts"], list)
                or len(payload["layouts"]) > MAX_LAYOUTS
                or not (payload["active"] is None or isinstance(payload["active"], str))
            ):
                raise ValueError("Unsupported window layouts schema")
            layouts = tuple(Layout.from_payload(item) for item in payload["layouts"])
            if len({item.signature for item in layouts}) != len(layouts):
                raise ValueError("Duplicate layout signature")
            return LayoutBook(layouts, payload["active"])
        except FileNotFoundError:
            return LayoutBook()
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            return LayoutBook()

    def save(self, book: LayoutBook):
        if len(book.layouts) > MAX_LAYOUTS:
            raise ValueError(f"At most {MAX_LAYOUTS} layouts are supported")
        return atomic_write_json(
            self.path,
            dict(
                schema=SCHEMA,
                active=book.active,
                layouts=[layout.as_dict() for layout in book.layouts],
            ),
        )


__all__ = [
    "Layout",
    "LayoutBook",
    "MAX_LAYOUTS",
    "Placement",
    "ScreenSpec",
    "WindowLayoutStore",
    "screen_signature",
]
