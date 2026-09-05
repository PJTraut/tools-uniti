"""Durable bounded storage for content-free dogfood aggregate segments."""

from __future__ import annotations

import gzip
import io
import json
import threading
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum
from itertools import islice
from pathlib import Path

from uniti.core.durability import (
    DurabilityAdapter,
    DurabilityError,
    DurabilityResult,
    NativeDurabilityAdapter,
)

from .atomic_json import atomic_write_bytes
from .cleanup import is_dogfood_artifact_name
from .dogfood import (
    MAX_DOGFOOD_SNAPSHOT_BYTES,
    DogfoodSnapshot,
    decode_dogfood_snapshot,
    encode_dogfood_snapshot,
)


MAX_DOGFOOD_COMPRESSED_BYTES = MAX_DOGFOOD_SNAPSHOT_BYTES + 4096
MAX_DOGFOOD_SEGMENTS_INSPECTED = 32
DEFAULT_RETENTION_DAYS = 7
DEFAULT_AGGREGATE_MAX_BYTES = 16 << 20


class StoreFailureCode(StrEnum):
    WRITE_FAILED = "write_failed"
    INVALID_STATE = "invalid_state"
    CAPACITY_EXCEEDED = "capacity_exceeded"


@dataclass(frozen=True, slots=True)
class StoreDiagnostic:
    code: StoreFailureCode
    available: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.code, StoreFailureCode):
            raise TypeError("store diagnostic code is invalid")
        if self.available is not False:
            raise ValueError("store failure diagnostics must be unavailable")


@dataclass(frozen=True, slots=True)
class PublicationResult:
    published: bool
    diagnostic: StoreDiagnostic | None
    durability: DurabilityResult | None

    def __post_init__(self) -> None:
        if type(self.published) is not bool:
            raise TypeError("publication state must be bool")
        if self.published:
            if self.diagnostic is not None or not isinstance(
                self.durability, DurabilityResult
            ):
                raise ValueError("successful publication result is inconsistent")
        elif not isinstance(self.diagnostic, StoreDiagnostic) or self.durability is not None:
            raise ValueError("failed publication result is inconsistent")


@dataclass(frozen=True, slots=True)
class ClearReport:
    removed: tuple[Path, ...]
    retained: int
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoreStatus:
    available: bool
    segment_count: int
    byte_count: int
    oldest_day: date | None
    newest_day: date | None
    last_failure: StoreFailureCode | None


def _compressed_snapshot(snapshot: DogfoodSnapshot) -> bytes:
    encoded = encode_dogfood_snapshot(snapshot)
    compressed = gzip.compress(encoded, compresslevel=6, mtime=0)
    if len(compressed) > MAX_DOGFOOD_COMPRESSED_BYTES:
        raise ValueError("compressed dogfood segment exceeds its limit")
    return compressed


def _decoded_snapshot(payload: bytes) -> DogfoodSnapshot:
    if len(payload) > MAX_DOGFOOD_COMPRESSED_BYTES:
        raise ValueError("compressed dogfood segment exceeds its limit")
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(payload), mode="rb") as handle:
            decoded = handle.read(MAX_DOGFOOD_SNAPSHOT_BYTES + 1)
    except (EOFError, OSError) as exc:
        raise ValueError("dogfood segment is not valid gzip") from exc
    if len(decoded) > MAX_DOGFOOD_SNAPSHOT_BYTES:
        raise ValueError("dogfood segment exceeds its decoded limit")
    return decode_dogfood_snapshot(decoded)


class DogfoodStore:
    """Own one current aggregate and bounded immutable completed days."""

    def __init__(
        self,
        root: Path,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
        aggregate_max_bytes: int = DEFAULT_AGGREGATE_MAX_BYTES,
        adapter: DurabilityAdapter | None = None,
    ) -> None:
        selected = Path(root)
        if not selected.is_absolute() or selected.is_symlink():
            raise ValueError("dogfood root must be absolute and not a symlink")
        if type(retention_days) is not int or not 1 <= retention_days <= 7:
            raise ValueError("dogfood retention must be between one and seven days")
        if (
            type(aggregate_max_bytes) is not int
            or aggregate_max_bytes <= 0
            or aggregate_max_bytes > DEFAULT_AGGREGATE_MAX_BYTES
        ):
            raise ValueError("dogfood aggregate limit is invalid")
        selected.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root = selected.resolve(strict=True)
        self.current_path = self.root / "current.json.gz"
        self.retention_days = retention_days
        self.aggregate_max_bytes = aggregate_max_bytes
        self._adapter = adapter or NativeDurabilityAdapter()
        self._last_failure: StoreFailureCode | None = None
        self._lock = threading.RLock()

    def completed_path(self, day: date) -> Path:
        if type(day) is not date:
            raise TypeError("completed segment day must be a date")
        return self.root / f"day-{day.isoformat()}.json.gz"

    def _owned(self, path: Path) -> Path:
        selected = Path(path)
        if (
            selected.parent.resolve(strict=True) != self.root
            or selected.is_symlink()
            or not is_dogfood_artifact_name(selected.name)
        ):
            raise ValueError("dogfood segment is outside recorder ownership")
        return selected

    def _completed(self) -> tuple[tuple[date, Path], ...]:
        values: list[tuple[date, Path]] = []
        entries = self._entries()
        for path in entries:
            if path.name == "current.json.gz" or not is_dogfood_artifact_name(path.name):
                continue
            self._owned(path)
            values.append((date.fromisoformat(path.name[4:14]), path))
        return tuple(values)

    def _entries(self) -> tuple[Path, ...]:
        entries = tuple(
            islice(
                self.root.iterdir(),
                MAX_DOGFOOD_SEGMENTS_INSPECTED + 1,
            )
        )
        if len(entries) > MAX_DOGFOOD_SEGMENTS_INSPECTED:
            raise ValueError("dogfood store contains too many entries")
        return tuple(sorted(entries, key=lambda item: item.name))

    def _read(self, path: Path) -> DogfoodSnapshot:
        selected = self._owned(path)
        if not selected.is_file():
            raise ValueError("dogfood segment is not a regular file")
        if selected.stat().st_size > MAX_DOGFOOD_COMPRESSED_BYTES:
            raise ValueError("compressed dogfood segment exceeds its limit")
        return _decoded_snapshot(selected.read_bytes())

    def _write(self, path: Path, payload: bytes) -> DurabilityResult:
        return atomic_write_bytes(
            self._owned(path),
            payload,
            adapter=self._adapter,
        )

    def _remove(self, path: Path) -> None:
        self._owned(path).unlink()

    def _prune(self, reference_day: date, incoming_bytes: int) -> None:
        if incoming_bytes > self.aggregate_max_bytes:
            raise OverflowError("dogfood current segment exceeds aggregate capacity")
        completed = list(self._completed())
        cutoff = reference_day - timedelta(days=self.retention_days - 1)
        for day, path in tuple(completed):
            if day < cutoff:
                self._remove(path)
                completed.remove((day, path))
        total = incoming_bytes + sum(path.stat().st_size for _day, path in completed)
        for item in tuple(completed):
            if total <= self.aggregate_max_bytes:
                break
            _day, path = item
            size = path.stat().st_size
            self._remove(path)
            total -= size

    def publish(self, snapshot: DogfoodSnapshot) -> PublicationResult:
        if not isinstance(snapshot, DogfoodSnapshot):
            raise TypeError("dogfood publication requires a snapshot")
        with self._lock:
            return self._publish(snapshot)

    def _publish(self, snapshot: DogfoodSnapshot) -> PublicationResult:
        payload = _compressed_snapshot(snapshot)
        try:
            current = self._read(self.current_path) if self.current_path.exists() else None
            if current is not None and current.day > snapshot.day:
                raise ValueError("dogfood publication moved backwards in time")
            if current is not None and current.day < snapshot.day:
                completed = self.completed_path(current.day)
                current_payload = self.current_path.read_bytes()
                if completed.exists():
                    if self._read(completed) != current:
                        raise ValueError("completed dogfood day conflicts with current")
                else:
                    self._write(completed, current_payload)
            self._prune(snapshot.day, len(payload))
            durability = self._write(self.current_path, payload)
        except OverflowError:
            self._last_failure = StoreFailureCode.CAPACITY_EXCEEDED
            return PublicationResult(
                False,
                StoreDiagnostic(self._last_failure),
                None,
            )
        except (DurabilityError, OSError):
            self._last_failure = StoreFailureCode.WRITE_FAILED
            return PublicationResult(
                False,
                StoreDiagnostic(self._last_failure),
                None,
            )
        except ValueError:
            self._last_failure = StoreFailureCode.INVALID_STATE
            return PublicationResult(
                False,
                StoreDiagnostic(self._last_failure),
                None,
            )
        self._last_failure = None
        return PublicationResult(True, None, durability)

    def load_segments(self) -> tuple[DogfoodSnapshot, ...]:
        with self._lock:
            return self._load_segments()

    def _load_segments(self) -> tuple[DogfoodSnapshot, ...]:
        completed = [(day, self._read(path)) for day, path in self._completed()]
        for filename_day, snapshot in completed:
            if snapshot.day != filename_day:
                raise ValueError("dogfood segment day does not match its filename")
        current = self._read(self.current_path) if self.current_path.exists() else None
        values = [snapshot for _day, snapshot in completed]
        if current is not None:
            if any(snapshot.day == current.day for snapshot in values):
                raise ValueError("dogfood current day duplicates a completed segment")
            values.append(current)
        if tuple(snapshot.day for snapshot in values) != tuple(
            sorted(snapshot.day for snapshot in values)
        ):
            raise ValueError("dogfood segments are not chronological")
        return tuple(values)

    def export(self, destination: Path) -> DurabilityResult:
        with self._lock:
            snapshots = self._load_segments()
            payload = {
                "schema": 1,
                "segments": [
                    json.loads(encode_dogfood_snapshot(snapshot))
                    for snapshot in snapshots
                ],
            }
            encoded = json.dumps(
                payload,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if len(encoded) > self.aggregate_max_bytes:
                raise ValueError("dogfood export exceeds the aggregate limit")
            return atomic_write_bytes(
                Path(destination),
                encoded,
                adapter=self._adapter,
            )

    def clear(self) -> ClearReport:
        with self._lock:
            return self._clear()

    def _clear(self) -> ClearReport:
        removed: list[Path] = []
        errors: list[str] = []
        retained = 0
        try:
            entries = self._entries()
        except (OSError, ValueError):
            return ClearReport((), 0, ("inspection_limit",))
        for path in entries:
            if not is_dogfood_artifact_name(path.name) or path.is_symlink():
                retained += 1
                continue
            try:
                self._remove(path)
            except (OSError, ValueError):
                errors.append(f"could_not_remove:{path.name}"[:128])
            else:
                removed.append(path)
        return ClearReport(tuple(removed), retained, tuple(errors))

    def status(self) -> StoreStatus:
        with self._lock:
            return self._status()

    def _status(self) -> StoreStatus:
        try:
            segments = self._load_segments()
            paths = tuple(path for _day, path in self._completed())
            if self.current_path.exists():
                paths += (self.current_path,)
            byte_count = sum(path.stat().st_size for path in paths)
            days = tuple(snapshot.day for snapshot in segments)
            return StoreStatus(
                self._last_failure is None,
                len(segments),
                byte_count,
                min(days) if days else None,
                max(days) if days else None,
                self._last_failure,
            )
        except (OSError, ValueError):
            self._last_failure = StoreFailureCode.INVALID_STATE
            return StoreStatus(False, 0, 0, None, None, self._last_failure)


__all__ = [
    "ClearReport",
    "DEFAULT_AGGREGATE_MAX_BYTES",
    "DEFAULT_RETENTION_DAYS",
    "DogfoodStore",
    "MAX_DOGFOOD_COMPRESSED_BYTES",
    "PublicationResult",
    "StoreDiagnostic",
    "StoreFailureCode",
    "StoreStatus",
]
