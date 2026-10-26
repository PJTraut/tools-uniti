"""Each environment's names for its windows (field test round 3, T3, D4).

An environment window is (environment, slot): slot 0 is the environment's
first window, 1 its second, and so on. By default a slot is named by a
number (1, 2, … 9), so the windows are "SFM-1", "SFM-2"; an
environment has at most nine windows (field test 2026-10-26).
The user can rename a slot; the name then belongs to that slot for that
environment. Renamed slots are stored as `windows.json` in the environment's
user configuration folder, next to its `groups.json`.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from .atomic_json import atomic_write_json

WINDOWS_FILE = "windows.json"
MAX_NAME_LENGTH = 32
MAX_SLOTS = 256
MAX_ENV_WINDOWS = 9  # windows per environment: "SFM-1" … "SFM-9" (field test 2026-10-26)
MAX_BYTES = 64 * 1024


def default_window_name(slot: int) -> str:
    """1, 2, … 9, 11, 12, … 19, 21, … for slots 0, 1, … 8, 9, 10, … (no zero)."""

    if slot < 0:
        raise ValueError("window slot must not be negative")
    digits = ""
    number = slot + 1
    while number:
        number, remainder = divmod(number - 1, 9)
        digits = str(remainder + 1) + digits
    return digits


def validate_window_name(name: str) -> str:
    name = name.strip() if isinstance(name, str) else ""
    if not name or len(name) > MAX_NAME_LENGTH or not name.isprintable():
        raise ValueError(f"A window name must be 1-{MAX_NAME_LENGTH} printable characters")
    return name


class EnvironmentWindowNames:
    """The names of each environment's window slots.

    `folder_for(environment_key)` is the environment's configuration folder;
    with no folder the names live in memory only.
    """

    def __init__(self, folder_for: Callable[[str], Path | None] | None = None) -> None:
        self._folder_for = folder_for
        self._cache: dict[str, dict[int, str]] = {}

    def path(self, environment_key: str) -> Path | None:
        folder = None if self._folder_for is None else self._folder_for(environment_key)
        return None if folder is None else Path(folder) / WINDOWS_FILE

    def renamed(self, environment_key: str) -> dict[int, str]:
        """The slots the user renamed, and their names."""

        cached = self._cache.get(environment_key)
        if cached is None:
            cached = self._cache[environment_key] = self._load(environment_key)
        return dict(cached)

    def name(self, environment_key: str, slot: int) -> str:
        return self.renamed(environment_key).get(slot) or default_window_name(slot)

    def names(self, environment_key: str, count: int) -> list[str]:
        """The names of the first `count` slots."""

        return [self.name(environment_key, slot) for slot in range(count)]

    def rename(self, environment_key: str, slot: int, name: str) -> None:
        names = self.renamed(environment_key)
        names[slot] = validate_window_name(name)
        self.save(environment_key, names)

    def set_names(self, environment_key: str, names: list[str]) -> None:
        """Name slots 0, 1, … in order (Manage Groups…); slots past the
        list keep their default names."""

        self.save(environment_key, dict(enumerate(names)))

    def save(self, environment_key: str, names: Mapping[int, str]) -> None:
        cleaned: dict[int, str] = {}
        for slot, name in names.items():
            if not isinstance(slot, int) or not 0 <= slot < MAX_SLOTS:
                raise ValueError("window slot out of range")
            name = validate_window_name(name)
            if name != default_window_name(slot):
                cleaned[slot] = name
        # Every slot's name, renamed or default, must differ from the others.
        renamed = [name.casefold() for name in cleaned.values()]
        defaults = {default_window_name(slot).casefold() for slot in range(MAX_SLOTS) if slot not in cleaned}
        if len(set(renamed)) != len(renamed) or defaults.intersection(renamed):
            raise ValueError("Window names must be different")
        path = self.path(environment_key)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, {"schema": 1, "names": {str(slot): name for slot, name in sorted(cleaned.items())}})
        self._cache[environment_key] = cleaned

    def _load(self, environment_key: str) -> dict[int, str]:
        path = self.path(environment_key)
        if path is None:
            return {}
        try:
            with path.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                return {}
            payload = json.loads(raw)
            if not isinstance(payload, dict) or payload.get("schema") != 1 or not isinstance(payload.get("names"), dict):
                return {}
            names: dict[int, str] = {}
            for slot, name in payload["names"].items():
                number = int(slot)
                if 0 <= number < MAX_SLOTS:
                    names[number] = validate_window_name(name)
            return names
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError, ValueError, TypeError):
            # A damaged file falls back to the default names; it isn't rewritten.
            return {}


__all__ = [
    "EnvironmentWindowNames",
    "MAX_NAME_LENGTH",
    "MAX_ENV_WINDOWS",
    "WINDOWS_FILE",
    "default_window_name",
    "validate_window_name",
]
