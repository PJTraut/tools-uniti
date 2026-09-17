"""Bounded, cross-line-aware syntax-highlighting profiles for UNITI
(BF-027/BF-041, extended for multi-line constructs per the "File-type
profiles and syntax highlighting" parked-capability catalog entry).

A profile's `tokenize` never mutates its input. It is called once per
*logical line*, taking that line's text plus the tokenizer's own state as
of the start of the line, and returns the line's tokens plus the state to
carry into the *next* logical line — this is what lets a multi-line
comment, a fenced code block, or a YAML block scalar highlight correctly
across the line where it opens and the lines where it continues. State is
opaque to callers: each profile defines its own state shape (or none at
all) and interprets only its own.

Deliberate scope, recorded here rather than left implicit:

- State threads across *logical* lines only. A single very long logical
  line that wraps or horizontally scrolls across multiple visible rows
  does not thread state *within* itself between those rows — every row of
  one logical line is tokenized from that line's own start state, not
  from whatever an earlier row of the same line ended in. Mixing a
  many-thousand-character single line with an opening comment partway
  through and its close much later in that same line is the one case
  this does not handle; a construct spanning multiple ordinary lines
  (the overwhelmingly common real case, and the one named in the parked
  capability's own re-evaluation trigger) is handled.
- Each visible row is still tokenized independently and boundedly (the UI
  layer caches only a *state* value per logical line, never a whole
  document's parse tree), so this stays huge-file-safe by construction —
  no new incremental-parsing subsystem, matching the original design's
  intent.
- Multi-line constructs are implemented for XML (`<!-- -->` comments,
  `<![CDATA[ ]]>` sections) and Markdown (fenced ``` ``` ```/`~~~` code
  blocks) and YAML (`|`/`>` block scalars) — the profiles with a genuine,
  common multi-line construct. JSON, SFM, and TSV have no construct that
  can span a line under their current rule sets (a JSON string cannot
  contain a literal newline; SFM markers and TSV fields are inherently
  line-oriented) and stay fully stateless. CSV's quoted-field newlines are
  deliberately not handled: a quoted CSV field containing a literal
  newline changes what a "row" even is, entangling this with the
  document's own line segmentation rather than being presentation-only —
  a materially different, larger change, left for a future decision.
  Markdown HTML block comments are also not handled here: unlike fenced
  code blocks, they had no single-line recognition at all before this
  pass, so adding them would be new tokenizing scope, not an extension of
  an existing flagged gap.
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
    tokenize: Callable[[str, object], tuple[tuple[SyntaxToken, ...], object]]
    initial_state: object = None


def _scan(
    line: str,
    rules: tuple[tuple[str, re.Pattern[str]], ...],
) -> tuple[SyntaxToken, ...]:
    """Single-pass left-to-right scan: the first rule whose pattern matches
    at a given position wins, mirroring how the Find/Replace regex lexer
    already resolves overlapping possibilities."""

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


def _regex_tokenizer(
    rules: tuple[tuple[str, re.Pattern[str]], ...],
) -> Callable[[str, object], tuple[tuple[SyntaxToken, ...], object]]:
    """A stateless tokenizer from ordered (category, pattern) rules, for a
    profile with no construct that can span more than one line."""

    def tokenize(line: str, state: object) -> tuple[tuple[SyntaxToken, ...], object]:
        del state
        return _scan(line, rules), None

    return tokenize


def _plain_text_tokenize(
    line: str, state: object
) -> tuple[tuple[SyntaxToken, ...], object]:
    del line, state
    return (), None


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

# A line ending in `: |`, `: >`, `- |2-`, etc. (optionally trailed by a
# comment) opens a YAML block scalar. Heuristic, not full YAML grammar: it
# can be fooled by a `|`/`>` inside a quoted value or comment that happens
# to sit right after a colon/dash, which is accepted as a known limitation
# of a presentation-only tokenizer rather than a full parser.
_YAML_BLOCK_SCALAR_OPEN_RE = re.compile(r"[:\-]\s*[|>][+-]?\d*\s*(?:#.*)?$")

_XML_TAG_RULES = (
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

# At most 3 leading spaces before the fence, per CommonMark.
_MARKDOWN_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})")

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


def _xml_tokenize(
    line: str, state: object
) -> tuple[tuple[SyntaxToken, ...], object]:
    tokens: list[SyntaxToken] = []
    i = 0
    n = len(line)
    if state == "comment":
        end = line.find("-->")
        if end == -1:
            if n:
                tokens.append(SyntaxToken("comment", 0, n))
            return tuple(tokens), "comment"
        tokens.append(SyntaxToken("comment", 0, end + 3))
        i = end + 3
    elif state == "cdata":
        end = line.find("]]>")
        if end == -1:
            if n:
                tokens.append(SyntaxToken("keyword", 0, n))
            return tuple(tokens), "cdata"
        tokens.append(SyntaxToken("keyword", 0, end + 3))
        i = end + 3
    while i < n:
        if line.startswith("<!--", i):
            end = line.find("-->", i + 4)
            if end == -1:
                tokens.append(SyntaxToken("comment", i, n))
                return tuple(tokens), "comment"
            tokens.append(SyntaxToken("comment", i, end + 3))
            i = end + 3
            continue
        if line.startswith("<![CDATA[", i):
            end = line.find("]]>", i + 9)
            if end == -1:
                tokens.append(SyntaxToken("keyword", i, n))
                return tuple(tokens), "cdata"
            tokens.append(SyntaxToken("keyword", i, end + 3))
            i = end + 3
            continue
        for category, pattern in _XML_TAG_RULES:
            match = pattern.match(line, i)
            if match:
                if match.end() > match.start():
                    tokens.append(SyntaxToken(category, match.start(), match.end()))
                i = max(match.end(), i + 1)
                break
        else:
            i += 1
    return tuple(tokens), None


def _markdown_tokenize(
    line: str, state: object
) -> tuple[tuple[SyntaxToken, ...], object]:
    if isinstance(state, tuple) and state[0] == "fence":
        _, char, min_length = state
        stripped = line.strip()
        closes = len(stripped) >= min_length and stripped == char * len(stripped)
        tokens = (SyntaxToken("string", 0, len(line)),) if line else ()
        return tokens, (None if closes else state)
    match = _MARKDOWN_FENCE_OPEN_RE.match(line)
    if match:
        fence = match.group(1)
        return (
            (SyntaxToken("string", 0, len(line)),),
            ("fence", fence[0], len(fence)),
        )
    return _scan(line, _MARKDOWN_RULES), None


def _yaml_tokenize(
    line: str, state: object
) -> tuple[tuple[SyntaxToken, ...], object]:
    if isinstance(state, tuple) and state[0] == "block_scalar":
        _, indent = state
        if not line.strip():
            return (), state
        current_indent = len(line) - len(line.lstrip(" "))
        if indent is None:
            return (
                (SyntaxToken("string", 0, len(line)),),
                ("block_scalar", current_indent),
            )
        if current_indent >= indent:
            return (SyntaxToken("string", 0, len(line)),), state
        state = None
    tokens = _scan(line, _YAML_RULES)
    if _YAML_BLOCK_SCALAR_OPEN_RE.search(line):
        return tokens, ("block_scalar", None)
    return tokens, None


PLAIN_TEXT = SyntaxProfile("plain_text", "Plain Text", _plain_text_tokenize)
MARKDOWN = SyntaxProfile("markdown", "Markdown", _markdown_tokenize)
XML = SyntaxProfile("xml", "XML", _xml_tokenize)
JSON = SyntaxProfile("json", "JSON", _regex_tokenizer(_JSON_RULES))
YAML = SyntaxProfile("yaml", "YAML", _yaml_tokenize)
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
