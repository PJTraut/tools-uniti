"""Immutable Qt-free records for regex expression intelligence."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


MAX_EXPRESSION_CHARS = 65_536


class ExpressionRole(StrEnum):
    PATTERN = "pattern"
    REPLACEMENT = "replacement"


class AnalysisState(StrEnum):
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    OVER_LIMIT = "over_limit"


class DiagnosticSeverity(StrEnum):
    WARNING = "warning"
    ERROR = "error"


@dataclass(frozen=True, slots=True)
class RegexDiagnostic:
    severity: DiagnosticSeverity
    message: str
    start: int
    end: int
    line: int | None = None
    column: int | None = None


@dataclass(frozen=True, slots=True)
class RegexToken:
    kind: str
    start: int
    end: int
    text: str
    valid: bool = True
    group_number: int | None = None
    group_name: str | None = None
    pair_id: int | None = None
    color_key: int | None = None
    reference: int | str | None = None


@dataclass(frozen=True, slots=True)
class TokenPair:
    pair_id: int
    open_token: int
    close_token: int


@dataclass(frozen=True, slots=True)
class InlineSwitch:
    start: int
    end: int
    added: str
    removed: str
    scoped: bool


@dataclass(frozen=True, slots=True)
class GroupIdentity:
    number: int
    names: tuple[str, ...]
    color_key: int


@dataclass(frozen=True, slots=True)
class RegexAnalysis:
    role: ExpressionRole
    expression: str
    engine_pattern: str
    generation: int
    pattern_generation: int | None
    state: AnalysisState
    tokens: tuple[RegexToken, ...]
    pairs: tuple[TokenPair, ...]
    switches: tuple[InlineSwitch, ...]
    groups: tuple[GroupIdentity, ...]
    diagnostics: tuple[RegexDiagnostic, ...]
    group_count: int
    group_names: tuple[tuple[str, int], ...]
    effective_flags: int
    identities_reconciled: bool
    compiled: object | None = None

    @classmethod
    def empty(
        cls,
        *,
        role: ExpressionRole,
        expression: str,
        engine_pattern: str,
        generation: int,
        state: AnalysisState,
        pattern_generation: int | None = None,
    ) -> "RegexAnalysis":
        return cls(
            role=role,
            expression=expression,
            engine_pattern=engine_pattern,
            generation=generation,
            pattern_generation=pattern_generation,
            state=state,
            tokens=(),
            pairs=(),
            switches=(),
            groups=(),
            diagnostics=(),
            group_count=0,
            group_names=(),
            effective_flags=0,
            identities_reconciled=False,
            compiled=None,
        )


__all__ = [
    "AnalysisState",
    "DiagnosticSeverity",
    "ExpressionRole",
    "GroupIdentity",
    "InlineSwitch",
    "MAX_EXPRESSION_CHARS",
    "RegexAnalysis",
    "RegexDiagnostic",
    "RegexToken",
    "TokenPair",
]
