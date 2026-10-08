"""USFM 3 marker forms: nested `\\+name`, milestones, column ranges,
attributes (field test round 2, R2)."""

from __future__ import annotations

from uniti.core.environments.sfm.inspection import marker_at
from uniti.core.environments.sfm.markers import is_closing, is_milestone, is_milestone_close, is_nested, marker_name
from uniti.core.environments.sfm.parser import parse_sfm
from uniti.core.environments.sfm.placement import placement_findings
from uniti.core.environments.sfm.semantic import apply_character_style
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
from uniti.core.environments.sfm.tokenizer import reconstruct, tokenize_sfm
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
from uniti.core.environments.sfm.validation import unmatched_end_marker_findings
from uniti.core.environments.sfm.views import layout_projection

_FEEDBACK = "\\id GEN\n\\c 1\n\\p\n\\v 1 The \\nd xx \\+it yy\\+it*\\nd* end.\n"


def _styles() -> LayeredStyleRegistry:
    return LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))


def _markers(source: str) -> list[str]:
    return [token.text for token in tokenize_sfm(source) if token.kind.name == "MARKER"]


def _span_attrs(projection, text: str) -> dict[str, str]:
    """Every attribute the spans covering `text` give it, outer first."""

    start = projection.text.index(text)
    merged: dict[str, str] = {}
    for span in projection.spans:
        if span.view_start <= start and start + len(text) <= span.view_end and "marker_token" not in span.attrs:
            merged.update(span.attrs)
    return merged


def test_marker_names():
    assert marker_name("\\+it*") == "it"
    assert marker_name("\\qt-s") == "qt-s"
    assert marker_name("\\th1-2") == "th1-2"
    assert marker_name("\\*") == ""
    assert is_nested("\\+xt") and not is_nested("\\xt")
    assert is_closing("\\+it*") and not is_closing("\\*") and not is_closing("\\it")
    assert is_milestone("\\qt-s") and is_milestone("\\ts1-e") and not is_milestone("\\th1-2")
    assert is_milestone_close("\\*")


def test_the_tokenizer_reads_every_marker_form_losslessly():
    samples = {
        "\\nd xx \\+it yy\\+it*\\nd*": ["\\nd", "\\+it", "\\+it*", "\\nd*"],
        '\\qt-s |sid="q1" who="Pilate"\\*Are you\\qt-e |eid="q1"\\*': ["\\qt-s", "\\*", "\\qt-e", "\\*"],
        "\\tr \\th1-2 Head \\tc3 x": ["\\tr", "\\th1-2", "\\tc3"],
        '\\w gracious|lemma="grace"\\w*-x': ["\\w", "\\w*"],
        "\\v 1-2 text": ["\\v"],
        "\\nd-x \\+ \\\\ end": ["\\nd"],
    }
    for source, markers in samples.items():
        assert reconstruct(tokenize_sfm(source)) == source
        assert _markers(source) == markers


def test_nested_markers_pair_inside_their_parent():
    tree = parse_sfm(tokenize_sfm("\\nd xx \\+it yy\\+it*\\nd*"))
    (outer,) = tree.children
    assert outer.marker == "\\nd"
    assert [child.marker for child in outer.children if child.marker] == ["\\+it"]


def test_preview_styles_a_nested_marker_inside_its_parent():
    """The feedback example: "yy" is small caps (built-in \\nd rule) and italic."""

    styles = _styles()
    preview = layout_projection(_FEEDBACK, styles, "sfm.preview", show_markers=False)
    preview.source_map.check()

    assert preview.text == "1\n1The xx yy end.\n"
    assert _span_attrs(preview, "yy") == {"smallcaps": "yes", "italic": "yes"}
    assert _span_attrs(preview, "xx") == {"smallcaps": "yes"}  # no underline: built-in uniti.sty


def test_standard_shows_nested_markers_as_their_own_tags():
    standard = layout_projection(_FEEDBACK, _styles(), "sfm.standard", show_markers=True)
    standard.source_map.check()
    assert "\\nd xx \\+it yy\\+it*\\nd*" in standard.text
    tags = {standard.text[span.view_start : span.view_end] for span in standard.spans if span.attrs.get("marker_token")}
    assert {"\\+it", "\\+it*"} <= tags
    assert _span_attrs(standard, "yy")["italic"] == "yes"


def test_nested_cross_reference_text_inside_a_footnote():
    source = "\\id GEN\n\\c 1\n\\p\n\\v 1 Text.\\f + \\fr 1:1 \\ft see \\+xt Jn 1:1\\+xt* and more\\f*\n"
    preview = layout_projection(source, _styles(), "sfm.preview", show_markers=False)
    (footnotes,) = preview.notes
    footnotes.projection.source_map.check()
    assert footnotes.projection.text == "a 1:1 see Jn 1:1 and more"
    # The nested \+xt doesn't end the \ft around it.
    ft_spans = [span for span in footnotes.projection.spans if span.marker == "ft"]
    assert all(footnotes.projection.text[span.view_start : span.view_end] != "see " for span in ft_spans)


def test_milestones_and_attributes_are_not_text_in_preview():
    source = (
        "\\id GEN\n\\c 1\n\\p\n\\v 1 He said, \\qt-s |sid=\"q1\" who=\"Pilate\"\\*Are you a "
        "\\w king|lemma=\"king\"\\w*?\\qt-e |eid=\"q1\"\\*\n"
    )
    styles = _styles()
    preview = layout_projection(source, styles, "sfm.preview", show_markers=False)
    preview.source_map.check()
    assert preview.text == "1\n1He said, Are you a king?\n"

    standard = layout_projection(source, styles, "sfm.standard", show_markers=True)
    standard.source_map.check()
    tags = {standard.text[span.view_start : span.view_end] for span in standard.spans if span.attrs.get("marker_token")}
    assert '\\qt-s |sid="q1" who="Pilate"\\*' in tags
    assert 'king|lemma="king"' in standard.text


def test_column_range_cells_are_one_marker():
    source = "\\id GEN\n\\c 1\n\\tr \\th1-2 Heading \\tc3 x\n"
    preview = layout_projection(source, _styles(), "sfm.preview", show_markers=False)
    assert preview.text == "1\nHeading \tx\n"  # one cell, not "\\th1" plus text "-2"


def test_applying_a_style_inside_another_nests_it():
    source = "\\p \\nd Lord God\\nd* said"
    start = source.index("God")
    plan = apply_character_style(source, start, start + 3, "it")
    assert [text for _s, _e, text in plan.replacements] == ["\\+it ", "\\+it*"]
    # Outside any character style, and inside a note's body, it isn't nested.
    plain = apply_character_style(source, source.index("said"), len(source), "it")
    assert [text for _s, _e, text in plain.replacements] == ["\\it ", "\\it*"]
    note = "\\p x\\f + \\ft note text\\f*"
    in_note = apply_character_style(note, note.index("text"), note.index("text") + 4, "bd")
    assert [text for _s, _e, text in in_note.replacements] == ["\\bd ", "\\bd*"]


def test_checks_understand_nesting_and_milestones():
    registry = _styles().registry
    source = "\\id GEN\n\\c 1\n\\p\n\\v 1 \\nd xx \\+it yy\\+it*\\nd* \\qt-s |sid=\"a\"\\*q\\qt-e\\*\n"
    assert unmatched_end_marker_findings(source) == ()
    assert [finding.message for finding in placement_findings(source, registry)] == []
    assert marker_at(source, source.index("yy")) == "it"
