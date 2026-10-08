"""Lossless generic-SFM tokenizer (Phase E5).

Splits raw SFM/USFM source into `MARKER` tokens (`\\word`, `\\word*`,
nested `\\+word`, milestones `\\word-s`/`\\word-e` and their `\\*`) and
`TEXT` tokens (everything between them), preserving exact spans so the
source can always be reconstructed byte-for-byte from the token stream.
This is deliberately a lexer, not a parser: it does not know which markers
pair with which, or what any marker means — see `parser.py` for that.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from .tokens import SfmToken, SfmTokenKind

# `\name`, `\name*`, nested `\+name` / `\+name*`, milestones `\name-s` /
# `\name-e`, column ranges `\th1-2`, and a milestone's closing `\*` (see
# `markers.py`).
_MARKER_RE = re.compile(r"\\(?:\*|\+?[A-Za-z][A-Za-z0-9]*(?:-(?:[se](?![A-Za-z0-9])|\d+))?\*?)")


def tokenize_sfm(text: str) -> tuple[SfmToken, ...]:
    """Tokenize `text` into a contiguous, gap-free stream of `SfmToken`s."""

    tokens: list[SfmToken] = []
    length = len(text)
    pos = 0
    while pos < length:
        match = _MARKER_RE.match(text, pos)
        if match is not None:
            tokens.append(SfmToken(SfmTokenKind.MARKER, match.start(), match.end(), match.group()))
            pos = match.end()
            continue
        next_backslash = text.find("\\", pos + 1)
        end = length if next_backslash == -1 else next_backslash
        tokens.append(SfmToken(SfmTokenKind.TEXT, pos, end, text[pos:end]))
        pos = end
    return tuple(tokens)


def reconstruct(tokens: Sequence[SfmToken]) -> str:
    """Rebuild the original source from a token stream (lossless-ness check)."""

    return "".join(token.text for token in tokens)
