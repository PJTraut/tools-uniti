"""Qt-independent UNITI document facade."""

from __future__ import annotations

import codecs
import os
from collections.abc import Callable, Iterator
from dataclasses import replace as dataclass_replace
from pathlib import Path

from .byte_source import ByteSource
from .encoding import EncodingInfo, detect_encoding
from .document_lines import DocumentLineIndex
from .file_identity import ExternalFileChangedError, FileIdentity
from .history import EditHistory, EditOperation, EditTransaction
from .lines import LineIndex
from .offsets import OffsetMapper
from .pieces import EditStore, PieceTable
from .save import EOLName, SaveOptions, save_document


class Document:
    """Own the lazy immutable-source services and edited piece table."""

    def __init__(
        self,
        source: ByteSource,
        encoding_info: EncodingInfo,
        offset_mapper: OffsetMapper,
        source_line_index: LineIndex,
        piece_table: PieceTable,
        document_line_index: DocumentLineIndex,
    ) -> None:
        self._source = source
        self._path = source.path
        self._source_identity = FileIdentity.from_path(source.path)
        self._disk_identity = self._source_identity
        self._encoding_info = encoding_info
        self._offset_mapper = offset_mapper
        self._source_line_index = source_line_index
        self._piece_table = piece_table
        self._document_line_index = document_line_index
        self._output_eol: EOLName | None = None
        self._history = EditHistory()
        self._saved_output_encoding = (
            encoding_info.output_encoding or encoding_info.detected
        )
        self._saved_output_eol: EOLName | None = None
        self._edit_listeners: list[Callable[[EditOperation], None]] = []
        self._save_listeners: list[Callable[[Path], None]] = []
        self._metadata_listeners: list[Callable[[str, EOLName | None], None]] = []
        self._closed = False

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        encoding: str | None = None,
    ) -> "Document":
        source = ByteSource.open(path)
        try:
            if encoding is None:
                encoding_info = detect_encoding(source)
            else:
                encoding_info = EncodingInfo(
                    detected=encoding,
                    confidence=1.0,
                    bom=None,
                    user_override=True,
                    output_encoding=encoding,
                )
            selected = encoding_info.detected
            mapper = OffsetMapper(source, selected)
            source_line_index = LineIndex(source, selected)
            edit_store = EditStore()
            piece_table = PieceTable(source, selected, mapper, edit_store)
            document_line_index = DocumentLineIndex(piece_table)
            return cls(
                source,
                encoding_info,
                mapper,
                source_line_index,
                piece_table,
                document_line_index,
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
        return self._output_eol

    @property
    def output_encoding(self) -> str:
        return self._encoding_info.output_encoding or self._encoding_info.detected

    @property
    def modified(self) -> bool:
        metadata_modified = (
            self.output_encoding != self._saved_output_encoding
            or self._output_eol != self._saved_output_eol
        )
        return self._history.modified or metadata_modified

    def set_output_encoding(self, encoding: str) -> None:
        self._ensure_open()
        if not isinstance(encoding, str) or not encoding:
            raise ValueError("output encoding must be a non-empty string")
        try:
            codecs.lookup(encoding)
        except LookupError as exc:
            raise ValueError(f"unknown output encoding: {encoding}") from exc
        if encoding == self.output_encoding:
            return
        self._encoding_info = dataclass_replace(
            self._encoding_info,
            output_encoding=encoding,
        )
        self._notify_metadata()

    def set_output_eol(self, eol: EOLName | None) -> None:
        self._ensure_open()
        if eol not in (None, "LF", "CRLF", "CR"):
            raise ValueError(f"unsupported EOL policy: {eol}")
        if eol == self._output_eol:
            return
        self._output_eol = eol
        self._notify_metadata()

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

    def _notify_edit(self, operation: EditOperation) -> None:
        for listener in tuple(self._edit_listeners):
            listener(operation)

    def _notify_save(self, path: Path) -> None:
        for listener in tuple(self._save_listeners):
            listener(path)

    def _notify_metadata(self) -> None:
        for listener in tuple(self._metadata_listeners):
            listener(self.output_encoding, self._output_eol)

    @property
    def can_undo(self) -> bool:
        return self._history.can_undo

    @property
    def can_redo(self) -> bool:
        return self._history.can_redo

    def read(self, start: int, end: int) -> str:
        self._ensure_open()
        return self._piece_table.read(start, end)

    def iter_text(
        self,
        start: int = 0,
        end: int | None = None,
        *,
        chunk_chars: int = 65_536,
    ) -> Iterator[tuple[int, str]]:
        self._ensure_open()
        return self._piece_table.iter_text(
            start,
            end,
            chunk_chars=chunk_chars,
        )

    def _replace_internal(
        self,
        start: int,
        end: int,
        text: str,
        *,
        record: bool,
    ) -> EditOperation | None:
        deleted = self._piece_table.read(start, end)
        if deleted == text:
            return None
        self._piece_table.replace(start, end, text)
        self._document_line_index.invalidate_from_char(start)
        operation = EditOperation(start, deleted, text)
        if record:
            self._history.record(EditTransaction((operation,)))
        self._notify_edit(operation)
        return operation

    def insert(self, char_offset: int, text: str) -> None:
        self._ensure_open()
        self._replace_internal(char_offset, char_offset, text, record=True)

    def delete(self, start: int, end: int) -> None:
        self._ensure_open()
        self._replace_internal(start, end, "", record=True)

    def replace(self, start: int, end: int, text: str) -> None:
        self._ensure_open()
        self._replace_internal(start, end, text, record=True)

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
        self._history.record(EditTransaction(tuple(operations)))
        return len(prepared)

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

    def line_count(self) -> int:
        self._ensure_open()
        return self._document_line_index.total_lines()

    def line_start(self, line: int) -> int:
        self._ensure_open()
        return self._document_line_index.line_start(line)

    def line_for_char(self, char_offset: int) -> int:
        self._ensure_open()
        return self._document_line_index.line_for_char(char_offset)

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

    def save(
        self,
        destination: str | os.PathLike[str] | None = None,
        *,
        encoding: str | None = None,
        eol: EOLName | None = None,
    ) -> Path:
        self._ensure_open()
        target = self._path if destination is None else Path(destination)

        # An mmap/open handle survives atomic path replacement, but an in-place
        # rewrite of the same filesystem object can mutate bytes beneath UNITI.
        # Refuse every save in that unsafe case rather than reconstructing from
        # bytes that may no longer be the source the user opened.
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
        output_encoding = (
            encoding
            or self._encoding_info.output_encoding
            or self._encoding_info.detected
        )
        output_eol = self._output_eol if eol is None else eol
        result = save_document(
            self._source,
            self._piece_table,
            source_encoding=self._encoding_info.detected,
            source_bom=self._encoding_info.bom,
            destination=target,
            options=SaveOptions(encoding=output_encoding, eol=output_eol),
        )
        self._path = result
        self._disk_identity = FileIdentity.from_path(result)
        self._encoding_info = dataclass_replace(
            self._encoding_info,
            output_encoding=output_encoding,
        )
        if eol is not None:
            self._output_eol = eol
        self._history.mark_saved()
        self._saved_output_encoding = output_encoding
        self._saved_output_eol = output_eol
        self._notify_save(result)
        return result

    def total_chars(self) -> int:
        self._ensure_open()
        return self._piece_table.total_chars()

    def close(self) -> None:
        if self._closed:
            return
        self._source.close()
        self._closed = True

    def __enter__(self) -> "Document":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
