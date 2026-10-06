"""Generic SFM environment (ADR-0013, Phase E5).

Same shape as `JsonEnvironment`/`XmlEnvironment`/`YamlEnvironment`: decoration
is an unchanged adapter over the existing regex-based `SFM` `SyntaxProfile`
(richer, STY-aware decoration — e.g. flagging an unknown marker — needs a
style registry wired into activation, which is Phase E6's job once USFM
detection exists). `validate()` adds one narrow, honest capability: flagging
an end marker (`\\xyz*`) that has no matching open marker anywhere in the
document. It deliberately does *not* flag an unclosed open marker, because
in generic SFM (no loaded stylesheet) an unclosed `\\p`/`\\v`/`\\c` is the
overwhelmingly normal case, not an error — see `sfm/parser.py`'s docstring
for the same reasoning applied to the source tree.
"""

from __future__ import annotations

from uniti.core.decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_commands import EnvironmentCommand, validate_command
from uniti.core.environment_findings import EnvironmentFinding
from uniti.core.syntax_profiles import SFM

from .sfm.stylesheet_support import StylesheetSupport
from .sfm.validation import unmatched_end_marker_findings


class SfmEnvironment(StylesheetSupport):
    """Generic-SFM environment: decoration, end-marker checks, and (ADR-0015)
    whatever project `.sty` layers sit next to the document — no official
    baseline, since generic SFM has none."""

    key = "sfm"

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(SFM)
        self._init_styles(None)

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider

    def commands(self) -> tuple[EnvironmentCommand, ...]:
        return (validate_command(self, label="Check Markers"), *self.stylesheet_commands())

    def validate(self, context: EnvironmentContext) -> tuple[EnvironmentFinding, ...]:
        if not context.resource_profile.allow_full_parse:
            return ()
        text = "".join(chunk for _start, chunk in context.edits.iter_text())
        if not text:
            return ()
        return unmatched_end_marker_findings(text)
