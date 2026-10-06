"""Chapter/verse navigation index (ADR-0013, Phase E6).

A flat, ordered index of `\\c`/`\\v` positions built from the lossless
tokenizer — independent of the STY-aware validation pieces, since chapter
and verse markers are fixed USFM lexical conventions, not stylesheet data.
No UI navigator consumes this yet, matching the same "build the mechanism,
defer UI wiring" pattern the E3–E5 `EnvironmentFinding`/`validate()` seam
already established (nothing in `ui/` surfaces those either).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .tokenizer import tokenize_sfm
from .tokens import SfmTokenKind

_LEADING_TOKEN_RE = re.compile(r"^\s*(\S+)")


@dataclass(frozen=True, slots=True)
class VerseLocation:
    """One `\\v` marker's position, with the chapter it falls under.

    `chapter`/`verse` are the raw marker text (e.g. `"1"`, `"1-2"` for a
    bridged verse) — USFM permits non-numeric-range forms this phase does
    not need to interpret, only to locate.
    """

    chapter: str | None
    verse: str
    start: int
    end: int


def build_chapter_verse_index(text: str) -> tuple[VerseLocation, ...]:
    """Build an ordered `\\v` index from `text`, tracking the current `\\c`."""

    tokens = tokenize_sfm(text)
    locations: list[VerseLocation] = []
    current_chapter: str | None = None
    for index, token in enumerate(tokens):
        if token.kind is not SfmTokenKind.MARKER or token.text not in (r"\c", r"\v"):
            continue
        if index + 1 >= len(tokens) or tokens[index + 1].kind is not SfmTokenKind.TEXT:
            continue
        following = tokens[index + 1]
        match = _LEADING_TOKEN_RE.match(following.text)
        if match is None:
            continue
        number = match.group(1)
        if token.text == r"\c":
            current_chapter = number
        else:
            locations.append(
                VerseLocation(
                    chapter=current_chapter,
                    verse=number,
                    start=token.start,
                    end=following.start + match.end(1),
                )
            )
    return tuple(locations)


__all__ = ["VerseLocation", "build_chapter_verse_index"]
