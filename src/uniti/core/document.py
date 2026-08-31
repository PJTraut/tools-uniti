"""Qt-independent UNITI document facade."""

from __future__ import annotations

import os
from pathlib import Path

from .byte_source import ByteSource
from .encoding import EncodingInfo, detect_encoding
from .lines import LineIndex
from .offsets import OffsetMapper
from .pieces import EditStore, PieceTable


class Document:
    """Own the lazy immutable-source services and edited piece table."""

    def __init__(
        self,
        source: ByteSource,
        encoding_info: EncodingInfo,
        offset_mapper: OffsetMapper,
        source_line_index: LineIndex,
        piece_table: PieceTable,
    ) -> None:
        self._source = source
        self._encoding_info = encoding_info
        self._offset_mapper = offset_mapper
        self._source_line_index = source_line_index
        self._piece_table = piece_table
        self._modified = False
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
            return cls(
                source,
                encoding_info,
                mapper,
                source_line_index,
                piece_table,
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
        return self._source.path

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
    def modified(self) -> bool:
        return self._modified

    def read(self, start: int, end: int) -> str:
        self._ensure_open()
        return self._piece_table.read(start, end)

    def insert(self, char_offset: int, text: str) -> None:
        self._ensure_open()
        self._piece_table.insert(char_offset, text)
        if text:
            self._modified = True

    def delete(self, start: int, end: int) -> None:
        self._ensure_open()
        self._piece_table.delete(start, end)
        if start != end:
            self._modified = True

    def replace(self, start: int, end: int, text: str) -> None:
        self._ensure_open()
        self._piece_table.replace(start, end, text)
        if start != end or text:
            self._modified = True

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
