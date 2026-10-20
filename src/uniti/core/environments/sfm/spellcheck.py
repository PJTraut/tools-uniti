"""Finding misspelled words in USFM (plan 2026-10-13-usfm-spellcheck-plan, S2).

The checker works a line at a time and remembers every line. A line's
flagged words depend only on its text and its start state (the paragraph
marker in effect and the character markers still open), so one cache keyed
by (start state, line text) serves every view of a document, and an edit
makes only the changed lines be checked again. Qt-free.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import regex

from .markers import is_closing, is_milestone, is_milestone_close, marker_name
from .spelling import Spelling, SpellingList, SpellingState, normalize
from .tokenizer import tokenize_sfm
from .tokens import SfmTokenKind

# A word: letters and combining marks, joined by an apostrophe, a hyphen or
# ZWJ/ZWNJ only when the run goes on with a letter. Digits and punctuation
# split words.
WORD_RE = regex.compile(
    r"[\p{L}\p{M}]+(?:['’\-‑‌‍](?=[\p{L}\p{M}])[\p{L}\p{M}]*)*"
)
# After these, the first word of the text is the number (`\c 1`, `\v 2-3`).
_NUMBERED = frozenset({"c", "v", "cp"})
_LINE_RE = re.compile(r"[^\r\n]*(?:\r\n|\r|\n|$)")


class _Styles(Protocol):
    def style_for(self, marker: str): ...


@dataclass(frozen=True, slots=True)
class LineState:
    """What carries from one line to the next."""

    paragraph: str | None = None
    open: tuple[str, ...] = ()
    milestone: bool = False


START = LineState()


@dataclass(frozen=True, slots=True)
class Span:
    """A flagged word: columns in its line (or offsets in the document)."""

    start: int
    end: int
    spelling: Spelling


class CheckContext:
    """The word lists and the stylesheet's idea of which text is checked."""

    def __init__(self, words: SpellingList, styles: _Styles, project_name: str = "the project") -> None:
        self.words = words
        self.project_name = project_name
        self._styles = styles
        self._skips: dict[str, bool] = {}
        self._paragraphs: dict[str, bool] = {}
        self._closable: dict[str, bool] = {}

    def skips(self, marker: str) -> bool:
        """Whether the text of `marker` isn't checked: `nonvernacular`
        text, and `\\ca`, `\\va`, `\\vp`, which hold numbers."""

        known = self._skips.get(marker)
        if known is None:
            style = self._styles.style_for(marker)
            known = marker in ("ca", "va", "vp") or (
                style is not None and "nonvernacular" in style.text_properties
            )
            self._skips[marker] = known
        return known

    def is_paragraph(self, marker: str) -> bool:
        known = self._paragraphs.get(marker)
        if known is None:
            style = self._styles.style_for(marker)
            known = style is not None and (style.style_type or "").lower() == "paragraph"
            self._paragraphs[marker] = known
        return known

    def has_end_marker(self, marker: str) -> bool:
        known = self._closable.get(marker)
        if known is None:
            style = self._styles.style_for(marker)
            known = style is not None and bool(style.end_marker)
            self._closable[marker] = known
        return known


def check_line(line: str, state: LineState, context: CheckContext) -> tuple[tuple[Span, ...], LineState]:
    """The flagged words of `line` (without its line ending), and the state
    its end leaves for the next line."""

    paragraph, stack, milestone = state.paragraph, list(state.open), state.milestone
    skip_number = False
    in_attributes = False
    spans: list[Span] = []
    for token in tokenize_sfm(line):
        if token.kind is SfmTokenKind.MARKER:
            text = token.text
            in_attributes = False
            if is_milestone_close(text):
                milestone = False
                continue
            name = marker_name(text)
            if is_closing(text):
                if name in stack:
                    del stack[len(stack) - 1 - stack[::-1].index(name) :]
                continue
            if is_milestone(text):
                milestone = True
                continue
            skip_number = name in _NUMBERED
            if context.is_paragraph(name) and not text.startswith("\\+"):
                paragraph, stack = name, []
            elif context.has_end_marker(name):
                stack.append(name)
            continue
        if milestone:
            continue
        body = token.text
        offset = token.start
        if skip_number:
            stripped = body.lstrip()
            first = len(body) - len(stripped)
            cut = first
            while cut < len(body) and not body[cut].isspace():
                cut += 1
            offset += cut
            body = body[cut:]
            skip_number = False
        if (paragraph is not None and context.skips(paragraph)) or any(context.skips(item) for item in stack):
            continue
        if stack and "|" in body:
            body = body[: body.index("|")]  # attributes follow the bar
            in_attributes = True
        elif in_attributes:
            continue
        matches = list(WORD_RE.finditer(body))
        pairs = context.words.wrong_pairs
        index = 0
        while index < len(matches):
            match = matches[index]
            if pairs and index + 1 < len(matches):
                following = matches[index + 1]
                if body[match.end() : following.start()] == " ":
                    pair = (normalize(match.group()), normalize(following.group()))
                    if pair in pairs:
                        # Paratext marks the two words wrong together (F-D3).
                        spelling = Spelling(
                            SpellingState.WRONG,
                            correction=pairs[pair],
                            pair=True,
                            user=pair in context.words.rejected_pairs,
                        )
                        spans.append(Span(offset + match.start(), offset + following.end(), spelling))
                        index += 2
                        continue
            spelling = context.words.status(match.group())
            if spelling.state is not SpellingState.CORRECT:
                spans.append(Span(offset + match.start(), offset + match.end(), spelling))
            index += 1
    return tuple(spans), LineState(paragraph, tuple(stack), milestone)


def describe(spelling: Spelling, project_name: str) -> str:
    """What hovering a flagged word says (plan D6)."""

    if spelling.user:
        return "Marked wrong in your spelling list"
    if spelling.pair:
        if spelling.correction:
            return f"Paratext marks these two words wrong together: use {spelling.correction}"
        return "Paratext marks these two words wrong together"
    if spelling.state is SpellingState.WRONG:
        if spelling.correction:
            return f"Paratext marks this wrong: use {spelling.correction}"
        return "Paratext marks this wrong"
    if spelling.state is SpellingState.WRONG_CASE:
        return "Paratext spells it: " + " or ".join(spelling.forms)
    return f"Not in {project_name}'s spelling list"


def _starts_paragraph(line: str, context: CheckContext) -> str | None:
    if not line.startswith("\\"):
        return None
    for token in tokenize_sfm(line[:40]):
        if token.kind is SfmTokenKind.MARKER:
            name = marker_name(token.text)
            return name if not is_closing(token.text) and context.is_paragraph(name) else None
        return None
    return None


class SpellingCache:
    """One document's checked lines. `spans_for` checks one line,
    `book_spans` every line; both go through the (start state, line text)
    cache, so an edit costs only the changed lines."""

    def __init__(self, document, context: CheckContext) -> None:
        self._document = document
        self._context = context
        self._lines: dict[tuple[LineState, str], tuple[tuple[Span, ...], LineState]] = {}
        self.checked = 0  # lines actually checked (not found in the cache)
        self.generation = 0  # counts context changes, for views' own memos

    @property
    def context(self) -> CheckContext:
        return self._context

    def set_context(self, context: CheckContext) -> None:
        """The word list or the stylesheet changed: everything is re-checked."""

        self._context = context
        self._lines.clear()
        self.generation += 1

    def _check(self, line: str, state: LineState) -> tuple[tuple[Span, ...], LineState]:
        key = (state, line)
        found = self._lines.get(key)
        if found is None:
            found = self._lines[key] = check_line(line, state, self._context)
            self.checked += 1
            if len(self._lines) > 200_000:
                self._lines.clear()
        return found

    def _line_text(self, number: int) -> str:
        document = self._document
        return document.read(document.line_start(number), document.line_end(number))

    def line_start_state(self, number: int) -> LineState:
        """The state at the start of line `number`: found from the nearest
        line at or before it that starts a paragraph, not from the top."""

        first = number
        paragraph = None
        while first >= 0:
            paragraph = _starts_paragraph(self._line_text(first), self._context)
            if paragraph is not None:
                break
            first -= 1
        if first < 0:
            first = 0
        state = START
        for line in range(first, number):
            state = self._check(self._line_text(line), state)[1]
        return state

    def spans_for(self, number: int) -> tuple[Span, ...]:
        """The flagged words of line `number`, in its columns."""

        state = self.line_start_state(number)
        return self._check(self._line_text(number), state)[0]

    def book_spans(self) -> "BookSpans":
        """Every flagged word of the document, in document offsets, sorted."""

        document = self._document
        text = document.read(0, document.total_chars())
        state = START
        result: list[Span] = []
        for match in _LINE_RE.finditer(text):
            raw = match.group()
            if not raw and match.start() >= len(text):
                break
            content = raw.rstrip("\r\n")
            spans, state = self._check(content, state)
            base = match.start()
            result.extend(Span(base + span.start, base + span.end, span.spelling) for span in spans)
        return BookSpans(result)


class BookSpans:
    """A document's flagged words, sorted by offset, searchable by range."""

    def __init__(self, spans: list[Span]) -> None:
        self.spans = spans
        self._starts = [span.start for span in spans]

    def __len__(self) -> int:
        return len(self.spans)

    def __iter__(self):
        return iter(self.spans)

    def overlapping(self, start: int, end: int) -> list[Span]:
        """The spans overlapping [start, end), found by bisection."""

        from bisect import bisect_left, bisect_right

        first = bisect_left(self._starts, start)
        while first > 0 and self.spans[first - 1].end > start:
            first -= 1
        return self.spans[first : bisect_right(self._starts, end - 1)]


__all__ = [
    "BookSpans",
    "CheckContext",
    "LineState",
    "START",
    "WORD_RE",
    "Span",
    "SpellingCache",
    "check_line",
    "describe",
]
