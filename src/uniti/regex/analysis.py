"""Immutable Qt-free records for regex expression intelligence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum

import regex


MAX_EXPRESSION_CHARS = 65_536

# Scripts conventionally written without spaces between words (BF-034).
# There is no universal, reliable definition of "whole word" for these
# without a segmentation dictionary this engine does not have, so — rather
# than silently returning zero matches, as plain `\b` does whenever a term
# in one of these scripts is embedded directly in more of the same script
# with no delimiter — a literal "Whole word" search skips the boundary
# requirement on whichever edge of the search term falls in one of these
# scripts, while leaving it unchanged (plain `\b`) for every other script.
_NO_SPACE_SCRIPTS = (
    "Han",
    "Hiragana",
    "Katakana",
    "Hangul",
    "Thai",
    "Lao",
    "Khmer",
    "Myanmar",
)
_NO_SPACE_SCRIPT_PATTERN = regex.compile(
    "|".join(rf"\p{{Script={script}}}" for script in _NO_SPACE_SCRIPTS)
)


def _boundary_for_edge(char: str | None) -> str:
    if char is not None and _NO_SPACE_SCRIPT_PATTERN.match(char):
        return ""
    return r"\b"


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
        leading = _boundary_for_edge(expression[0]) if expression else r"\b"
        trailing = _boundary_for_edge(expression[-1]) if expression else r"\b"
        engine_pattern = f"{leading}(?:{engine_pattern}){trailing}"
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


def analyze_replacement(
    expression: str,
    pattern: RegexAnalysis,
    generation: int,
    *,
    literal: bool = False,
) -> RegexAnalysis:
    """Validate replacement references against one exact pattern generation."""
    if not isinstance(expression, str):
        raise TypeError("replacement must be a string")
    if len(expression) > MAX_EXPRESSION_CHARS:
        result = RegexAnalysis.empty(
            role=ExpressionRole.REPLACEMENT,
            expression=expression,
            engine_pattern=expression,
            generation=generation,
            pattern_generation=pattern.generation,
            state=AnalysisState.OVER_LIMIT,
        )
        return replace(result, diagnostics=(_length_diagnostic(expression),))

    pattern_valid = pattern.state is AnalysisState.VALID
    group_names = dict(pattern.group_names) if pattern_valid else {}
    group_count = pattern.group_count if pattern_valid else 0
    if literal:
        scanned = (
            (RegexToken("literal", 0, len(expression), expression),)
            if expression
            else ()
        )
    else:
        from .lexer import tokenize_replacement

        scanned = tokenize_replacement(
            expression,
            group_count=group_count,
            group_names=group_names,
        )
    if not pattern_valid:
        state = (
            AnalysisState.PENDING
            if pattern.state is AnalysisState.PENDING
            else AnalysisState.INVALID
        )
        tokens = tuple(
            replace(token, group_number=None, group_name=None, color_key=None)
            for token in scanned
        )
        return RegexAnalysis(
            role=ExpressionRole.REPLACEMENT,
            expression=expression,
            engine_pattern=expression,
            generation=generation,
            pattern_generation=pattern.generation,
            state=state,
            tokens=tokens,
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

    diagnostics: list[RegexDiagnostic] = []
    tokens: list[RegexToken] = []
    for token in scanned:
        if not token.valid:
            if token.kind == "backreference":
                message = f"Replacement refers to unknown group {token.reference}"
            else:
                message = "Invalid replacement syntax"
            diagnostics.append(
                RegexDiagnostic(
                    DiagnosticSeverity.ERROR,
                    message,
                    token.start,
                    token.end,
                )
            )
        if token.valid and pattern.identities_reconciled:
            color_key = (
                token.group_number
                if token.group_number is not None and token.group_number > 0
                else None
            )
            tokens.append(replace(token, color_key=color_key))
        else:
            tokens.append(
                replace(token, group_number=None, group_name=None, color_key=None)
                if not pattern.identities_reconciled
                else token
            )
    return RegexAnalysis(
        role=ExpressionRole.REPLACEMENT,
        expression=expression,
        engine_pattern=expression,
        generation=generation,
        pattern_generation=pattern.generation,
        state=AnalysisState.INVALID if diagnostics else AnalysisState.VALID,
        tokens=tuple(tokens),
        pairs=(),
        switches=(),
        groups=pattern.groups,
        diagnostics=tuple(diagnostics),
        group_count=pattern.group_count,
        group_names=pattern.group_names,
        effective_flags=pattern.effective_flags,
        identities_reconciled=pattern.identities_reconciled,
        compiled=None,
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
    "analyze_replacement",
    "pending_pattern_analysis",
]
