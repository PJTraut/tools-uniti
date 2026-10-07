"""SFM view styling from the stylesheet, `uniti.sty` presentation rules,
and Preview's notes sections (USFM field-test feedback, 2026-10-07)."""

from __future__ import annotations

from pathlib import Path

from uniti.core.environments.sfm.semantic import character_markers, paragraph_markers
from uniti.core.environments.sfm.sty import parse_raw_stylesheet
from uniti.core.environments.sfm.sty_export import export_overrides, export_resolved
from uniti.core.environments.sfm.style_layers import (
    LayeredStyleRegistry,
    StyleLayer,
    StyleOrigin,
    build_layers,
    discover_project_stylesheets,
    is_selector,
)
from uniti.core.environments.sfm.usfm_baseline import load_uniti_builtin, load_usfm_baseline
from uniti.core.environments.sfm.views import (
    SfmPreviewView,
    SfmStandardView,
    auto_caller,
    caller_attrs,
    note_label,
    presentation_attrs,
)
from uniti.core.rich_views import SegmentRole

STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))


def _styles(tmp_path: Path, **files: str) -> LayeredStyleRegistry:
    for name, text in files.items():
        (tmp_path / name.replace("_", ".")).write_text(text, encoding="utf-8")
    book = tmp_path / "01GEN.usfm"
    book.write_text("\\id GEN\n", encoding="utf-8")
    return LayeredStyleRegistry(build_layers(load_usfm_baseline(), book))


def _spans(projection) -> dict[tuple[str | None, str], dict[str, str]]:
    return {(s.marker, projection.text[s.view_start : s.view_end]): dict(s.attrs) for s in projection.spans}


def _blocks(projection) -> list[tuple[str | None, dict[str, str]]]:
    return [(block.marker, dict(block.attrs)) for block in projection.blocks]


# --- styling comes from the stylesheet ------------------------------------------


def test_chapter_and_verse_numbers_take_their_sty_styles():
    projection = SfmPreviewView(lambda: STYLES).project("\\c 1\n\\p\n\\v 1 Text\n")
    blocks = dict(_blocks(projection))
    # usfm.sty: \\c is Bold, FontSize 18 (1.5 x the 12 pt body), SpaceBefore 8.
    assert blocks["c"]["bold"] == "yes" and blocks["c"]["font_scale"] == "1.500"
    assert blocks["c"]["space_before"] == "8"
    spans = _spans(projection)
    assert spans[("c", "1")] == {"bold": "yes", "font_scale": "1.500"}
    # usfm.sty: \\v is Superscript only — no view-invented bold or muting.
    assert spans[("v", "1")] == {"superscript": "yes"}


def test_project_stylesheet_changes_the_rendered_look(tmp_path: Path):
    styles = _styles(
        tmp_path,
        custom_sty="\\Marker v\n\\Bold\n\\Marker c\n\\FontSize 24\n\\Marker th1\n\\Italic -\n\\Bold\n",
    )
    projection = SfmPreviewView(lambda: styles).project("\\c 1\n\\p\n\\v 1 Text\n\\tr \\th1 Head\n")
    spans = _spans(projection)
    assert spans[("v", "1")] == {"superscript": "yes", "bold": "yes"}
    assert dict(_blocks(projection))["c"]["font_scale"] == "2.000"
    assert spans[("th1", "Head\n")] == {"bold": "yes"}


def test_unclosed_note_markers_style_text_up_to_the_next_marker():
    source = "\\p a\\f + \\fr 1:1 \\fq quoted \\ft plain\\f* b"
    standard = SfmStandardView(lambda: STYLES).project(source)
    spans = _spans(standard)
    assert spans[("fr", "1:1 ")] == {"bold": "yes"}  # usfm.sty: \\fr bold
    assert spans[("fq", "quoted ")] == {"italic": "yes"}  # usfm.sty: \\fq italic
    assert ("ft", "plain") not in spans  # \\ft has no formatting of its own
    # No view-invented muting or shrinking of note text.
    assert not any(attrs.get("muted") or attrs.get("font_scale") for attrs in spans.values())
    (section,) = SfmPreviewView(lambda: STYLES).project(source).notes
    section_spans = _spans(section.projection)
    assert section_spans[("fr", "1:1 ")] == {"bold": "yes"}
    assert section_spans[("fq", "quoted ")] == {"italic": "yes"}


def test_unclosed_note_stays_inline_in_preview():
    projection = SfmPreviewView(lambda: STYLES).project("\\p a\\f + \\fr 1:1 \\ft text\n\\p b")
    projection.source_map.check()
    assert projection.notes == ()
    assert projection.text == "a+ 1:1 text\nb"
    assert _spans(projection)[("fr", "1:1 ")] == {"bold": "yes"}


# --- presentation rules --------------------------------------------------------------


def test_builtin_rule_separates_prose_from_poetry():
    projection = SfmPreviewView(lambda: STYLES).project("\\p prose\n\\q1 poem\n\\q2 more\n\\p prose\n\\q poem")
    blocks = _blocks(projection)
    assert [marker for marker, _attrs in blocks] == ["p", "q1", "q2", "p", "q"]
    assert "space_before" not in blocks[0][1]
    assert blocks[1][1]["space_before"] == "12"  # p+q1
    assert "space_before" not in blocks[2][1]  # q1 then q2: no rule
    assert blocks[3][1]["space_before"] == "12"  # q2+p
    assert blocks[4][1]["space_before"] == "12"  # p+q1 also matches \\q (q = q1)
    assert blocks[1][1]["left_margin"] == "0.75"  # q1's own style still applies


def test_sibling_rules_follow_source_order_even_through_hidden_paragraphs():
    # \\rem is hidden in Preview but is still the paragraph before \\q1.
    projection = SfmPreviewView(lambda: STYLES).project("\\p prose\n\\rem note\n\\q1 poem")
    assert "space_before" not in dict(_blocks(projection))["q1"]


def test_project_uniti_sty_overrides_builtin_rules(tmp_path: Path):
    styles = _styles(
        tmp_path,
        uniti_sty="\\Marker p+q1\n\\SpaceBefore 4\n\\Marker q1+p\n\\FirstLineIndent 0\n\\Marker f::caller\n\\Bold -\n",
    )
    assert styles.layers[-1].origin is StyleOrigin.UNITI_PROJECT
    assert styles.formatting("q1", "p")["spacebefore"] == "4"
    assert styles.formatting("p", "q1")["firstlineindent"] == "0"
    assert styles.formatting("p", "q1")["spacebefore"] == "12"  # built-in rule still applies
    assert styles.formatting("q1")["leftmargin"] == "0.75"  # no previous: no rules
    # A flag the built-in rule set is turned off again with "-".
    assert caller_attrs(styles, "f") == {"superscript": "yes"}


def test_uniti_sty_is_the_highest_precedence_project_layer(tmp_path: Path):
    for name in ("usfm.sty", "custom.sty", "uniti.sty"):
        (tmp_path / name).write_text("\\Marker p\n\\FontSize 10\n", encoding="utf-8")
    book = tmp_path / "book.usfm"
    book.write_text("", encoding="utf-8")
    assert [layer.name for layer in discover_project_stylesheets(book)] == ["usfm.sty", "custom.sty", "uniti.sty"]


def test_caller_style_comes_only_from_caller_rules():
    assert caller_attrs(STYLES, "f") == {"superscript": "yes", "bold": "yes"}
    assert caller_attrs(STYLES, "x") == {"superscript": "yes", "italic": "yes"}
    no_rules = LayeredStyleRegistry(
        [StyleLayer("usfm.sty", StyleOrigin.USFM_BASE, load_usfm_baseline())]
    )
    assert caller_attrs(no_rules, "f") == {}
    projection = SfmPreviewView(lambda: no_rules).project("\\p a\\f + \\ft n\\f* b")
    assert ("caller", "a") not in _spans(projection)


def test_rule_records_never_become_marker_styles():
    assert any(is_selector(record.marker) for record in load_uniti_builtin().records)
    markers = STYLES.markers()
    assert not any(is_selector(marker) for marker in markers)
    assert STYLES.style_for("p+q1") is None
    assert not any(is_selector(m) for m in paragraph_markers(STYLES.registry) + character_markers(STYLES.registry))
    assert "q1" in paragraph_markers(STYLES.registry)


def test_malformed_selectors_are_ignored():
    sheet = parse_raw_stylesheet("\\Marker +q1\n\\Bold\n\\Marker a+b+c\n\\Bold\n\\Marker ::caller\n\\Bold\n")
    styles = LayeredStyleRegistry([StyleLayer("bad.sty", StyleOrigin.UNITI_IMPORT, sheet)])
    assert styles.rules == ()
    assert styles.markers() == ()


def test_overrides_export_leaves_out_builtin_rules_but_keeps_project_ones(tmp_path: Path):
    assert export_overrides(STYLES).count("\\Marker") == 0
    styles = _styles(tmp_path, uniti_sty="\\Marker p+q1\n\\SpaceBefore 4\n\\Marker s1+p\n\\SpaceBefore 2\n")
    by_marker = {
        record.marker: {entry.key: entry.value for entry in record.entries}
        for record in parse_raw_stylesheet(export_overrides(styles)).records
    }
    assert by_marker == {"p+q1": {"SpaceBefore": "4"}, "s1+p": {"SpaceBefore": "2"}}
    # A resolved export keeps the rules, so re-importing it renders the same.
    reimported = LayeredStyleRegistry(
        [StyleLayer("resolved.sty", StyleOrigin.UNITI_IMPORT, parse_raw_stylesheet(export_resolved(styles)))]
    )
    assert reimported.formatting("q1", "p") == styles.formatting("q1", "p")
    assert caller_attrs(reimported, "x") == caller_attrs(styles, "x")


# --- Preview notes -------------------------------------------------------------------

NOTES_SOURCE = (
    "\\c 1\n\\p\n\\v 1 In the beginning\\f + \\fr 1:1 \\ft note one\\f* God"
    "\\x - \\xo 1:1 \\xt Jn 1:1\\x* created\\f + \\ft note two\\f*.\n"
    "\\c 2\n\\p \\v 1 Again\\f + \\fr 2:1 \\ft three\\f* and\\f * \\ft literal\\f*\\fe + \\ft end\\fe*\n"
)


def test_preview_text_keeps_only_callers():
    projection = SfmPreviewView(lambda: STYLES).project(NOTES_SOURCE)
    projection.source_map.check()
    # Footnote callers run a, b … and restart at each chapter; "-" shows no
    # caller; a literal caller is kept; each note kind counts separately.
    assert projection.text == "1\n1In the beginninga God createdb.\n2\n1Againa and*a\n"


def test_preview_notes_sections_by_kind():
    projection = SfmPreviewView(lambda: STYLES).project(NOTES_SOURCE)
    sections = projection.notes
    assert [(section.key, section.label) for section in sections] == [
        ("f", "Footnotes"),
        ("fe", "Endnotes"),
        ("x", "Cross References"),
    ]
    texts = {section.key: section.projection.text for section in sections}
    assert texts == {
        "f": "a 1:1 note one\nb note two\na 2:1 three\n* literal",
        "fe": "a end",
        "x": "1:1 Jn 1:1",
    }
    for section in sections:
        section.projection.source_map.check()
        assert section.projection.source_map.source_length == len(NOTES_SOURCE)
    footnotes = sections[0].projection
    # Clicking a word in the notes frame lands in that note's source.
    position = footnotes.text.index("three") + 2
    assert footnotes.source_map.view_to_source(position) == NOTES_SOURCE.index("three") + 2
    assert footnotes.source_map.source_to_view(NOTES_SOURCE.index("note two")) == footnotes.text.index("note two")
    generated = [
        footnotes.text[s.view_start : s.view_end]
        for s in footnotes.source_map.segments
        if s.role is SegmentRole.GENERATED
    ]
    assert generated == ["a", " ", "\n", "b", " ", "\n", "a", " ", "\n", "*", " "]
    assert _spans(footnotes)[("caller", "a")] == {"superscript": "yes", "bold": "yes"}


def test_note_entries_take_the_note_style_as_their_block(tmp_path: Path):
    styles = _styles(tmp_path, custom_sty="\\Marker f\n\\FontSize 10\n\\LeftMargin .25\n")
    (section,) = SfmPreviewView(lambda: styles).project("\\p a\\f + \\ft one\\f* b\\f + \\ft two\\f*").notes
    blocks = section.projection.blocks
    assert [section.projection.text[b.view_start : b.view_end] for b in blocks] == ["a one", "b two"]
    assert all(dict(b.attrs) == {"font_scale": "0.833", "left_margin": ".25"} for b in blocks)


def test_standard_keeps_notes_inline_and_editable():
    projection = SfmStandardView(lambda: STYLES).project(NOTES_SOURCE)
    assert projection.notes == ()
    assert "\\f + \\fr 1:1 \\ft note one\\f*" in projection.text
    assert _spans(projection)[("caller", "+")] == {"superscript": "yes", "bold": "yes"}


def test_notes_inside_hidden_metadata_are_left_out():
    projection = SfmPreviewView(lambda: STYLES).project("\\rem x\\f + \\ft hidden\\f*\n\\p shown\\f + \\ft kept\\f*")
    assert projection.text == "showna"
    (section,) = projection.notes
    assert section.projection.text == "a kept"


def test_auto_callers_and_labels():
    assert [auto_caller(i) for i in (0, 1, 25, 26, 27, 51, 52)] == ["a", "b", "z", "aa", "ab", "az", "ba"]
    assert note_label(STYLES, "f") == "Footnotes"
    assert note_label(STYLES, "x") == "Cross References"
    assert note_label(STYLES, "zz") == "zz"


def test_previous_paragraph_rules_feed_presentation_attrs():
    assert presentation_attrs(STYLES, "q1", block=True, previous="p")["space_before"] == "12"
    assert "space_before" not in presentation_attrs(STYLES, "q1", block=True)
