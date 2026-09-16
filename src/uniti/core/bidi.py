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

import unicodedata

_STRONG_LTR = "L"
_STRONG_RTL = ("R", "AL")


def is_rtl_paragraph(text: str) -> bool:
    """True if `text`'s first strong-directional character is right-to-left."""

    for character in text:
        bidi_category = unicodedata.bidirectional(character)
        if bidi_category == _STRONG_LTR:
            return False
        if bidi_category in _STRONG_RTL:
            return True
    return False
