"""Bounded progressive logical-line indexing for edited UNITI documents."""

from __future__ import annotations

from array import array
from bisect import bisect_right
from collections import OrderedDict
from collections.abc import Hashable
from dataclasses import dataclass, replace
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uniti.resources.manager import ResourceManager

from .pieces import PieceTable


@dataclass(frozen=True, slots=True)
class LineChunkSummary:
    """Stable counts for one bounded character interval."""

    char_start: int
    char_end: int
    line_count_before: int
    line_starts_in_chunk: int
    pending_cr_in: bool
    pending_cr_out: bool


@dataclass(frozen=True, slots=True)
class LineChunkDetail:
    """Disposable local line-start offsets for one summary."""

    chunk_index: int
    relative_starts: array

    @property
    def retained_size_bytes(self) -> int:
        return sys.getsizeof(self.relative_starts)


@dataclass(frozen=True, slots=True)
class LineIndexBatch:
    """Revision-bound summaries produced by an independent read snapshot."""

    revision: int
    start_char: int
    summaries: tuple[LineChunkSummary, ...]
    complete: bool
    details: tuple[LineChunkDetail, ...] = ()

    @property
    def indexed_char_end(self) -> int:
        if not self.summaries:
            return self.start_char
        return self.summaries[-1].char_end


def scan_line_chunk(
    start: int,
    text: str,
    *,
    line_count_before: int,
    pending_cr_in: bool,
    finish_pending_cr: bool,
    chunk_index: int,
) -> tuple[LineChunkSummary, LineChunkDetail]:
    """Summarize one chunk while preserving CRLF across chunk boundaries."""

    pending_cr_end = start if pending_cr_in else None
    relative_starts = array("I")
    for index, char in enumerate(text):
        char_end = start + index + 1
        if pending_cr_end is not None:
            if char == "\n":
                relative_starts.append(char_end - start)
                pending_cr_end = None
                continue
            relative_starts.append(pending_cr_end - start)
            pending_cr_end = None

        if char == "\r":
            pending_cr_end = char_end
        elif char == "\n":
            relative_starts.append(char_end - start)

    if finish_pending_cr and pending_cr_end is not None:
        relative_starts.append(pending_cr_end - start)
        pending_cr_end = None

    summary = LineChunkSummary(
        char_start=start,
        char_end=start + len(text),
        line_count_before=line_count_before,
        line_starts_in_chunk=len(relative_starts),
        pending_cr_in=pending_cr_in,
        pending_cr_out=pending_cr_end is not None,
    )
    return summary, LineChunkDetail(chunk_index, relative_starts)


class DocumentLineIndex:
    """Progressive line summaries with bounded, rebuildable local details."""

    _SUMMARY_SIZE_BYTES = 64

    def __init__(
        self,
        piece_table: PieceTable,
        *,
        chunk_chars: int = 65_536,
        detail_budget_bytes: int = 2 << 20,
        resource_manager: "ResourceManager | None" = None,
        cache_owner: Hashable | None = None,
    ) -> None:
        if chunk_chars <= 0:
            raise ValueError("chunk_chars must be positive")
        if detail_budget_bytes < 0:
            raise ValueError("detail_budget_bytes must be non-negative")
        if (resource_manager is None) != (cache_owner is None):
            raise ValueError("resource_manager and cache_owner must be supplied together")
        self._piece_table = piece_table
        self._chunk_chars = chunk_chars
        self._detail_budget_bytes = detail_budget_bytes
        self._resource_manager = resource_manager
        self._cache_owner = cache_owner
        self._summaries: list[LineChunkSummary] = []
        self._details: OrderedDict[int, LineChunkDetail] = OrderedDict()
        self._detail_sizes: OrderedDict[int, int] = OrderedDict()
        self._resident_detail_bytes = 0
        self._indexed_char_end = 0
        self._complete = False
        self._pending_cr_end: int | None = None

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def indexed_char_end(self) -> int:
        return self._indexed_char_end

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
        if self._resource_manager is not None:
            for chunk_index in tuple(self._detail_sizes):
                if self._resource_manager.get_cache(
                    self._cache_owner,
                    ("line-detail", chunk_index),
                ) is None:
                    self._resident_detail_bytes -= self._detail_sizes.pop(chunk_index)
        return self._resident_detail_bytes

    @property
    def summaries(self) -> tuple[LineChunkSummary, ...]:
        return tuple(self._summaries)

    def _store_detail(self, detail: LineChunkDetail) -> None:
        size = detail.retained_size_bytes
        if self._resource_manager is not None:
            old_size = self._detail_sizes.pop(detail.chunk_index, None)
            if old_size is not None:
                self._resource_manager.remove_cache(
                    self._cache_owner,
                    ("line-detail", detail.chunk_index),
                )
                self._resident_detail_bytes -= old_size
        else:
            old = self._details.pop(detail.chunk_index, None)
            if old is not None:
                self._resident_detail_bytes -= old.retained_size_bytes
        if size > self._detail_budget_bytes:
            return
        while self._resident_detail_bytes + size > self._detail_budget_bytes:
            if self._resource_manager is not None and self._detail_sizes:
                chunk_index, evicted_size = self._detail_sizes.popitem(last=False)
                self._resource_manager.remove_cache(
                    self._cache_owner,
                    ("line-detail", chunk_index),
                )
                self._resident_detail_bytes -= evicted_size
            elif self._details:
                _, evicted = self._details.popitem(last=False)
                self._resident_detail_bytes -= evicted.retained_size_bytes
            else:
                break
        if self._resident_detail_bytes + size <= self._detail_budget_bytes:
            if self._resource_manager is not None:
                from uniti.resources.cache import CachePriority

                self._resource_manager.put_cache(
                    self._cache_owner,
                    ("line-detail", detail.chunk_index),
                    detail,
                    size_bytes=size,
                    priority=CachePriority.INDEX,
                )
                self._detail_sizes[detail.chunk_index] = size
            else:
                self._details[detail.chunk_index] = detail
            self._resident_detail_bytes += size

    def _cached_detail(self, chunk_index: int) -> LineChunkDetail | None:
        if self._resource_manager is not None:
            cached = self._resource_manager.get_cache(
                self._cache_owner,
                ("line-detail", chunk_index),
            )
            if cached is None:
                removed = self._detail_sizes.pop(chunk_index, None)
                if removed is not None:
                    self._resident_detail_bytes -= removed
                return None
            if chunk_index in self._detail_sizes:
                self._detail_sizes.move_to_end(chunk_index)
            return cached
        cached = self._details.get(chunk_index)
        if cached is not None:
            self._details.move_to_end(chunk_index)
        return cached

    def _clear_details(self) -> None:
        if self._resource_manager is not None:
            for chunk_index in tuple(self._detail_sizes):
                self._resource_manager.remove_cache(
                    self._cache_owner,
                    ("line-detail", chunk_index),
                )
            self._detail_sizes.clear()
        self._details.clear()
        self._resident_detail_bytes = 0

    def _finish(self) -> None:
        if self._pending_cr_end is not None and self._summaries:
            chunk_index = len(self._summaries) - 1
            summary = self._summaries[chunk_index]
            self._summaries[chunk_index] = replace(
                summary,
                line_starts_in_chunk=summary.line_starts_in_chunk + 1,
                pending_cr_out=False,
            )
            cached = self._cached_detail(chunk_index)
            if cached is not None:
                starts = array("I", cached.relative_starts)
                starts.append(self._pending_cr_end - summary.char_start)
                self._store_detail(LineChunkDetail(chunk_index, starts))
            self._pending_cr_end = None
        self._complete = True

    def _advance(self) -> None:
        if self._complete:
            return
        iterator = self._piece_table.iter_text(
            self._indexed_char_end,
            chunk_chars=self._chunk_chars,
        )
        try:
            start, text = next(iterator)
        except StopIteration:
            self._finish()
            return
        if start != self._indexed_char_end:
            raise RuntimeError("piece-table iterator returned a discontinuous range")

        chunk_index = len(self._summaries)
        summary, detail = scan_line_chunk(
            start,
            text,
            line_count_before=self.indexed_line_count,
            pending_cr_in=self._pending_cr_end is not None,
            finish_pending_cr=False,
            chunk_index=chunk_index,
        )
        self._summaries.append(summary)
        self._store_detail(detail)
        self._indexed_char_end = summary.char_end
        self._pending_cr_end = summary.char_end if summary.pending_cr_out else None
        if len(text) < self._chunk_chars:
            self._finish()

    def ensure_char(self, char_offset: int) -> None:
        if char_offset < 0:
            raise ValueError("character offset must be non-negative")
        while char_offset > self._indexed_char_end and not self._complete:
            self._advance()
        if (
            char_offset == self._indexed_char_end
            and self._pending_cr_end == char_offset
            and not self._complete
        ):
            self._advance()
        if char_offset > self._indexed_char_end:
            raise ValueError("character offset is beyond end of document")

    def ensure_line(self, line_index: int) -> None:
        if line_index < 0:
            raise ValueError("line index must be non-negative")
        while line_index >= self.indexed_line_count and not self._complete:
            self._advance()
        if line_index >= self.indexed_line_count:
            raise ValueError("line index is beyond end of document")

    def _summary_for_line(self, line_index: int) -> int:
        counts = [summary.line_count_before for summary in self._summaries]
        chunk_index = bisect_right(counts, line_index) - 1
        while chunk_index >= 0:
            summary = self._summaries[chunk_index]
            if line_index < summary.line_count_before + summary.line_starts_in_chunk:
                return chunk_index
            chunk_index -= 1
        raise ValueError("line index is not represented by a chunk")

    def _detail(self, chunk_index: int) -> LineChunkDetail:
        cached = self._cached_detail(chunk_index)
        if cached is not None:
            return cached
        summary = self._summaries[chunk_index]
        text = self._piece_table.read(summary.char_start, summary.char_end)
        rebuilt, detail = scan_line_chunk(
            summary.char_start,
            text,
            line_count_before=summary.line_count_before,
            pending_cr_in=summary.pending_cr_in,
            finish_pending_cr=not summary.pending_cr_out,
            chunk_index=chunk_index,
        )
        if rebuilt != summary:
            raise RuntimeError("line detail no longer matches its summary")
        self._store_detail(detail)
        return detail

    def line_start(self, line_index: int) -> int:
        self.ensure_line(line_index)
        if line_index == 0:
            return 0
        chunk_index = self._summary_for_line(line_index)
        summary = self._summaries[chunk_index]
        detail = self._detail(chunk_index)
        local_index = line_index - summary.line_count_before
        return summary.char_start + int(detail.relative_starts[local_index])

    def line_for_char(self, char_offset: int) -> int:
        self.ensure_char(char_offset)
        if not self._summaries:
            return 0
        starts = [summary.char_start for summary in self._summaries]
        chunk_index = max(0, bisect_right(starts, char_offset) - 1)
        summary = self._summaries[chunk_index]
        detail = self._detail(chunk_index)
        relative = char_offset - summary.char_start
        return summary.line_count_before - 1 + bisect_right(
            detail.relative_starts,
            relative,
        )

    def total_lines(self) -> int:
        while not self._complete:
            self._advance()
        return self.indexed_line_count

    def publish(self, batch: LineIndexBatch, expected_revision: int) -> bool:
        """Publish a background batch only for its captured live revision."""

        if batch.revision != expected_revision:
            return False
        if batch.start_char == 0:
            self._summaries.clear()
            self._clear_details()
            base_line_count = 1
            base_chunk_index = 0
        elif batch.start_char == self._indexed_char_end:
            base_line_count = self.indexed_line_count
            base_chunk_index = len(self._summaries)
        else:
            return False

        self._summaries.extend(
            replace(
                summary,
                line_count_before=base_line_count + summary.line_count_before,
            )
            for summary in batch.summaries
        )
        self._indexed_char_end = batch.indexed_char_end
        self._complete = batch.complete
        self._pending_cr_end = (
            self._indexed_char_end
            if self._summaries and self._summaries[-1].pending_cr_out
            else None
        )
        for detail in batch.details:
            self._store_detail(
                LineChunkDetail(
                    base_chunk_index + detail.chunk_index,
                    array("I", detail.relative_starts),
                )
            )
        return True

    def invalidate_from_char(self, char_offset: int) -> None:
        if char_offset < 0:
            raise ValueError("character offset must be non-negative")
        if char_offset > self._indexed_char_end:
            return
        if (
            char_offset == self._indexed_char_end
            and self._pending_cr_end is None
            and not self._complete
        ):
            return

        starts = [summary.char_start for summary in self._summaries]
        discard_from = max(0, bisect_right(starts, char_offset) - 1)
        if discard_from < len(self._summaries):
            restart = self._summaries[discard_from].char_start
            del self._summaries[discard_from:]
        else:
            restart = self._indexed_char_end
        detail_indexes = (
            tuple(self._detail_sizes)
            if self._resource_manager is not None
            else tuple(self._details)
        )
        for index in detail_indexes:
            if index < discard_from:
                continue
            if self._resource_manager is not None:
                size = self._detail_sizes.pop(index)
                self._resource_manager.remove_cache(
                    self._cache_owner,
                    ("line-detail", index),
                )
            else:
                size = self._details.pop(index).retained_size_bytes
            self._resident_detail_bytes -= size
        self._indexed_char_end = restart
        self._pending_cr_end = (
            restart
            if self._summaries and self._summaries[-1].pending_cr_out
            else None
        )
        self._complete = False
