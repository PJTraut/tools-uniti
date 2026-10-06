from __future__ import annotations

from uniti.core.environments.sfm.tokenizer import reconstruct, tokenize_sfm
from uniti.core.environments.sfm.tokens import SfmTokenKind


def test_tokenizes_a_simple_marker_and_text():
    tokens = tokenize_sfm(r"\v 1 In the beginning")

    assert tokens[0].kind is SfmTokenKind.MARKER
    assert tokens[0].text == r"\v"
    assert tokens[1].kind is SfmTokenKind.TEXT
    assert tokens[1].text == " 1 In the beginning"


def test_recognizes_end_markers_with_trailing_star():
    tokens = tokenize_sfm(r"\bd bold\bd* plain")

    markers = [t for t in tokens if t.kind is SfmTokenKind.MARKER]
    assert [m.text for m in markers] == [r"\bd", r"\bd*"]


def test_recognizes_numbered_markers():
    tokens = tokenize_sfm(r"\q1 text")

    assert tokens[0].text == r"\q1"


def test_is_lossless_for_arbitrary_source():
    source = "\\id GEN\n\\c 1\n\\v 1  In the \\bd beginning\\bd*  God created.\n"

    tokens = tokenize_sfm(source)

    assert reconstruct(tokens) == source


def test_tokens_are_contiguous_and_gap_free():
    source = r"\p \v 1 text \bd bold\bd* more \unknown123"

    tokens = tokenize_sfm(source)

    assert tokens[0].start == 0
    for previous, current in zip(tokens, tokens[1:]):
        assert previous.end == current.start
    assert tokens[-1].end == len(source)


def test_lone_backslash_does_not_infinite_loop():
    tokens = tokenize_sfm("a \\ b \\ c")

    assert reconstruct(tokens) == "a \\ b \\ c"


def test_empty_text_produces_no_tokens():
    assert tokenize_sfm("") == ()
