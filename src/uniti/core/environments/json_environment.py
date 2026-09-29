"""JSON light environment (ADR-0013, Phase E3).

The first proof that the environment framework does more than relabel
`syntax_profiles.py`: decoration is a straight adapter over the existing
`JSON` `SyntaxProfile`, and `validate()` adds one genuinely new capability
— bracket-match validation — surfaced through `EnvironmentContext` rather
than baked into the UI layer.

Deliberately narrow scope: this is bracket-match validation only, not a
JSON parser or schema validator. It tracks `{}`/`[]` nesting and ignores
brackets inside string literals (so a literal ``"{"`` in a value is not
misread as structure), but does not otherwise validate JSON grammar
(commas, colons, numbers, duplicate keys, ...). That is a materially larger
scope, left for a future phase if it turns out to matter in practice —
matching this project's stated preference for reuse/need discovered by
building the next real thing, not speculative generalization.
"""

from __future__ import annotations

from uniti.core.decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from uniti.core.environment import EnvironmentContext
from uniti.core.environment_findings import EnvironmentFinding, FindingSeverity
from uniti.core.syntax_profiles import JSON

_CLOSERS = {"}": "{", "]": "["}
_OPENERS = frozenset(_CLOSERS.values())


class JsonEnvironment:
    """Light environment: JSON decoration plus bracket-match validation."""

    key = "json"

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(JSON)

    def activate(self, context: EnvironmentContext) -> None:
        del context

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider

    def validate(self, context: EnvironmentContext) -> tuple[EnvironmentFinding, ...]:
        findings: list[EnvironmentFinding] = []
        stack: list[tuple[str, int]] = []
        in_string = False
        escaped = False
        offset = 0
        for _chunk_start, text in context.edits.iter_text():
            for char in text:
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                elif char == '"':
                    in_string = True
                elif char in _OPENERS:
                    stack.append((char, offset))
                elif char in _CLOSERS:
                    if stack and stack[-1][0] == _CLOSERS[char]:
                        stack.pop()
                    else:
                        findings.append(
                            EnvironmentFinding(
                                offset,
                                offset + 1,
                                FindingSeverity.ERROR,
                                f"unmatched {char!r}",
                                code="json.bracket-mismatch",
                            )
                        )
                offset += 1
        for char, start in stack:
            findings.append(
                EnvironmentFinding(
                    start,
                    start + 1,
                    FindingSeverity.ERROR,
                    f"unclosed {char!r}",
                    code="json.bracket-unclosed",
                )
            )
        return tuple(findings)
