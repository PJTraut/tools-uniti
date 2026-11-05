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

import re

from uniti.core.decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import EnvironmentCommand, validate_command
from uniti.core.environment_findings import EnvironmentFinding, FindingSeverity
from uniti.core.syntax_profiles import YAML

from .settings import NUMBER, EnvironmentSetting

YAML_SETTINGS: tuple[EnvironmentSetting, ...] = (
    EnvironmentSetting(
        "indent",
        "Indent width",
        NUMBER,
        2,
        "Check Indentation warns about indentation that isn't a multiple of this.",
        minimum=1,
        maximum=8,
        section="Check Indentation",
    ),
)
_BLOCK_SCALAR_RE = re.compile(r".*[:\-][ \t]+[|>][-+0-9]*[ \t]*(?:#.*)?$|^[ \t]*[|>][-+0-9]*[ \t]*$")


class YamlEnvironment:
    """Light environment: YAML decoration plus tab-indentation validation."""

    key = "yaml"

    @staticmethod
    def settings_declarations() -> tuple[EnvironmentSetting, ...]:
        return YAML_SETTINGS

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(YAML)

    def activate(self, context: EnvironmentContext) -> None:
        del context

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider

    def commands(self) -> tuple[EnvironmentCommand, ...]:
        return (validate_command(self, label="Check Indentation"),)

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
        return tuple(findings) + self._width_findings(context)

    @staticmethod
    def _width_findings(context: EnvironmentContext) -> tuple[EnvironmentFinding, ...]:
        """Indentation that isn't a multiple of the Indent width setting
        (N31): warnings. Blank lines, comments, tab-indented lines (already
        errors) and block scalar text (`|`, `>`) are skipped."""

        from .settings import environment_settings

        width = environment_settings("yaml").get("indent")
        if not isinstance(width, int) or width <= 1:
            return ()
        findings: list[EnvironmentFinding] = []
        scalar_indent: int | None = None  # inside a block scalar deeper than this
        offset = 0
        pending = ""
        chunks = (text for _start, text in context.edits.iter_text())
        for text in (*chunks, None):
            pending = pending + text if text is not None else pending + "\n"
            *lines, pending = pending.split("\n")
            for line in lines:
                stripped = line.lstrip(" ")
                indent = len(line) - len(stripped)
                content = stripped.strip()
                if scalar_indent is not None and (not content or indent > scalar_indent):
                    offset += len(line) + 1
                    continue
                scalar_indent = None
                if content and not content.startswith("#") and not stripped.startswith("\t") and indent % width:
                    findings.append(
                        EnvironmentFinding(
                            offset,
                            offset + indent,
                            FindingSeverity.WARNING,
                            f"indented {indent} spaces, not a multiple of {width}",
                            code="yaml.indent-width",
                        )
                    )
                if _BLOCK_SCALAR_RE.match(line):
                    scalar_indent = indent
                offset += len(line) + 1
            if text is None:
                break
        return tuple(findings)
