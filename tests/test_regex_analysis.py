from dataclasses import FrozenInstanceError

import pytest
import regex

from uniti.regex.analysis import (
    AnalysisState,
    DiagnosticSeverity,
    ExpressionRole,
    RegexAnalysis,
)
from uniti.regex.engine import compile_pattern, normalize_compile_error


def test_compile_error_is_safe_structured_and_located():
    expression = "(abc"
    try:
        compile_pattern(expression)
    except regex.error as error:
        diagnostic = normalize_compile_error(error, expression)
    else:
        raise AssertionError("invalid pattern compiled")

    assert diagnostic.severity is DiagnosticSeverity.ERROR
    assert diagnostic.start == len(expression)
    assert diagnostic.end == len(expression)
    assert diagnostic.line == 1
    assert diagnostic.column == len(expression) + 1
    assert diagnostic.message == "missing ) at column 5"
    assert expression not in diagnostic.message


def test_analysis_record_carries_exact_generation_and_expression_immutably():
    analysis = RegexAnalysis.empty(
        role=ExpressionRole.PATTERN,
        expression="abc",
        engine_pattern="abc",
        generation=7,
        state=AnalysisState.PENDING,
    )

    assert analysis.generation == 7
    assert analysis.expression == "abc"
    assert analysis.state is AnalysisState.PENDING
    assert analysis.tokens == ()
    with pytest.raises(FrozenInstanceError):
        analysis.generation = 8
