"""Incremental crash-recovery journal primitives for UNITI."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from .file_identity import FileIdentity
from .history import EditOperation

if TYPE_CHECKING:
    from .document import Document


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

    @property
    def encoding(self) -> str:
        """Compatibility alias for alpha10 journals/tests."""
        return self.source_encoding


class RecoverySourceMismatchError(RuntimeError):
    pass


class RecoveryReplayError(RuntimeError):
    pass


class RecoveryJournal:
    """Append-only JSONL journal flushed after each durable record."""

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
        source_encoding: str | None = None,
        output_encoding: str | None = None,
        output_eol: str | None = None,
        encoding: str | None = None,
    ) -> "RecoveryJournal":
        # ``encoding`` is accepted for alpha10 callers. In that format source
        # and output were conflated, so using it for both is the only safe
        # compatibility interpretation.
        if source_encoding is None:
            source_encoding = encoding
        if source_encoding is None:
            raise TypeError("source_encoding is required")
        if output_encoding is None:
            output_encoding = source_encoding if encoding is None else encoding

        journal_path = Path(path)
        source = Path(source_path)
        identity = FileIdentity.from_path(source)
        handle = journal_path.open("w", encoding="utf-8", newline="\n")
        journal = cls(journal_path, handle)
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

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("RecoveryJournal is closed")

    def _write_record(
        self, record: dict[str, object], *, durable: bool = True
    ) -> None:
        self._ensure_open()
        self._handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
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
        self._write_record(
            {
                "type": "edit",
                "start": operation.start,
                "deleted": operation.deleted_text,
                "inserted": operation.inserted_text,
            },
            durable=durable,
        )

    def update_metadata(
        self,
        *,
        output_encoding: str,
        output_eol: str | None,
        durable: bool = True,
    ) -> None:
        self._write_record(
            {
                "type": "metadata",
                "output_encoding": output_encoding,
                "output_eol": output_eol,
            },
            durable=durable,
        )

    def mark_clean(self, *, durable: bool = True) -> None:
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


def load_recovery(path: str | os.PathLike[str]) -> RecoverySession:
    journal_path = Path(path)
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
            elif record_type == "metadata":
                if "output_encoding" in record:
                    output_encoding = str(record["output_encoding"])
                output_eol = (
                    None if record.get("output_eol") is None else str(record["output_eol"])
                )
            elif record_type == "clean":
                clean = True
            else:
                raise ValueError(f"unknown recovery record type: {record_type!r}")

    if header is None:
        raise ValueError("recovery journal has no header")
    version = int(header.get("format", 0))
    if version not in (1, 2):
        raise ValueError("unsupported recovery journal format")

    if version == 1:
        # Alpha10 conflated source/output. Treat the value as the source
        # decoder and preserve it as output only because no safer metadata
        # exists in the old format.
        source_encoding = str(header["encoding"])
        initial_output_encoding = source_encoding
        initial_output_eol = None
    else:
        source_encoding = str(header["source_encoding"])
        initial_output_encoding = str(header.get("output_encoding", source_encoding))
        initial_output_eol = (
            None if header.get("output_eol") is None else str(header["output_eol"])
        )

    return RecoverySession(
        source_path=Path(str(header["source_path"])),
        source_identity=FileIdentity(
            size=int(header["source_size"]),
            mtime_ns=int(header["source_mtime_ns"]),
            inode=(None if header.get("source_inode") is None else int(header["source_inode"])),
            device=(None if header.get("source_device") is None else int(header["source_device"])),
        ),
        source_encoding=source_encoding,
        output_encoding=output_encoding or initial_output_encoding,
        output_eol=initial_output_eol if output_eol is None else output_eol,
        operations=tuple(operations),
        clean=clean,
        format_version=version,
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
