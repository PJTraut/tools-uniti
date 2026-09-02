"""Authoritative third-party regex compilation for UNITI."""

from __future__ import annotations

import regex

from .analysis import DiagnosticSeverity, RegexDiagnostic


def compile_pattern(pattern: str, flags: int = 0) -> regex.Pattern:
    """Compile a Unicode text pattern with the pinned third-party regex engine."""
    if not isinstance(pattern, str):
        raise TypeError("UNITI regex patterns must be Unicode strings")
    return regex.compile(pattern, flags)


def normalize_compile_error(
    error: regex.error,
    expression: str,
) -> RegexDiagnostic:
    """Return a safe source diagnostic without repeating the expression."""

    raw_position = getattr(error, "pos", 0)
    position = raw_position if isinstance(raw_position, int) else 0
    position = max(0, min(len(expression), position))
    end = position if position == len(expression) else position + 1
    message = str(getattr(error, "msg", None) or "invalid regular expression")
    raw_line = getattr(error, "lineno", None)
    raw_column = getattr(error, "colno", None)
    line = raw_line if isinstance(raw_line, int) else 1
    column = raw_column if isinstance(raw_column, int) else position + 1
    return RegexDiagnostic(
        severity=DiagnosticSeverity.ERROR,
        message=f"{message} at column {column}",
        start=position,
        end=end,
        line=line,
        column=column,
    )
