import json
from pathlib import Path

import pytest

from uniti.app.setup_state import SetupStateStore, UnsupportedSetupSchema
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


def test_setup_state_round_trips_and_fills_schema_sections(tmp_path: Path):
    path = tmp_path / "setup-state.json"
    store = SetupStateStore(path)
    payload = store.prepare()
    payload["startup"] = {"ok": True, "stage": "READY"}

    store.save(payload)

    loaded = store.prepare()
    assert loaded["startup"] == {"ok": True, "stage": "READY"}
    assert loaded["schemas"] == {"settings": 5, "recovery": 3, "session": 5}
    assert loaded["last_bootstrap"] is None


def test_setup_state_save_exposes_file_synced_durability(tmp_path: Path, monkeypatch):
    expected = _file_synced("atomic_write_json")
    monkeypatch.setattr(
        "uniti.app.setup_state.atomic_write_json",
        lambda _path, _payload: expected,
    )
    store = SetupStateStore(tmp_path / "setup-state.json")

    result = store.save(store.prepare())

    assert result is expected


def test_setup_state_refreshes_supported_schema_versions(tmp_path: Path):
    path = tmp_path / "setup-state.json"
    path.write_text(
        '{"schema":1,"schemas":{"settings":1,"recovery":2,"session":1}}',
        encoding="utf-8",
    )

    loaded = SetupStateStore(path).prepare()

    assert loaded["schemas"] == {"settings": 5, "recovery": 3, "session": 5}


def test_setup_state_preserves_malformed_before_using_defaults(tmp_path: Path):
    path = tmp_path / "setup-state.json"
    path.write_text("broken state", encoding="utf-8")

    payload = SetupStateStore(path).prepare()

    preserved = list(tmp_path.glob("setup-state.json.*.invalid"))
    assert len(preserved) == 1
    assert preserved[0].read_text(encoding="utf-8") == "broken state"
    assert payload["schema"] == 1
    assert json.loads(path.read_text(encoding="utf-8"))["schema"] == 1


def test_setup_state_refuses_future_schema_without_replacing_it(tmp_path: Path):
    path = tmp_path / "setup-state.json"
    original = '{"schema": 2}'
    path.write_text(original, encoding="utf-8")

    with pytest.raises(UnsupportedSetupSchema, match="schema 2"):
        SetupStateStore(path).prepare()

    assert path.read_text(encoding="utf-8") == original


def test_future_setup_schema_never_invokes_the_writer(tmp_path: Path, monkeypatch):
    path = tmp_path / "setup-state.json"
    original = '{"schema":2}'
    path.write_text(original, encoding="utf-8")
    writes: list[object] = []
    monkeypatch.setattr(
        "uniti.app.setup_state.atomic_write_json",
        lambda *_args, **_kwargs: writes.append(object()) or _file_synced("write"),
    )

    with pytest.raises(UnsupportedSetupSchema, match="schema 2"):
        SetupStateStore(path).prepare()

    assert writes == []
    assert path.read_text(encoding="utf-8") == original
