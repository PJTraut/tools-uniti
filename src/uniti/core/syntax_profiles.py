"""Bounded, per-line syntax-highlighting profiles for UNITI (BF-027/BF-041).

Presentation-only: a profile's `tokenize` never mutates its input and is
scoped to exactly one line/visible-row's text, so it stays safe for huge
files without a new incremental-parsing or caching subsystem — matching the
scanning granularity the editor already uses for whitespace markers. This is
a deliberately bounded first slice of the parked "File-type profiles and
syntax highlighting" capability: constructs spanning more than one visible
row (a multi-line comment, a fenced code block, a value wrapped across
visual rows) are not tracked across rows and will not highlight correctly
across that boundary. Un-parked and scoped down to this for an initial
implementation; broader incremental/multiline support remains future work.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True, slots=True)
class SyntaxToken:
    category: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class SyntaxProfile:
    key: str
    label: str
    tokenize: Callable[[str], tuple[SyntaxToken, ...]]


def _regex_tokenizer(
    rules: tuple[tuple[str, re.Pattern[str]], ...],
) -> Callable[[str], tuple[SyntaxToken, ...]]:
    """Build a tokenizer from ordered (category, pattern) rules — the first
    rule whose pattern matches at a given position wins, mirroring how the
    Find/Replace regex lexer already resolves overlapping possibilities."""

    def tokenize(line: str) -> tuple[SyntaxToken, ...]:
        tokens: list[SyntaxToken] = []
        i = 0
        n = len(line)
        while i < n:
            for category, pattern in rules:
                match = pattern.match(line, i)
                if match:
                    if match.end() > match.start():
                        tokens.append(SyntaxToken(category, match.start(), match.end()))
                    i = max(match.end(), i + 1)
                    break
            else:
                i += 1
        return tuple(tokens)

    return tokenize


def _plain_text_tokenize(line: str) -> tuple[SyntaxToken, ...]:
    return ()


_JSON_RULES = (
    ("comment", re.compile(r"//[^\n]*")),
    ("string", re.compile(r'"(?:\\.|[^"\\])*"?')),
    ("number", re.compile(r"-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")),
    ("keyword", re.compile(r"\b(?:true|false|null)\b")),
    ("punctuation", re.compile(r"[{}\[\]:,]")),
)

_YAML_RULES = (
    ("comment", re.compile(r"#.*")),
    ("string", re.compile(r'"(?:\\.|[^"\\])*"?|\'(?:[^\']|\'\')*\'?')),
    ("keyword", re.compile(r"\b(?:true|false|null|yes|no)\b", re.IGNORECASE)),
    ("number", re.compile(r"-?\d+(?:\.\d+)?\b")),
    ("punctuation", re.compile(r"^(\s*)(-)(?=\s|$)")),
    ("attribute", re.compile(r"^\s*[\w.\-]+(?=\s*:(?:\s|$))")),
    ("punctuation", re.compile(r":")),
)

_XML_RULES = (
    ("comment", re.compile(r"<!--.*?-->")),
    ("keyword", re.compile(r"<!\[CDATA\[.*?\]\]>", re.DOTALL)),
    ("tag", re.compile(r"</?[A-Za-z_][\w.\-]*")),
    ("punctuation", re.compile(r"/?>")),
    ("attribute", re.compile(r"[A-Za-z_][\w.\-]*(?=\s*=)")),
    ("string", re.compile(r'"[^"]*"?|\'[^\']*\'?')),
)

_MARKDOWN_RULES = (
    ("heading", re.compile(r"^#{1,6}\s.*")),
    ("keyword", re.compile(r"^\s*(?:[-*+]|\d+\.)\s")),
    ("string", re.compile(r"`[^`]*`?")),
    ("keyword", re.compile(r"\*\*[^*]+\*\*|__[^_]+__")),
    ("attribute", re.compile(r"\*[^*]+\*|_[^_]+_")),
    ("tag", re.compile(r"!?\[[^\]]*\]\([^)]*\)?")),
)

_SFM_RULES = (
    ("keyword", re.compile(r"\\[A-Za-z][A-Za-z0-9]*\*?")),
)

_CSV_RULES = (
    ("string", re.compile(r'"(?:[^"]|"")*"?')),
    ("punctuation", re.compile(r",")),
)

_TSV_RULES = (
    ("punctuation", re.compile(r"\t")),
)


PLAIN_TEXT = SyntaxProfile("plain_text", "Plain Text", _plain_text_tokenize)
MARKDOWN = SyntaxProfile("markdown", "Markdown", _regex_tokenizer(_MARKDOWN_RULES))
XML = SyntaxProfile("xml", "XML", _regex_tokenizer(_XML_RULES))
JSON = SyntaxProfile("json", "JSON", _regex_tokenizer(_JSON_RULES))
YAML = SyntaxProfile("yaml", "YAML", _regex_tokenizer(_YAML_RULES))
SFM = SyntaxProfile("sfm", "SFM", _regex_tokenizer(_SFM_RULES))
CSV = SyntaxProfile("csv", "CSV", _regex_tokenizer(_CSV_RULES))
TSV = SyntaxProfile("tsv", "TSV", _regex_tokenizer(_TSV_RULES))

PROFILES: tuple[SyntaxProfile, ...] = (
    PLAIN_TEXT,
    MARKDOWN,
    XML,
    JSON,
    YAML,
    SFM,
    CSV,
    TSV,
)

PROFILES_BY_KEY: dict[str, SyntaxProfile] = {profile.key: profile for profile in PROFILES}

# Extension (lowercase, no leading dot) -> profile key. An extension with no
# entry here (including an unrecognized one) falls back to Plain Text.
DEFAULT_EXTENSION_PROFILES: dict[str, str] = {
    "md": "markdown",
    "markdown": "markdown",
    "xml": "xml",
    "json": "json",
    "yaml": "yaml",
    "yml": "yaml",
    "sfm": "sfm",
    "csv": "csv",
    "tsv": "tsv",
}


def profile_for_extension(
    extension: str,
    overrides: dict[str, str] | None = None,
) -> SyntaxProfile:
    """Resolve a file extension to its syntax profile.

    `extension` is matched case-insensitively and tolerates a leading dot.
    `overrides` (e.g. a user's own extension-to-profile assignment, such as
    mapping a custom `.usj` extension to the JSON profile) take priority
    over `DEFAULT_EXTENSION_PROFILES`. An unrecognized extension, or an
    override/default naming an unknown profile key, falls back to Plain
    Text — highlighting must never fail to display a document.
    """

    key = extension.lower().lstrip(".")
    profile_key = (overrides or {}).get(key) or DEFAULT_EXTENSION_PROFILES.get(key)
    if profile_key is None:
        return PLAIN_TEXT
    return PROFILES_BY_KEY.get(profile_key, PLAIN_TEXT)
