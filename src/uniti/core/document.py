"""Qt-independent UNITI document facade."""

from __future__ import annotations

import codecs
import os
from collections.abc import Callable, Iterator, Mapping
from dataclasses import replace as dataclass_replace
from pathlib import Path
from typing import TYPE_CHECKING, Hashable

if TYPE_CHECKING:
    from uniti.resources.manager import ResourceManager

from .byte_source import ByteSource
from .encoding import EncodingInfo, detect_encoding, matching_bom
from .eol import EOLReport, analyze_eol
from .document_lines import DocumentLineIndex
from .file_identity import ExternalFileChangedError, FileIdentity
from .history import (
    EditHistory,
    EditOperation,
    EditTransaction,
    HistoryEvent,
    HistoryEventKind,
    HistorySnapshot,
)
from .lines import LineIndex
from .offsets import OffsetMapper, ReadIntent
from .pieces import AnnotatedChunk, AnnotatedText, EditStore, PieceTable
from .save import (
    EOLName,
    StaleDocumentRevisionError,
    commit_staged_document,
    stage_document,
    verify_staged_document,
)
from .save_job import (
    DocumentSaveRequest,
    ImmediateSaveContext,
    PreparedDocumentSave,
    prepare_document_save,
)
from .text_format import (
    EOLPolicy,
    EncodingProfile,
    OutputFormat,
    profile_from_codec,
)


def _decoder_encoding(profile: EncodingProfile) -> str:
    if profile.key == "utf-8-bom":
        return "utf-8-sig"
    return profile.codec


def _output_profile_from_encoding(encoding: str) -> EncodingProfile:
    try:
        normalized = codecs.lookup(encoding).name
    except LookupError as exc:
        raise ValueError(f"unknown output encoding: {encoding}") from exc
    bom = b"\xef\xbb\xbf" if normalized == "utf-8-sig" else None
    return profile_from_codec(encoding, bom)


class _UnspecifiedDestinationIdentity:
    pass


_UNSPECIFIED_DESTINATION_IDENTITY = _UnspecifiedDestinationIdentity()


class ReplacementPlanLimitError(MemoryError):
    """A replacement transaction exceeds its admitted apply-memory bound."""


class Document:
    """Own the lazy immutable-source services and edited piece table."""

    def __init__(
        self,
        source: ByteSource,
        encoding_info: EncodingInfo,
        source_profile: EncodingProfile,
        offset_mapper: OffsetMapper,
        source_line_index: LineIndex,
        piece_table: PieceTable,
        document_line_index: DocumentLineIndex,
        resource_manager: "ResourceManager | None" = None,
        cache_owner: Hashable | None = None,
        source_eol_report: EOLReport | None = None,
    ) -> None:
        self._source = source
        self._path = source.path
        self._source_identity = FileIdentity.from_path(source.path)
        self._disk_identity = self._source_identity
        self._encoding_info = encoding_info
        self._source_profile = source_profile
        self._piece_source_profile = source_profile
        self._offset_mapper = offset_mapper
        self._source_line_index = source_line_index
        self._piece_table = piece_table
        self._document_line_index = document_line_index
        self._source_eol_report = source_eol_report
        self._insertion_eol_override: EOLName | None = None
        self._history = EditHistory()
        self._output_format = OutputFormat(
            encoding=source_profile,
            eol=EOLPolicy.PRESERVE,
        )
        self._saved_output_format = self._output_format
        self._revision = 0
        self._edit_listeners: list[Callable[[EditOperation], None]] = []
        self._save_listeners: list[Callable[[Path], None]] = []
        self._metadata_listeners: list[Callable[[str, EOLName | None], None]] = []
        self._history_listeners: list[Callable[[HistoryEvent], None]] = []
        self._resource_manager = resource_manager
        self._cache_owner = cache_owner
        self._closed = False

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        encoding: str | None = None,
        profile: EncodingProfile | None = None,
        resource_manager: "ResourceManager | None" = None,
    ) -> "Document":
        if encoding is not None and profile is not None:
            raise ValueError("profile and encoding cannot both be specified")
        source = ByteSource.open(path)
        try:
            if profile is not None:
                source_profile = profile
                selected = _decoder_encoding(source_profile)
                encoding_info = EncodingInfo(
                    detected=selected,
                    confidence=1.0,
                    bom=source_profile.bom or None,
                    user_override=True,
                    output_encoding=source_profile.codec,
                )
            elif encoding is None:
                encoding_info = detect_encoding(source)
                source_profile = profile_from_codec(
                    encoding_info.detected,
                    encoding_info.bom,
                )
                selected = encoding_info.detected
            else:
                bom = matching_bom(source, encoding)
                source_profile = profile_from_codec(encoding, bom)
                selected = _decoder_encoding(source_profile)
                encoding_info = EncodingInfo(
                    detected=selected,
                    confidence=1.0,
                    bom=bom,
                    user_override=True,
                    output_encoding=source_profile.codec,
                )
            cache_owner = object()
            mapper = OffsetMapper(
                source,
                selected,
                resource_manager=resource_manager,
                cache_owner=cache_owner,
            )
            source_line_index = LineIndex(source, selected)
            source_eol_report = analyze_eol(
                source, encoding=selected, end=min(source.size, 65_536)
            )
            edit_store = EditStore()
            piece_table = PieceTable(source, selected, mapper, edit_store)
            if resource_manager is None:
                document_line_index = DocumentLineIndex(piece_table)
            else:
                document_line_index = DocumentLineIndex(
                    piece_table,
                    resource_manager=resource_manager,
                    cache_owner=cache_owner,
                )
            return cls(
                source,
                encoding_info,
                source_profile,
                mapper,
                source_line_index,
                piece_table,
                document_line_index,
                resource_manager,
                cache_owner,
                source_eol_report,
            )
        except Exception:
            source.close()
            raise

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("Document is closed")

    @property
    def source(self) -> ByteSource:
        return self._source

    @property
    def path(self) -> Path:
        return self._path

    @property
    def disk_identity(self) -> FileIdentity:
        return self._disk_identity

    @property
    def encoding_info(self) -> EncodingInfo:
        return self._encoding_info

    @property
    def source_profile(self) -> EncodingProfile:
        return self._source_profile

    @property
    def offset_mapper(self) -> OffsetMapper:
        return self._offset_mapper

    @property
    def source_line_index(self) -> LineIndex:
        """Progressive line index for the immutable source bytes only."""

        return self._source_line_index

    @property
    def document_line_index(self) -> DocumentLineIndex:
        """Progressive line index for the current edited document."""

        return self._document_line_index

    @property
    def output_eol(self) -> EOLName | None:
        if self._output_format.eol is EOLPolicy.PRESERVE:
            return None
        return self._output_format.eol.value  # type: ignore[return-value]

    @property
    def output_format(self) -> OutputFormat:
        return self._output_format

    @property
    def saved_output_format(self) -> OutputFormat:
        return self._saved_output_format

    @property
    def source_eol_report(self) -> EOLReport | None:
        return self._source_eol_report

    @property
    def insertion_eol(self) -> EOLName:
        if self._insertion_eol_override is not None:
            return self._insertion_eol_override
        report = self._source_eol_report
        if report is None or (report.lf == 0 and report.crlf == 0 and report.cr == 0):
            return "LF"
        counts = ((report.crlf, "CRLF"), (report.lf, "LF"), (report.cr, "CR"))
        return max(counts, key=lambda item: item[0])[1]  # type: ignore[return-value]

    def set_insertion_eol(self, eol: EOLName | None) -> None:
        self._ensure_open()
        if eol not in (None, "LF", "CRLF", "CR"):
            raise ValueError(f"unsupported insertion EOL policy: {eol}")
        self._insertion_eol_override = eol

    def set_source_eol_report(self, report: EOLReport) -> None:
        self._ensure_open()
        self._source_eol_report = report

    @property
    def output_encoding(self) -> str:
        return self._output_format.encoding.codec

    @property
    def revision(self) -> int:
        """Monotonic logical-text revision used to invalidate derived results."""

        return self._revision

    def set_resource_active(self, active: bool) -> None:
        if self._resource_manager is not None and self._cache_owner is not None:
            self._resource_manager.set_owner_active(self._cache_owner, active)

    def snapshot(self):
        """Capture immutable source/edit state for independently cancellable work."""

        self._ensure_open()
        from .snapshot import DocumentReadSnapshot

        source = self._source.fork()
        try:
            pieces = self._piece_table.snapshot(source)
            return DocumentReadSnapshot(
                revision=self._revision,
                path=self._path,
                disk_identity=self._disk_identity,
                source_profile=self._piece_source_profile,
                output_format=self._output_format,
                _source=source,
                _piece_table=pieces,
            )
        except Exception:
            source.close()
            raise

    @property
    def modified(self) -> bool:
        return self._history.modified or self._output_format != self._saved_output_format

    def set_output_format(self, output_format: OutputFormat) -> None:
        self._ensure_open()
        if not isinstance(output_format, OutputFormat):
            raise TypeError("output format must be an OutputFormat")
        if output_format == self._output_format:
            return
        self._output_format = output_format
        self._encoding_info = dataclass_replace(
            self._encoding_info,
            output_encoding=output_format.encoding.codec,
        )
        self._notify_metadata()

    def set_output_encoding(self, encoding: str) -> None:
        self._ensure_open()
        if not isinstance(encoding, str) or not encoding:
            raise ValueError("output encoding must be a non-empty string")
        profile = _output_profile_from_encoding(encoding)
        self.set_output_format(
            OutputFormat(
                encoding=profile,
                eol=self._output_format.eol,
            )
        )

    def set_output_eol(self, eol: EOLName | None) -> None:
        self._ensure_open()
        if eol not in (None, "LF", "CRLF", "CR"):
            raise ValueError(f"unsupported EOL policy: {eol}")
        policy = EOLPolicy.PRESERVE if eol is None else EOLPolicy(eol)
        self.set_output_format(
            OutputFormat(
                encoding=self._output_format.encoding,
                eol=policy,
            )
        )

    def add_edit_listener(self, listener: Callable[[EditOperation], None]) -> Callable[[], None]:
        self._ensure_open()
        self._edit_listeners.append(listener)

        def remove() -> None:
            try:
                self._edit_listeners.remove(listener)
            except ValueError:
                pass

        return remove

    def add_save_listener(self, listener: Callable[[Path], None]) -> Callable[[], None]:
        self._ensure_open()
        self._save_listeners.append(listener)

        def remove() -> None:
            try:
                self._save_listeners.remove(listener)
            except ValueError:
                pass

        return remove

    def add_metadata_listener(
        self,
        listener: Callable[[str, EOLName | None], None],
    ) -> Callable[[], None]:
        self._ensure_open()
        self._metadata_listeners.append(listener)

        def remove() -> None:
            try:
                self._metadata_listeners.remove(listener)
            except ValueError:
                pass

        return remove

    def add_history_listener(
        self,
        listener: Callable[[HistoryEvent], None],
    ) -> Callable[[], None]:
        self._ensure_open()
        self._history_listeners.append(listener)

        def remove() -> None:
            try:
                self._history_listeners.remove(listener)
            except ValueError:
                pass

        return remove

    def _notify_edit(self, operation: EditOperation) -> None:
        for listener in tuple(self._edit_listeners):
            listener(operation)

    def _notify_save(self, path: Path) -> None:
        for listener in tuple(self._save_listeners):
            listener(path)

    def _notify_metadata(self) -> None:
        for listener in tuple(self._metadata_listeners):
            listener(self.output_encoding, self.output_eol)
        self._notify_history(
            HistoryEventKind.METADATA,
            metadata=self._history_metadata(),
        )

    def _history_metadata(self) -> dict[str, object]:
        return {
            "output_profile_key": self._output_format.encoding.key,
            "output_encoding": self.output_encoding,
            "output_eol": self.output_eol,
        }

    def _notify_history(
        self,
        kind: HistoryEventKind,
        transaction: EditTransaction | None = None,
        coalesce: str | None = None,
        metadata: Mapping[str, object] | None = None,
    ) -> None:
        event = HistoryEvent(
            kind=kind,
            transaction=transaction,
            cursor=self._history.cursor,
            saved_cursor=self._history.saved_cursor,
            revision=self._revision,
            coalesce=coalesce,
            metadata=dict(metadata or {}),
        )
        for listener in tuple(self._history_listeners):
            listener(event)

    def export_history(
        self,
        *,
        max_transactions: int = 50,
        max_bytes: int = 32 << 20,
    ) -> HistorySnapshot:
        self._ensure_open()
        return self._history.export_snapshot(
            max_transactions=max_transactions,
            max_bytes=max_bytes,
        )

    def restore_history(self, snapshot: HistorySnapshot) -> None:
        self._ensure_open()
        if self._revision != 0:
            raise ValueError("document must be pristine before history restore")
        self._history.restore(snapshot)

    @property
    def can_undo(self) -> bool:
        return self._history.can_undo

    @property
    def can_redo(self) -> bool:
        return self._history.can_redo

    def read(
        self,
        start: int,
        end: int,
        *,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> str:
        self._ensure_open()
        return self._piece_table.read(start, end, intent=intent)

    def read_with_annotations(
        self,
        start: int,
        end: int,
        *,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> AnnotatedText:
        self._ensure_open()
        return self._piece_table.read_with_annotations(start, end, intent=intent)

    def iter_text(
        self,
        start: int = 0,
        end: int | None = None,
        *,
        chunk_chars: int = 65_536,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> Iterator[tuple[int, str]]:
        self._ensure_open()
        return self._piece_table.iter_text(
            start,
            end,
            chunk_chars=chunk_chars,
            intent=intent,
        )

    def iter_annotated_text(
        self,
        start: int = 0,
        end: int | None = None,
        *,
        chunk_chars: int = 65_536,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> Iterator[AnnotatedChunk]:
        self._ensure_open()
        return self._piece_table.iter_annotated_text(
            start,
            end,
            chunk_chars=chunk_chars,
            intent=intent,
        )

    def _replace_internal(
        self,
        start: int,
        end: int,
        text: str,
        *,
        record: bool,
        coalesce: str | None = None,
    ) -> EditOperation | None:
        deleted = self._piece_table.read(start, end)
        if deleted == text:
            annotated = self._piece_table.read_with_annotations(start, end)
            if not annotated.invalid_bytes:
                return None
        self._piece_table.replace(start, end, text)
        self._document_line_index.invalidate_from_char(start)
        self._revision += 1
        operation = EditOperation(start, deleted, text)
        if record:
            transaction = EditTransaction((operation,))
            self._history.record(transaction, coalesce=coalesce)
            self._notify_history(
                HistoryEventKind.TRANSACTION,
                transaction,
                coalesce=coalesce,
            )
        self._notify_edit(operation)
        return operation

    def insert(
        self,
        char_offset: int,
        text: str,
        *,
        coalesce: str | None = None,
    ) -> None:
        self._ensure_open()
        self._replace_internal(
            char_offset,
            char_offset,
            text,
            record=True,
            coalesce=coalesce,
        )

    def delete(
        self,
        start: int,
        end: int,
        *,
        coalesce: str | None = None,
    ) -> None:
        self._ensure_open()
        self._replace_internal(start, end, "", record=True, coalesce=coalesce)

    def replace(
        self,
        start: int,
        end: int,
        text: str,
        *,
        coalesce: str | None = None,
    ) -> None:
        self._ensure_open()
        self._replace_internal(start, end, text, record=True, coalesce=coalesce)

    def break_history_coalescing(self) -> None:
        self._history.break_coalescing()

    def replace_many(self, replacements: list[tuple[int, int, str]]) -> int:
        """Apply non-overlapping original-coordinate replacements as one history step."""
        self._ensure_open()
        prepared: list[tuple[int, int, str, str]] = []
        previous_end = 0
        for index, (start, end, text) in enumerate(replacements):
            if start < 0 or end < start:
                raise ValueError("invalid replacement range")
            if index and start < previous_end:
                raise ValueError("replacement ranges must be sorted and non-overlapping")
            deleted = self._piece_table.read(start, end)
            prepared.append((start, end, text, deleted))
            previous_end = end

        delta = 0
        operations: list[EditOperation] = []
        for start, end, text, deleted in prepared:
            actual_start = start + delta
            actual_end = actual_start + len(deleted)
            operation = self._replace_internal(
                actual_start,
                actual_end,
                text,
                record=False,
            )
            if operation is not None:
                operations.append(operation)
            delta += len(text) - len(deleted)
        transaction = EditTransaction(tuple(operations))
        self._history.record(transaction)
        if operations:
            self._notify_history(HistoryEventKind.TRANSACTION, transaction)
        return len(prepared)

    def apply_replacement_plan(
        self,
        plan,
        *,
        expected_revision: int,
        memory_limit_bytes: int,
    ) -> int:
        """Atomically apply one admitted, revision-bound replacement plan."""

        self._ensure_open()
        if memory_limit_bytes <= 0:
            raise ValueError("memory_limit_bytes must be positive")
        if (
            expected_revision != self._revision
            or plan.document_revision != expected_revision
        ):
            raise StaleDocumentRevisionError(
                "replacement plan no longer matches the document revision"
            )
        if plan.estimate.apply_bytes > memory_limit_bytes:
            raise ReplacementPlanLimitError(
                "replacement plan requires "
                f"{plan.estimate.apply_bytes:,} apply bytes; "
                f"limit is {memory_limit_bytes:,}"
            )
        operations = self._piece_table.replace_many_bulk(plan)
        if not operations:
            return 0
        self._document_line_index.invalidate_from_char(operations[0].start)
        self._revision += 1
        transaction = EditTransaction(operations)
        self._history.record(transaction)
        self._notify_history(HistoryEventKind.TRANSACTION, transaction)
        for operation in operations:
            self._notify_edit(operation)
        return len(operations)

    def undo(self) -> None:
        self._ensure_open()
        transaction = self._history.undo()
        for operation in reversed(transaction.operations):
            self._replace_internal(
                operation.start,
                operation.start + len(operation.inserted_text),
                operation.deleted_text,
                record=False,
            )
        self._notify_history(HistoryEventKind.UNDO, transaction)

    def redo(self) -> None:
        self._ensure_open()
        transaction = self._history.redo()
        for operation in transaction.operations:
            self._replace_internal(
                operation.start,
                operation.start + len(operation.deleted_text),
                operation.inserted_text,
                record=False,
            )
        self._notify_history(HistoryEventKind.REDO, transaction)

    def line_count(self) -> int:
        self._ensure_open()
        return self._document_line_index.total_lines()

    def line_start(self, line: int) -> int:
        self._ensure_open()
        return self._document_line_index.line_start(line)

    def line_for_char(self, char_offset: int) -> int:
        self._ensure_open()
        return self._document_line_index.line_for_char(char_offset)

    def line_end(self, line: int) -> int:
        """Return the logical content end for *line* without materializing it."""

        self._ensure_open()
        start = self._document_line_index.line_start(line)
        try:
            next_start = self._document_line_index.line_start(line + 1)
        except ValueError:
            return self._piece_table.total_chars()

        probe_start = max(start, next_start - 2)
        tail = self._piece_table.read(probe_start, next_start)
        if tail.endswith("\r\n"):
            return next_start - 2
        if tail.endswith(("\r", "\n")):
            return next_start - 1
        return next_start

    def read_line(self, line: int, *, keep_eol: bool = False) -> str:
        self._ensure_open()
        start = self._document_line_index.line_start(line)
        try:
            end = self._document_line_index.line_start(line + 1)
        except ValueError:
            end = self._piece_table.total_chars()
        text = self._piece_table.read(start, end)
        if keep_eol:
            return text
        if text.endswith("\r\n"):
            return text[:-2]
        if text.endswith(("\r", "\n")):
            return text[:-1]
        return text

    def read_line_window(
        self,
        line: int,
        *,
        column_start: int = 0,
        max_chars: int = 4096,
    ) -> str:
        """Read a bounded visible slice of one logical line.

        Unlike :meth:`read_line`, this method never needs to discover the
        next line start merely to return a viewport-sized prefix. That keeps
        a single enormous line renderable without materializing or indexing
        the complete line.
        """

        self._ensure_open()
        if line < 0 or column_start < 0:
            raise ValueError("line and column_start must be non-negative")
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")

        line_start = self._document_line_index.line_start(line)
        absolute_start = line_start + column_start
        try:
            if self._document_line_index.line_for_char(absolute_start) != line:
                return ""
        except ValueError:
            return ""

        iterator = self._piece_table.iter_text(
            absolute_start,
            chunk_chars=max_chars + 2,
        )
        try:
            chunk_start, text = next(iterator)
        except StopIteration:
            return ""
        if chunk_start != absolute_start:
            raise RuntimeError("piece-table iterator returned a discontinuous line window")

        visible_end = min(len(text), max_chars)
        for index, char in enumerate(text[: max_chars + 1]):
            if char in "\r\n":
                visible_end = min(visible_end, index)
                break
        return text[:visible_end]

    def read_line_window_annotated(
        self,
        line: int,
        *,
        column_start: int = 0,
        max_chars: int = 4096,
    ) -> AnnotatedText:
        text = self.read_line_window(
            line, column_start=column_start, max_chars=max_chars
        )
        line_start = self._document_line_index.line_start(line)
        absolute_start = line_start + column_start
        if not text:
            return AnnotatedText("", ())
        return self._piece_table.read_with_annotations(
            absolute_start, absolute_start + len(text)
        )

    def read_lines(
        self,
        first: int,
        count: int,
        *,
        keep_eol: bool = False,
    ) -> list[str]:
        self._ensure_open()
        if first < 0 or count < 0:
            raise ValueError("line range must be non-negative")
        return [
            self.read_line(line, keep_eol=keep_eol)
            for line in range(first, first + count)
        ]

    def assert_safe_overwrite(
        self,
        destination: str | os.PathLike[str] | None = None,
    ) -> None:
        """Raise when streaming/Save would overwrite externally changed bytes."""

        self._ensure_open()
        target = self._path if destination is None else Path(destination)
        try:
            source_actual = FileIdentity.from_path(self._source.path)
        except OSError:
            source_actual = None
        if source_actual is not None and source_actual != self._source_identity:
            same_backing_file = (
                source_actual.device == self._source_identity.device
                and source_actual.inode == self._source_identity.inode
            )
            if same_backing_file:
                raise ExternalFileChangedError(
                    self._source.path,
                    self._source_identity,
                    source_actual,
                )
        if target == self._path:
            try:
                actual_identity = FileIdentity.from_path(target)
            except OSError:
                actual_identity = None
            if actual_identity != self._disk_identity:
                raise ExternalFileChangedError(
                    target,
                    self._disk_identity,
                    actual_identity,
                )

    @staticmethod
    def _same_resolved_file(left: Path, right: Path) -> bool:
        if left.resolve(strict=False) == right.resolve(strict=False):
            return True
        try:
            return os.path.samefile(left, right)
        except OSError:
            return False

    def create_save_request(
        self,
        destination: str | os.PathLike[str],
        output_format: OutputFormat,
        *,
        expected_destination_identity: (
            FileIdentity | None | _UnspecifiedDestinationIdentity
        ) = _UNSPECIFIED_DESTINATION_IDENTITY,
    ) -> DocumentSaveRequest:
        """Capture one revision and target identity for staged output work."""

        self._ensure_open()
        if not isinstance(output_format, OutputFormat):
            raise TypeError("output_format must be an OutputFormat")
        target = Path(destination)
        self.assert_safe_overwrite(target)
        try:
            actual_identity = FileIdentity.from_path(target)
        except FileNotFoundError:
            actual_identity = None
        if (
            expected_destination_identity
            is not _UNSPECIFIED_DESTINATION_IDENTITY
            and actual_identity != expected_destination_identity
        ):
            assert expected_destination_identity is None or isinstance(
                expected_destination_identity, FileIdentity
            )
            raise ExternalFileChangedError(
                target,
                expected_destination_identity,
                actual_identity,
            )
        expected = (
            actual_identity
            if expected_destination_identity is _UNSPECIFIED_DESTINATION_IDENTITY
            else expected_destination_identity
        )
        assert expected is None or isinstance(expected, FileIdentity)
        snapshot = self.snapshot()
        return DocumentSaveRequest(
            snapshot=snapshot,
            destination=target,
            output_format=output_format,
            expected_destination_identity=expected,
            in_place=self._same_resolved_file(self._path, target),
        )

    def _validate_prepared_save(
        self,
        prepared: PreparedDocumentSave,
        *,
        in_place: bool,
    ) -> None:
        self._ensure_open()
        if not isinstance(prepared, PreparedDocumentSave):
            raise TypeError("prepared must be a PreparedDocumentSave")
        request = prepared.request
        if request.in_place is not in_place:
            operation = "Save" if in_place else "export"
            raise ValueError(f"prepared request is not an in-place {operation}")
        if (
            request.snapshot.revision != self._revision
            or request.snapshot.output_format != self._output_format
        ):
            raise StaleDocumentRevisionError(
                "document text or output format changed while save was staged"
            )
        self.assert_safe_overwrite(request.destination)

    def commit_prepared_save(self, prepared: PreparedDocumentSave) -> Path:
        """Commit verified in-place output and advance the document save point."""

        self._validate_prepared_save(prepared, in_place=True)
        selected = prepared.request.output_format
        result = commit_staged_document(prepared.staged)
        self._reload_verified_save(selected)
        if selected.eol is not EOLPolicy.PRESERVE:
            self._history = EditHistory()
            self._revision += 1
        else:
            self._history.mark_saved()
        self._output_format = selected
        self._saved_output_format = selected
        self._notify_history(
            HistoryEventKind.SAVE_POINT,
            metadata=self._history_metadata(),
        )
        self._notify_save(result)
        return result

    def commit_prepared_export(self, prepared: PreparedDocumentSave) -> Path:
        """Commit verified output to another path without retargeting source."""

        self._validate_prepared_save(prepared, in_place=False)
        return commit_staged_document(prepared.staged)

    def _reload_verified_save(self, output_format: OutputFormat) -> None:
        source = ByteSource.open(self._path)
        decoder_encoding = _decoder_encoding(output_format.encoding)
        cache_owner = object()
        try:
            mapper = OffsetMapper(
                source,
                decoder_encoding,
                resource_manager=self._resource_manager,
                cache_owner=cache_owner,
            )
            source_line_index = LineIndex(source, decoder_encoding)
            source_eol_report = analyze_eol(
                source,
                encoding=decoder_encoding,
                end=min(source.size, 65_536),
            )
            piece_table = PieceTable(
                source,
                decoder_encoding,
                mapper,
                EditStore(),
            )
            if self._resource_manager is None:
                document_line_index = DocumentLineIndex(piece_table)
            else:
                document_line_index = DocumentLineIndex(
                    piece_table,
                    resource_manager=self._resource_manager,
                    cache_owner=cache_owner,
                )
            identity = FileIdentity.from_path(self._path)
        except Exception:
            if self._resource_manager is not None:
                self._resource_manager.evict_owner(cache_owner)
            source.close()
            raise

        old_source = self._source
        old_cache_owner = self._cache_owner
        self._source = source
        self._source_identity = identity
        self._disk_identity = identity
        self._encoding_info = EncodingInfo(
            detected=decoder_encoding,
            confidence=1.0,
            bom=output_format.encoding.bom or None,
            user_override=True,
            output_encoding=output_format.encoding.codec,
        )
        self._source_profile = output_format.encoding
        self._piece_source_profile = output_format.encoding
        self._offset_mapper = mapper
        self._source_line_index = source_line_index
        self._piece_table = piece_table
        self._document_line_index = document_line_index
        self._source_eol_report = source_eol_report
        self._cache_owner = cache_owner
        if self._resource_manager is not None and old_cache_owner is not None:
            self._resource_manager.evict_owner(old_cache_owner)
        old_source.close()

    def save(self, *, output_format: OutputFormat | None = None) -> Path:
        """Save the current document in place and advance its save point."""

        self._ensure_open()
        selected = self._output_format if output_format is None else output_format
        if not isinstance(selected, OutputFormat):
            raise TypeError("output format must be an OutputFormat")
        request = self.create_save_request(self._path, selected)
        prepared = prepare_document_save(
            request,
            ImmediateSaveContext(),
            stage=stage_document,
            verify=verify_staged_document,
        )
        try:
            return self.commit_prepared_save(prepared)
        finally:
            prepared.discard()

    def export_copy(
        self,
        destination: str | os.PathLike[str],
        *,
        output_format: OutputFormat,
        expected_destination_identity: (
            FileIdentity | None | _UnspecifiedDestinationIdentity
        ) = _UNSPECIFIED_DESTINATION_IDENTITY,
    ) -> Path:
        """Write another path without changing this document's identity or state."""

        self._ensure_open()
        target = Path(destination)
        if self._same_resolved_file(self._path, target):
            raise ValueError("use in-place Save for the current document path")
        if not isinstance(output_format, OutputFormat):
            raise TypeError("output format must be an OutputFormat")
        request = self.create_save_request(
            target,
            output_format,
            expected_destination_identity=expected_destination_identity,
        )
        prepared = prepare_document_save(
            request,
            ImmediateSaveContext(),
            stage=stage_document,
            verify=verify_staged_document,
        )
        try:
            return self.commit_prepared_export(prepared)
        finally:
            prepared.discard()

    def total_chars(self) -> int:
        self._ensure_open()
        return self._piece_table.total_chars()

    def close(self) -> None:
        if self._closed:
            return
        if self._resource_manager is not None and self._cache_owner is not None:
            self._resource_manager.evict_owner(self._cache_owner)
        self._source.close()
        self._closed = True

    def __enter__(self) -> "Document":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
