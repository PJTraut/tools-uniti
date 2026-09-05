from __future__ import annotations

import inspect
import json
from dataclasses import replace
from datetime import date, timedelta

import pytest

from uniti.app.dogfood import (
    MAX_COUNTER,
    MAX_DOGFOOD_SNAPSHOT_BYTES,
    CPUClass,
    RAMClass,
    DogfoodRecorder,
    Durability,
    HostFacts,
    LatencyBucket,
    Operation,
    OSFamily,
    Outcome,
    ResourceBand,
    classify_cpu,
    classify_ram,
    decode_dogfood_snapshot,
    encode_dogfood_snapshot,
    latency_bucket,
    merge_dogfood_snapshots,
)


DAY = date(2026, 9, 5)
HOST = HostFacts(
    "v0.001a22",
    OSFamily.MACOS,
    CPUClass.C5_8,
    RAMClass.GIB_16_31,
)


def test_observation_api_accepts_only_fixed_vocabulary():
    parameters = tuple(inspect.signature(DogfoodRecorder.observe).parameters)
    assert parameters == (
        "self",
        "operation",
        "outcome",
        "elapsed_ms",
        "durability",
        "peak_resource",
        "retained_resource",
    )
    recorder = DogfoodRecorder(HOST, day=DAY)
    recorder.observe(
        Operation.SAVE,
        Outcome.SUCCESS,
        elapsed_ms=12.0,
        durability=Durability.FULL,
        peak_resource=ResourceBand.BUSY,
        retained_resource=ResourceBand.NORMAL,
    )

    with pytest.raises(TypeError):
        recorder.observe("save", Outcome.SUCCESS)
    with pytest.raises(TypeError):
        recorder.observe(Operation.SAVE, "success")
    with pytest.raises(TypeError):
        recorder.observe(Operation.SAVE, Outcome.SUCCESS, durability="full")
    with pytest.raises(TypeError):
        recorder.observe(
            Operation.SAVE,
            Outcome.SUCCESS,
            peak_resource="critical",
        )


@pytest.mark.parametrize(
    ("elapsed_ms", "expected"),
    [
        (0.0, LatencyBucket.UNDER_1_MS),
        (0.999, LatencyBucket.UNDER_1_MS),
        (1.0, LatencyBucket.UNDER_5_MS),
        (5.0, LatencyBucket.UNDER_16_MS),
        (16.0, LatencyBucket.UNDER_50_MS),
        (50.0, LatencyBucket.UNDER_100_MS),
        (100.0, LatencyBucket.UNDER_250_MS),
        (250.0, LatencyBucket.UNDER_1000_MS),
        (1000.0, LatencyBucket.AT_LEAST_1000_MS),
    ],
)
def test_latency_maps_to_fixed_histogram_buckets(elapsed_ms, expected):
    assert latency_bucket(elapsed_ms) is expected


def test_counters_saturate_and_snapshots_merge_without_raw_events():
    recorder = DogfoodRecorder(HOST, day=DAY, counter_limit=2)
    for _ in range(3):
        recorder.observe(
            Operation.FIND_NEXT,
            Outcome.SUCCESS,
            elapsed_ms=3,
            durability=Durability.NOT_APPLICABLE,
            peak_resource=ResourceBand.CONSTRAINED,
            retained_resource=ResourceBand.BUSY,
        )
    snapshot = recorder.snapshot()
    find_next = snapshot.for_operation(Operation.FIND_NEXT)

    assert find_next.count == 2
    assert find_next.outcomes[Outcome.SUCCESS] == 2
    assert find_next.latencies[LatencyBucket.UNDER_5_MS] == 2
    assert find_next.durability[Durability.NOT_APPLICABLE] == 2
    assert find_next.peak_resource is ResourceBand.CONSTRAINED
    assert find_next.retained_resource is ResourceBand.BUSY
    assert not hasattr(snapshot, "raw_events")

    merged = merge_dogfood_snapshots(snapshot, snapshot, counter_limit=3)
    merged_find = merged.for_operation(Operation.FIND_NEXT)
    assert merged_find.count == 3
    assert merged_find.outcomes[Outcome.SUCCESS] == 3
    assert merged_find.latencies[LatencyBucket.UNDER_5_MS] == 3
    assert MAX_COUNTER > 3


def test_one_recorder_rolls_completed_day_and_starts_new_day_empty():
    recorder = DogfoodRecorder(HOST, day=DAY)
    recorder.observe(Operation.EDIT_TRANSACTION, Outcome.SUCCESS)

    completed = recorder.rollover(DAY + timedelta(days=1))

    assert completed is not None
    assert completed.day == DAY
    assert completed.for_operation(Operation.EDIT_TRANSACTION).count == 1
    current = recorder.snapshot()
    assert current.day == DAY + timedelta(days=1)
    assert current.for_operation(Operation.EDIT_TRANSACTION).count == 0


def test_recorder_reset_discards_current_counts_without_replacing_recorder():
    recorder = DogfoodRecorder(HOST, day=DAY)
    recorder.observe(Operation.SAVE, Outcome.SUCCESS)

    recorder.reset(day=DAY)

    assert recorder.snapshot().for_operation(Operation.SAVE).count == 0


def test_active_day_requires_open_authoritative_edit_and_lifecycle_outcome():
    recorder = DogfoodRecorder(HOST, day=DAY)
    assert recorder.snapshot().active_day is False

    recorder.observe(Operation.DOCUMENT_OPEN, Outcome.SUCCESS)
    assert recorder.snapshot().active_day is False
    recorder.observe(Operation.EDIT_TRANSACTION, Outcome.SUCCESS)
    assert recorder.snapshot().active_day is False
    recorder.observe(Operation.DOCUMENT_CLOSE, Outcome.SUCCESS)
    assert recorder.snapshot().active_day is True

    failed = DogfoodRecorder(HOST, day=DAY)
    failed.observe(Operation.DOCUMENT_OPEN, Outcome.FAILED)
    failed.observe(Operation.EDIT_TRANSACTION, Outcome.SUCCESS)
    failed.observe(Operation.SAVE, Outcome.FAILED)
    assert failed.snapshot().active_day is False


def test_host_facts_are_limited_to_build_os_and_coarse_cpu_ram_classes():
    assert tuple(HOST.__dataclass_fields__) == (
        "build_id",
        "os_family",
        "cpu_class",
        "ram_class",
    )
    assert classify_cpu(1) is CPUClass.C1_2
    assert classify_cpu(4) is CPUClass.C3_4
    assert classify_cpu(8) is CPUClass.C5_8
    assert classify_cpu(32) is CPUClass.C16_PLUS
    assert classify_ram(4 << 30) is RAMClass.UNDER_8_GIB
    assert classify_ram(16 << 30) is RAMClass.GIB_16_31
    assert classify_ram(64 << 30) is RAMClass.GIB_32_PLUS

    with pytest.raises(TypeError):
        HostFacts("v0.001a22", "darwin", CPUClass.C5_8, RAMClass.GIB_16_31)
    for unsafe in (
        "/Users/person/project",
        "notes.txt",
        "(a+)+$",
        "OSError: private path failed",
    ):
        with pytest.raises(ValueError):
            HostFacts(unsafe, OSFamily.MACOS, CPUClass.C5_8, RAMClass.GIB_16_31)


def test_snapshot_json_is_strict_private_and_bounded():
    recorder = DogfoodRecorder(HOST, day=DAY)
    recorder.observe(Operation.DOCUMENT_OPEN, Outcome.SUCCESS, elapsed_ms=2)
    recorder.observe(Operation.EDIT_TRANSACTION, Outcome.SUCCESS)
    recorder.observe(Operation.SAVE, Outcome.REFUSED_EXTERNAL_CHANGE, elapsed_ms=9)
    snapshot = recorder.snapshot()

    payload = encode_dogfood_snapshot(snapshot)
    decoded = decode_dogfood_snapshot(payload)
    assert decoded == snapshot
    assert len(payload) <= MAX_DOGFOOD_SNAPSHOT_BYTES
    text = payload.decode("utf-8")
    for forbidden in (
        "/Users/",
        "notes.txt",
        "(a+)+$",
        "private path failed",
        "document_id",
        "expression",
        "exception",
    ):
        assert forbidden not in text

    unknown = json.loads(payload)
    unknown["raw_document"] = "secret"
    with pytest.raises(ValueError, match="keys"):
        decode_dogfood_snapshot(json.dumps(unknown).encode("utf-8"))
    unknown = json.loads(payload)
    unknown["host"]["machine_name"] = "private"
    with pytest.raises(ValueError, match="keys"):
        decode_dogfood_snapshot(json.dumps(unknown).encode("utf-8"))
    with pytest.raises(ValueError, match="finite"):
        decode_dogfood_snapshot(b'{"schema":NaN}')
    with pytest.raises(ValueError, match="exceeds"):
        decode_dogfood_snapshot(b"x" * (MAX_DOGFOOD_SNAPSHOT_BYTES + 1))

    aggregate = snapshot.for_operation(Operation.SAVE)
    with pytest.raises(ValueError, match="fixed vocabulary"):
        replace(
            aggregate,
            outcomes={key.value: value for key, value in aggregate.outcomes.items()},
        )
