import json
from pathlib import Path

from uniti.app.settings import Settings, SettingsStore


def test_settings_store_defaults_when_missing(tmp_path: Path):
    store = SettingsStore(tmp_path / "settings.json")
    assert store.load() == Settings()


def test_settings_store_round_trips_and_replaces_atomically(tmp_path: Path):
    path = tmp_path / "config" / "settings.json"
    store = SettingsStore(path)
    settings = Settings(last_directory=str(tmp_path / "docs"), performance_mode="Automatic")
    store.save(settings)
    assert store.load() == settings
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["last_directory"] == str(tmp_path / "docs")
    assert not list(path.parent.glob("*.tmp"))


def test_settings_store_ignores_unknown_keys_for_forward_compatibility(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text('{"last_directory":"/tmp","future":42}', encoding="utf-8")
    assert SettingsStore(path).load().last_directory == "/tmp"


def test_settings_store_invalid_json_falls_back_to_defaults(tmp_path: Path):
    path = tmp_path / "settings.json"
    path.write_text("not-json", encoding="utf-8")
    assert SettingsStore(path).load() == Settings()
