"""Restricted edit facade exposed to environments (ADR-0013, Phase E1).

An environment must never construct or replay `EditTransaction`/`EditOperation`
directly (those are `EditHistory`'s internal recording shape, not a
submission boundary — see `history.py`), and must never reach the piece
table or a Qt widget. It only sees this narrowed view of `Document`'s
existing public mutators. Staleness is the caller's responsibility, exactly
as it already is for every other `Document` caller: compare `revision`
before and after, the same pattern `apply_replacement_plan` and the save
flow already use.
"""

from __future__ import annotations

from collections.abc import Iterator

from .document import Document
from .offsets import ReadIntent


class EnvironmentEditFacade:
    """Narrow, revision-aware view of one `Document` for environment use."""

    def __init__(self, document: Document) -> None:
        self._document = document

    @property
    def revision(self) -> int:
        return self._document.revision

    def snapshot(self):
        return self._document.snapshot()

    def iter_text(
        self,
        start: int = 0,
        end: int | None = None,
        *,
        chunk_chars: int = 65_536,
        intent: ReadIntent = ReadIntent.RANDOM,
    ) -> Iterator[tuple[int, str]]:
        return self._document.iter_text(start, end, chunk_chars=chunk_chars, intent=intent)

    def insert(self, char_offset: int, text: str, *, coalesce: str | None = None) -> None:
        self._document.insert(char_offset, text, coalesce=coalesce)

    def delete(self, start: int, end: int, *, coalesce: str | None = None) -> None:
        self._document.delete(start, end, coalesce=coalesce)

    def replace(self, start: int, end: int, text: str, *, coalesce: str | None = None) -> None:
        self._document.replace(start, end, text, coalesce=coalesce)

    def replace_many(self, replacements: list[tuple[int, int, str]]) -> int:
        return self._document.replace_many(replacements)
