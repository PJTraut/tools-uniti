"""Regex replacement services for UNITI."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import regex

from uniti.core.document import Document
from .search import SearchOptions, _iter_engine_matches


@dataclass(frozen=True, slots=True)
class Replacement:
    start: int
    end: int
    text: str


def collect_replacements(
    document: Document,
    compiled: regex.Pattern,
    replacement: str,
    *,
    options: SearchOptions | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> list[Replacement]:
    opts = SearchOptions() if options is None else options
    replacements: list[Replacement] = []
    for record, match in _iter_engine_matches(
        document,
        compiled,
        options=opts,
        cancelled=cancelled,
    ):
        replacements.append(Replacement(record.start, record.end, match.expand(replacement)))
    return replacements


def replace_all(
    document: Document,
    compiled: regex.Pattern,
    replacement: str,
    *,
    options: SearchOptions | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> int:
    replacements = collect_replacements(
        document,
        compiled,
        replacement,
        options=options,
        cancelled=cancelled,
    )
    document.replace_many([(r.start, r.end, r.text) for r in replacements])
    return len(replacements)
