"""Bounded, content-free aggregate recording for local UNITI dogfood use."""

from __future__ import annotations

import json
import math
import re
import threading
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


DOGFOOD_SCHEMA = 1
MAX_COUNTER = (1 << 31) - 1
MAX_DOGFOOD_SNAPSHOT_BYTES = 256 << 10


class Operation(StrEnum):
    DOCUMENT_OPEN = "document_open"
    EDIT_TRANSACTION = "edit_transaction"
    FIND_PREVIOUS = "find_previous"
    FIND_NEXT = "find_next"
    FIND_ALL = "find_all"
    REPLACE = "replace"
    REPLACE_ALL = "replace_all"
    SAVE = "save"
    SAVE_AS = "save_as"
    FORMAT_INSPECTION = "format_inspection"
    SESSION_PUBLISH = "session_publish"
    SESSION_RESTORE = "session_restore"
    RECOVERY = "recovery"
    DISCARD = "discard"
    DOCUMENT_CLOSE = "document_close"
    WINDOW_OPEN = "window_open"
    WINDOW_CLOSE = "window_close"
    QUIT = "quit"


class Outcome(StrEnum):
    SUCCESS = "success"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    RECOVERED = "recovered"
    REFUSED_EXTERNAL_CHANGE = "refused_external_change"
    REDUCED_DURABILITY = "reduced_durability"
    UNAVAILABLE = "unavailable"
    DISCARDED = "discarded"
    FAILED = "failed"


class Durability(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    FULL = "full"
    FILE_SYNCED = "file_synced"
    UNSAFE = "unsafe"


class ResourceBand(StrEnum):
    NORMAL = "normal"
    BUSY = "busy"
    CONSTRAINED = "constrained"
    CRITICAL = "critical"


class LatencyBucket(StrEnum):
    UNDER_1_MS = "under_1_ms"
    UNDER_5_MS = "under_5_ms"
    UNDER_16_MS = "under_16_ms"
    UNDER_50_MS = "under_50_ms"
    UNDER_100_MS = "under_100_ms"
    UNDER_250_MS = "under_250_ms"
    UNDER_1000_MS = "under_1000_ms"
    AT_LEAST_1000_MS = "at_least_1000_ms"


class OSFamily(StrEnum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"
    OTHER = "other"


class CPUClass(StrEnum):
    UNKNOWN = "unknown"
    C1_2 = "1_2"
    C3_4 = "3_4"
    C5_8 = "5_8"
    C9_15 = "9_15"
    C16_PLUS = "16_plus"


class RAMClass(StrEnum):
    UNKNOWN = "unknown"
    UNDER_8_GIB = "under_8_gib"
    GIB_8_15 = "8_15_gib"
    GIB_16_31 = "16_31_gib"
    GIB_32_PLUS = "32_plus_gib"


_BUILD_ID_RE = re.compile(
    r"(?:v?\d+(?:\.\d+)*(?:[a-z]\d+)?|[0-9a-f]{7,40}|"
    r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)+)\Z"
)
_RESOURCE_RANK = {band: rank for rank, band in enumerate(ResourceBand)}
_LATENCY_LIMITS = (
    (1.0, LatencyBucket.UNDER_1_MS),
    (5.0, LatencyBucket.UNDER_5_MS),
    (16.0, LatencyBucket.UNDER_16_MS),
    (50.0, LatencyBucket.UNDER_50_MS),
    (100.0, LatencyBucket.UNDER_100_MS),
    (250.0, LatencyBucket.UNDER_250_MS),
    (1000.0, LatencyBucket.UNDER_1000_MS),
)
_LIFECYCLE_OPERATIONS = (
    Operation.SAVE,
    Operation.SAVE_AS,
    Operation.DISCARD,
    Operation.DOCUMENT_CLOSE,
)
_LIFECYCLE_OUTCOMES = (
    Outcome.SUCCESS,
    Outcome.REDUCED_DURABILITY,
    Outcome.DISCARDED,
)


def _plain_count(value: object, field: str) -> int:
    if type(value) is not int or not 0 <= value <= MAX_COUNTER:
        raise ValueError(f"{field} must be a bounded non-negative integer")
    return value


def _counter_map(
    value: object,
    vocabulary: type[StrEnum],
    field: str,
) -> Mapping:
    if (
        not isinstance(value, Mapping)
        or not all(isinstance(key, vocabulary) for key in value)
        or set(value) != set(vocabulary)
    ):
        raise ValueError(f"{field} must contain the fixed vocabulary")
    return MappingProxyType(
        {item: _plain_count(value[item], field) for item in vocabulary}
    )


def _saturating_add(left: int, right: int, limit: int) -> int:
    return min(limit, left + right)


def _counter_limit(value: object) -> int:
    if type(value) is not int or not 1 <= value <= MAX_COUNTER:
        raise ValueError("counter limit must be a positive bounded integer")
    return value


def latency_bucket(elapsed_ms: float) -> LatencyBucket:
    if (
        isinstance(elapsed_ms, bool)
        or not isinstance(elapsed_ms, (int, float))
        or not math.isfinite(float(elapsed_ms))
        or elapsed_ms < 0
    ):
        raise ValueError("elapsed milliseconds must be finite and non-negative")
    value = float(elapsed_ms)
    for upper, bucket in _LATENCY_LIMITS:
        if value < upper:
            return bucket
    return LatencyBucket.AT_LEAST_1000_MS


def classify_cpu(logical_cores: int | None) -> CPUClass:
    if logical_cores is None or type(logical_cores) is not int or logical_cores <= 0:
        return CPUClass.UNKNOWN
    if logical_cores <= 2:
        return CPUClass.C1_2
    if logical_cores <= 4:
        return CPUClass.C3_4
    if logical_cores <= 8:
        return CPUClass.C5_8
    if logical_cores <= 15:
        return CPUClass.C9_15
    return CPUClass.C16_PLUS


def classify_ram(physical_bytes: int | None) -> RAMClass:
    if physical_bytes is None or type(physical_bytes) is not int or physical_bytes <= 0:
        return RAMClass.UNKNOWN
    gib = 1 << 30
    if physical_bytes < 8 * gib:
        return RAMClass.UNDER_8_GIB
    if physical_bytes < 16 * gib:
        return RAMClass.GIB_8_15
    if physical_bytes < 32 * gib:
        return RAMClass.GIB_16_31
    return RAMClass.GIB_32_PLUS


@dataclass(frozen=True, slots=True)
class HostFacts:
    build_id: str
    os_family: OSFamily
    cpu_class: CPUClass
    ram_class: RAMClass

    def __post_init__(self) -> None:
        if not isinstance(self.build_id, str) or _BUILD_ID_RE.fullmatch(self.build_id) is None:
            raise ValueError("build ID must use the bounded version vocabulary")
        if not isinstance(self.os_family, OSFamily):
            raise TypeError("OS family must be an OSFamily")
        if not isinstance(self.cpu_class, CPUClass):
            raise TypeError("CPU class must be a CPUClass")
        if not isinstance(self.ram_class, RAMClass):
            raise TypeError("RAM class must be a RAMClass")


@dataclass(frozen=True, slots=True)
class OperationAggregate:
    operation: Operation
    count: int
    outcomes: Mapping[Outcome, int]
    latencies: Mapping[LatencyBucket, int]
    durability: Mapping[Durability, int]
    peak_resource: ResourceBand
    retained_resource: ResourceBand

    def __post_init__(self) -> None:
        if not isinstance(self.operation, Operation):
            raise TypeError("aggregate operation must be an Operation")
        object.__setattr__(self, "count", _plain_count(self.count, "operation count"))
        object.__setattr__(
            self,
            "outcomes",
            _counter_map(self.outcomes, Outcome, "outcome counts"),
        )
        object.__setattr__(
            self,
            "latencies",
            _counter_map(self.latencies, LatencyBucket, "latency counts"),
        )
        object.__setattr__(
            self,
            "durability",
            _counter_map(self.durability, Durability, "durability counts"),
        )
        if not isinstance(self.peak_resource, ResourceBand):
            raise TypeError("peak resource must be a ResourceBand")
        if not isinstance(self.retained_resource, ResourceBand):
            raise TypeError("retained resource must be a ResourceBand")


@dataclass(frozen=True, slots=True)
class DogfoodSnapshot:
    schema: int
    day: date
    host: HostFacts
    operations: tuple[OperationAggregate, ...]

    def __post_init__(self) -> None:
        if type(self.schema) is not int or self.schema != DOGFOOD_SCHEMA:
            raise ValueError(f"unsupported dogfood schema: {self.schema!r}")
        if type(self.day) is not date:
            raise TypeError("dogfood day must be a date")
        if not isinstance(self.host, HostFacts):
            raise TypeError("dogfood host facts are invalid")
        if (
            not isinstance(self.operations, tuple)
            or not all(
                isinstance(aggregate, OperationAggregate)
                for aggregate in self.operations
            )
            or tuple(aggregate.operation for aggregate in self.operations)
            != tuple(Operation)
        ):
            raise ValueError("dogfood operations must use the complete fixed order")

    def for_operation(self, operation: Operation) -> OperationAggregate:
        if not isinstance(operation, Operation):
            raise TypeError("operation must be an Operation")
        return self.operations[tuple(Operation).index(operation)]

    @property
    def active_day(self) -> bool:
        opened = self.for_operation(Operation.DOCUMENT_OPEN).outcomes[Outcome.SUCCESS]
        edited = self.for_operation(Operation.EDIT_TRANSACTION).outcomes[Outcome.SUCCESS]
        lifecycle = sum(
            self.for_operation(operation).outcomes[outcome]
            for operation in _LIFECYCLE_OPERATIONS
            for outcome in _LIFECYCLE_OUTCOMES
        )
        return opened > 0 and edited > 0 and lifecycle > 0


@dataclass(slots=True)
class _MutableAggregate:
    count: int
    outcomes: dict[Outcome, int]
    latencies: dict[LatencyBucket, int]
    durability: dict[Durability, int]
    peak_resource: ResourceBand
    retained_resource: ResourceBand


def _empty_mutable() -> _MutableAggregate:
    return _MutableAggregate(
        0,
        {item: 0 for item in Outcome},
        {item: 0 for item in LatencyBucket},
        {item: 0 for item in Durability},
        ResourceBand.NORMAL,
        ResourceBand.NORMAL,
    )


def _freeze(operation: Operation, value: _MutableAggregate) -> OperationAggregate:
    return OperationAggregate(
        operation,
        value.count,
        value.outcomes,
        value.latencies,
        value.durability,
        value.peak_resource,
        value.retained_resource,
    )


class DogfoodRecorder:
    """One lock-owned mutable accumulator producing immutable snapshots."""

    def __init__(
        self,
        host: HostFacts,
        *,
        day: date,
        counter_limit: int = MAX_COUNTER,
    ) -> None:
        if not isinstance(host, HostFacts):
            raise TypeError("dogfood host facts are invalid")
        if type(day) is not date:
            raise TypeError("dogfood day must be a date")
        self._host = host
        self._day = day
        self._counter_limit = _counter_limit(counter_limit)
        self._operations = {operation: _empty_mutable() for operation in Operation}
        self._lock = threading.Lock()

    def observe(
        self,
        operation: Operation,
        outcome: Outcome,
        *,
        elapsed_ms: float | None = None,
        durability: Durability = Durability.NOT_APPLICABLE,
        peak_resource: ResourceBand = ResourceBand.NORMAL,
        retained_resource: ResourceBand = ResourceBand.NORMAL,
    ) -> None:
        if not isinstance(operation, Operation):
            raise TypeError("operation must be an Operation")
        if not isinstance(outcome, Outcome):
            raise TypeError("outcome must be an Outcome")
        if not isinstance(durability, Durability):
            raise TypeError("durability must be a Durability")
        if not isinstance(peak_resource, ResourceBand):
            raise TypeError("peak resource must be a ResourceBand")
        if not isinstance(retained_resource, ResourceBand):
            raise TypeError("retained resource must be a ResourceBand")
        selected_bucket = (
            None if elapsed_ms is None else latency_bucket(elapsed_ms)
        )
        with self._lock:
            aggregate = self._operations[operation]
            if aggregate.count >= self._counter_limit:
                return
            aggregate.count += 1
            aggregate.outcomes[outcome] += 1
            aggregate.durability[durability] += 1
            if selected_bucket is not None:
                aggregate.latencies[selected_bucket] += 1
            if _RESOURCE_RANK[peak_resource] > _RESOURCE_RANK[aggregate.peak_resource]:
                aggregate.peak_resource = peak_resource
            if (
                _RESOURCE_RANK[retained_resource]
                > _RESOURCE_RANK[aggregate.retained_resource]
            ):
                aggregate.retained_resource = retained_resource

    def snapshot(self) -> DogfoodSnapshot:
        with self._lock:
            operations = tuple(
                _freeze(operation, self._operations[operation])
                for operation in Operation
            )
        return DogfoodSnapshot(DOGFOOD_SCHEMA, self._day, self._host, operations)


def merge_dogfood_snapshots(
    left: DogfoodSnapshot,
    right: DogfoodSnapshot,
    *,
    counter_limit: int = MAX_COUNTER,
) -> DogfoodSnapshot:
    if not isinstance(left, DogfoodSnapshot) or not isinstance(right, DogfoodSnapshot):
        raise TypeError("dogfood merge requires snapshots")
    if left.day != right.day or left.host != right.host:
        raise ValueError("dogfood snapshots must share one day and host class")
    limit = _counter_limit(counter_limit)
    operations: list[OperationAggregate] = []
    for first, second in zip(left.operations, right.operations, strict=True):
        operations.append(
            OperationAggregate(
                first.operation,
                _saturating_add(first.count, second.count, limit),
                {
                    item: _saturating_add(
                        first.outcomes[item], second.outcomes[item], limit
                    )
                    for item in Outcome
                },
                {
                    item: _saturating_add(
                        first.latencies[item], second.latencies[item], limit
                    )
                    for item in LatencyBucket
                },
                {
                    item: _saturating_add(
                        first.durability[item], second.durability[item], limit
                    )
                    for item in Durability
                },
                max(
                    (first.peak_resource, second.peak_resource),
                    key=_RESOURCE_RANK.__getitem__,
                ),
                max(
                    (first.retained_resource, second.retained_resource),
                    key=_RESOURCE_RANK.__getitem__,
                ),
            )
        )
    return DogfoodSnapshot(DOGFOOD_SCHEMA, left.day, left.host, tuple(operations))


_SNAPSHOT_KEYS = {"day", "host", "operations", "schema"}
_HOST_KEYS = {"build_id", "cpu_class", "os_family", "ram_class"}
_OPERATION_KEYS = {
    "count",
    "durability",
    "latencies",
    "operation",
    "outcomes",
    "peak_resource",
    "retained_resource",
}


def _require_keys(value: object, expected: set[str], field: str) -> dict:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"dogfood {field} keys are invalid")
    return value


def _reject_constant(value: str):
    raise ValueError(f"dogfood numbers must be finite: {value}")


def _as_counter_map(values: object, vocabulary: type[StrEnum], field: str) -> dict:
    if not isinstance(values, list) or len(values) != len(tuple(vocabulary)):
        raise ValueError(f"dogfood {field} must use the fixed vocabulary")
    return {
        item: _plain_count(value, field)
        for item, value in zip(vocabulary, values, strict=True)
    }


def _snapshot_payload(snapshot: DogfoodSnapshot) -> dict[str, object]:
    return {
        "day": snapshot.day.isoformat(),
        "host": {
            "build_id": snapshot.host.build_id,
            "cpu_class": snapshot.host.cpu_class.value,
            "os_family": snapshot.host.os_family.value,
            "ram_class": snapshot.host.ram_class.value,
        },
        "operations": [
            {
                "count": aggregate.count,
                "durability": [aggregate.durability[item] for item in Durability],
                "latencies": [aggregate.latencies[item] for item in LatencyBucket],
                "operation": aggregate.operation.value,
                "outcomes": [aggregate.outcomes[item] for item in Outcome],
                "peak_resource": aggregate.peak_resource.value,
                "retained_resource": aggregate.retained_resource.value,
            }
            for aggregate in snapshot.operations
        ],
        "schema": snapshot.schema,
    }


def encode_dogfood_snapshot(snapshot: DogfoodSnapshot) -> bytes:
    if not isinstance(snapshot, DogfoodSnapshot):
        raise TypeError("dogfood snapshot is invalid")
    payload = json.dumps(
        _snapshot_payload(snapshot),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(payload) > MAX_DOGFOOD_SNAPSHOT_BYTES:
        raise ValueError("dogfood snapshot exceeds the decoded limit")
    return payload


def decode_dogfood_snapshot(payload: bytes) -> DogfoodSnapshot:
    if not isinstance(payload, bytes):
        raise TypeError("dogfood snapshot payload must be bytes")
    if len(payload) > MAX_DOGFOOD_SNAPSHOT_BYTES:
        raise ValueError("dogfood snapshot exceeds the decoded limit")
    try:
        raw = json.loads(payload, parse_constant=_reject_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("dogfood snapshot is not valid JSON") from exc
    values = _require_keys(raw, _SNAPSHOT_KEYS, "snapshot")
    if values["schema"] != DOGFOOD_SCHEMA:
        raise ValueError("unsupported dogfood schema")
    day_value = values["day"]
    if not isinstance(day_value, str):
        raise ValueError("dogfood day is invalid")
    try:
        selected_day = date.fromisoformat(day_value)
    except ValueError as exc:
        raise ValueError("dogfood day is invalid") from exc
    if selected_day.isoformat() != day_value:
        raise ValueError("dogfood day is not canonical")
    host_value = _require_keys(values["host"], _HOST_KEYS, "host")
    try:
        host = HostFacts(
            host_value["build_id"],
            OSFamily(host_value["os_family"]),
            CPUClass(host_value["cpu_class"]),
            RAMClass(host_value["ram_class"]),
        )
    except (TypeError, ValueError) as exc:
        raise ValueError("dogfood host values are invalid") from exc
    raw_operations = values["operations"]
    if not isinstance(raw_operations, list):
        raise ValueError("dogfood operations must be a collection")
    operations: list[OperationAggregate] = []
    for raw_operation in raw_operations:
        item = _require_keys(raw_operation, _OPERATION_KEYS, "operation")
        try:
            operations.append(
                OperationAggregate(
                    Operation(item["operation"]),
                    _plain_count(item["count"], "operation count"),
                    _as_counter_map(item["outcomes"], Outcome, "outcomes"),
                    _as_counter_map(
                        item["latencies"], LatencyBucket, "latencies"
                    ),
                    _as_counter_map(
                        item["durability"], Durability, "durability"
                    ),
                    ResourceBand(item["peak_resource"]),
                    ResourceBand(item["retained_resource"]),
                )
            )
        except (TypeError, ValueError) as exc:
            raise ValueError("dogfood operation values are invalid") from exc
    return DogfoodSnapshot(DOGFOOD_SCHEMA, selected_day, host, tuple(operations))


__all__ = [
    "CPUClass",
    "DOGFOOD_SCHEMA",
    "DogfoodRecorder",
    "DogfoodSnapshot",
    "Durability",
    "HostFacts",
    "LatencyBucket",
    "MAX_COUNTER",
    "MAX_DOGFOOD_SNAPSHOT_BYTES",
    "OSFamily",
    "Operation",
    "OperationAggregate",
    "Outcome",
    "RAMClass",
    "ResourceBand",
    "classify_cpu",
    "classify_ram",
    "decode_dogfood_snapshot",
    "encode_dogfood_snapshot",
    "latency_bucket",
    "merge_dogfood_snapshots",
]
