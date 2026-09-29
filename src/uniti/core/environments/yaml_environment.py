"""YAML light environment (ADR-0013, Phase E4).

Decoration adapts the existing `YAML` `SyntaxProfile`. `validate()` adds one
bounded, dependency-free check: a line whose leading indentation contains a
literal tab character, which the YAML spec forbids for block structure and
which is a common, easy-to-miss source of "why won't this parse" reports.

Deliberately narrow, like JSON's bracket-match validation: this is not a
YAML parser or schema validator (no third-party YAML library is added as a
dependency for this phase — see the project's dependency policy), and it
does not validate anything else about YAML structure. Streams chunk-by-
chunk via `iter_text()`, so — unlike XML's `ElementTree`-based validation —
it never materializes the whole document and needs no resource-profile gate.
"""

from __future__ import annotations

from uniti.core.decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_findings import EnvironmentFinding, FindingSeverity
from uniti.core.syntax_profiles import YAML


class YamlEnvironment:
    """Light environment: YAML decoration plus tab-indentation validation."""

    key = "yaml"

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(YAML)

    def activate(self, context: EnvironmentContext) -> None:
        del context

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider

    def validate(self, context: EnvironmentContext) -> tuple[EnvironmentFinding, ...]:
        findings: list[EnvironmentFinding] = []
        offset = 0
        at_line_start = True
        tab_found_this_line = False
        line_start_offset = 0
        for _chunk_start, text in context.edits.iter_text():
            for char in text:
                if char == "\n":
                    at_line_start = True
                    tab_found_this_line = False
                    line_start_offset = offset + 1
                elif at_line_start:
                    if char == "\t":
                        if not tab_found_this_line:
                            findings.append(
                                EnvironmentFinding(
                                    line_start_offset,
                                    offset + 1,
                                    FindingSeverity.ERROR,
                                    "tab used for indentation (YAML forbids "
                                    "tabs in indentation)",
                                    code="yaml.tab-indentation",
                                )
                            )
                            tab_found_this_line = True
                    elif char != " ":
                        at_line_start = False
                offset += 1
        return tuple(findings)
