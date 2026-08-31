"""Qt-independent UNITI document facade."""

from __future__ import annotations

import os
from collections.abc import Iterator
from dataclasses import replace as dataclass_replace
from pathlib import Path

from .byte_source import ByteSource
from .encoding import EncodingInfo, detect_encoding
from .document_lines import DocumentLineIndex
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
        self._encoding_info = encoding_info
        self._offset_mapper = offset_mapper
        self._source_line_index = source_line_index
        self._piece_table = piece_table
        self._document_line_index = document_line_index
        self._output_eol: EOLName | None = None
        self._history = EditHistory()
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
    def modified(self) -> bool:
        return self._history.modified

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
        self._encoding_info = dataclass_replace(
            self._encoding_info,
            output_encoding=output_encoding,
        )
        if eol is not None:
            self._output_eol = eol
        self._history.mark_saved()
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
