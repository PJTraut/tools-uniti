"""Compact progressive line-start indexing for UNITI."""

from __future__ import annotations

from array import array
from bisect import bisect_right

from .byte_source import ByteSource
from .decoder import iter_decoded_spans
from .offsets import OffsetMapper


class LineIndex:
    """Progressively index logical line starts as unsigned 64-bit byte offsets."""

    def __init__(
        self,
        source: ByteSource,
        encoding: str,
        *,
        chunk_size: int = 65_536,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        self._source = source
        self._encoding = encoding
        self._chunk_size = chunk_size
        visible_start = OffsetMapper(source, encoding, checkpoint_bytes=chunk_size).char_to_byte(0)
        self._starts = array("Q", [visible_start])
        self._indexed_byte_end = visible_start
        self._complete = visible_start >= source.size
        self._pending_cr_end: int | None = None

    @property
    def indexed_byte_end(self) -> int:
        return self._indexed_byte_end

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def indexed_line_count(self) -> int:
        return len(self._starts)

    def _append_start(self, byte_offset: int) -> None:
        if self._starts[-1] != byte_offset:
            self._starts.append(byte_offset)

    def _consume_span(self, span) -> None:
        for index, char in enumerate(span.text):
            char_end = span.byte_start + span.char_boundaries[index + 1]
            if self._pending_cr_end is not None:
                if char == "\n":
                    self._append_start(char_end)
                    self._pending_cr_end = None
                    continue
                self._append_start(self._pending_cr_end)
                self._pending_cr_end = None

            if char == "\r":
                self._pending_cr_end = char_end
            elif char == "\n":
                self._append_start(char_end)

    def _advance(self) -> None:
        if self._complete:
            return
        iterator = iter_decoded_spans(
            self._source,
            self._encoding,
            start=self._indexed_byte_end,
            end=self._source.size,
            chunk_size=self._chunk_size,
        )
        try:
            span = next(iterator)
        except StopIteration:
            self._complete = True
            return

        self._consume_span(span)
        self._indexed_byte_end = span.byte_end
        if self._indexed_byte_end >= self._source.size:
            if self._pending_cr_end is not None:
                self._append_start(self._pending_cr_end)
                self._pending_cr_end = None
            self._complete = True

    def ensure_byte(self, byte_offset: int) -> None:
        first = self._starts[0]
        if byte_offset < first or byte_offset > self._source.size:
            raise ValueError("byte offset is outside visible source text")
        while byte_offset > self._indexed_byte_end and not self._complete:
            self._advance()

    def ensure_line(self, line_index: int) -> None:
        if line_index < 0:
            raise ValueError("line index must be non-negative")
        while line_index >= len(self._starts) and not self._complete:
            self._advance()
        if line_index >= len(self._starts):
            raise ValueError("line index is beyond end of source")

    def line_start(self, line_index: int) -> int:
        self.ensure_line(line_index)
        return int(self._starts[line_index])

    def line_for_byte(self, byte_offset: int) -> int:
        self.ensure_byte(byte_offset)
        return bisect_right(self._starts, byte_offset) - 1

    def total_lines(self) -> int:
        while not self._complete:
            self._advance()
        return len(self._starts)
