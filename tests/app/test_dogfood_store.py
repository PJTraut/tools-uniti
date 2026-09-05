from __future__ import annotations

import gzip
import json
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from uniti.app.dogfood import (
    CPUClass,
    RAMClass,
    DogfoodRecorder,
    HostFacts,
    Operation,
    OSFamily,
    Outcome,
    decode_dogfood_snapshot,
)
from uniti.app.dogfood_store import (
    DogfoodStore,
    StoreFailureCode,
)


HOST = HostFacts(
    "v0.001a22",
    OSFamily.LINUX,
    CPUClass.C5_8,
    RAMClass.GIB_16_31,
)


class RecordingAdapter:
    def __init__(self, *, fail_sync: bool = False) -> None:
        self.fail_sync = fail_sync
        self.calls = []

    def sync_file(self, descriptor: int) -> None:
        self.calls.append(("sync_file", descriptor))
        if self.fail_sync:
            raise OSError("private injected detail")

    def replace(self, source: Path, destination: Path) -> None:
        self.calls.append(("replace", source.name, destination.name))
        os.replace(source, destination)

    def sync_directory(self, directory: Path) -> bool:
        self.calls.append(("sync_directory", directory.name))
        return True


def _snapshot(day: date, *, edits: int = 1):
    recorder = DogfoodRecorder(HOST, day=day)
    recorder.observe(Operation.DOCUMENT_OPEN, Outcome.SUCCESS)
    for _ in range(edits):
        recorder.observe(Operation.EDIT_TRANSACTION, Outcome.SUCCESS)
    recorder.observe(Operation.SAVE, Outcome.SUCCESS)
    return recorder.snapshot()


def test_current_segment_is_bounded_gzip_with_strict_snapshot_validation(
    tmp_path: Path,
):
    store = DogfoodStore(tmp_path / "dogfood")
    snapshot = _snapshot(date(2026, 9, 1))

    result = store.publish(snapshot)

    assert result.published is True
    assert result.diagnostic is None
    assert gzip.decompress(store.current_path.read_bytes())
    assert store.load_segments() == (snapshot,)
    store.current_path.write_bytes(gzip.compress(b'{"schema":NaN}'))
    with pytest.raises(ValueError):
        store.load_segments()


def test_rollover_keeps_one_current_and_one_immutable_segment_per_day(
    tmp_path: Path,
):
    store = DogfoodStore(tmp_path / "dogfood")
    first = _snapshot(date(2026, 9, 1))
    second = _snapshot(date(2026, 9, 2), edits=2)

    assert store.publish(first).published
    assert store.publish(second).published
    assert store.publish(second).published

    assert sorted(path.name for path in store.root.iterdir()) == [
        "current.json.gz",
        "day-2026-09-01.json.gz",
    ]
    assert store.load_segments() == (first, second)


def test_publication_uses_injected_atomic_durability_adapter(tmp_path: Path):
    adapter = RecordingAdapter()
    store = DogfoodStore(tmp_path / "dogfood", adapter=adapter)

    result = store.publish(_snapshot(date(2026, 9, 1)))

    assert result.published is True
    assert [call[0] for call in adapter.calls] == [
        "sync_file",
        "replace",
        "sync_directory",
    ]
    assert not tuple(store.root.glob(".current.json.gz.*.tmp"))


def test_publication_failure_returns_one_bounded_unavailable_diagnostic(
    tmp_path: Path,
):
    adapter = RecordingAdapter(fail_sync=True)
    store = DogfoodStore(tmp_path / "dogfood", adapter=adapter)

    result = store.publish(_snapshot(date(2026, 9, 1)))

    assert result.published is False
    assert result.diagnostic is not None
    assert result.diagnostic.code is StoreFailureCode.WRITE_FAILED
    assert len(result.diagnostic.code.value) < 64
    assert len(adapter.calls) == 1
    assert not store.current_path.exists()


def test_retention_prunes_oldest_completed_days_and_preserves_current(
    tmp_path: Path,
):
    store = DogfoodStore(tmp_path / "dogfood", retention_days=7)
    first = date(2026, 9, 1)

    for offset in range(8):
        assert store.publish(_snapshot(first + timedelta(days=offset))).published

    assert store.current_path.exists()
    names = sorted(path.name for path in store.root.glob("day-*.json.gz"))
    assert names == [
        f"day-{(first + timedelta(days=offset)).isoformat()}.json.gz"
        for offset in range(1, 7)
    ]


def test_aggregate_cap_prunes_oldest_before_admitting_publication(tmp_path: Path):
    root = tmp_path / "dogfood"
    first_store = DogfoodStore(root)
    assert first_store.publish(_snapshot(date(2026, 9, 1))).published
    segment_size = first_store.current_path.stat().st_size
    store = DogfoodStore(root, aggregate_max_bytes=segment_size * 2 + 64)

    for day_number in (2, 3, 4):
        assert store.publish(_snapshot(date(2026, 9, day_number))).published

    assert sum(path.stat().st_size for path in store.root.iterdir()) <= (
        segment_size * 2 + 64
    )
    assert not store.completed_path(date(2026, 9, 1)).exists()
    assert store.current_path.exists()


def test_manual_export_contains_only_valid_sanitized_aggregates(tmp_path: Path):
    store = DogfoodStore(tmp_path / "dogfood")
    first = _snapshot(date(2026, 9, 1))
    second = _snapshot(date(2026, 9, 2))
    store.publish(first)
    store.publish(second)
    destination = tmp_path / "chosen" / "dogfood-export.json"

    store.export(destination)

    payload = json.loads(destination.read_text(encoding="utf-8"))
    assert set(payload) == {"schema", "segments"}
    assert payload["schema"] == 1
    decoded = tuple(
        decode_dogfood_snapshot(
            json.dumps(item, sort_keys=True, separators=(",", ":")).encode("utf-8")
        )
        for item in payload["segments"]
    )
    assert decoded == (first, second)
    text = destination.read_text(encoding="utf-8")
    assert str(store.root) not in text
    assert "document_id" not in text
    assert "expression" not in text


def test_clear_removes_only_resolved_recorder_owned_names(tmp_path: Path):
    store = DogfoodStore(tmp_path / "dogfood")
    store.publish(_snapshot(date(2026, 9, 1)))
    store.publish(_snapshot(date(2026, 9, 2)))
    unrelated = store.root / "keep-me.json.gz"
    unrelated.write_bytes(b"keep")
    outside = tmp_path / "outside.json.gz"
    outside.write_bytes(b"outside")
    linked = store.root / "day-2026-08-31.json.gz"
    try:
        linked.symlink_to(outside)
    except OSError:
        linked = None

    report = store.clear()

    assert {path.name for path in report.removed} == {
        "current.json.gz",
        "day-2026-09-01.json.gz",
    }
    assert unrelated.read_bytes() == b"keep"
    assert outside.read_bytes() == b"outside"
    if linked is not None:
        assert linked.is_symlink()


def test_store_scan_fails_closed_at_its_directory_inspection_bound(tmp_path: Path):
    store = DogfoodStore(tmp_path / "dogfood")
    for index in range(33):
        (store.root / f"unrelated-{index:02d}").write_bytes(b"x")

    with pytest.raises(ValueError, match="too many"):
        store.load_segments()
    assert store.status().available is False
