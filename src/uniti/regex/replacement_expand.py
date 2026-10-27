r"""Expanding a replacement template for one match, with case conversion.

The `regex` engine's `Match.expand` knows groups and character escapes but not
case conversion, so the template is tokenized (`tokenize_replacement`) and each
token expanded by the engine on its own, with `\U`, `\L`, `\E`, `\u` and `\l`
applied here: `\U` and `\L` upper- or lower-case everything up to `\E`, and
`\u` and `\l` change only the next character (`\u\L\1` is "Lord" for "LORD").
"""

from __future__ import annotations

from collections.abc import Sequence

import regex

from .lexer import RegexToken, tokenize_replacement


class _CaseState:
    def __init__(self) -> None:
        self.mode: str | None = None  # "U", "L" or None
        self.once: str | None = None  # "u", "l" or None

    def apply(self, text: str) -> str:
        if not text:
            return text  # a pending \u or \l waits for the next character
        first, rest = text[0], text[1:]
        if self.mode == "U":
            rest = rest.upper()
        elif self.mode == "L":
            rest = rest.lower()
        if self.once is not None:
            first = first.upper() if self.once == "u" else first.lower()
            self.once = None
        elif self.mode == "U":
            first = first.upper()
        elif self.mode == "L":
            first = first.lower()
        return first + rest

    def switch(self, escape: str) -> None:
        if escape == r"\E":
            self.mode = None
        elif escape in (r"\U", r"\L"):
            self.mode = escape[1]
        else:
            self.once = escape[1]


def expand_tokens(match: regex.Match, tokens: Sequence[RegexToken]) -> list[str]:
    """Each token's text for `match`, case conversion applied (a case escape
    itself is empty), in order."""

    state = _CaseState()
    pieces: list[str] = []
    for token in tokens:
        if token.kind == "case_escape":
            state.switch(token.text)
            pieces.append("")
        else:
            pieces.append(state.apply(match.expand(token.text)))
    return pieces


def expand_replacement(match: regex.Match, template: str) -> str:
    """`template` for `match`; raises `regex.error` for a bad group reference."""

    if "\\" not in template:
        return template  # nothing to expand: the common plain replacement
    tokens = tokenize_replacement(template, group_count=match.re.groups, group_names=match.re.groupindex)
    return "".join(expand_tokens(match, tokens))


__all__ = ["expand_replacement", "expand_tokens"]
