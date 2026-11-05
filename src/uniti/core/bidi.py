"""Paragraph base-direction detection for bidirectional text (BF-064).

Implements the Unicode Bidirectional Algorithm's first-strong-character
rule (UAX #9 P2/P3): a paragraph's base direction is that of the first
character with a strong directional type (`L`, `R`, or `AL`); weak types
(digits, punctuation) and neutral types (whitespace) are skipped. Text with
no strong character defaults to left-to-right.

This is Qt-free and intentionally narrow: it only answers "which way does
this paragraph start," not full bidi reordering — that is Qt's
`QTextLayout`'s job once given the correct base direction (see
`uniti.ui.text_layout`).
"""

from __future__ import annotations

import re
import unicodedata

_STRONG_LTR = "L"
_STRONG_RTL = ("R", "AL")

# A USFM-style marker: `\\v`, `\\+nd`, `\\f*`.
MARKER_PATTERN = r"\\\+?[A-Za-z][A-Za-z0-9]*\*?"
_MARKER = re.compile(MARKER_PATTERN)


def first_strong_direction(text: str) -> str | None:
    """`"rtl"` or `"ltr"` by `text`'s first strong letter, None when it has
    none (a tag-only line such as `\\p` or `\\c 1`). Backslash markers
    (`\\v`, `\\+nd*`) are skipped (N39): they are Latin in every book, so a
    Persian verse line that starts with `\\v 1` would otherwise always read
    left to right."""

    for character in _MARKER.sub(" ", text) if "\\" in text else text:
        bidi_category = unicodedata.bidirectional(character)
        if bidi_category == _STRONG_LTR:
            return "ltr"
        if bidi_category in _STRONG_RTL:
            return "rtl"
    return None


def is_rtl_paragraph(text: str) -> bool:
    """True if `text`'s first strong-directional character is right-to-left."""

    return first_strong_direction(text) == "rtl"


# Digits joined by a dash, colon or the like: a verse range (`1-3`, `2:3–5`).
RANGE_PATTERN = r"\d+(?:[-\u2010-\u2015\u2212:.,]\d+)+"


def dominant_direction(text: str, *, minimum: int = 20) -> str | None:
    """`"rtl"` when most of `text`'s strong letters are right-to-left,
    `"ltr"` when most are left-to-right, None when there are fewer than
    `minimum` of them to go by (N39: Auto reading of a Persian book).
    Backslash markers (`\\id`, `\\+nd*`) are skipped: they are Latin in every
    book and would outvote an Arabic-script text."""

    right = left = 0
    for character in _MARKER.sub(" ", text):
        category = unicodedata.bidirectional(character)
        if category == _STRONG_LTR:
            left += 1
        elif category in _STRONG_RTL:
            right += 1
    if right + left < minimum:
        return None
    return "rtl" if right > left else "ltr"
