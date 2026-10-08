"""Each environment's window names (field test round 3, T3, D4)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniti.app.environment_window_names import EnvironmentWindowNames, default_window_name


def test_default_names_are_letters():
    assert [default_window_name(slot) for slot in (0, 1, 2, 25, 26, 27, 51, 52)] == [
        "A", "B", "C", "Z", "AA", "AB", "AZ", "BA"
    ]


def test_a_renamed_slot_keeps_its_name_per_environment(tmp_path: Path):
    names = EnvironmentWindowNames(lambda key: tmp_path / key)

    names.rename("usfm", 1, "Compare")

    assert names.names("usfm", 3) == ["A", "Compare", "C"]
    assert names.names("plain_text", 2) == ["A", "B"]  # each environment its own
    saved = json.loads((tmp_path / "usfm" / "windows.json").read_text(encoding="utf-8"))
    assert saved == {"schema": 1, "names": {"1": "Compare"}}
    assert EnvironmentWindowNames(lambda key: tmp_path / key).name("usfm", 1) == "Compare"

    names.set_names("usfm", ["Draft", "B"])  # back to the default for slot 1
    assert names.names("usfm", 3) == ["Draft", "B", "C"]


def test_names_are_validated_and_unique(tmp_path: Path):
    names = EnvironmentWindowNames(lambda key: tmp_path / key)

    with pytest.raises(ValueError):
        names.rename("usfm", 0, "  ")
    with pytest.raises(ValueError):
        names.rename("usfm", 0, "B")  # slot 1 is already "B"
    with pytest.raises(ValueError):
        names.rename("usfm", 0, "x" * 33)
    assert names.name("usfm", 0) == "A"


def test_a_damaged_file_gives_the_default_names(tmp_path: Path):
    (tmp_path / "usfm").mkdir()
    (tmp_path / "usfm" / "windows.json").write_text("{not json", encoding="utf-8")

    assert EnvironmentWindowNames(lambda key: tmp_path / key).name("usfm", 0) == "A"
