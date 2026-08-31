"""Compact regex result records independent of engine Match lifetimes."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CaptureRecord:
    group: int
    name: str | None
    spans: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class MatchRecord:
    start: int
    end: int
    captures: tuple[CaptureRecord, ...] = ()

    @property
    def span(self) -> tuple[int, int]:
        return self.start, self.end


class MatchIndex:
    """Tuple-backed compact result index for navigation and viewport queries."""

    def __init__(self, records) -> None:
        self._records = tuple(sorted(records, key=lambda record: (record.start, record.end)))
        self._starts = tuple(record.start for record in self._records)

    @property
    def records(self) -> tuple[MatchRecord, ...]:
        return self._records

    def __len__(self) -> int:
        return len(self._records)

    def intersecting(self, start: int, end: int) -> tuple[MatchRecord, ...]:
        from bisect import bisect_left

        if start < 0 or end < start:
            raise ValueError("invalid match query range")
        if not self._records:
            return ()
        index = bisect_left(self._starts, start)
        while index > 0 and self._records[index - 1].end > start:
            index -= 1
        found: list[MatchRecord] = []
        while index < len(self._records):
            record = self._records[index]
            if record.start >= end and not (record.start == record.end == start == end):
                break
            intersects = (
                start <= record.start < end
                if record.start == record.end
                else record.end > start and record.start < end
            )
            if start == end == record.start == record.end:
                intersects = True
            if intersects:
                found.append(record)
            index += 1
        return tuple(found)

    def next_index(self, position: int) -> int | None:
        from bisect import bisect_left

        if not self._records:
            return None
        index = bisect_left(self._starts, position)
        return 0 if index >= len(self._records) else index

    def previous_index(self, position: int) -> int | None:
        from bisect import bisect_left

        if not self._records:
            return None
        index = bisect_left(self._starts, position) - 1
        return len(self._records) - 1 if index < 0 else index
