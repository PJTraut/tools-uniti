"""XML light environment (ADR-0013, Phase E4).

Decoration adapts the existing `XML` `SyntaxProfile`. `validate()` adds
well-formedness checking using the standard library's `xml.etree.
ElementTree` — a real, correct XML parser already in the standard library,
not a hand-rolled tag matcher and not a new project dependency.

Unlike JSON's bracket-match validation (which streams chunk-by-chunk and
never materializes the whole document), `ElementTree.fromstring` needs the
complete text in memory to build its tree. This validation therefore only
runs when `context.resource_profile.allow_full_parse` is true — degrading
to "no findings" on a large file rather than reading an arbitrarily huge
document into memory, matching this project's large-file principle (see
ADR-0013 decision 5, and the original spec's own "do not construct a full
DOM for mega files").
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

from uniti.core.decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_findings import EnvironmentFinding, FindingSeverity
from uniti.core.syntax_profiles import XML


class XmlEnvironment:
    """Light environment: XML decoration plus well-formedness validation."""

    key = "xml"

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(XML)

    def activate(self, context: EnvironmentContext) -> None:
        del context

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider

    def validate(self, context: EnvironmentContext) -> tuple[EnvironmentFinding, ...]:
        if not context.resource_profile.allow_full_parse:
            return ()
        text = "".join(chunk for _start, chunk in context.edits.iter_text())
        if not text.strip():
            # An empty or whitespace-only document is not "invalid XML" in
            # any sense a user editing a new file cares about.
            return ()
        try:
            ET.fromstring(text)
        except ET.ParseError as exc:
            offset = _char_offset(text, exc.position)
            return (
                EnvironmentFinding(
                    offset,
                    offset + 1,
                    FindingSeverity.ERROR,
                    str(exc),
                    code="xml.not-well-formed",
                ),
            )
        return ()


def _char_offset(text: str, position: tuple[int, int]) -> int:
    """Convert `ElementTree.ParseError.position` (1-based line, 0-based
    column) into a char offset into `text`."""

    line, column = position
    lines = text.split("\n")
    preceding = sum(len(entry) + 1 for entry in lines[: line - 1])
    return preceding + column
