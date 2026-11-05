"""Environment settings (N31, 2026-11-05).

Each environment declares its settings in code (`settings_declarations()` on
the environment class): a key, a label, a type (choice, number or on/off), a
default and a one-line description. The user's values live in
`<user data>/Environments/<Environment>/settings.json`, next to the
environment's `groups.json`; only values that differ from the default are
written. An unknown key or a bad value is ignored and noted, and never stops
the environment loading. **Environment Settings…** edits them.

`environment_settings(key)` is what environment code reads: it loads the
file on first use and again whenever the file changes on disk (so editing
`settings.json` as text works too). Qt-free.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .user_config import environment_folder

logger = logging.getLogger(__name__)

SETTINGS_FILE = "settings.json"
MAX_SETTINGS_BYTES = 64 * 1024

# A CHOICE setting any environment may declare: the mode its files open in,
# TEXT_MODE or one of its view providers' keys.
OPENS_IN = "opens_in"
TEXT_MODE = "text"

CHOICE = "choice"
NUMBER = "number"
FLAG = "flag"

SettingValue = str | int | bool


@dataclass(frozen=True, slots=True)
class EnvironmentSetting:
    """One setting an environment declares.

    `choices` are `(value, label)` pairs for a CHOICE; `minimum`/`maximum`
    bound a NUMBER. `section` groups rows in the dialog ("Format Document").
    """

    key: str
    label: str
    kind: str  # CHOICE | NUMBER | FLAG
    default: SettingValue
    description: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    minimum: int = 0
    maximum: int = 99
    section: str = ""

    def accepts(self, value: object) -> bool:
        if self.kind == FLAG:
            return isinstance(value, bool)
        if self.kind == NUMBER:
            return isinstance(value, int) and not isinstance(value, bool) and self.minimum <= value <= self.maximum
        return isinstance(value, str) and value in {choice for choice, _label in self.choices}

    def choice_label(self, value: object) -> str:
        return next((label for choice, label in self.choices if choice == value), str(value))


@dataclass(frozen=True, slots=True)
class EnvironmentSettings:
    """An environment's declarations and the user's values for them.

    `values` holds only the settings that differ from their defaults.
    `notes` lists what was ignored when the file was read.
    """

    declarations: tuple[EnvironmentSetting, ...] = ()
    values: Mapping[str, SettingValue] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def declaration(self, key: str) -> EnvironmentSetting | None:
        return next((setting for setting in self.declarations if setting.key == key), None)

    def get(self, key: str) -> SettingValue:
        if key in self.values:
            return self.values[key]
        setting = self.declaration(key)
        if setting is None:
            raise KeyError(key)
        return setting.default

    def __getitem__(self, key: str) -> SettingValue:
        return self.get(key)

    def as_dict(self) -> dict[str, SettingValue]:
        """Every declared setting with its value in effect."""

        return {setting.key: self.get(setting.key) for setting in self.declarations}

    def with_values(self, values: Mapping[str, object]) -> EnvironmentSettings:
        """These settings with `values` (declared keys, valid values) applied;
        a value equal to its default is dropped, so it isn't written."""

        changed = dict(self.values)
        for key, value in values.items():
            setting = self.declaration(key)
            if setting is None or not setting.accepts(value):
                continue
            if value == setting.default:
                changed.pop(key, None)
            else:
                changed[key] = value  # type: ignore[assignment]
        return EnvironmentSettings(self.declarations, changed, ())

    def restored(self) -> EnvironmentSettings:
        return EnvironmentSettings(self.declarations, {}, ())


def parse_settings(declarations: tuple[EnvironmentSetting, ...], text: str, *, source: str = SETTINGS_FILE) -> EnvironmentSettings:
    """`declarations` with the values in `text` (a `settings.json`)."""

    empty = EnvironmentSettings(declarations)
    if not text.strip():
        return empty
    try:
        payload = json.loads(text)
    except ValueError as exc:
        return EnvironmentSettings(declarations, {}, (f"{source} isn't valid JSON ({exc.msg}, line {exc.lineno}); using the defaults",))
    if not isinstance(payload, dict):
        return EnvironmentSettings(declarations, {}, (f"{source} must hold a JSON object; using the defaults",))
    values: dict[str, SettingValue] = {}
    notes: list[str] = []
    for key, value in payload.items():
        setting = next((s for s in declarations if s.key == key), None)
        if setting is None:
            notes.append(f"unknown setting {key!r} ignored")
        elif not setting.accepts(value):
            notes.append(f"{key}: {value!r} isn't a valid value; using {setting.default!r}")
        elif value != setting.default:
            values[key] = value
    return EnvironmentSettings(declarations, values, tuple(notes))


def settings_path(environment_key: str) -> Path | None:
    """`settings.json` in the environment's user configuration folder."""

    from .catalog import ENVIRONMENTS_BY_KEY

    descriptor = ENVIRONMENTS_BY_KEY.get(environment_key)
    if descriptor is None:
        return None
    folder = environment_folder(descriptor.label)
    return None if folder is None else folder / SETTINGS_FILE


def declarations_for(environment_key: str) -> tuple[EnvironmentSetting, ...]:
    from .catalog import ENVIRONMENTS_BY_KEY

    descriptor = ENVIRONMENTS_BY_KEY.get(environment_key)
    if descriptor is None:
        return ()
    declare = getattr(descriptor.factory, "settings_declarations", None)
    if not callable(declare):
        return ()
    try:
        return tuple(declare())
    except Exception:  # an environment must never break loading
        logger.exception("settings declarations of %r failed", environment_key)
        return ()


def load_settings(declarations: tuple[EnvironmentSetting, ...], path: Path | None) -> EnvironmentSettings:
    if path is None or not declarations:
        return EnvironmentSettings(declarations)
    try:
        if path.stat().st_size > MAX_SETTINGS_BYTES:
            return EnvironmentSettings(declarations, {}, (f"{path.name} is larger than {MAX_SETTINGS_BYTES // 1024} KiB; using the defaults",))
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return EnvironmentSettings(declarations)
    except (OSError, UnicodeDecodeError) as exc:
        return EnvironmentSettings(declarations, {}, (f"couldn't read {path.name} ({exc}); using the defaults",))
    return parse_settings(declarations, text, source=path.name)


def save_settings(settings: EnvironmentSettings, path: Path) -> None:
    """Write the values that differ from their defaults (raises OSError).

    Keys in the file that this version doesn't declare are kept, so an older
    UNITI doesn't drop a newer one's settings."""

    kept: dict[str, object] = {}
    try:
        existing = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            declared = {setting.key for setting in settings.declarations}
            kept = {key: value for key, value in existing.items() if key not in declared}
    except (OSError, ValueError):
        pass
    payload = {**kept, **{setting.key: settings.values[setting.key] for setting in settings.declarations if setting.key in settings.values}}
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
    for key in [key for key in _cache if key[1] == str(path)]:
        del _cache[key]


# --- what environment code reads ------------------------------------------------

_cache: dict[tuple[str, str], tuple[object, EnvironmentSettings]] = {}


def _cache_key(path: Path | None, environment_key: str) -> tuple[str, str]:
    return (environment_key, "" if path is None else str(path))


def _stamp(path: Path | None) -> object:
    if path is None:
        return None
    try:
        status = path.stat()
    except OSError:
        return None
    return (status.st_mtime_ns, status.st_size)


_session: dict[str, EnvironmentSettings] = {}


def store_environment_settings(environment_key: str, settings: EnvironmentSettings) -> Path | None:
    """Make `settings` the ones in effect: written to `settings.json`, or
    kept for this session when there is no user data folder (raises
    OSError). Returns the file written, if any."""

    path = settings_path(environment_key)
    if path is None:
        _session[environment_key] = settings
        return None
    save_settings(settings, path)
    return path


def environment_settings(environment_key: str) -> EnvironmentSettings:
    """The settings in effect for `environment_key`, re-read when its
    `settings.json` changes."""

    path = settings_path(environment_key)
    if path is None and environment_key in _session:
        return _session[environment_key]
    key = _cache_key(path, environment_key)
    stamp = _stamp(path)
    cached = _cache.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    settings = load_settings(declarations_for(environment_key), path)
    for note in settings.notes:
        logger.warning("%s settings: %s", environment_key, note)
    _cache[key] = (stamp, settings)
    return settings


def clear_settings_cache() -> None:
    _cache.clear()
    _session.clear()


__all__ = [
    "CHOICE",
    "FLAG",
    "NUMBER",
    "OPENS_IN",
    "SETTINGS_FILE",
    "TEXT_MODE",
    "EnvironmentSetting",
    "EnvironmentSettings",
    "clear_settings_cache",
    "declarations_for",
    "environment_settings",
    "load_settings",
    "parse_settings",
    "save_settings",
    "settings_path",
    "store_environment_settings",
]
