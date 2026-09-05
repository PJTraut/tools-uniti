"""Versioned setup and startup state persistence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

from uniti.core.recovery import RECOVERY_FORMAT_VERSION

from .atomic_json import atomic_write_json, preserve_invalid
from .session import SESSION_SCHEMA
from .settings import SETTINGS_SCHEMA

SETUP_STATE_SCHEMA = 1


class UnsupportedSetupSchema(ValueError):
    """Raised when state belongs to a newer UNITI schema."""


def _supported_schemas() -> dict[str, int]:
    return {
        "settings": SETTINGS_SCHEMA,
        "recovery": RECOVERY_FORMAT_VERSION,
        "session": SESSION_SCHEMA,
    }


def empty_setup_state() -> dict[str, object]:
    return {
        "schema": SETUP_STATE_SCHEMA,
        "uniti": {},
        "startup": {},
        "install": {},
        "python": {},
        "platform": {},
        "dependencies": {},
        "schemas": _supported_schemas(),
        "resources": {},
        "capabilities": {},
        "session_id": None,
        "last_bootstrap": None,
        "last_startup_attempt": None,
        "last_successful_startup": None,
    }


class SetupStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def prepare(self) -> dict[str, object]:
        if not self.path.exists():
            return empty_setup_state()
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as error:
            if isinstance(error, OSError):
                raise
            preserve_invalid(self.path)
            defaults = empty_setup_state()
            self.save(defaults)
            return defaults
        if not isinstance(payload, dict):
            preserve_invalid(self.path)
            defaults = empty_setup_state()
            self.save(defaults)
            return defaults
        schema = payload.get("schema")
        if isinstance(schema, int) and schema > SETUP_STATE_SCHEMA:
            raise UnsupportedSetupSchema(f"unsupported setup-state schema {schema}")
        if schema != SETUP_STATE_SCHEMA:
            preserve_invalid(self.path)
            defaults = empty_setup_state()
            self.save(defaults)
            return defaults
        merged = empty_setup_state()
        merged.update(payload)
        merged["schemas"] = _supported_schemas()
        return merged

    def save(self, payload: Mapping[str, object]) -> None:
        schema = payload.get("schema")
        if schema != SETUP_STATE_SCHEMA:
            raise UnsupportedSetupSchema(f"unsupported setup-state schema {schema}")
        atomic_write_json(self.path, payload)
