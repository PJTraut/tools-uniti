"""Revision-bound line-index work for resource-coordinated navigation."""

from __future__ import annotations

from array import array
from bisect import bisect_right
from dataclasses import dataclass, replace
from typing import Protocol

from .document_lines import (
    LineChunkDetail,
    LineChunkSummary,
    LineIndexBatch,
    scan_line_chunk,
)
from .offsets import OffsetCheckpoint, ReadIntent
from .snapshot import DocumentReadSnapshot


class IndexTaskContext(Protocol):
    def check_cancelled(self) -> None: ...

    def report(
        self,
        phase: str,
        completed: int,
        total: int | None,
        *,
        cancellable: bool = True,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class LineNavigationResult:
    batch: LineIndexBatch
    target_char: int | None
    source_checkpoints: tuple[OffsetCheckpoint, ...] = ()
    source_mapping_complete: bool = False


def build_line_index_batch(
    snapshot: DocumentReadSnapshot,
    start_char: int,
    max_chars: int,
    context: IndexTaskContext,
    *,
    chunk_chars: int = 65_536,
) -> LineIndexBatch:
    """Scan at most ``max_chars`` into compact line-count summaries."""

    if start_char < 0:
        raise ValueError("start_char must be non-negative")
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if chunk_chars <= 0:
        raise ValueError("chunk_chars must be positive")

    pending_cr = False
    if start_char:
        pending_cr = snapshot.read(
            start_char - 1,
            start_char,
            intent=ReadIntent.STREAMING,
        ) == "\r"

    summaries: list[LineChunkSummary] = []
    iterator = snapshot.iter_text(
        start_char,
        chunk_chars=chunk_chars,
        intent=ReadIntent.STREAMING,
    )
    scanned = 0
    relative_line_count = 0
    complete = False
    while scanned < max_chars:
        context.check_cancelled()
        try:
            chunk_start, text = next(iterator)
        except StopIteration:
            complete = True
            break
        if chunk_start != start_char + scanned:
            raise RuntimeError("snapshot iterator returned a discontinuous range")
        remaining = max_chars - scanned
        truncated = len(text) > remaining
        if truncated:
            text = text[:remaining]
        summary, _detail = scan_line_chunk(
            chunk_start,
            text,
            line_count_before=relative_line_count,
            pending_cr_in=pending_cr,
            finish_pending_cr=False,
            chunk_index=len(summaries),
        )
        summaries.append(summary)
        relative_line_count += summary.line_starts_in_chunk
        pending_cr = summary.pending_cr_out
        scanned += len(text)
        context.report("Indexing lines", scanned, None)
        if truncated:
            break

    if scanned == max_chars and not complete:
        context.check_cancelled()
        try:
            next(iterator)
        except StopIteration:
            complete = True

    if complete and pending_cr and summaries:
        final = summaries[-1]
        summaries[-1] = replace(
            final,
            line_starts_in_chunk=final.line_starts_in_chunk + 1,
            pending_cr_out=False,
        )

    context.check_cancelled()
    return LineIndexBatch(
        revision=snapshot.revision,
        start_char=start_char,
        summaries=tuple(summaries),
        complete=complete,
    )


def resolve_line_in_batch(
    snapshot: DocumentReadSnapshot,
    batch: LineIndexBatch,
    line_index: int,
    *,
    base_line_count: int = 1,
) -> LineNavigationResult:
    """Resolve one requested line and retain only its disposable detail."""

    if line_index < 0:
        raise ValueError("line index must be non-negative")
    if line_index < base_line_count:
        target = batch.start_char if line_index == base_line_count - 1 else None
        return LineNavigationResult(batch, target)

    counts = [
        base_line_count + summary.line_count_before
        for summary in batch.summaries
    ]
    chunk_index = bisect_right(counts, line_index) - 1
    if chunk_index < 0:
        return LineNavigationResult(batch, None)
    summary = batch.summaries[chunk_index]
    count_before = base_line_count + summary.line_count_before
    if line_index >= count_before + summary.line_starts_in_chunk:
        return LineNavigationResult(batch, None)

    text = snapshot.read(
        summary.char_start,
        summary.char_end,
        intent=ReadIntent.STREAMING,
    )
    rebuilt, detail = scan_line_chunk(
        summary.char_start,
        text,
        line_count_before=summary.line_count_before,
        pending_cr_in=summary.pending_cr_in,
        finish_pending_cr=not summary.pending_cr_out,
        chunk_index=chunk_index,
    )
    if rebuilt != summary:
        raise RuntimeError("navigation detail does not match line summary")
    local_index = line_index - count_before
    target = summary.char_start + int(detail.relative_starts[local_index])
    retained = LineChunkDetail(detail.chunk_index, array("I", detail.relative_starts))
    return LineNavigationResult(replace(batch, details=(retained,)), target)
