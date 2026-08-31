"""Incremental crash-recovery journal primitives for UNITI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO, TYPE_CHECKING

from .file_identity import FileIdentity
from .history import EditOperation

if TYPE_CHECKING:
    from .document import Document


@dataclass(frozen=True, slots=True)
class RecoverySession:
    source_path: Path
    source_identity: FileIdentity
    encoding: str
    operations: tuple[EditOperation, ...]
    clean: bool


class RecoverySourceMismatchError(RuntimeError):
    pass


class RecoveryReplayError(RuntimeError):
    pass


class RecoveryJournal:
    """Append-only JSONL journal flushed after each durable edit record."""

    def __init__(self, path: Path, handle: TextIO) -> None:
        self.path = path
        self._handle = handle
        self._closed = False

    @classmethod
    def create(
        cls,
        path: str | os.PathLike[str],
        source_path: str | os.PathLike[str],
        *,
        encoding: str,
    ) -> "RecoveryJournal":
        journal_path = Path(path)
        source = Path(source_path)
        identity = FileIdentity.from_path(source)
        handle = journal_path.open("w", encoding="utf-8", newline="\n")
        journal = cls(journal_path, handle)
        journal._write_record(
            {
                "type": "header",
                "format": 1,
                "source_path": str(source),
                "source_size": identity.size,
                "source_mtime_ns": identity.mtime_ns,
                "encoding": encoding,
                "source_inode": identity.inode,
                "source_device": identity.device,
            }
        )
        return journal

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("RecoveryJournal is closed")

    def _write_record(self, record: dict[str, object]) -> None:
        self._ensure_open()
        self._handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
        self._handle.write("\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def append(self, operation: EditOperation) -> None:
        self._write_record(
            {
                "type": "edit",
                "start": operation.start,
                "deleted": operation.deleted_text,
                "inserted": operation.inserted_text,
            }
        )

    def mark_clean(self) -> None:
        self._write_record({"type": "clean"})

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


def load_recovery(path: str | os.PathLike[str]) -> RecoverySession:
    journal_path = Path(path)
    header: dict[str, object] | None = None
    operations: list[EditOperation] = []
    clean = False
    with journal_path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid recovery JSON at line {line_number}") from exc
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
            elif record_type == "clean":
                clean = True
            else:
                raise ValueError(f"unknown recovery record type: {record_type!r}")
    if header is None:
        raise ValueError("recovery journal has no header")
    if int(header.get("format", 0)) != 1:
        raise ValueError("unsupported recovery journal format")
    return RecoverySession(
        source_path=Path(str(header["source_path"])),
        source_identity=FileIdentity(
            size=int(header["source_size"]),
            mtime_ns=int(header["source_mtime_ns"]),
            inode=(None if header.get("source_inode") is None else int(header["source_inode"])),
            device=(None if header.get("source_device") is None else int(header["source_device"])),
        ),
        encoding=str(header["encoding"]),
        operations=tuple(operations),
        clean=clean,
    )


def replay_recovery(document: "Document", session: RecoverySession) -> None:
    if session.clean:
        return
    try:
        actual_identity = FileIdentity.from_path(document.source.path)
    except OSError as exc:
        raise RecoverySourceMismatchError("recovery source is unavailable") from exc
    if actual_identity != session.source_identity:
        raise RecoverySourceMismatchError("recovery source identity has changed")
    for operation in session.operations:
        end = operation.start + len(operation.deleted_text)
        try:
            current = document.read(operation.start, end)
        except ValueError as exc:
            raise RecoveryReplayError("recovery edit range is outside document") from exc
        if current != operation.deleted_text:
            raise RecoveryReplayError("recovery deleted text does not match document")
        document.replace(operation.start, end, operation.inserted_text)
