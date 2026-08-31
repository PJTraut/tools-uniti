"""Progressive source byte-to-character mapping for UNITI."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from dataclasses import dataclass

from .byte_source import ByteSource
from .decoder import decode_span, iter_decoded_spans


@dataclass(frozen=True, slots=True)
class OffsetCheckpoint:
    byte_offset: int
    char_offset: int


_BOM_BY_ENCODING: dict[str, bytes] = {
    "utf-8-sig": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
    "utf-32-le": b"\xff\xfe\x00\x00",
    "utf-32-be": b"\x00\x00\xfe\xff",
}


def _normalize_encoding(encoding: str) -> str:
    return encoding.lower().replace("_", "-")


def _visible_start(source: ByteSource, encoding: str) -> int:
    bom = _BOM_BY_ENCODING.get(_normalize_encoding(encoding))
    if bom is None or source.size < len(bom):
        return 0
    return len(bom) if source.read(0, len(bom)) == bom else 0


class OffsetMapper:
    """Lazily map immutable source byte boundaries to Unicode characters."""

    def __init__(
        self,
        source: ByteSource,
        encoding: str,
        *,
        checkpoint_bytes: int = 65_536,
    ) -> None:
        if checkpoint_bytes <= 0:
            raise ValueError("checkpoint_bytes must be positive")
        self._source = source
        self._encoding = encoding
        self._checkpoint_bytes = checkpoint_bytes
        start = _visible_start(source, encoding)
        self._checkpoints: list[OffsetCheckpoint] = [OffsetCheckpoint(start, 0)]
        self._indexed_byte_end = start
        self._indexed_char_end = 0
        self._complete = start >= source.size

    @property
    def indexed_byte_end(self) -> int:
        return self._indexed_byte_end

    @property
    def indexed_char_end(self) -> int:
        return self._indexed_char_end

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def checkpoints(self) -> tuple[OffsetCheckpoint, ...]:
        return tuple(self._checkpoints)

    def _advance(self) -> None:
        if self._complete:
            return
        iterator = iter_decoded_spans(
            self._source,
            self._encoding,
            start=self._indexed_byte_end,
            end=self._source.size,
            chunk_size=self._checkpoint_bytes,
        )
        try:
            span = next(iterator)
        except StopIteration:
            self._complete = True
            return

        self._indexed_byte_end = span.byte_end
        self._indexed_char_end += len(span.text)
        checkpoint = OffsetCheckpoint(self._indexed_byte_end, self._indexed_char_end)
        if checkpoint != self._checkpoints[-1]:
            self._checkpoints.append(checkpoint)
        self._complete = self._indexed_byte_end >= self._source.size

    def _ensure_char(self, char_offset: int) -> None:
        if char_offset < 0:
            raise ValueError("character offset must be non-negative")
        while char_offset > self._indexed_char_end and not self._complete:
            self._advance()
        if char_offset > self._indexed_char_end:
            raise ValueError("character offset is beyond end of source")

    def _ensure_byte(self, byte_offset: int) -> None:
        visible_start = self._checkpoints[0].byte_offset
        if byte_offset < visible_start or byte_offset > self._source.size:
            raise ValueError("byte offset is outside visible source text")
        while byte_offset > self._indexed_byte_end and not self._complete:
            self._advance()
        if byte_offset > self._indexed_byte_end:
            raise ValueError("byte offset is beyond indexed source")

    def char_to_byte(self, char_offset: int) -> int:
        self._ensure_char(char_offset)
        char_points = [cp.char_offset for cp in self._checkpoints]
        index = bisect_right(char_points, char_offset) - 1
        checkpoint = self._checkpoints[index]
        if checkpoint.char_offset == char_offset:
            return checkpoint.byte_offset

        if index + 1 >= len(self._checkpoints):
            raise ValueError("character offset is beyond end of source")
        end_checkpoint = self._checkpoints[index + 1]
        span = decode_span(
            self._source,
            checkpoint.byte_offset,
            end_checkpoint.byte_offset - checkpoint.byte_offset,
            self._encoding,
        )
        local = char_offset - checkpoint.char_offset
        return span.byte_offset_for_char_boundary(local)

    def byte_to_char(self, byte_offset: int) -> int:
        self._ensure_byte(byte_offset)
        byte_points = [cp.byte_offset for cp in self._checkpoints]
        index = bisect_right(byte_points, byte_offset) - 1
        checkpoint = self._checkpoints[index]
        if checkpoint.byte_offset == byte_offset:
            return checkpoint.char_offset

        if index + 1 >= len(self._checkpoints):
            raise ValueError("byte offset is not a visible character boundary")
        end_checkpoint = self._checkpoints[index + 1]
        span = decode_span(
            self._source,
            checkpoint.byte_offset,
            end_checkpoint.byte_offset - checkpoint.byte_offset,
            self._encoding,
        )
        absolute_boundaries = [checkpoint.byte_offset + value for value in span.char_boundaries]
        boundary_index = bisect_left(absolute_boundaries, byte_offset)
        if (
            boundary_index >= len(absolute_boundaries)
            or absolute_boundaries[boundary_index] != byte_offset
        ):
            raise ValueError("byte offset is not a visible character boundary")
        return checkpoint.char_offset + boundary_index

    def total_chars(self) -> int:
        while not self._complete:
            self._advance()
        return self._indexed_char_end
