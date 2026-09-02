"""Immutable, independently readable snapshots of live UNITI documents."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .byte_source import ByteSource
from .file_identity import FileIdentity
from .offsets import OffsetMapper, ReadIntent
from .pieces import (
    AnnotatedChunk,
    AnnotatedText,
    EditRef,
    Piece,
    PieceTable,
    TextSegment,
)
from .text_format import EncodingProfile, OutputFormat


@dataclass(frozen=True, slots=True)
class EditStoreSnapshot:
    blocks: tuple[str, ...]

    @property
    def block_count(self) -> int:
        return len(self.blocks)

    def read(self, ref: EditRef, start: int = 0, end: int | None = None) -> str:
        stop = ref.length if end is None else end
        if start < 0 or stop < start or stop > ref.length:
            raise ValueError("invalid edit-store range")
        try:
            block = self.blocks[ref.block]
        except IndexError as error:
            raise ValueError("edit reference uses an unknown block") from error
        absolute_start = ref.start + start
        absolute_end = ref.start + stop
        if absolute_end > len(block):
            raise ValueError("edit reference extends beyond stored block")
        return block[absolute_start:absolute_end]


class PieceTableSnapshot:
    """Read-only facade over a private piece table and mapper."""

    __slots__ = ("_table",)

    def __init__(self, table: PieceTable) -> None:
        self._table = table

    @classmethod
    def capture(
        cls,
        source: ByteSource,
        encoding: str,
        pieces: tuple[Piece, ...],
        edit_store: EditStoreSnapshot,
    ) -> "PieceTableSnapshot":
        mapper = OffsetMapper(source, encoding)
        table = PieceTable(source, encoding, mapper, edit_store)  # type: ignore[arg-type]
        table._pieces = list(pieces)
        return cls(table)

    @property
    def piece_count(self) -> int:
        return self._table.piece_count

    def read(
        self,
        start: int,
        end: int,
        *,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> str:
        return self._table.read(start, end, intent=intent)

    def read_with_annotations(
        self,
        start: int,
        end: int,
        *,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> AnnotatedText:
        return self._table.read_with_annotations(start, end, intent=intent)

    def iter_text(
        self,
        start: int = 0,
        end: int | None = None,
        *,
        chunk_chars: int = 65_536,
        intent: ReadIntent = ReadIntent.STREAMING,
    ):
        return self._table.iter_text(
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
        intent: ReadIntent = ReadIntent.STREAMING,
    ):
        return self._table.iter_annotated_text(
            start,
            end,
            chunk_chars=chunk_chars,
            intent=intent,
        )

    def iter_segments(self):
        return self._table.iter_segments()

    def total_chars(self, *, intent: ReadIntent = ReadIntent.STREAMING) -> int:
        return self._table.total_chars(intent=intent)


@dataclass(frozen=True, slots=True)
class DocumentReadSnapshot:
    revision: int
    path: Path
    disk_identity: FileIdentity
    source_profile: EncodingProfile
    output_format: OutputFormat
    _source: ByteSource
    _piece_table: PieceTableSnapshot
    _closed: bool = field(default=False, init=False, repr=False, compare=False)

    @property
    def source(self) -> ByteSource:
        self._ensure_open()
        return self._source

    @property
    def piece_table(self) -> PieceTableSnapshot:
        self._ensure_open()
        return self._piece_table

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("DocumentReadSnapshot is closed")

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
        intent: ReadIntent = ReadIntent.STREAMING,
    ):
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
        intent: ReadIntent = ReadIntent.STREAMING,
    ):
        self._ensure_open()
        return self._piece_table.iter_annotated_text(
            start,
            end,
            chunk_chars=chunk_chars,
            intent=intent,
        )

    def total_chars(self) -> int:
        self._ensure_open()
        return self._piece_table.total_chars(intent=ReadIntent.STREAMING)

    def close(self) -> None:
        if self._closed:
            return
        self._source.close()
        object.__setattr__(self, "_closed", True)

    def __enter__(self) -> "DocumentReadSnapshot":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
