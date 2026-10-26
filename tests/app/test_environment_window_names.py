"""Each environment's window names (field test round 3, T3, D4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniti.app.environment_window_names import EnvironmentWindowNames, default_window_name


def test_default_names_are_numbers_without_zero():
    assert [default_window_name(slot) for slot in (0, 1, 2, 8, 9, 10, 17, 18)] == [
        "1", "2", "3", "9", "11", "12", "19", "21"
    ]


def test_a_renamed_slot_keeps_its_name_per_environment(tmp_path: Path):
    names = EnvironmentWindowNames(lambda key: tmp_path / key)

    names.rename("usfm", 1, "Compare")

    assert names.names("usfm", 3) == ["1", "Compare", "3"]
    assert names.names("plain_text", 2) == ["1", "2"]  # each environment its own
    saved = json.loads((tmp_path / "usfm" / "windows.json").read_text(encoding="utf-8"))
    assert saved == {"schema": 1, "names": {"1": "Compare"}}
    assert EnvironmentWindowNames(lambda key: tmp_path / key).name("usfm", 1) == "Compare"

    names.set_names("usfm", ["Draft", "2"])  # back to the default for slot 1
    assert names.names("usfm", 3) == ["Draft", "2", "3"]


def test_names_are_validated_and_unique(tmp_path: Path):
    names = EnvironmentWindowNames(lambda key: tmp_path / key)

    with pytest.raises(ValueError):
        names.rename("usfm", 0, "  ")
    with pytest.raises(ValueError):
        names.rename("usfm", 0, "2")  # slot 1 is already "2"
    with pytest.raises(ValueError):
        names.rename("usfm", 0, "x" * 33)
    assert names.name("usfm", 0) == "1"


def test_a_damaged_file_gives_the_default_names(tmp_path: Path):
    (tmp_path / "usfm").mkdir()
    (tmp_path / "usfm" / "windows.json").write_text("{not json", encoding="utf-8")

    assert EnvironmentWindowNames(lambda key: tmp_path / key).name("usfm", 0) == "1"
