"""Line-level diff engine for document comparison (BF-070, Phase 1).

Qt-free and deliberately narrow, mirroring `uniti.core.bidi`'s shape: this
module only diffs two already-split sequences of lines and answers "which
hunk does this line belong to" and "what's the corresponding line on the
other side" — it knows nothing about `Document`, encoding, or Qt. Callers
are responsible for splitting a document into lines consistent with
UNITI's own line semantics (`Document.line_start`/`line_end`, not Python's
broader `str.splitlines()`, which also breaks on separators UNITI's EOL
model does not treat as line breaks).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from enum import Enum


class HunkKind(Enum):
    EQUAL = "equal"
    INSERT = "insert"
    DELETE = "delete"
    REPLACE = "replace"


@dataclass(frozen=True, slots=True)
class Hunk:
    """One aligned span between the two sides, in line-index coordinates.

    Ranges are half-open, like `range()`: `[left_start, left_end)` and
    `[right_start, right_end)`. An `INSERT` hunk has an empty left range
    (`left_start == left_end`); a `DELETE` hunk has an empty right range.
    """

    kind: HunkKind
    left_start: int
    left_end: int
    right_start: int
    right_end: int


_TAG_TO_KIND = {
    "equal": HunkKind.EQUAL,
    "insert": HunkKind.INSERT,
    "delete": HunkKind.DELETE,
    "replace": HunkKind.REPLACE,
}


def diff_lines(left_lines: Sequence[str], right_lines: Sequence[str]) -> tuple[Hunk, ...]:
    """Diff two line sequences, returning hunks in left-to-right order."""

    matcher = SequenceMatcher(a=list(left_lines), b=list(right_lines), autojunk=False)
    return tuple(
        Hunk(_TAG_TO_KIND[tag], i1, i2, j1, j2)
        for tag, i1, i2, j1, j2 in matcher.get_opcodes()
    )


def changed_hunks(hunks: Sequence[Hunk]) -> tuple[Hunk, ...]:
    """Every hunk except `EQUAL` — the ones worth navigating to or applying."""

    return tuple(hunk for hunk in hunks if hunk.kind is not HunkKind.EQUAL)


def _align(hunks: Sequence[Hunk], line: int, *, source_start: str, source_end: str, target_start: str, target_end: str) -> float:
    for hunk in hunks:
        start = getattr(hunk, source_start)
        end = getattr(hunk, source_end)
        if start <= line < end:
            span = end - start
            fraction = (line - start) / span if span else 0.0
            target_span = getattr(hunk, target_end) - getattr(hunk, target_start)
            return getattr(hunk, target_start) + fraction * target_span
    if hunks:
        last = hunks[-1]
        return float(getattr(last, target_end))
    return 0.0


def align_left_to_right(hunks: Sequence[Hunk], left_line: int) -> float:
    """The right-side line position corresponding to `left_line`.

    Found by locating the hunk containing `left_line` on the left and
    mapping its fractional position within that hunk onto the
    corresponding right-side span. Used to keep two independently-scrolled
    panes visually aligned even though they generally have different line
    counts after insertions/deletions — a raw scrollbar-value link would
    drift inside any hunk of unequal length.
    """

    return _align(
        hunks,
        left_line,
        source_start="left_start",
        source_end="left_end",
        target_start="right_start",
        target_end="right_end",
    )


def align_right_to_left(hunks: Sequence[Hunk], right_line: int) -> float:
    """The mirror of `align_left_to_right`, mapping right lines to left."""

    return _align(
        hunks,
        right_line,
        source_start="right_start",
        source_end="right_end",
        target_start="left_start",
        target_end="left_end",
    )
