import json
from pathlib import Path

import pytest

from uniti.app.settings import (
    Settings,
    SettingsStore,
    UnsupportedSettingsSchema,
)


def test_settings_store_defaults_when_missing(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load() == Settings()


def test_settings_store_round_trips_and_replaces_atomically(tmp_path: Path):
    path = tmp_path / "config" / "settings.json"
    store = SettingsStore(path)
    settings = Settings(
        last_directory=str(tmp_path / "docs"),
        performance_mode="Automatic",
        editor_zoom_percent=130,
        soft_wrap=True,
    )
    store.save(settings)
    assert store.load() == settings
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["last_directory"] == str(tmp_path / "docs")
    assert payload["editor_zoom_percent"] == 130
    assert payload["soft_wrap"] is True
    assert not list(path.parent.glob("*.tmp"))


def test_settings_reject_invalid_editor_view_state(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"schema":1,"editor_zoom_percent":999,"soft_wrap":"yes"}',
        encoding="utf-8",
    )

    settings = SettingsStore(path).load()

    assert settings.editor_zoom_percent == 100
    assert settings.soft_wrap is False


def test_find_replace_view_state_round_trips(tmp_path: Path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    expected = Settings(
        find_replace_zoom_percent=140,
        find_replace_report_location="Right",
        find_replace_geometry=(20, 30, 700, 360),
    )

    store.save(expected)

    assert store.load() == expected


def test_settings_store_ignores_unknown_keys_for_forward_compatibility(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text('{"last_directory":"/tmp","future":42}', encoding="utf-8")
    assert SettingsStore(path).load().last_directory == "/tmp"


def test_settings_store_invalid_json_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("not-json", encoding="utf-8")
    assert SettingsStore(path).load() == Settings()


def test_prepare_migrates_legacy_settings_to_schema_one(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"last_directory":"/tmp","performance_mode":"Automatic"}',
        encoding="utf-8",
    )

    result = SettingsStore(path).prepare()

    assert result.migrated is True
    assert result.preserved_path is None
    assert result.settings.last_directory == "/tmp"
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == 1


def test_prepare_preserves_malformed_before_writing_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("broken", encoding="utf-8")

    result = SettingsStore(path).prepare()

    assert result.migrated is True
    assert result.preserved_path is not None
    assert result.preserved_path.read_text(encoding="utf-8") == "broken"
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "editor_zoom_percent": 100,
        "find_replace_geometry": None,
        "find_replace_report_location": "Bottom",
        "find_replace_zoom_percent": 100,
        "last_directory": None,
        "performance_mode": "Automatic",
        "schema": 1,
        "soft_wrap": False,
    }


def test_prepare_refuses_future_schema_without_replacing_it(tmp_path: Path):
    path = tmp_path / "settings.json"
    original = '{"schema":9,"last_directory":null}'
    path.write_text(original, encoding="utf-8")

    with pytest.raises(UnsupportedSettingsSchema, match="schema 9"):
        SettingsStore(path).prepare()

    assert path.read_text(encoding="utf-8") == original
