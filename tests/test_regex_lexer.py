import pytest

from uniti.regex.lexer import scan_pattern, tokenize_pattern, tokenize_replacement


def test_pattern_lexer_identifies_regex_structure_and_capture_numbers():
    pattern = r"^(?P<word>\p{L}+)\s+(?:x)(?<=x)(\d{2,3})\1$"
    tokens = tokenize_pattern(pattern)
    kinds = [token.kind for token in tokens]
    assert "anchor" in kinds
    assert "unicode_property" in kinds
    assert "char_class" not in kinds
    assert "quantifier" in kinds
    assert "backreference" in kinds

    groups = [token for token in tokens if token.kind == "group_open"]
    assert [(token.group_number, token.group_name) for token in groups] == [
        (1, "word"),
        (None, None),
        (None, None),
        (2, None),
    ]


def test_pattern_lexer_handles_classes_escapes_alternation_and_flags():
    tokens = tokenize_pattern(r"(?im)[A-Z_]+|\bfoo\?$")
    assert any(token.kind == "flag" and token.text == "(?im)" for token in tokens)
    assert any(token.kind == "char_class" and token.text == "[A-Z_]" for token in tokens)
    assert any(token.kind == "alternation" for token in tokens)
    assert any(token.kind == "escape" and token.text == r"\b" for token in tokens)
    assert any(token.kind == "escape" and token.text == r"\?" for token in tokens)


def test_pattern_lexer_marks_unclosed_class_and_group_invalid():
    tokens = tokenize_pattern("(abc[def")
    assert any(token.kind == "invalid" and token.text == "[def" for token in tokens)
    assert any(token.kind == "group_open" and not token.valid for token in tokens)


def test_pattern_lexer_marks_unmatched_group_close_invalid():
    tokens = tokenize_pattern("abc)")
    assert tokens[-1].kind == "invalid"
    assert tokens[-1].text == ")"


def test_replacement_lexer_validates_numeric_and_named_references():
    tokens = tokenize_replacement(
        r"\g<word>-\2-\g<missing>-\\",
        group_count=2,
        group_names={"word": 1},
    )
    references = [token for token in tokens if token.kind == "backreference"]
    assert [(token.reference, token.valid) for token in references] == [
        ("word", True),
        (2, True),
        ("missing", False),
    ]
    assert any(token.kind == "escape" and token.text == r"\\" for token in tokens)


def test_pattern_lexer_matches_regex_engine_branch_reset_numbering():
    tokens = tokenize_pattern(r"(?|(a)|(b))(c)")
    groups = [token for token in tokens if token.kind == "group_open"]
    assert [token.group_number for token in groups] == [None, 1, 1, 2]


def test_pattern_lexer_reuses_engine_group_number_for_duplicate_named_groups():
    tokens = tokenize_pattern(r"(?P<item>a)(?P<item>b)(c)")
    groups = [token for token in tokens if token.kind == "group_open"]
    assert [(token.group_number, token.group_name) for token in groups] == [
        (1, "item"),
        (1, "item"),
        (2, None),
    ]


def test_pattern_scanner_pairs_delimiters_and_emits_group_name_spans():
    structure = scan_pattern(r"(?P<word>a)(?:b)(?<=c)")

    assert len(structure.pairs) == 3
    for pair in structure.pairs:
        opening = structure.tokens[pair.open_token]
        closing = structure.tokens[pair.close_token]
        assert opening.kind == "group_open"
        assert closing.kind == "group_close"
        assert opening.pair_id == closing.pair_id == pair.pair_id
    assert any(
        token.kind == "group_name" and token.text == "word"
        for token in structure.tokens
    )


def test_pattern_scanner_records_global_and_scoped_inline_switches():
    structure = scan_pattern(r"(?im)(?x-s:a)")

    assert [(switch.added, switch.removed, switch.scoped) for switch in structure.switches] == [
        ("im", "", False),
        ("x", "s", True),
    ]


def test_pattern_scanner_recognizes_references_and_advanced_group_headers():
    structure = scan_pattern(
        r"(a)(?:b)(?>c)(?=d)(?!e)(?<=f)(?<!g)(?(1)h|i)\1\g<1>(?P=word)"
    )

    group_opens = [token for token in structure.tokens if token.kind == "group_open"]
    references = [token for token in structure.tokens if token.kind == "backreference"]
    assert len(group_opens) == 8
    assert [token.reference for token in references] == [1, 1, "word"]
    assert all(token.kind != "group_open" for token in references)


def test_pattern_scanner_recognizes_lazy_and_possessive_quantifiers():
    tokens = scan_pattern(r"a*?b++c{2,3}?d{4}+").tokens

    assert [token.text for token in tokens if token.kind == "quantifier"] == [
        "*?",
        "++",
        "{2,3}?",
        "{4}+",
    ]


@pytest.mark.parametrize(
    "pattern",
    ("abc\\", "[abc", "(abc", "abc)", r"\p{Letter"),
)
def test_pattern_scanner_retains_malformed_spans(pattern):
    structure = scan_pattern(pattern)

    assert any(not token.valid for token in structure.tokens)
