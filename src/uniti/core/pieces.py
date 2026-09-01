"""Hybrid immutable-source / Unicode-edit piece table for UNITI."""

from __future__ import annotations

from dataclasses import dataclass
from bisect import bisect_left
from collections.abc import Iterator

from .byte_source import ByteSource
from .decoder import decode_span
from .offsets import OffsetMapper


@dataclass(frozen=True, slots=True)
class EditRef:
    block: int
    start: int
    length: int


class _EditBlock:
    __slots__ = ("chunks", "length", "_cache")

    def __init__(self, text: str) -> None:
        self.chunks = [text]
        self.length = len(text)
        self._cache: str | None = text

    def append(self, text: str) -> None:
        if not text:
            return
        self.chunks.append(text)
        self.length += len(text)
        self._cache = None

    def text(self) -> str:
        if self._cache is None:
            self._cache = "".join(self.chunks)
        return self._cache


class EditStore:
    """Append-only Unicode edit blocks with cheap sequential extension."""

    def __init__(self) -> None:
        self._blocks: list[_EditBlock] = []

    @property
    def block_count(self) -> int:
        return len(self._blocks)

    def append(self, text: str) -> EditRef:
        block = len(self._blocks)
        self._blocks.append(_EditBlock(text))
        return EditRef(block=block, start=0, length=len(text))

    def append_to(self, ref: EditRef, text: str) -> EditRef | None:
        """Extend *ref* when it reaches the physical tail of its edit block."""

        if not text:
            return ref
        block = self._blocks[ref.block]
        if ref.start + ref.length != block.length:
            return None
        block.append(text)
        return EditRef(ref.block, ref.start, ref.length + len(text))

    def read(self, ref: EditRef, start: int = 0, end: int | None = None) -> str:
        stop = ref.length if end is None else end
        if start < 0 or stop < start or stop > ref.length:
            raise ValueError("invalid edit-store range")
        block = self._blocks[ref.block]
        absolute_start = ref.start + start
        absolute_end = ref.start + stop
        if absolute_end > block.length:
            raise ValueError("edit reference extends beyond stored block")
        return block.text()[absolute_start:absolute_end]

    @staticmethod
    def slice(ref: EditRef, start: int, end: int) -> EditRef:
        if start < 0 or end < start or end > ref.length:
            raise ValueError("invalid edit reference slice")
        return EditRef(ref.block, ref.start + start, end - start)


@dataclass(slots=True)
class SourcePiece:
    byte_start: int
    byte_end: int
    source_char_start: int
    char_length: int | None


@dataclass(slots=True)
class EditPiece:
    ref: EditRef


Piece = SourcePiece | EditPiece


@dataclass(frozen=True, slots=True)
class SourceSegment:
    byte_start: int
    byte_end: int


@dataclass(frozen=True, slots=True)
class EditSegment:
    text: str


TextSegment = SourceSegment | EditSegment


@dataclass(frozen=True, slots=True)
class InvalidByteSpan:
    start: int
    end: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class AnnotatedText:
    text: str
    invalid_bytes: tuple[InvalidByteSpan, ...]


@dataclass(frozen=True, slots=True)
class AnnotatedChunk:
    document_offset: int
    text: str
    invalid_bytes: tuple[InvalidByteSpan, ...]


class PieceTable:
    """List-backed piece table with one optional unresolved final source tail."""

    def __init__(
        self,
        source: ByteSource,
        encoding: str,
        mapper: OffsetMapper,
        edit_store: EditStore,
    ) -> None:
        self._source = source
        self._encoding = encoding
        self._mapper = mapper
        self._edit_store = edit_store
        visible_start = mapper.char_to_byte(0)
        self._pieces: list[Piece] = []
        if visible_start < source.size:
            self._pieces.append(
                SourcePiece(
                    byte_start=visible_start,
                    byte_end=source.size,
                    source_char_start=0,
                    char_length=None,
                )
            )

    @property
    def piece_count(self) -> int:
        return len(self._pieces)

    @staticmethod
    def _known_length(piece: Piece) -> int | None:
        if isinstance(piece, EditPiece):
            return piece.ref.length
        return piece.char_length

    def _split_piece(self, index: int, local_offset: int) -> int:
        piece = self._pieces[index]
        known_length = self._known_length(piece)
        if local_offset < 0:
            raise ValueError("piece split offset must be non-negative")
        if local_offset == 0:
            return index
        if known_length is not None and local_offset > known_length:
            raise ValueError("piece split extends beyond piece")
        if known_length is not None and local_offset == known_length:
            return index + 1

        if isinstance(piece, EditPiece):
            left = EditPiece(EditStore.slice(piece.ref, 0, local_offset))
            right = EditPiece(EditStore.slice(piece.ref, local_offset, piece.ref.length))
            self._pieces[index : index + 1] = [left, right]
            return index + 1

        split_source_char = piece.source_char_start + local_offset
        split_byte = self._mapper.char_to_byte(split_source_char)
        if split_byte < piece.byte_start or split_byte > piece.byte_end:
            raise ValueError("mapped split is outside source piece")

        if split_byte == piece.byte_end:
            piece.char_length = local_offset
            return index + 1

        left = SourcePiece(
            byte_start=piece.byte_start,
            byte_end=split_byte,
            source_char_start=piece.source_char_start,
            char_length=local_offset,
        )
        right_length = None if piece.char_length is None else piece.char_length - local_offset
        right = SourcePiece(
            byte_start=split_byte,
            byte_end=piece.byte_end,
            source_char_start=split_source_char,
            char_length=right_length,
        )
        self._pieces[index : index + 1] = [left, right]
        return index + 1

    def _validate_offset(self, char_offset: int) -> None:
        if char_offset < 0:
            raise ValueError("character offset must be non-negative")
        remaining = char_offset
        for index, piece in enumerate(self._pieces):
            length = self._known_length(piece)
            if length is None:
                if not isinstance(piece, SourcePiece) or index != len(self._pieces) - 1:
                    raise RuntimeError("only final source tail may have unknown length")
                self._mapper.char_to_byte(piece.source_char_start + remaining)
                return
            if remaining <= length:
                return
            remaining -= length
        if remaining != 0:
            raise ValueError("character offset is beyond end of document")

    def _split_at(self, char_offset: int) -> int:
        if char_offset < 0:
            raise ValueError("character offset must be non-negative")
        remaining = char_offset
        for index, piece in enumerate(self._pieces):
            length = self._known_length(piece)
            if length is None:
                if not isinstance(piece, SourcePiece) or index != len(self._pieces) - 1:
                    raise RuntimeError("only final source tail may have unknown length")
                if remaining == 0:
                    return index
                return self._split_piece(index, remaining)

            if remaining < length:
                return self._split_piece(index, remaining)
            if remaining == length:
                return index + 1
            remaining -= length

        if remaining == 0:
            return len(self._pieces)
        raise ValueError("character offset is beyond end of document")

    def _merge_neighbors(self) -> None:
        merged: list[Piece] = []
        for piece in self._pieces:
            length = self._known_length(piece)
            if length == 0:
                continue
            if not merged:
                merged.append(piece)
                continue

            previous = merged[-1]
            if isinstance(previous, EditPiece) and isinstance(piece, EditPiece):
                if (
                    previous.ref.block == piece.ref.block
                    and previous.ref.start + previous.ref.length == piece.ref.start
                ):
                    previous.ref = EditRef(
                        previous.ref.block,
                        previous.ref.start,
                        previous.ref.length + piece.ref.length,
                    )
                    continue

            if isinstance(previous, SourcePiece) and isinstance(piece, SourcePiece):
                if previous.char_length is not None:
                    contiguous_chars = (
                        previous.source_char_start + previous.char_length
                        == piece.source_char_start
                    )
                    if previous.byte_end == piece.byte_start and contiguous_chars:
                        previous.byte_end = piece.byte_end
                        previous.char_length = (
                            None
                            if piece.char_length is None
                            else previous.char_length + piece.char_length
                        )
                        continue
            merged.append(piece)
        self._pieces = merged

    def insert(self, char_offset: int, text: str) -> None:
        if not text:
            self._validate_offset(char_offset)
            return
        boundary = self._split_at(char_offset)
        if boundary > 0 and isinstance(self._pieces[boundary - 1], EditPiece):
            previous = self._pieces[boundary - 1]
            extended = self._edit_store.append_to(previous.ref, text)
            if extended is not None:
                previous.ref = extended
                return
        ref = self._edit_store.append(text)
        self._pieces.insert(boundary, EditPiece(ref))
        self._merge_neighbors()

    def delete(self, start: int, end: int) -> None:
        if start < 0 or end < start:
            raise ValueError("invalid document character range")
        if start == end:
            self._validate_offset(start)
            return
        start_index = self._split_at(start)
        end_index = self._split_at(end)
        del self._pieces[start_index:end_index]
        self._merge_neighbors()

    def replace(self, start: int, end: int, text: str) -> None:
        self.delete(start, end)
        if text:
            self.insert(start, text)

    def _read_source_piece(self, piece: SourcePiece, start: int, end: int) -> str:
        source_start = piece.source_char_start + start
        source_end = piece.source_char_start + end
        byte_start = self._mapper.char_to_byte(source_start)
        byte_end = self._mapper.char_to_byte(source_end)
        span = decode_span(
            self._source,
            byte_start,
            byte_end - byte_start,
            self._encoding,
        )
        return span.text

    def _read_source_piece_annotated(
        self,
        piece: SourcePiece,
        start: int,
        end: int,
        *,
        document_start: int,
    ) -> AnnotatedText:
        source_start = piece.source_char_start + start
        source_end = piece.source_char_start + end
        byte_start = self._mapper.char_to_byte(source_start)
        byte_end = self._mapper.char_to_byte(source_end)
        span = decode_span(
            self._source,
            byte_start,
            byte_end - byte_start,
            self._encoding,
        )
        invalid: list[InvalidByteSpan] = []
        for error in span.errors:
            local_byte = error.byte_start - span.byte_start
            char_index = bisect_left(span.char_boundaries, local_byte)
            if (
                char_index >= len(span.char_boundaries)
                or span.char_boundaries[char_index] != local_byte
            ):
                raise UnicodeError("decode error is not aligned to a character boundary")
            invalid.append(
                InvalidByteSpan(
                    start=document_start + char_index,
                    end=document_start + char_index + 1,
                    raw=error.raw,
                )
            )
        return AnnotatedText(span.text, tuple(invalid))

    def read(self, start: int, end: int) -> str:
        if start < 0 or end < start:
            raise ValueError("invalid document character range")
        if start == end:
            self._validate_offset(start)
            return ""

        output: list[str] = []
        position = 0
        consumed_to = start
        for index, piece in enumerate(self._pieces):
            known_length = self._known_length(piece)
            if known_length is None:
                if not isinstance(piece, SourcePiece) or index != len(self._pieces) - 1:
                    raise RuntimeError("only final source tail may have unknown length")
                required = max(0, end - position)
                if required == 0:
                    break
                # Validates that the requested end exists without measuring EOF.
                self._mapper.char_to_byte(piece.source_char_start + required)
                piece_length = required
            else:
                piece_length = known_length

            piece_end_position = position + piece_length
            if piece_end_position <= start:
                position = piece_end_position
                continue
            if position >= end:
                break

            local_start = max(0, start - position)
            local_end = min(piece_length, end - position)
            if local_start < local_end:
                if isinstance(piece, EditPiece):
                    output.append(self._edit_store.read(piece.ref, local_start, local_end))
                else:
                    output.append(self._read_source_piece(piece, local_start, local_end))
                consumed_to = position + local_end
            position = piece_end_position
            if consumed_to >= end:
                break

        if consumed_to < end:
            raise ValueError("document range extends beyond end of document")
        return "".join(output)

    def read_with_annotations(self, start: int, end: int) -> AnnotatedText:
        if start < 0 or end < start:
            raise ValueError("invalid document character range")
        if start == end:
            self._validate_offset(start)
            return AnnotatedText("", ())

        output: list[str] = []
        invalid: list[InvalidByteSpan] = []
        position = 0
        consumed_to = start
        for index, piece in enumerate(self._pieces):
            known_length = self._known_length(piece)
            if known_length is None:
                if not isinstance(piece, SourcePiece) or index != len(self._pieces) - 1:
                    raise RuntimeError("only final source tail may have unknown length")
                required = max(0, end - position)
                if required == 0:
                    break
                self._mapper.char_to_byte(piece.source_char_start + required)
                piece_length = required
            else:
                piece_length = known_length

            piece_end_position = position + piece_length
            if piece_end_position <= start:
                position = piece_end_position
                continue
            if position >= end:
                break

            local_start = max(0, start - position)
            local_end = min(piece_length, end - position)
            if local_start < local_end:
                document_start = position + local_start
                if isinstance(piece, EditPiece):
                    output.append(self._edit_store.read(piece.ref, local_start, local_end))
                else:
                    annotated = self._read_source_piece_annotated(
                        piece, local_start, local_end, document_start=document_start
                    )
                    output.append(annotated.text)
                    invalid.extend(annotated.invalid_bytes)
                consumed_to = position + local_end
            position = piece_end_position
            if consumed_to >= end:
                break

        if consumed_to < end:
            raise ValueError("document range extends beyond end of document")
        return AnnotatedText("".join(output), tuple(invalid))

    def iter_segments(self) -> Iterator[TextSegment]:
        """Yield immutable source-byte or Unicode-edit segments in document order."""
        for piece in self._pieces:
            if isinstance(piece, SourcePiece):
                yield SourceSegment(piece.byte_start, piece.byte_end)
            else:
                yield EditSegment(self._edit_store.read(piece.ref))

    def iter_text(
        self,
        start: int = 0,
        end: int | None = None,
        *,
        chunk_chars: int = 65_536,
    ) -> Iterator[tuple[int, str]]:
        """Yield bounded logical Unicode chunks without eagerly measuring EOF."""
        if start < 0:
            raise ValueError("character offset must be non-negative")
        if end is not None and end < start:
            raise ValueError("invalid document character range")
        if chunk_chars <= 0:
            raise ValueError("chunk_chars must be positive")
        position = start
        while end is None or position < end:
            requested_end = position + chunk_chars
            if end is not None:
                requested_end = min(requested_end, end)
            try:
                text = self.read(position, requested_end)
            except ValueError:
                total = self.total_chars()
                if position > total or (end is not None and end > total):
                    raise
                if position == total:
                    return
                requested_end = min(requested_end, total)
                text = self.read(position, requested_end)
            if not text:
                return
            yield position, text
            position = requested_end

    def iter_annotated_text(
        self,
        start: int = 0,
        end: int | None = None,
        *,
        chunk_chars: int = 65_536,
    ) -> Iterator[AnnotatedChunk]:
        """Yield bounded logical text with absolute source-byte annotations."""

        if start < 0:
            raise ValueError("character offset must be non-negative")
        if end is not None and end < start:
            raise ValueError("invalid document character range")
        if chunk_chars <= 0:
            raise ValueError("chunk_chars must be positive")
        position = start
        while end is None or position < end:
            requested_end = position + chunk_chars
            if end is not None:
                requested_end = min(requested_end, end)
            try:
                annotated = self.read_with_annotations(position, requested_end)
            except ValueError:
                total = self.total_chars()
                if position > total or (end is not None and end > total):
                    raise
                if position == total:
                    return
                requested_end = min(requested_end, total)
                annotated = self.read_with_annotations(position, requested_end)
            if not annotated.text:
                return
            yield AnnotatedChunk(
                document_offset=position,
                text=annotated.text,
                invalid_bytes=annotated.invalid_bytes,
            )
            position = requested_end

    def total_chars(self) -> int:
        total = 0
        for piece in self._pieces:
            length = self._known_length(piece)
            if length is None:
                assert isinstance(piece, SourcePiece)
                length = self._mapper.total_chars() - piece.source_char_start
                piece.char_length = length
            total += length
        return total
