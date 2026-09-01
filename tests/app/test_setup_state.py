import json
from pathlib import Path

import pytest

from uniti.app.setup_state import SetupStateStore, UnsupportedSetupSchema


def test_setup_state_round_trips_and_fills_schema_sections(tmp_path: Path):
    path = tmp_path / "setup-state.json"
    store = SetupStateStore(path)
    payload = store.prepare()
    payload["startup"] = {"ok": True, "stage": "READY"}

    store.save(payload)

    loaded = store.prepare()
    assert loaded["startup"] == {"ok": True, "stage": "READY"}
    assert loaded["schemas"] == {"settings": 1, "recovery": 2, "session": 1}
    assert loaded["last_bootstrap"] is None


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
