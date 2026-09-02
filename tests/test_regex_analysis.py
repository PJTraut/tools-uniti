from dataclasses import FrozenInstanceError, replace

import pytest
import regex

import uniti.regex.lexer as regex_lexer
from uniti.regex.analysis import (
    AnalysisState,
    DiagnosticSeverity,
    ExpressionRole,
    MAX_EXPRESSION_CHARS,
    RegexAnalysis,
    analyze_pattern,
    analyze_replacement,
    pending_pattern_analysis,
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


def test_regex_package_exports_pattern_analysis_surface():
    from uniti.regex import (
        PatternStructure,
        analyze_pattern,
        analyze_replacement,
        pending_pattern_analysis,
    )

    assert PatternStructure is not None
    assert callable(analyze_pattern)
    assert callable(analyze_replacement)
    assert callable(pending_pattern_analysis)


@pytest.mark.parametrize(
    ("pattern", "groups", "names"),
    (
        (r"(a)(?:b)(c)", 2, ()),
        (r"(?P<word>\p{L}+)-(?P=word)", 1, (("word", 1),)),
        (r"(?<word>a)(?P<word>b)", 1, (("word", 1),)),
        (r"(?|(a)|(b))(c)", 2, ()),
        (r"(?P<digit>\d)+", 1, (("digit", 1),)),
        (r"(a)?(?(1)b|c)", 1, ()),
        (r"(?im-s:^a.+$)", 0, ()),
        (r"(?V1)(?>a++|b*?)(?<=a)(?!z)", 0, ()),
    ),
)
def test_pattern_analysis_matches_pinned_engine_metadata(pattern, groups, names):
    analysis = analyze_pattern(pattern, generation=3)

    assert analysis.state is AnalysisState.VALID
    assert analysis.group_count == groups
    assert analysis.group_names == names
    assert analysis.identities_reconciled


def test_group_open_close_name_and_references_share_engine_number_and_color():
    analysis = analyze_pattern(
        r"(?P<word>a)(?P<word>b)(?P=word)\g<word>", generation=4
    )

    colored = [token for token in analysis.tokens if token.color_key == 1]
    assert {token.kind for token in colored} >= {
        "group_open",
        "group_close",
        "group_name",
        "backreference",
    }
    assert all(token.group_number == 1 for token in colored)
    pair_ids = [token.pair_id for token in colored if token.kind == "group_open"]
    assert len(pair_ids) == 2
    assert len(set(pair_ids)) == 2


def test_pending_pattern_analysis_preserves_structure_without_compiling():
    analysis = pending_pattern_analysis(r"(a)(?:b)", generation=5)

    assert analysis.state is AnalysisState.PENDING
    assert analysis.compiled is None
    assert analysis.generation == 5
    assert analysis.pairs
    assert not analysis.identities_reconciled


def test_literal_pattern_analysis_keeps_engine_syntax_out_of_user_tokens():
    expression = r"(a)\d"
    analysis = analyze_pattern(
        expression,
        generation=6,
        literal=True,
        case_sensitive=False,
        whole_word=True,
    )

    assert analysis.state is AnalysisState.VALID
    assert analysis.expression == expression
    assert analysis.engine_pattern != expression
    assert analysis.group_count == 0
    assert all(token.kind == "literal" for token in analysis.tokens)
    assert "(?:" not in "".join(token.text for token in analysis.tokens)


def test_pattern_analysis_enforces_length_limit_before_compilation():
    at_limit = "(?x)#" + "x" * (MAX_EXPRESSION_CHARS - 5)
    assert analyze_pattern(at_limit, 1).state is AnalysisState.VALID
    over_limit = analyze_pattern("x" * (MAX_EXPRESSION_CHARS + 1), 2)

    assert over_limit.state is AnalysisState.OVER_LIMIT
    assert over_limit.compiled is None
    assert over_limit.diagnostics[0].severity is DiagnosticSeverity.ERROR


def test_invalid_pattern_analysis_retains_structural_tokens_and_diagnostic():
    analysis = analyze_pattern("(abc", generation=7)

    assert analysis.state is AnalysisState.INVALID
    assert analysis.compiled is None
    assert analysis.tokens
    assert any(not token.valid for token in analysis.tokens)
    assert analysis.diagnostics[0].severity is DiagnosticSeverity.ERROR


def test_reconciliation_failure_suppresses_all_uncertain_group_identity(monkeypatch):
    real_scan = regex_lexer.scan_pattern

    def disagreeing_scan(expression):
        structure = real_scan(expression)
        return replace(
            structure,
            claimed_group_count=structure.claimed_group_count + 1,
        )

    monkeypatch.setattr(regex_lexer, "scan_pattern", disagreeing_scan)
    analysis = analyze_pattern(r"(?P<word>a)\g<word>", generation=8)

    assert analysis.state is AnalysisState.VALID
    assert analysis.compiled is not None
    assert not analysis.identities_reconciled
    assert analysis.groups == ()
    assert all(token.group_number is None for token in analysis.tokens)
    assert all(token.group_name is None for token in analysis.tokens)
    assert all(token.color_key is None for token in analysis.tokens)
    assert analysis.diagnostics[0].severity is DiagnosticSeverity.WARNING


def test_replacement_references_share_pattern_group_identity():
    pattern = analyze_pattern(r"(?P<word>\w+)-(\d+)", generation=11)
    replacement = analyze_replacement(
        r"\g<word>:\2:\g<0>", pattern, generation=12
    )

    assert replacement.state is AnalysisState.VALID
    references = [
        token for token in replacement.tokens if token.kind == "backreference"
    ]
    assert [
        (token.reference, token.group_number, token.color_key)
        for token in references
    ] == [
        ("word", 1, 1),
        (2, 2, 2),
        (0, 0, None),
    ]
    assert replacement.pattern_generation == 11


def test_invalid_replacement_reference_blocks_replacement_only():
    pattern = analyze_pattern(r"(a)", generation=20)
    replacement = analyze_replacement(
        r"\2-\g<missing>", pattern, generation=21
    )

    assert replacement.state is AnalysisState.INVALID
    assert len(replacement.diagnostics) == 2
    assert all(
        diagnostic.severity is DiagnosticSeverity.ERROR
        for diagnostic in replacement.diagnostics
    )


def test_over_limit_replacement_is_refused_without_losing_editable_text():
    pattern = analyze_pattern(r"(a)", generation=30)
    replacement = analyze_replacement(
        "x" * (MAX_EXPRESSION_CHARS + 1), pattern, generation=31
    )

    assert replacement.state is AnalysisState.OVER_LIMIT
    assert replacement.expression.endswith("x")
    assert replacement.diagnostics[0].start == MAX_EXPRESSION_CHARS


def test_replacement_waits_for_pending_pattern_without_semantic_colors():
    pattern = pending_pattern_analysis(r"(a)", generation=40)
    replacement = analyze_replacement(r"\1", pattern, generation=41)

    assert replacement.state is AnalysisState.PENDING
    assert replacement.pattern_generation == 40
    assert all(token.color_key is None for token in replacement.tokens)
