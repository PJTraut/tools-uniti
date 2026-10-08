"""What a USFM marker token is (field test round 2, R2).

USFM 3 marker forms, as `tokenize_sfm` produces them:

- `\\name` / `\\name*` — a marker and its end marker;
- `\\+name` / `\\+name*` — a character style nested inside another one: the
  `+` says "nested", the style is still `name`'s (`\\+xt` is styled as `\\xt`);
- `\\name-s` / `\\name-e` — milestone start and end (`\\qt-s`, `\\ts-e`), each
  closed by its own `\\*` after any attributes;
- `\\th1-2`, `\\tc2-4` — table cells spanning columns.

Every consumer that looks a marker up in a stylesheet or compares markers
goes through `marker_name`, so the `+` and the end-marker `*` never leak
into a style lookup.
"""

from __future__ import annotations

import re

MILESTONE_CLOSE = "\\*"
_MILESTONE_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*-[se]")
# Notes are not character styles: a style applied inside a note's body is
# not nested (`\\f + \\ft text \\bd word\\bd*\\f*`).
NOTE_MARKERS = frozenset({"f", "fe", "ef", "x", "ex", "efe"})


def marker_name(token_text: str) -> str:
    """The style name of a marker token: ``\\+it*`` → ``it``, ``\\qt-s`` →
    ``qt-s``, ``\\th1-2`` → ``th1-2`` (see `views._cell_style_marker`),
    ``\\*`` → ``""``."""

    name = token_text[1:] if token_text.startswith("\\") else token_text
    if name.startswith("+"):
        name = name[1:]
    if name.endswith("*"):
        name = name[:-1]
    return name


def is_closing(token_text: str) -> bool:
    """An end marker (``\\it*``, ``\\+it*``) — not a milestone's ``\\*``."""

    return token_text.endswith("*") and token_text != MILESTONE_CLOSE


def is_nested(token_text: str) -> bool:
    return token_text.startswith("\\+")


def is_milestone(token_text: str) -> bool:
    """A milestone start or end (``\\qt-s``, ``\\ts-e``)."""

    return _MILESTONE_RE.fullmatch(marker_name(token_text)) is not None and not token_text.endswith("*")


def is_milestone_close(token_text: str) -> bool:
    return token_text == MILESTONE_CLOSE


__all__ = [
    "MILESTONE_CLOSE",
    "NOTE_MARKERS",
    "is_closing",
    "is_milestone",
    "is_milestone_close",
    "is_nested",
    "marker_name",
]
