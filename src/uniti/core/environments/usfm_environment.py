"""USFM environment (ADR-0013, Phase E6).

Generic SFM plus official USFM knowledge: the vendored baseline `usfm.sty`
(`sfm/usfm_baseline.py`) loaded into a `StyleRegistry` for structural
queries (`occurs_under`/`rank`/`end_marker`/`is_repeatable`/`style_type` —
exposed for a future marker/style inspector, not consumed by anything in
this phase, matching Phase E5's decision 6), plus `usfmtc`-backed
reference-conformance validation. A separate `Environment` (not a mode
switch on `SfmEnvironment`) because `.usfm` and `.sfm` resolve to distinct
environment keys via `profile_for_extension` (`syntax_profiles.USFM` vs.
`SFM`) — ADR-0013 decision 3's per-document environment-key resolution.

Deliberately not in this phase: loading a project's *own* `.sty` on top of
the baseline (no discovery/precedence mechanism is wired into activation
yet — `StyleRegistry.from_layers` already supports it mechanically), and
OccursUnder-driven structural validation (misplaced-marker checking is left
to `usfmtc`'s grammar-based parser, which already reports this class of
error; hand-rolling a second, likely-redundant OccursUnder walker before a
real gap is observed would be exactly the speculative generalization this
project avoids).
"""

from __future__ import annotations

import re

from uniti.core.decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import (
    CommandResult,
    EnvironmentCommand,
    NavigateTo,
    ShowMessage,
    document_text,
    validate_command,
)
from uniti.core.environment_findings import EnvironmentFinding
from uniti.core.syntax_profiles import USFM

from .sfm.navigation import VerseLocation, build_chapter_verse_index
from .sfm.stylesheet_support import StylesheetSupport
from .sfm.usfm_baseline import load_usfm_baseline
from .sfm.usfmtc_adapter import validate_with_usfmtc
from .sfm.validation import unmatched_end_marker_findings


_REFERENCE_RE = re.compile(r"\s*(\d+)\s*(?:[:.\s]\s*(\d+)\s*)?")
_VERSE_NUMBER_RE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")


def _verse_contains(verse: str, number: int) -> bool:
    """Whether a `\\v` label (``"16"``, a bridge ``"16-17"``, ``"16a"``) covers `number`."""

    match = _VERSE_NUMBER_RE.match(verse)
    if match is None:
        return False
    first = int(match.group(1))
    last = int(match.group(2)) if match.group(2) else first
    return first <= number <= last


def find_verse(
    index: tuple[VerseLocation, ...], chapter: int, verse: int | None
) -> VerseLocation | None:
    """The first `\\v` location matching `chapter` (and `verse`, when given)."""

    for location in index:
        if location.chapter is None or not location.chapter.isdigit() or int(location.chapter) != chapter:
            continue
        if verse is None or _verse_contains(location.verse, verse):
            return location
    return None


class UsfmEnvironment(StylesheetSupport):
    """USFM environment: layered STY (official baseline + project layers,
    ADR-0015), reference validation, chapter/verse navigation."""

    key = "usfm"

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(USFM)
        self._init_styles(load_usfm_baseline())

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider

    def chapter_verse_index(self, context: EnvironmentContext) -> tuple[VerseLocation, ...]:
        """Ordered `\\v` locations (chapter/verse navigation, future UI)."""

        if not context.resource_profile.allow_full_parse:
            return ()
        text = "".join(chunk for _start, chunk in context.edits.iter_text())
        return build_chapter_verse_index(text) if text else ()

    def validate(self, context: EnvironmentContext) -> tuple[EnvironmentFinding, ...]:
        if not context.resource_profile.allow_full_parse:
            return ()
        text = "".join(chunk for _start, chunk in context.edits.iter_text())
        if not text:
            return ()
        return unmatched_end_marker_findings(text) + validate_with_usfmtc(text)

    def commands(self) -> tuple[EnvironmentCommand, ...]:
        return (
            EnvironmentCommand(
                "go_to",
                "Go to Chapter:Verse…",
                group="navigate",
                run=self._go_to_verse,
                prompt="Chapter:Verse (e.g. 3:16, or just 3):",
                prompt_title="Go to Chapter:Verse",
            ),
            validate_command(self, label="Validate USFM"),
            *self.stylesheet_commands(),
        )

    def _go_to_verse(self, context: EnvironmentContext, argument: str | None) -> CommandResult:
        title = "Go to Chapter:Verse"
        match = _REFERENCE_RE.fullmatch(argument or "")
        if match is None:
            return ShowMessage(title, f"Not a chapter:verse reference: {argument!r}", level="warning")
        chapter = int(match.group(1))
        verse = int(match.group(2)) if match.group(2) else None
        if not context.resource_profile.allow_full_parse:
            return ShowMessage(
                title,
                "This document is too large to index chapters and verses; "
                "use Go to Line instead.",
            )
        text = document_text(context)
        location = find_verse(build_chapter_verse_index(text) if text else (), chapter, verse)
        if location is None:
            reference = f"{chapter}:{verse}" if verse is not None else f"chapter {chapter}"
            return ShowMessage(title, f"{reference} was not found in this document.")
        return NavigateTo(location.start)
