"""Incremental crash-recovery journal primitives for UNITI."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import TYPE_CHECKING, TextIO

from .file_identity import FileIdentity, sha256_file
from .history import (
    EditHistory,
    EditOperation,
    EditTransaction,
    HistorySnapshot,
    HistoryTruncation,
)
from .text_format import EOLPolicy, OutputFormat, encoding_profile

if TYPE_CHECKING:
    from .document import Document


RECOVERY_FORMAT_VERSION = 3
MAX_RECOVERY_RECORD_BYTES = 64 << 20
MAX_RECOVERY_EVENTS = 1_000_000
MAX_TRANSACTION_OPERATIONS = 1_000_000
_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")
_EOL_VALUES = frozenset({None, "LF", "CRLF", "CR"})


def _open_windows_write_shared_delete(path: Path) -> TextIO:
    from .windows_io import open_shared_delete_descriptor

    descriptor = open_shared_delete_descriptor(path, mode="truncate-write")
    try:
        return os.fdopen(
            descriptor,
            "w",
            encoding="utf-8",
            newline="\n",
            closefd=True,
        )
    except Exception:
        os.close(descriptor)
        raise


class RecoveryEventKind(StrEnum):
    TRANSACTION = "transaction"
    UNDO = "undo"
    REDO = "redo"
    SAVE_POINT = "save_point"
    METADATA = "metadata"
    CHECKPOINT = "checkpoint"
    TERMINAL = "terminal"


class _RecoveryEventAccessor:
    """Expose a record value on instances and its constructor on the class."""

    def __init__(self, storage_name: str, constructor_name: str) -> None:
        self._storage_name = storage_name
        self._constructor_name = constructor_name

    def __get__(self, instance, owner):
        if instance is None:
            return getattr(owner, self._constructor_name)
        return getattr(instance, self._storage_name)


@dataclass(frozen=True, slots=True, init=False)
class RecoveryEvent:
    sequence: int
    kind: RecoveryEventKind
    _transaction: EditTransaction | None = field(repr=False)
    _cursor: int = field(repr=False)
    saved_cursor: int | None
    revision: int
    metadata: Mapping[str, object]

    transaction = _RecoveryEventAccessor("_transaction", "_for_transaction")
    cursor = _RecoveryEventAccessor("_cursor", "_for_cursor")

    def __init__(
        self,
        sequence: int,
        kind: RecoveryEventKind,
        transaction: EditTransaction | None,
        cursor: int,
        saved_cursor: int | None,
        revision: int,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        if type(sequence) is not int or sequence <= 0:
            raise ValueError("recovery event sequence must be positive")
        if not isinstance(kind, RecoveryEventKind):
            raise ValueError("recovery event kind is invalid")
        if type(cursor) is not int or cursor < 0:
            raise ValueError("recovery event cursor must be non-negative")
        if saved_cursor is not None and (
            type(saved_cursor) is not int or saved_cursor < 0
        ):
            raise ValueError("recovery event saved cursor is invalid")
        if type(revision) is not int or revision < 0:
            raise ValueError("recovery event revision must be non-negative")
        if kind is RecoveryEventKind.TRANSACTION:
            if not isinstance(transaction, EditTransaction) or not transaction.operations:
                raise ValueError("transaction event requires a transaction")
        elif transaction is not None:
            raise ValueError("only transaction events may contain a transaction")
        if kind is RecoveryEventKind.CHECKPOINT:
            raise ValueError("checkpoints use RecoveryCheckpoint records")
        metadata_value = {} if metadata is None else metadata
        if not isinstance(metadata_value, Mapping) or any(
            not isinstance(key, str) for key in metadata_value
        ):
            raise ValueError("recovery event metadata is invalid")
        metadata_copy = dict(metadata_value)
        _validate_json_value(metadata_copy)
        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "_transaction", transaction)
        object.__setattr__(self, "_cursor", cursor)
        object.__setattr__(self, "saved_cursor", saved_cursor)
        object.__setattr__(self, "revision", revision)
        object.__setattr__(self, "metadata", MappingProxyType(metadata_copy))

    @classmethod
    def _for_transaction(
        cls,
        sequence: int,
        transaction: EditTransaction,
        *,
        cursor: int,
        saved_cursor: int | None,
        revision: int,
    ) -> "RecoveryEvent":
        return cls(
            sequence,
            RecoveryEventKind.TRANSACTION,
            transaction,
            cursor,
            saved_cursor,
            revision,
        )

    @classmethod
    def _for_cursor(
        cls,
        sequence: int,
        kind: RecoveryEventKind,
        *,
        cursor: int,
        saved_cursor: int | None,
        revision: int,
    ) -> "RecoveryEvent":
        if kind not in {
            RecoveryEventKind.UNDO,
            RecoveryEventKind.REDO,
            RecoveryEventKind.SAVE_POINT,
            RecoveryEventKind.TERMINAL,
        }:
            raise ValueError("cursor event kind is invalid")
        return cls(sequence, kind, None, cursor, saved_cursor, revision)


@dataclass(frozen=True, slots=True)
class RecoveryCheckpoint:
    history: HistorySnapshot
    events: tuple[RecoveryEvent, ...]

    def __post_init__(self) -> None:
        _validate_history(self.history)
        if not isinstance(self.events, tuple) or any(
            not isinstance(event, RecoveryEvent) for event in self.events
        ):
            raise ValueError("recovery checkpoint events are invalid")
        _validate_contiguous_events(self.events, require_first=False)


@dataclass(frozen=True, slots=True)
class RecoverySession:
    source_path: Path
    source_identity: FileIdentity
    source_encoding: str
    output_encoding: str
    output_eol: str | None
    operations: tuple[EditOperation, ...]
    clean: bool
    format_version: int = 2
    base_hash: str | None = None
    base_history: HistorySnapshot = HistorySnapshot.empty()
    events: tuple[RecoveryEvent, ...] = ()
    durable_revision: int = 0

    @property
    def encoding(self) -> str:
        """Compatibility alias for alpha10 journals/tests."""
        return self.source_encoding


class RecoveryLoadStatus(StrEnum):
    COMPLETE = "complete"
    TRUNCATED_TAIL = "truncated_tail"
    CORRUPT = "corrupt"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class RecoveryLoadResult:
    path: Path
    status: RecoveryLoadStatus
    session: RecoverySession | None
    durable_events: tuple[RecoveryEvent, ...]
    error: str | None = None


class RecoverySourceMismatchError(RuntimeError):
    pass


class RecoveryReplayError(RuntimeError):
    pass


class _UnsupportedRecovery(ValueError):
    pass


def _validate_json_value(value: object, *, depth: int = 0) -> None:
    if depth > 16:
        raise ValueError("recovery metadata is too deeply nested")
    if value is None or isinstance(value, (str, int, float, bool)):
        return
    if isinstance(value, list):
        if len(value) > MAX_TRANSACTION_OPERATIONS:
            raise ValueError("recovery metadata collection is too large")
        for item in value:
            _validate_json_value(item, depth=depth + 1)
        return
    if isinstance(value, dict):
        if len(value) > MAX_TRANSACTION_OPERATIONS or any(
            not isinstance(key, str) for key in value
        ):
            raise ValueError("recovery metadata mapping is invalid")
        for item in value.values():
            _validate_json_value(item, depth=depth + 1)
        return
    raise ValueError("recovery metadata contains an unsupported value")


def _canonical_bytes(payload: object) -> bytes:
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _require_plain_int(value: object, label: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} is invalid")
    return value


def _require_mapping(value: object, label: str) -> dict[str, object]:
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _require_list(value: object, label: str, *, maximum: int) -> list[object]:
    if not isinstance(value, list) or len(value) > maximum:
        raise ValueError(f"{label} is invalid")
    return value


def _require_keys(
    payload: Mapping[str, object], expected: set[str], label: str
) -> None:
    if set(payload) != expected:
        raise ValueError(f"{label} fields are invalid")


def _identity_to_payload(identity: FileIdentity) -> dict[str, object]:
    if not isinstance(identity, FileIdentity):
        raise ValueError("recovery base identity is invalid")
    return {
        "device": identity.device,
        "inode": identity.inode,
        "mtime_ns": identity.mtime_ns,
        "size": identity.size,
    }


def _identity_from_payload(value: object) -> FileIdentity:
    payload = _require_mapping(value, "recovery base identity")
    _require_keys(payload, {"size", "mtime_ns", "inode", "device"}, "identity")
    size = _require_plain_int(payload["size"], "identity size")
    mtime_ns = _require_plain_int(payload["mtime_ns"], "identity mtime")
    values: list[int | None] = []
    for name in ("inode", "device"):
        item = payload[name]
        values.append(
            None if item is None else _require_plain_int(item, f"identity {name}")
        )
    return FileIdentity(size, mtime_ns, values[0], values[1])


def _operation_to_payload(operation: EditOperation) -> dict[str, object]:
    return {
        "deleted_text": operation.deleted_text,
        "inserted_text": operation.inserted_text,
        "start": operation.start,
    }


def _transaction_to_payload(transaction: EditTransaction) -> list[dict[str, object]]:
    if not isinstance(transaction, EditTransaction) or not transaction.operations:
        raise ValueError("recovery transaction is invalid")
    if len(transaction.operations) > MAX_TRANSACTION_OPERATIONS or any(
        not isinstance(operation, EditOperation)
        for operation in transaction.operations
    ):
        raise ValueError("recovery transaction operations are invalid")
    return [_operation_to_payload(operation) for operation in transaction.operations]


def _transaction_from_payload(value: object) -> EditTransaction:
    items = _require_list(
        value,
        "recovery transaction",
        maximum=MAX_TRANSACTION_OPERATIONS,
    )
    if not items:
        raise ValueError("recovery transaction cannot be empty")
    operations: list[EditOperation] = []
    for value in items:
        payload = _require_mapping(value, "recovery operation")
        _require_keys(
            payload,
            {"start", "deleted_text", "inserted_text"},
            "recovery operation",
        )
        if not isinstance(payload["deleted_text"], str) or not isinstance(
            payload["inserted_text"], str
        ):
            raise ValueError("recovery operation text is invalid")
        operations.append(
            EditOperation(
                _require_plain_int(payload["start"], "recovery operation start"),
                payload["deleted_text"],
                payload["inserted_text"],
            )
        )
    return EditTransaction(tuple(operations))


def _history_to_payload(snapshot: HistorySnapshot) -> dict[str, object]:
    _validate_history(snapshot)
    return {
        "coalesce": snapshot.coalesce,
        "cursor": snapshot.cursor,
        "decoded_bytes": snapshot.decoded_bytes,
        "persistable": snapshot.persistable,
        "saved_cursor": snapshot.saved_cursor,
        "transactions": [
            _transaction_to_payload(transaction)
            for transaction in snapshot.transactions
        ],
        "truncations": [
            {
                "dropped_bytes": item.dropped_bytes,
                "dropped_transactions": item.dropped_transactions,
                "reason": item.reason,
            }
            for item in snapshot.truncations
        ],
    }


def _history_from_payload(value: object) -> HistorySnapshot:
    payload = _require_mapping(value, "recovery history")
    _require_keys(
        payload,
        {
            "transactions",
            "cursor",
            "saved_cursor",
            "coalesce",
            "decoded_bytes",
            "persistable",
            "truncations",
        },
        "recovery history",
    )
    transaction_values = _require_list(
        payload["transactions"], "recovery history transactions", maximum=50
    )
    truncation_values = _require_list(
        payload["truncations"], "recovery history truncations", maximum=100
    )
    truncations: list[HistoryTruncation] = []
    for value in truncation_values:
        item = _require_mapping(value, "recovery history truncation")
        _require_keys(
            item,
            {"reason", "dropped_transactions", "dropped_bytes"},
            "recovery history truncation",
        )
        if not isinstance(item["reason"], str) or not item["reason"]:
            raise ValueError("recovery history truncation reason is invalid")
        truncations.append(
            HistoryTruncation(
                item["reason"],
                _require_plain_int(
                    item["dropped_transactions"], "dropped transaction count"
                ),
                _require_plain_int(item["dropped_bytes"], "dropped byte count"),
            )
        )
    if type(payload["persistable"]) is not bool:
        raise ValueError("recovery history persistable flag is invalid")
    saved_cursor = payload["saved_cursor"]
    if saved_cursor is not None:
        saved_cursor = _require_plain_int(saved_cursor, "recovery saved cursor")
    coalesce = payload["coalesce"]
    if coalesce is not None and not isinstance(coalesce, str):
        raise ValueError("recovery history coalescing value is invalid")
    snapshot = HistorySnapshot(
        transactions=tuple(
            _transaction_from_payload(item) for item in transaction_values
        ),
        cursor=_require_plain_int(payload["cursor"], "recovery history cursor"),
        saved_cursor=saved_cursor,
        coalesce=coalesce,
        decoded_bytes=_require_plain_int(
            payload["decoded_bytes"], "recovery history decoded bytes"
        ),
        persistable=payload["persistable"],
        truncations=tuple(truncations),
    )
    _validate_history(snapshot)
    return snapshot


def _validate_history(snapshot: HistorySnapshot) -> None:
    if not isinstance(snapshot, HistorySnapshot):
        raise ValueError("recovery history is invalid")
    validator = EditHistory()
    validator.restore(snapshot)


def _event_payload(event: RecoveryEvent) -> dict[str, object]:
    return {
        "cursor": event.cursor,
        "kind": event.kind.value,
        "metadata": dict(event.metadata),
        "revision": event.revision,
        "saved_cursor": event.saved_cursor,
        "transaction": (
            None
            if event.transaction is None
            else _transaction_to_payload(event.transaction)
        ),
    }


def _event_envelope(event: RecoveryEvent) -> dict[str, object]:
    payload = _event_payload(event)
    return {
        "payload": payload,
        "schema": RECOVERY_FORMAT_VERSION,
        "sequence": event.sequence,
        "sha256": hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
    }


def _checkpoint_envelope(checkpoint: RecoveryCheckpoint) -> dict[str, object]:
    payload = {
        "events": [_event_envelope(event) for event in checkpoint.events],
        "history": _history_to_payload(checkpoint.history),
        "kind": RecoveryEventKind.CHECKPOINT.value,
    }
    sequence = checkpoint.events[-1].sequence if checkpoint.events else 0
    return {
        "payload": payload,
        "schema": RECOVERY_FORMAT_VERSION,
        "sequence": sequence,
        "sha256": hashlib.sha256(_canonical_bytes(payload)).hexdigest(),
    }


def _decode_envelope(value: object) -> tuple[int, dict[str, object]]:
    envelope = _require_mapping(value, "recovery envelope")
    _require_keys(
        envelope,
        {"schema", "sequence", "payload", "sha256"},
        "recovery envelope",
    )
    schema = _require_plain_int(envelope["schema"], "recovery envelope schema")
    if schema != RECOVERY_FORMAT_VERSION:
        if schema > RECOVERY_FORMAT_VERSION:
            raise _UnsupportedRecovery("future recovery record schema")
        raise ValueError("unsupported recovery record schema")
    sequence = _require_plain_int(envelope["sequence"], "recovery sequence")
    payload = _require_mapping(envelope["payload"], "recovery payload")
    checksum = envelope["sha256"]
    if not isinstance(checksum, str) or _SHA256_RE.fullmatch(checksum) is None:
        raise ValueError("recovery record checksum is invalid")
    actual = hashlib.sha256(_canonical_bytes(payload)).hexdigest()
    if not hmac.compare_digest(actual, checksum):
        raise ValueError("recovery record checksum does not match")
    return sequence, payload


def _event_from_envelope(value: object) -> RecoveryEvent:
    sequence, payload = _decode_envelope(value)
    _require_keys(
        payload,
        {"kind", "transaction", "cursor", "saved_cursor", "revision", "metadata"},
        "recovery event",
    )
    try:
        kind = RecoveryEventKind(payload["kind"])
    except (TypeError, ValueError) as exc:
        raise ValueError("recovery event kind is invalid") from exc
    transaction_value = payload["transaction"]
    transaction = (
        None
        if transaction_value is None
        else _transaction_from_payload(transaction_value)
    )
    metadata = _require_mapping(payload["metadata"], "recovery event metadata")
    saved_cursor = payload["saved_cursor"]
    if saved_cursor is not None:
        saved_cursor = _require_plain_int(saved_cursor, "recovery saved cursor")
    return RecoveryEvent(
        sequence=sequence,
        kind=kind,
        transaction=transaction,
        cursor=_require_plain_int(payload["cursor"], "recovery cursor"),
        saved_cursor=saved_cursor,
        revision=_require_plain_int(payload["revision"], "recovery revision"),
        metadata=metadata,
    )


def _checkpoint_from_payload(
    sequence: int, payload: dict[str, object]
) -> RecoveryCheckpoint:
    _require_keys(payload, {"kind", "history", "events"}, "recovery checkpoint")
    if payload["kind"] != RecoveryEventKind.CHECKPOINT.value:
        raise ValueError("recovery checkpoint kind is invalid")
    values = _require_list(
        payload["events"], "recovery checkpoint events", maximum=MAX_RECOVERY_EVENTS
    )
    events = tuple(_event_from_envelope(value) for value in values)
    checkpoint = RecoveryCheckpoint(_history_from_payload(payload["history"]), events)
    expected_sequence = events[-1].sequence if events else 0
    if sequence != expected_sequence:
        raise ValueError("recovery checkpoint sequence does not match")
    return checkpoint


def _validate_contiguous_events(
    events: tuple[RecoveryEvent, ...], *, require_first: bool
) -> None:
    if len(events) > MAX_RECOVERY_EVENTS:
        raise ValueError("recovery contains too many events")
    if not events:
        return
    if require_first and events[0].sequence != 1:
        raise ValueError("recovery event sequence must begin at one")
    previous = events[0].sequence
    for event in events[1:]:
        if event.sequence != previous + 1:
            raise ValueError("recovery event sequence is not contiguous")
        previous = event.sequence


class RecoveryJournal:
    """Append-only JSONL journal flushed after each durable record."""

    def __init__(
        self,
        path: Path,
        handle: TextIO,
        *,
        format_version: int = 2,
        last_sequence: int = 0,
    ) -> None:
        self.path = path
        self._handle = handle
        self._format_version = format_version
        self._last_sequence = last_sequence
        self._closed = False

    @staticmethod
    def _open_private(path: Path) -> TextIO:
        if sys.platform.startswith("win"):
            return _open_windows_write_shared_delete(path)
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            0o600,
        )
        return os.fdopen(descriptor, "w", encoding="utf-8", newline="\n")

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        source_path: str | os.PathLike[str],
        *,
        source_encoding: str | None = None,
        output_encoding: str | None = None,
        output_eol: str | None = None,
        encoding: str | None = None,
    ) -> "RecoveryJournal":
        if source_encoding is None:
            source_encoding = encoding
        if source_encoding is None:
            raise TypeError("source_encoding is required")
        if output_encoding is None:
            output_encoding = source_encoding if encoding is None else encoding
        if output_eol not in _EOL_VALUES:
            raise ValueError("output EOL is invalid")

        journal_path = Path(path)
        source = Path(source_path)
        identity = FileIdentity.from_path(source)
        journal = cls(journal_path, cls._open_private(journal_path))
        journal._write_record(
            {
                "type": "header",
                "format": 2,
                "source_path": str(source),
                "source_size": identity.size,
                "source_mtime_ns": identity.mtime_ns,
                "source_encoding": source_encoding,
                "output_encoding": output_encoding,
                "output_eol": output_eol,
                "source_inode": identity.inode,
                "source_device": identity.device,
            }
        )
        return journal

    @classmethod
    def create_v3(
        cls,
        path: Path,
        source_path: Path,
        *,
        base_identity: FileIdentity,
        base_hash: str,
        source_encoding: str,
        output_encoding: str,
        output_eol: str | None,
        base_history: HistorySnapshot,
    ) -> "RecoveryJournal":
        if not isinstance(source_encoding, str) or not source_encoding:
            raise ValueError("source encoding is invalid")
        if not isinstance(output_encoding, str) or not output_encoding:
            raise ValueError("output encoding is invalid")
        if output_eol not in _EOL_VALUES:
            raise ValueError("output EOL is invalid")
        if not isinstance(base_hash, str) or _SHA256_RE.fullmatch(base_hash) is None:
            raise ValueError("recovery base hash is invalid")
        _validate_history(base_history)
        journal_path = Path(path)
        journal = cls(
            journal_path,
            cls._open_private(journal_path),
            format_version=RECOVERY_FORMAT_VERSION,
        )
        journal._write_record(
            {
                "base_hash": base_hash,
                "base_history": _history_to_payload(base_history),
                "base_identity": _identity_to_payload(base_identity),
                "format": RECOVERY_FORMAT_VERSION,
                "output_encoding": output_encoding,
                "output_eol": output_eol,
                "source_encoding": source_encoding,
                "source_path": str(Path(source_path)),
                "type": "header",
            }
        )
        return journal

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("RecoveryJournal is closed")

    def _write_record(
        self, record: dict[str, object], *, durable: bool = True
    ) -> None:
        self._ensure_open()
        self._handle.write(_canonical_bytes(record).decode("utf-8"))
        self._handle.write("\n")
        self._handle.flush()
        if durable:
            os.fsync(self._handle.fileno())

    def flush(self, *, durable: bool = True) -> None:
        self._ensure_open()
        self._handle.flush()
        if durable:
            os.fsync(self._handle.fileno())

    def append(self, operation: EditOperation, *, durable: bool = True) -> None:
        if self._format_version != 2:
            raise ValueError("raw edits are supported only by legacy journals")
        self._write_record(
            {
                "type": "edit",
                "start": operation.start,
                "deleted": operation.deleted_text,
                "inserted": operation.inserted_text,
            },
            durable=durable,
        )

    def append_event(self, event: RecoveryEvent, *, durable: bool = True) -> None:
        if self._format_version != RECOVERY_FORMAT_VERSION:
            raise ValueError("semantic events require a v3 journal")
        if not isinstance(event, RecoveryEvent):
            raise TypeError("event must be a RecoveryEvent")
        if event.sequence != self._last_sequence + 1:
            raise ValueError("recovery event sequence is not contiguous")
        self._write_record(_event_envelope(event), durable=durable)
        self._last_sequence = event.sequence

    def append_checkpoint(
        self, checkpoint: RecoveryCheckpoint, *, durable: bool = True
    ) -> None:
        if self._format_version != RECOVERY_FORMAT_VERSION:
            raise ValueError("checkpoints require a v3 journal")
        if not isinstance(checkpoint, RecoveryCheckpoint):
            raise TypeError("checkpoint must be a RecoveryCheckpoint")
        if self._last_sequence:
            raise ValueError("a checkpoint must be the first v3 journal record")
        self._write_record(_checkpoint_envelope(checkpoint), durable=durable)
        if checkpoint.events:
            self._last_sequence = checkpoint.events[-1].sequence

    def update_metadata(
        self,
        *,
        output_encoding: str,
        output_eol: str | None,
        durable: bool = True,
    ) -> None:
        if self._format_version != 2:
            raise ValueError("legacy metadata records require a v2 journal")
        self._write_record(
            {
                "type": "metadata",
                "output_encoding": output_encoding,
                "output_eol": output_eol,
            },
            durable=durable,
        )

    def mark_clean(self, *, durable: bool = True) -> None:
        if self._format_version != 2:
            raise ValueError("legacy clean markers require a v2 journal")
        self._write_record({"type": "clean"}, durable=durable)

    def close(self) -> None:
        if self._closed:
            return
        self._handle.close()
        self._closed = True

    def __enter__(self) -> "RecoveryJournal":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _load_legacy_recovery(journal_path: Path) -> RecoverySession:
    header: dict[str, object] | None = None
    operations: list[EditOperation] = []
    clean = False
    output_encoding: str | None = None
    output_eol: str | None = None

    with journal_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(
                    f"invalid recovery JSON at line {line_number}"
                ) from exc
            if not isinstance(record, dict):
                raise ValueError("recovery record must be an object")
            record_type = record.get("type")
            if line_number == 1 and record_type != "header":
                raise ValueError("recovery journal must begin with header")
            if record_type == "header":
                if header is not None:
                    raise ValueError("duplicate recovery header")
                header = record
            elif record_type == "edit":
                operations.append(
                    EditOperation(
                        int(record["start"]),
                        str(record["deleted"]),
                        str(record["inserted"]),
                    )
                )
            elif record_type == "metadata":
                if "output_encoding" in record:
                    output_encoding = str(record["output_encoding"])
                output_eol = (
                    None
                    if record.get("output_eol") is None
                    else str(record["output_eol"])
                )
            elif record_type == "clean":
                clean = True
            else:
                raise ValueError(f"unknown recovery record type: {record_type!r}")

    if header is None:
        raise ValueError("recovery journal has no header")
    version = int(header.get("format", 0))
    if version not in (1, 2):
        raise _UnsupportedRecovery("unsupported recovery journal format")

    if version == 1:
        source_encoding = str(header["encoding"])
        initial_output_encoding = source_encoding
        initial_output_eol = None
    else:
        source_encoding = str(header["source_encoding"])
        initial_output_encoding = str(
            header.get("output_encoding", source_encoding)
        )
        initial_output_eol = (
            None
            if header.get("output_eol") is None
            else str(header["output_eol"])
        )

    return RecoverySession(
        source_path=Path(str(header["source_path"])),
        source_identity=FileIdentity(
            size=int(header["source_size"]),
            mtime_ns=int(header["source_mtime_ns"]),
            inode=(
                None
                if header.get("source_inode") is None
                else int(header["source_inode"])
            ),
            device=(
                None
                if header.get("source_device") is None
                else int(header["source_device"])
            ),
        ),
        source_encoding=source_encoding,
        output_encoding=output_encoding or initial_output_encoding,
        output_eol=initial_output_eol if output_eol is None else output_eol,
        operations=tuple(operations),
        clean=clean,
        format_version=version,
    )


def _v3_header(value: object) -> dict[str, object]:
    header = _require_mapping(value, "recovery header")
    _require_keys(
        header,
        {
            "type",
            "format",
            "source_path",
            "base_identity",
            "base_hash",
            "source_encoding",
            "output_encoding",
            "output_eol",
            "base_history",
        },
        "recovery header",
    )
    if header["type"] != "header" or header["format"] != RECOVERY_FORMAT_VERSION:
        raise ValueError("recovery v3 header is invalid")
    if not isinstance(header["source_path"], str) or not header["source_path"]:
        raise ValueError("recovery source path is invalid")
    if not isinstance(header["source_encoding"], str) or not header["source_encoding"]:
        raise ValueError("recovery source encoding is invalid")
    if not isinstance(header["output_encoding"], str) or not header["output_encoding"]:
        raise ValueError("recovery output encoding is invalid")
    if header["output_eol"] not in _EOL_VALUES:
        raise ValueError("recovery output EOL is invalid")
    base_hash = header["base_hash"]
    if not isinstance(base_hash, str) or _SHA256_RE.fullmatch(base_hash) is None:
        raise ValueError("recovery base hash is invalid")
    _identity_from_payload(header["base_identity"])
    _history_from_payload(header["base_history"])
    return header


def _session_from_v3(
    header: Mapping[str, object],
    base_history: HistorySnapshot,
    events: tuple[RecoveryEvent, ...],
) -> RecoverySession:
    output_encoding = str(header["output_encoding"])
    output_eol = header["output_eol"]
    for event in events:
        if event.kind not in {
            RecoveryEventKind.METADATA,
            RecoveryEventKind.SAVE_POINT,
        }:
            continue
        encoding = event.metadata.get("output_encoding")
        eol = event.metadata.get("output_eol", output_eol)
        if encoding is not None:
            if not isinstance(encoding, str) or not encoding:
                raise ValueError("recovery event output encoding is invalid")
            output_encoding = encoding
        if eol not in _EOL_VALUES:
            raise ValueError("recovery event output EOL is invalid")
        output_eol = eol
    return RecoverySession(
        source_path=Path(str(header["source_path"])),
        source_identity=_identity_from_payload(header["base_identity"]),
        source_encoding=str(header["source_encoding"]),
        output_encoding=output_encoding,
        output_eol=output_eol if isinstance(output_eol, str) else None,
        operations=(),
        clean=bool(events and events[-1].kind is RecoveryEventKind.TERMINAL),
        format_version=RECOVERY_FORMAT_VERSION,
        base_hash=str(header["base_hash"]),
        base_history=base_history,
        events=events,
        durable_revision=events[-1].revision if events else 0,
    )


def _decode_json_line(raw: bytes, label: str) -> object:
    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid {label}") from exc


def _read_v3_candidate(
    journal_path: Path,
    handle,
    header_value: object,
    *,
    consumed_bytes: int,
    max_bytes: int,
) -> RecoveryLoadResult:
    header = _v3_header(header_value)
    base_history = _history_from_payload(header["base_history"])
    events: list[RecoveryEvent] = []
    last_sequence = 0
    saw_checkpoint = False
    saw_terminal = False
    status = RecoveryLoadStatus.COMPLETE
    error: str | None = None

    while True:
        raw = handle.readline(MAX_RECOVERY_RECORD_BYTES + 2)
        if not raw:
            break
        consumed_bytes += len(raw)
        if consumed_bytes > max_bytes:
            raise ValueError("recovery journal exceeds its byte limit")
        if len(raw) > MAX_RECOVERY_RECORD_BYTES:
            raise ValueError("recovery record exceeds its decoded byte limit")
        if not raw.endswith(b"\n"):
            status = RecoveryLoadStatus.TRUNCATED_TAIL
            error = "recovery journal has a truncated final record"
            break
        value = _decode_json_line(raw, "recovery record")
        sequence, payload = _decode_envelope(value)
        if payload.get("kind") == RecoveryEventKind.CHECKPOINT.value:
            if saw_checkpoint or events:
                raise ValueError("recovery checkpoint is not the first record")
            checkpoint = _checkpoint_from_payload(sequence, payload)
            base_history = checkpoint.history
            events = list(checkpoint.events)
            last_sequence = events[-1].sequence if events else 0
            saw_checkpoint = True
            saw_terminal = bool(
                events and events[-1].kind is RecoveryEventKind.TERMINAL
            )
            continue
        event = _event_from_envelope(value)
        if sequence != last_sequence + 1:
            raise ValueError("recovery event sequence is not contiguous")
        if saw_terminal:
            raise ValueError("recovery event follows a terminal event")
        if len(events) >= MAX_RECOVERY_EVENTS:
            raise ValueError("recovery contains too many events")
        events.append(event)
        last_sequence = event.sequence
        saw_terminal = event.kind is RecoveryEventKind.TERMINAL

    durable_events = tuple(events)
    session = _session_from_v3(header, base_history, durable_events)
    return RecoveryLoadResult(
        journal_path,
        status,
        session,
        durable_events,
        error,
    )


def load_recovery_candidate(
    path: str | os.PathLike[str], *, max_bytes: int = 64 << 20
) -> RecoveryLoadResult:
    journal_path = Path(path)
    if type(max_bytes) is not int or max_bytes <= 0:
        raise ValueError("recovery byte limit must be positive")
    try:
        if journal_path.stat().st_size > max_bytes:
            raise ValueError("recovery journal exceeds its byte limit")
        with journal_path.open("rb") as handle:
            first = handle.readline(MAX_RECOVERY_RECORD_BYTES + 2)
            if not first or len(first) > MAX_RECOVERY_RECORD_BYTES:
                raise ValueError("recovery header is missing or too large")
            if not first.endswith(b"\n"):
                raise ValueError("recovery header is truncated")
            header_value = _decode_json_line(first, "recovery header")
            header = _require_mapping(header_value, "recovery header")
            if header.get("type") != "header":
                raise ValueError("recovery journal must begin with header")
            version = _require_plain_int(
                header.get("format"), "recovery journal format", minimum=1
            )
            if version > RECOVERY_FORMAT_VERSION:
                raise _UnsupportedRecovery("future recovery journal format")
            if version not in (1, 2, RECOVERY_FORMAT_VERSION):
                raise ValueError("unsupported recovery journal format")
            if version in (1, 2):
                session = _load_legacy_recovery(journal_path)
                return RecoveryLoadResult(
                    journal_path,
                    RecoveryLoadStatus.COMPLETE,
                    session,
                    (),
                )
            return _read_v3_candidate(
                journal_path,
                handle,
                header,
                consumed_bytes=len(first),
                max_bytes=max_bytes,
            )
    except _UnsupportedRecovery as exc:
        return RecoveryLoadResult(
            journal_path,
            RecoveryLoadStatus.UNSUPPORTED,
            None,
            (),
            str(exc),
        )
    except (OSError, TypeError, ValueError, KeyError) as exc:
        return RecoveryLoadResult(
            journal_path,
            RecoveryLoadStatus.CORRUPT,
            None,
            (),
            str(exc),
        )


def load_recovery(path: str | os.PathLike[str]) -> RecoverySession:
    result = load_recovery_candidate(path)
    if result.session is not None and result.status in {
        RecoveryLoadStatus.COMPLETE,
        RecoveryLoadStatus.TRUNCATED_TAIL,
    }:
        return result.session
    raise ValueError(result.error or "recovery journal could not be loaded")


def _apply_recovery_metadata(document: "Document", event: RecoveryEvent) -> None:
    if not event.metadata:
        return
    profile_key = event.metadata.get("output_profile_key")
    output_encoding = event.metadata.get("output_encoding")
    output_eol = event.metadata.get("output_eol", document.output_eol)
    if output_eol not in _EOL_VALUES:
        raise RecoveryReplayError("recovery output EOL is invalid")
    try:
        profile = (
            encoding_profile(profile_key)
            if isinstance(profile_key, str)
            else (
                encoding_profile(output_encoding)
                if isinstance(output_encoding, str)
                else document.output_format.encoding
            )
        )
        document.set_output_format(
            OutputFormat(
                profile,
                EOLPolicy.PRESERVE
                if output_eol is None
                else EOLPolicy(output_eol),
            )
        )
    except ValueError as exc:
        raise RecoveryReplayError("recovery output metadata is invalid") from exc


def _validate_replayed_event(
    document: "Document",
    event: RecoveryEvent,
    revision_offset: int,
) -> None:
    history = document.export_history()
    if history.cursor != event.cursor or history.saved_cursor != event.saved_cursor:
        raise RecoveryReplayError("recovery history cursor does not match event")
    if document.revision + revision_offset != event.revision:
        raise RecoveryReplayError("recovery document revision does not match event")


def replay_recovery(document: "Document", session: RecoverySession) -> None:
    if session.clean:
        return
    if session.format_version in (1, 2):
        try:
            actual_identity = FileIdentity.from_path(document.source.path)
        except OSError as exc:
            raise RecoverySourceMismatchError(
                "recovery source is unavailable"
            ) from exc
        if actual_identity != session.source_identity:
            raise RecoverySourceMismatchError("recovery source identity has changed")
        for operation in session.operations:
            end = operation.start + len(operation.deleted_text)
            try:
                current = document.read(operation.start, end)
            except ValueError as exc:
                raise RecoveryReplayError(
                    "recovery edit range is outside document"
                ) from exc
            if current != operation.deleted_text:
                raise RecoveryReplayError(
                    "recovery deleted text does not match document"
                )
            document.replace(operation.start, end, operation.inserted_text)
        return

    if session.format_version != RECOVERY_FORMAT_VERSION or session.base_hash is None:
        raise RecoveryReplayError("recovery session format is unsupported")
    try:
        actual_hash = sha256_file(document.source.path)
    except OSError as exc:
        raise RecoverySourceMismatchError("recovery source is unavailable") from exc
    if actual_hash != session.base_hash:
        raise RecoverySourceMismatchError("recovery source content has changed")
    try:
        document.restore_history(session.base_history)
    except (TypeError, ValueError) as exc:
        raise RecoveryReplayError("recovery base history is invalid") from exc

    revision_offset: int | None = None
    for event in session.events:
        try:
            if event.kind is RecoveryEventKind.TRANSACTION:
                assert event.transaction is not None
                coalesce = event.metadata.get("history_coalesce")
                if coalesce is not None and not isinstance(coalesce, str):
                    raise RecoveryReplayError(
                        "recovery history coalescing value is invalid"
                    )
                document.replay_transaction(
                    event.transaction,
                    coalesce=coalesce,
                )
            elif event.kind is RecoveryEventKind.UNDO:
                document.undo()
            elif event.kind is RecoveryEventKind.REDO:
                document.redo()
            elif event.kind is RecoveryEventKind.METADATA:
                _apply_recovery_metadata(document, event)
            elif event.kind is RecoveryEventKind.SAVE_POINT:
                _apply_recovery_metadata(document, event)
                document.replay_save_point()
            elif event.kind is RecoveryEventKind.TERMINAL:
                pass
            else:
                raise RecoveryReplayError("recovery event kind cannot be replayed")
        except RecoveryReplayError:
            raise
        except (TypeError, ValueError) as exc:
            raise RecoveryReplayError("recovery semantic event could not be replayed") from exc
        if revision_offset is None:
            revision_offset = event.revision - document.revision
        _validate_replayed_event(document, event, revision_offset)
