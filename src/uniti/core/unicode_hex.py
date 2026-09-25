"""Unicode hex-codepoint <-> character conversion (BF-053).

The input-direction inverse of the existing Unicode inspection combination
(BF-003/BF-004), which shows a code point and name for a character already
in the document. This module is Qt-free; `EditorState.toggle_unicode_hex`
(`uniti.app.editor_state`) is the editing entry point.
"""

from __future__ import annotations

import re

MAX_CODE_POINT = 0x10FFFF
_SURROGATE_RANGE = range(0xD800, 0xE000)

# Mirrors the well-known Microsoft Word Alt+X convention: a contiguous run
# of 4-6 hex digits immediately before the cursor, with an optional `U+` or
# `0x` prefix. 6 digits covers every valid code point (0x10FFFF).
#
# BF-089: the minimum was 1, not 4, until a beta tester flagged the
# resulting ambiguity -- a bare trailing hex letter (e.g. "A") converted
# forward as a control character (0x0A, a newline) instead of reversing to
# its own U+0041 notation, which is what a user typing a single letter then
# invoking the toggle almost always means. `hex_notation` below already
# always renders at least 4 digits, so requiring the same minimum on the
# way in is the same convention applied both directions, not an arbitrary
# new rule -- and it matches how a real U+XXXX codepoint is always written.
_HEX_RUN_RE = re.compile(r"(?:[Uu]\+|0[xX])?([0-9A-Fa-f]{4,6})$")

# Bounded lookback window so this never reads an arbitrarily long line just
# to check for a trailing hex run.
LOOKBACK_WINDOW = 16


def hex_run_before_cursor(text_before: str) -> tuple[int, int] | None:
    """Find the hex run ending exactly at the end of `text_before`.

    Returns `(run_length, code_point)` — `run_length` includes any matched
    prefix, so the caller can replace exactly that span — if it parses to a
    valid, non-surrogate code point, else `None` (including for an
    out-of-range or surrogate value: treated as no match rather than an
    error, so the caller can fall back to the reverse direction).
    """

    match = _HEX_RUN_RE.search(text_before)
    if match is None:
        return None
    code_point = int(match.group(1), 16)
    if code_point > MAX_CODE_POINT or code_point in _SURROGATE_RANGE:
        return None
    return len(match.group(0)), code_point


def hex_notation(character: str) -> str:
    """`U+XXXX` notation (uppercase, at least 4 digits) for one character."""

    if len(character) != 1:
        raise ValueError("hex_notation expects exactly one character")
    return f"U+{ord(character):04X}"
