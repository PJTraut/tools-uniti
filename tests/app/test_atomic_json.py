import json
import stat
from datetime import UTC, datetime
from pathlib import Path

from uniti.app.atomic_json import atomic_write_bytes, atomic_write_json, preserve_invalid


def test_atomic_write_json_replaces_payload_and_leaves_no_temporary_file(tmp_path: Path):
    path = tmp_path / "state" / "record.json"

    atomic_write_json(path, {"value": 7})

    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 7}
    assert not list(path.parent.glob(".record.json.*.tmp"))


def test_preserve_invalid_copies_original_with_stable_timestamp(tmp_path: Path):
    path = tmp_path / "record.json"
    path.write_bytes(b"not-json\n")

    preserved = preserve_invalid(path, now=datetime(2026, 9, 1, 12, 30, tzinfo=UTC))

    assert preserved.name == "record.json.20260901T123000000000Z.invalid"
    assert preserved.read_bytes() == b"not-json\n"
    assert path.read_bytes() == b"not-json\n"


def test_atomic_write_bytes_replaces_exact_payload_with_user_only_mode(tmp_path: Path):
    path = tmp_path / "state" / "pack.bin"

    atomic_write_bytes(path, b"\x00history\xff")

    assert path.read_bytes() == b"\x00history\xff"
    assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    assert not list(path.parent.glob(".pack.bin.*.tmp"))
