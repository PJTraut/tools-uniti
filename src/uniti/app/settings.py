"""Small atomic JSON settings store for UNITI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .atomic_json import atomic_write_json, preserve_invalid

SETTINGS_SCHEMA = 1


class UnsupportedSettingsSchema(ValueError):
    """Raised when settings belong to a newer UNITI schema."""


@dataclass(frozen=True, slots=True)
class Settings:
    last_directory: str | None = None
    performance_mode: str = "Automatic"
    editor_zoom_percent: int = 100
    soft_wrap: bool = False


@dataclass(frozen=True, slots=True)
class SettingsPreparation:
    migrated: bool
    preserved_path: Path | None
    settings: Settings


def _settings_from_payload(payload: object) -> Settings:
    if not isinstance(payload, dict):
        raise ValueError("settings must be a JSON object")
    schema = payload.get("schema", 0)
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 0:
        raise ValueError("settings schema must be a non-negative integer")
    if schema > SETTINGS_SCHEMA:
        raise UnsupportedSettingsSchema(f"unsupported settings schema {schema}")
    last_directory = payload.get("last_directory")
    if last_directory is not None and not isinstance(last_directory, str):
        last_directory = None
    performance_mode = payload.get("performance_mode", "Automatic")
    if performance_mode not in {"Conservative", "Automatic", "Maximum Performance"}:
        performance_mode = "Automatic"
    editor_zoom_percent = payload.get("editor_zoom_percent", 100)
    if (
        not isinstance(editor_zoom_percent, int)
        or isinstance(editor_zoom_percent, bool)
        or not 50 <= editor_zoom_percent <= 300
    ):
        editor_zoom_percent = 100
    soft_wrap = payload.get("soft_wrap", False)
    if not isinstance(soft_wrap, bool):
        soft_wrap = False
    return Settings(
        last_directory=last_directory,
        performance_mode=performance_mode,
        editor_zoom_percent=editor_zoom_percent,
        soft_wrap=soft_wrap,
    )


def _payload(settings: Settings) -> dict[str, object]:
    return {"schema": SETTINGS_SCHEMA, **asdict(settings)}


class SettingsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> Settings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return _settings_from_payload(payload)
        except UnsupportedSettingsSchema:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return Settings()

    def prepare(self) -> SettingsPreparation:
        if not self.path.exists():
            settings = Settings()
            self.save(settings)
            return SettingsPreparation(True, None, settings)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            settings = _settings_from_payload(payload)
        except UnsupportedSettingsSchema:
            raise
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            preserved = preserve_invalid(self.path)
            settings = Settings()
            self.save(settings)
            return SettingsPreparation(True, preserved, settings)
        schema = payload.get("schema", 0)
        migrated = schema == 0
        if migrated:
            self.save(settings)
        return SettingsPreparation(migrated, None, settings)

    def save(self, settings: Settings) -> None:
        atomic_write_json(self.path, _payload(settings))
