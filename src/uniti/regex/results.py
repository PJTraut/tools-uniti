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
