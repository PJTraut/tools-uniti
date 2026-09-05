import json
import os
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from uniti.app.atomic_json import atomic_write_bytes, atomic_write_json, preserve_invalid
from uniti.core.durability import DurabilityError, DurabilityLevel


class InjectedDurabilityAdapter:
    def __init__(
        self,
        *,
        fail_file_sync: bool = False,
        fail_replace: bool = False,
        directory_synced: bool = True,
        fail_directory_sync: bool = False,
    ) -> None:
        self.fail_file_sync = fail_file_sync
        self.fail_replace = fail_replace
        self.directory_synced = directory_synced
        self.fail_directory_sync = fail_directory_sync
        self.calls = []

    def sync_file(self, descriptor: int) -> None:
        self.calls.append(("sync_file", descriptor))
        if self.fail_file_sync:
            raise OSError("injected file-sync detail")

    def replace(self, source: Path, destination: Path) -> None:
        self.calls.append(("replace", source, destination))
        if self.fail_replace:
            raise OSError("injected replace detail")
        os.replace(source, destination)

    def sync_directory(self, directory: Path) -> bool:
        self.calls.append(("sync_directory", directory))
        if self.fail_directory_sync:
            raise OSError("injected directory-sync detail")
        return self.directory_synced


def test_atomic_write_json_replaces_payload_and_leaves_no_temporary_file(tmp_path: Path):
    path = tmp_path / "state" / "record.json"

    atomic_write_json(path, {"value": 7})

    assert path.read_bytes() == b'{\n  "value": 7\n}\n'
    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 7}
    assert not list(path.parent.glob(".record.json.*.tmp"))


def test_preserve_invalid_copies_original_with_stable_timestamp(tmp_path: Path):
    path = tmp_path / "record.json"
    path.write_bytes(b"not-json\n")

    preserved = preserve_invalid(path, now=datetime(2026, 9, 1, 12, 30, tzinfo=UTC))

    assert preserved.name == "record.json.20260901T123000000000Z.invalid"
    assert preserved.read_bytes() == b"not-json\n"
    assert path.read_bytes() == b"not-json\n"


def test_atomic_write_bytes_replaces_exact_payload_with_platform_mode(tmp_path: Path):
    path = tmp_path / "state" / "pack.bin"

    atomic_write_bytes(path, b"\x00history\xff")

    assert path.read_bytes() == b"\x00history\xff"
    if os.name == "nt":
        assert stat.S_IMODE(path.stat().st_mode) & stat.S_IWRITE
    else:
        assert stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    assert not list(path.parent.glob(".pack.bin.*.tmp"))


def test_atomic_bytes_reports_full_durability(tmp_path: Path):
    path = tmp_path / "state" / "record.bin"
    adapter = InjectedDurabilityAdapter()

    result = atomic_write_bytes(path, b"new bytes", adapter=adapter)

    assert result.level is DurabilityLevel.FULL
    assert result.file_synced is True
    assert result.replaced is True
    assert result.directory_synced is True
    assert path.read_bytes() == b"new bytes"
    assert [call[0] for call in adapter.calls] == [
        "sync_file",
        "replace",
        "sync_directory",
    ]


def test_atomic_json_reports_file_synced_when_directory_sync_is_unavailable(
    tmp_path: Path,
):
    path = tmp_path / "state" / "record.json"
    adapter = InjectedDurabilityAdapter(directory_synced=False)

    result = atomic_write_json(path, {"value": 7}, adapter=adapter)

    assert result.level is DurabilityLevel.FILE_SYNCED
    assert result.reason == "directory_sync_unavailable"
    assert json.loads(path.read_text(encoding="utf-8")) == {"value": 7}


def test_atomic_bytes_file_sync_failure_preserves_destination_and_cleans_temp(
    tmp_path: Path,
):
    path = tmp_path / "state" / "record.bin"
    path.parent.mkdir()
    path.write_bytes(b"original")
    adapter = InjectedDurabilityAdapter(fail_file_sync=True)

    with pytest.raises(DurabilityError) as caught:
        atomic_write_bytes(path, b"replacement", adapter=adapter)

    assert caught.value.result.level is DurabilityLevel.UNSAFE
    assert caught.value.result.file_synced is False
    assert caught.value.result.replaced is False
    assert caught.value.result.reason == "file_sync:OSError"
    assert path.read_bytes() == b"original"
    assert not list(path.parent.glob(".record.bin.*.tmp"))


def test_atomic_bytes_replace_failure_preserves_destination_and_cleans_temp(
    tmp_path: Path,
):
    path = tmp_path / "state" / "record.bin"
    path.parent.mkdir()
    path.write_bytes(b"original")
    adapter = InjectedDurabilityAdapter(fail_replace=True)

    with pytest.raises(DurabilityError) as caught:
        atomic_write_bytes(path, b"replacement", adapter=adapter)

    assert caught.value.result.level is DurabilityLevel.UNSAFE
    assert caught.value.result.file_synced is True
    assert caught.value.result.replaced is False
    assert caught.value.result.reason == "replace:OSError"
    assert path.read_bytes() == b"original"
    assert not list(path.parent.glob(".record.bin.*.tmp"))


def test_atomic_bytes_directory_sync_failure_reports_replaced_file_synced_result(
    tmp_path: Path,
):
    path = tmp_path / "state" / "record.bin"
    path.parent.mkdir()
    path.write_bytes(b"original")
    adapter = InjectedDurabilityAdapter(fail_directory_sync=True)

    result = atomic_write_bytes(path, b"replacement", adapter=adapter)

    assert result.level is DurabilityLevel.FILE_SYNCED
    assert result.file_synced is True
    assert result.replaced is True
    assert result.directory_synced is False
    assert result.reason == "directory_sync:OSError"
    assert path.read_bytes() == b"replacement"
    assert not list(path.parent.glob(".record.bin.*.tmp"))
