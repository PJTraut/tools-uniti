"""Immutable Qt-free records for regex expression intelligence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

import regex


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
class PatternStructure:
    tokens: tuple[RegexToken, ...]
    pairs: tuple[TokenPair, ...]
    switches: tuple[InlineSwitch, ...]
    claimed_group_count: int
    claimed_names: tuple[tuple[str, int], ...]


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


def _engine_expression(
    expression: str,
    *,
    literal: bool,
    case_sensitive: bool,
    whole_word: bool,
) -> tuple[str, int]:
    if not literal:
        return expression, 0
    engine_pattern = regex.escape(expression)
    if whole_word:
        engine_pattern = rf"\b(?:{engine_pattern})\b"
    flags = 0 if case_sensitive else regex.IGNORECASE
    return engine_pattern, flags


def _pattern_structure(expression: str, *, literal: bool) -> PatternStructure:
    if literal:
        tokens = (
            (RegexToken("literal", 0, len(expression), expression),)
            if expression
            else ()
        )
        return PatternStructure(tokens, (), (), 0, ())
    from .lexer import scan_pattern

    return scan_pattern(expression)


def _length_diagnostic(expression: str) -> RegexDiagnostic:
    return RegexDiagnostic(
        severity=DiagnosticSeverity.ERROR,
        message=f"expression exceeds the {MAX_EXPRESSION_CHARS:,}-character limit",
        start=MAX_EXPRESSION_CHARS,
        end=len(expression),
    )


def _pending_pattern_analysis(
    expression: str,
    generation: int,
    *,
    literal: bool = False,
    case_sensitive: bool = True,
    whole_word: bool = False,
) -> tuple[RegexAnalysis, PatternStructure | None]:
    if not isinstance(expression, str):
        raise TypeError("pattern must be a string")
    engine_pattern, flags = _engine_expression(
        expression,
        literal=literal,
        case_sensitive=case_sensitive,
        whole_word=whole_word,
    )
    if len(expression) > MAX_EXPRESSION_CHARS:
        result = RegexAnalysis.empty(
            role=ExpressionRole.PATTERN,
            expression=expression,
            engine_pattern=engine_pattern,
            generation=generation,
            state=AnalysisState.OVER_LIMIT,
        )
        return replace(
            result,
            diagnostics=(_length_diagnostic(expression),),
        ), None
    structure = _pattern_structure(expression, literal=literal)
    return (
        RegexAnalysis(
            role=ExpressionRole.PATTERN,
            expression=expression,
            engine_pattern=engine_pattern,
            generation=generation,
            pattern_generation=None,
            state=AnalysisState.PENDING,
            tokens=structure.tokens,
            pairs=structure.pairs,
            switches=structure.switches,
            groups=(),
            diagnostics=(),
            group_count=0,
            group_names=(),
            effective_flags=int(flags),
            identities_reconciled=False,
            compiled=None,
        ),
        structure,
    )


def pending_pattern_analysis(
    expression: str,
    generation: int,
    *,
    literal: bool = False,
    case_sensitive: bool = True,
    whole_word: bool = False,
) -> RegexAnalysis:
    """Return immediate structural pattern facts without invoking the engine."""
    analysis, _structure = _pending_pattern_analysis(
        expression,
        generation,
        literal=literal,
        case_sensitive=case_sensitive,
        whole_word=whole_word,
    )
    return analysis


def _resolved_tokens(
    structure: PatternStructure,
    group_names: dict[str, int],
    group_count: int,
) -> tuple[RegexToken, ...]:
    resolved: list[RegexToken] = []
    names_by_number: dict[int, str] = {
        number: name for name, number in group_names.items()
    }
    for token in structure.tokens:
        number = token.group_number
        name = token.group_name
        if token.kind == "backreference":
            reference = token.reference
            if isinstance(reference, int) and 1 <= reference <= group_count:
                number = reference
                name = names_by_number.get(reference)
            elif isinstance(reference, str) and reference in group_names:
                number = group_names[reference]
                name = reference
            else:
                number = None
                name = None
        color_key = number if number is not None and 1 <= number <= group_count else None
        resolved.append(
            replace(
                token,
                group_number=number,
                group_name=name,
                color_key=color_key,
            )
        )
    return tuple(resolved)


def _unidentified_tokens(structure: PatternStructure) -> tuple[RegexToken, ...]:
    return tuple(
        replace(token, group_number=None, group_name=None, color_key=None)
        for token in structure.tokens
    )


def analyze_pattern(
    expression: str,
    generation: int,
    *,
    literal: bool = False,
    case_sensitive: bool = True,
    whole_word: bool = False,
) -> RegexAnalysis:
    """Compile a pattern and reconcile scanner identities with engine metadata."""
    pending, structure = _pending_pattern_analysis(
        expression,
        generation,
        literal=literal,
        case_sensitive=case_sensitive,
        whole_word=whole_word,
    )
    if pending.state is AnalysisState.OVER_LIMIT:
        return pending
    assert structure is not None

    from .engine import compile_pattern, normalize_compile_error

    try:
        compiled = compile_pattern(pending.engine_pattern, pending.effective_flags)
    except regex.error as error:
        return replace(
            pending,
            state=AnalysisState.INVALID,
            diagnostics=(normalize_compile_error(error, expression),),
        )

    engine_names = dict(compiled.groupindex)
    identities_reconciled = (
        structure.claimed_group_count == compiled.groups
        and dict(structure.claimed_names) == engine_names
    )
    diagnostics: tuple[RegexDiagnostic, ...] = ()
    if identities_reconciled:
        tokens = _resolved_tokens(structure, engine_names, compiled.groups)
        groups = tuple(
            GroupIdentity(
                number=number,
                names=tuple(
                    name for name, group_number in engine_names.items()
                    if group_number == number
                ),
                color_key=number,
            )
            for number in range(1, compiled.groups + 1)
        )
    else:
        tokens = _unidentified_tokens(structure)
        groups = ()
        diagnostics = (
            RegexDiagnostic(
                severity=DiagnosticSeverity.WARNING,
                message="advanced group coloring is unavailable for this expression",
                start=0,
                end=len(expression),
            ),
        )
    return RegexAnalysis(
        role=ExpressionRole.PATTERN,
        expression=expression,
        engine_pattern=pending.engine_pattern,
        generation=generation,
        pattern_generation=None,
        state=AnalysisState.VALID,
        tokens=tokens,
        pairs=structure.pairs,
        switches=structure.switches,
        groups=groups,
        diagnostics=diagnostics,
        group_count=compiled.groups,
        group_names=tuple(engine_names.items()),
        effective_flags=int(compiled.flags),
        identities_reconciled=identities_reconciled,
        compiled=compiled,
    )


__all__ = [
    "AnalysisState",
    "DiagnosticSeverity",
    "ExpressionRole",
    "GroupIdentity",
    "InlineSwitch",
    "MAX_EXPRESSION_CHARS",
    "PatternStructure",
    "RegexAnalysis",
    "RegexDiagnostic",
    "RegexToken",
    "TokenPair",
    "analyze_pattern",
    "pending_pattern_analysis",
]
