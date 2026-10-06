from __future__ import annotations

from uniti.core.environments.sfm.nodes import SfmNodeKind
from uniti.core.environments.sfm.parser import parse_sfm
from uniti.core.environments.sfm.tokenizer import tokenize_sfm


def _kinds(node):
    return [child.kind for child in node.children]


def test_empty_token_stream_yields_empty_document():
    tree = parse_sfm(())

    assert tree.kind is SfmNodeKind.DOCUMENT
    assert tree.children == ()


def test_unclosed_paragraph_markers_stay_flat_not_nested():
    tree = parse_sfm(tokenize_sfm(r"\p \v 1 text \p more"))

    assert _kinds(tree) == [
        SfmNodeKind.MARKER,  # \p
        SfmNodeKind.TEXT,  # " "
        SfmNodeKind.MARKER,  # \v
        SfmNodeKind.TEXT,  # " 1 text "
        SfmNodeKind.MARKER,  # \p
        SfmNodeKind.TEXT,  # " more"
    ]


def test_matched_character_style_pair_nests():
    tree = parse_sfm(tokenize_sfm(r"before \bd bold\bd* after"))

    assert _kinds(tree) == [SfmNodeKind.TEXT, SfmNodeKind.CHARACTER, SfmNodeKind.TEXT]
    character = tree.children[1]
    assert character.marker == r"\bd"
    assert _kinds(character) == [SfmNodeKind.TEXT]
    assert character.children[0].start == tree.children[1].start + len(r"\bd")


def test_character_pair_spans_exactly_open_to_close():
    source = r"\bd bold\bd*"
    tree = parse_sfm(tokenize_sfm(source))

    character = tree.children[0]
    assert character.kind is SfmNodeKind.CHARACTER
    assert character.start == 0
    assert character.end == len(source)


def test_nested_character_styles_nest_correctly():
    tree = parse_sfm(tokenize_sfm(r"\bd bold \it italic\it* still bold\bd*"))

    outer = tree.children[0]
    assert outer.kind is SfmNodeKind.CHARACTER
    assert outer.marker == r"\bd"
    kinds = _kinds(outer)
    assert SfmNodeKind.CHARACTER in kinds
    inner = next(c for c in outer.children if c.kind is SfmNodeKind.CHARACTER)
    assert inner.marker == r"\it"


def test_unmatched_end_marker_becomes_a_standalone_marker_leaf():
    tree = parse_sfm(tokenize_sfm(r"text \bd* trailing"))

    assert _kinds(tree) == [SfmNodeKind.TEXT, SfmNodeKind.MARKER, SfmNodeKind.TEXT]
    assert tree.children[1].marker == r"\bd*"


def test_end_marker_only_closes_the_matching_open_and_flattens_others_between():
    # \it is never closed; \bd* should still find and close the outer \bd,
    # flattening the unclosed \it in between rather than losing its text.
    tree = parse_sfm(tokenize_sfm(r"\bd bold \it italic text\bd* after"))

    outer = tree.children[0]
    assert outer.kind is SfmNodeKind.CHARACTER
    assert outer.marker == r"\bd"
    assert _kinds(outer) == [
        SfmNodeKind.TEXT,  # "bold "
        SfmNodeKind.MARKER,  # \it, flattened (never closed)
        SfmNodeKind.TEXT,  # " italic text"
    ]
