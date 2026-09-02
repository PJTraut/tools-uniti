"""Bounded progressive line-start indexing for immutable source bytes."""

from __future__ import annotations

from array import array
from bisect import bisect_right
from collections import OrderedDict
from dataclasses import dataclass, replace
import sys

from .byte_source import ByteSource
from .decoder import decode_span, iter_decoded_spans
from .offsets import OffsetMapper


@dataclass(frozen=True, slots=True)
class SourceLineChunkSummary:
    byte_start: int
    byte_end: int
    line_count_before: int
    line_starts_in_chunk: int
    pending_cr_in: bool
    pending_cr_out: bool


@dataclass(frozen=True, slots=True)
class SourceLineChunkDetail:
    chunk_index: int
    relative_starts: array

    @property
    def retained_size_bytes(self) -> int:
        return sys.getsizeof(self.relative_starts)


def _scan_span(
    span,
    *,
    line_count_before: int,
    pending_cr_in: bool,
    finish_pending_cr: bool,
    chunk_index: int,
) -> tuple[SourceLineChunkSummary, SourceLineChunkDetail]:
    pending_cr_end = span.byte_start if pending_cr_in else None
    starts = array("I")
    for index, char in enumerate(span.text):
        char_end = span.byte_start + span.char_boundaries[index + 1]
        if pending_cr_end is not None:
            if char == "\n":
                starts.append(char_end - span.byte_start)
                pending_cr_end = None
                continue
            starts.append(pending_cr_end - span.byte_start)
            pending_cr_end = None
        if char == "\r":
            pending_cr_end = char_end
        elif char == "\n":
            starts.append(char_end - span.byte_start)
    if finish_pending_cr and pending_cr_end is not None:
        starts.append(pending_cr_end - span.byte_start)
        pending_cr_end = None
    return (
        SourceLineChunkSummary(
            span.byte_start,
            span.byte_end,
            line_count_before,
            len(starts),
            pending_cr_in,
            pending_cr_end is not None,
        ),
        SourceLineChunkDetail(chunk_index, starts),
    )


class LineIndex:
    """Map source bytes to lines using compact summaries and bounded details."""

    _SUMMARY_SIZE_BYTES = 64

    def __init__(
        self,
        source: ByteSource,
        encoding: str,
        *,
        chunk_size: int = 65_536,
        detail_budget_bytes: int = 2 << 20,
    ) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        if detail_budget_bytes < 0:
            raise ValueError("detail_budget_bytes must be non-negative")
        self._source = source
        self._encoding = encoding
        self._chunk_size = chunk_size
        self._detail_budget_bytes = detail_budget_bytes
        visible_start = OffsetMapper(
            source,
            encoding,
            checkpoint_bytes=chunk_size,
        ).char_to_byte(0)
        self._visible_start = visible_start
        self._summaries: list[SourceLineChunkSummary] = []
        self._details: OrderedDict[int, SourceLineChunkDetail] = OrderedDict()
        self._resident_detail_bytes = 0
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
        if not self._summaries:
            return 1
        final = self._summaries[-1]
        return final.line_count_before + final.line_starts_in_chunk

    @property
    def summary_bytes(self) -> int:
        return len(self._summaries) * self._SUMMARY_SIZE_BYTES

    @property
    def resident_detail_bytes(self) -> int:
        return self._resident_detail_bytes

    def _store_detail(self, detail: SourceLineChunkDetail) -> None:
        size = detail.retained_size_bytes
        old = self._details.pop(detail.chunk_index, None)
        if old is not None:
            self._resident_detail_bytes -= old.retained_size_bytes
        if size > self._detail_budget_bytes:
            return
        while self._details and self._resident_detail_bytes + size > self._detail_budget_bytes:
            _, evicted = self._details.popitem(last=False)
            self._resident_detail_bytes -= evicted.retained_size_bytes
        if self._resident_detail_bytes + size <= self._detail_budget_bytes:
            self._details[detail.chunk_index] = detail
            self._resident_detail_bytes += size

    def _finish(self) -> None:
        if self._pending_cr_end is not None and self._summaries:
            index = len(self._summaries) - 1
            summary = self._summaries[index]
            self._summaries[index] = replace(
                summary,
                line_starts_in_chunk=summary.line_starts_in_chunk + 1,
                pending_cr_out=False,
            )
            cached = self._details.get(index)
            if cached is not None:
                starts = array("I", cached.relative_starts)
                starts.append(self._pending_cr_end - summary.byte_start)
                self._store_detail(SourceLineChunkDetail(index, starts))
            self._pending_cr_end = None
        self._complete = True

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
            self._finish()
            return
        index = len(self._summaries)
        summary, detail = _scan_span(
            span,
            line_count_before=self.indexed_line_count,
            pending_cr_in=self._pending_cr_end is not None,
            finish_pending_cr=False,
            chunk_index=index,
        )
        self._summaries.append(summary)
        self._store_detail(detail)
        self._indexed_byte_end = span.byte_end
        self._pending_cr_end = span.byte_end if summary.pending_cr_out else None
        if self._indexed_byte_end >= self._source.size:
            self._finish()

    def ensure_byte(self, byte_offset: int) -> None:
        if byte_offset < self._visible_start or byte_offset > self._source.size:
            raise ValueError("byte offset is outside visible source text")
        while byte_offset > self._indexed_byte_end and not self._complete:
            self._advance()
        if (
            byte_offset == self._indexed_byte_end
            and self._pending_cr_end == byte_offset
            and not self._complete
        ):
            self._advance()

    def ensure_line(self, line_index: int) -> None:
        if line_index < 0:
            raise ValueError("line index must be non-negative")
        while line_index >= self.indexed_line_count and not self._complete:
            self._advance()
        if line_index >= self.indexed_line_count:
            raise ValueError("line index is beyond end of source")

    def _summary_for_line(self, line_index: int) -> int:
        counts = [summary.line_count_before for summary in self._summaries]
        index = bisect_right(counts, line_index) - 1
        while index >= 0:
            summary = self._summaries[index]
            if line_index < summary.line_count_before + summary.line_starts_in_chunk:
                return index
            index -= 1
        raise ValueError("line index is not represented by a source chunk")

    def _detail(self, index: int) -> SourceLineChunkDetail:
        cached = self._details.get(index)
        if cached is not None:
            self._details.move_to_end(index)
            return cached
        summary = self._summaries[index]
        span = decode_span(
            self._source,
            summary.byte_start,
            summary.byte_end - summary.byte_start,
            self._encoding,
        )
        rebuilt, detail = _scan_span(
            span,
            line_count_before=summary.line_count_before,
            pending_cr_in=summary.pending_cr_in,
            finish_pending_cr=not summary.pending_cr_out,
            chunk_index=index,
        )
        if rebuilt != summary:
            raise RuntimeError("source line detail no longer matches its summary")
        self._store_detail(detail)
        return detail

    def line_start(self, line_index: int) -> int:
        self.ensure_line(line_index)
        if line_index == 0:
            return self._visible_start
        index = self._summary_for_line(line_index)
        summary = self._summaries[index]
        local = line_index - summary.line_count_before
        return summary.byte_start + int(self._detail(index).relative_starts[local])

    def line_for_byte(self, byte_offset: int) -> int:
        self.ensure_byte(byte_offset)
        if not self._summaries:
            return 0
        starts = [summary.byte_start for summary in self._summaries]
        index = max(0, bisect_right(starts, byte_offset) - 1)
        summary = self._summaries[index]
        relative = byte_offset - summary.byte_start
        return summary.line_count_before - 1 + bisect_right(
            self._detail(index).relative_starts,
            relative,
        )

    def total_lines(self) -> int:
        while not self._complete:
            self._advance()
        return self.indexed_line_count
