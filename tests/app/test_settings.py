import json
from pathlib import Path

import pytest

from uniti.app.settings import (
    Settings,
    SettingsStore,
    UnsupportedSettingsSchema,
)
from uniti.core.durability import DurabilityLevel, DurabilityResult


def _file_synced(operation: str) -> DurabilityResult:
    return DurabilityResult(
        operation,
        DurabilityLevel.FILE_SYNCED,
        True,
        True,
        False,
        "directory_sync_unavailable",
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
    assert payload["schema"] == 3
    assert payload["last_directory"] == str(tmp_path / "docs")
    assert payload["editor_zoom_percent"] == 130
    assert payload["soft_wrap"] is True
    assert not list(path.parent.glob("*.tmp"))


def test_settings_save_exposes_file_synced_durability(tmp_path: Path, monkeypatch):
    expected = _file_synced("atomic_write_json")
    monkeypatch.setattr(
        "uniti.app.settings.atomic_write_json",
        lambda _path, _payload: expected,
    )

    result = SettingsStore(tmp_path / "settings.json").save(Settings())

    assert result is expected


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


def test_legacy_bottom_report_setting_migrates_to_right(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"schema":1,"find_replace_report_location":"Bottom"}',
        encoding="utf-8",
    )

    assert SettingsStore(path).load().find_replace_report_location == "Right"


def test_theme_mode_round_trips_and_invalid_values_fall_back_to_system(
    tmp_path: Path,
):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    store.save(Settings(theme_mode="Dark"))
    assert store.load().theme_mode == "Dark"

    path.write_text('{"schema":1,"theme_mode":"Neon"}', encoding="utf-8")
    assert store.load().theme_mode == "System"


def test_shortcut_overrides_round_trip_and_invalid_entries_are_dropped(tmp_path: Path):
    path = tmp_path / "settings.json"
    store = SettingsStore(path)
    store.save(Settings(shortcut_overrides={"editor.zoom_in": "Ctrl+K"}))
    assert store.load().shortcut_overrides == {"editor.zoom_in": "Ctrl+K"}

    path.write_text(
        '{"schema":1,"shortcut_overrides":{"ok":"Ctrl+K","bad":42}}',
        encoding="utf-8",
    )
    assert store.load().shortcut_overrides == {"ok": "Ctrl+K"}


def test_settings_store_ignores_unknown_keys_for_forward_compatibility(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text('{"last_directory":"/tmp","future":42}', encoding="utf-8")
    assert SettingsStore(path).load().last_directory == "/tmp"


def test_settings_store_invalid_json_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("not-json", encoding="utf-8")
    assert SettingsStore(path).load() == Settings()


def test_prepare_migrates_legacy_settings_to_current_schema(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"last_directory":"/tmp","performance_mode":"Automatic"}',
        encoding="utf-8",
    )

    result = SettingsStore(path).prepare()

    assert result.migrated is True
    assert result.preserved_path is None
    assert result.settings.last_directory == "/tmp"
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == 3


def test_prepare_migrates_schema_one_panel_values_with_current_defaults(
    tmp_path: Path,
):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "schema": 1,
                "find_replace_zoom_percent": 140,
                "find_replace_report_location": "Hidden",
                "find_replace_geometry": [20, 30, 700, 360],
            }
        ),
        encoding="utf-8",
    )

    result = SettingsStore(path).prepare()

    assert result.migrated is True
    assert result.settings.find_replace_zoom_percent == 140
    assert result.settings.find_replace_report_location == "Hidden"
    assert result.settings.find_replace_geometry == (20, 30, 700, 360)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema"] == 3
    assert payload["find_replace_zoom_percent"] == 140
    assert payload["find_replace_report_location"] == "Hidden"
    assert payload["find_replace_geometry"] == [20, 30, 700, 360]


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
        "find_replace_report_location": "Right",
        "find_replace_zoom_percent": 100,
        "last_directory": None,
        "performance_mode": "Automatic",
        "schema": 3,
        "shortcut_overrides": {},
        "soft_wrap": False,
        "theme_contrast": "Standard",
        "theme_mode": "System",
        "whitespace_mode": "off",
    }


def test_schema_two_settings_migrate_visibility_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text('{"schema":2,"theme_mode":"Dark"}', encoding="utf-8")

    prepared = SettingsStore(path).prepare()

    assert prepared.migrated is True
    assert prepared.settings.theme_mode == "Dark"
    assert prepared.settings.theme_contrast == "Standard"
    assert prepared.settings.whitespace_mode == "off"
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == 3


def test_invalid_new_fields_do_not_erase_valid_theme_mode(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text(
        '{"schema":3,"theme_mode":"Light","theme_contrast":"Extreme",'
        '"whitespace_mode":"everything"}',
        encoding="utf-8",
    )

    loaded = SettingsStore(path).load()

    assert loaded.theme_mode == "Light"
    assert loaded.theme_contrast == "Standard"
    assert loaded.whitespace_mode == "off"


def test_prepare_refuses_future_schema_without_replacing_it(tmp_path: Path):
    path = tmp_path / "settings.json"
    original = '{"schema":9,"last_directory":null}'
    path.write_text(original, encoding="utf-8")

    with pytest.raises(UnsupportedSettingsSchema, match="schema 9"):
        SettingsStore(path).prepare()

    assert path.read_text(encoding="utf-8") == original


def test_future_settings_schema_never_invokes_the_writer(tmp_path: Path, monkeypatch):
    path = tmp_path / "settings.json"
    original = '{"schema":9,"last_directory":null}'
    path.write_text(original, encoding="utf-8")
    writes: list[object] = []
    monkeypatch.setattr(
        "uniti.app.settings.atomic_write_json",
        lambda *_args, **_kwargs: writes.append(object()) or _file_synced("write"),
    )

    with pytest.raises(UnsupportedSettingsSchema, match="schema 9"):
        SettingsStore(path).prepare()

    assert writes == []
    assert path.read_text(encoding="utf-8") == original
