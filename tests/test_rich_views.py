from __future__ import annotations

import random

import pytest

from uniti.core.environments import MarkdownEnvironment, SfmEnvironment, UsfmEnvironment
from uniti.core.environments.markdown_views import MarkdownRenderedView
from uniti.core.environments.sfm.semantic import (
    apply_character_style,
    change_paragraph_marker,
    character_markers,
    insert_verse,
    paragraph_enter_text,
    paragraph_markers,
    remove_character_style,
)
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
from uniti.core.environments.sfm.views import SfmFormattedView, SfmStandardView, presentation_attrs, sty_color
from uniti.core.rich_views import (
    EditRejected,
    ProjectionBuilder,
    SegmentRole,
    environment_view_providers,
    plan_view_edit,
)
from uniti.core.rich_views.projection import identity_projection

STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))
SOURCE = (
    "\\id GEN Genesis\n\\c 1\n\\s1 The Creation\n\\p\n"
    "\\v 1 In the \\bd beginning\\bd* God created.\n\\v 2 Earth \\zz odd\n"
)


def _apply(source: str, plan) -> str:
    result = source
    for start, end, text in sorted(plan.replacements, reverse=True):
        result = result[:start] + text + result[end:]
    return result


def _formatted():
    return SfmFormattedView(lambda: STYLES)


def _standard():
    return SfmStandardView(lambda: STYLES)


# --- source map / builder ----------------------------------------------------


def test_identity_projection_round_trips_every_offset():
    projection = identity_projection("plain", "abc\ndef")
    source_map = projection.source_map
    source_map.check()
    for offset in range(8):
        assert source_map.source_to_view(offset) == offset
        assert source_map.view_to_source(offset) == offset


def test_builder_rejects_gaps_and_mismatched_text():
    builder = ProjectionBuilder("x")
    with pytest.raises(ValueError):
        builder.text(3, "ab")
    builder.text(2, "ab")
    with pytest.raises(ValueError):
        builder.build(5)


@pytest.mark.parametrize("view_factory", [_standard, _formatted, MarkdownRenderedView])
def test_projections_satisfy_source_map_invariants(view_factory):
    source = SOURCE if view_factory is not MarkdownRenderedView else "# T\n- a **b** `c` [d](e)\n> q\n```\nx\n```\n"
    projection = view_factory().project(source)
    projection.source_map.check()
    for offset in range(len(source) + 1):
        view = projection.source_map.source_to_view(offset)
        assert 0 <= view <= len(projection.text)
    for position in range(len(projection.text) + 1):
        assert 0 <= projection.source_map.view_to_source(position) <= len(source)


def test_text_round_trips_through_the_map_in_every_view():
    for view in (_standard(), _formatted()):
        projection = view.project(SOURCE)
        for segment in projection.source_map.segments:
            if segment.role is SegmentRole.TEXT:
                assert projection.text[segment.view_start : segment.view_end] == SOURCE[segment.source_start : segment.source_end]


# --- SFM views ----------------------------------------------------------------


def test_formatted_view_hides_markers_and_formats_styles():
    projection = _formatted().project(SOURCE)
    assert projection.text == "GEN Genesis\n1\nThe Creation\n1In the beginning God created.\n2Earth \\zz odd\n"
    spans = {(span.marker, projection.text[span.view_start : span.view_end]) for span in projection.spans}
    assert ("bd", "beginning") in spans and ("v", "1") in spans and ("c", "1") in spans
    assert ("zz", "\\zz") in spans  # unknown marker stays visible, protected
    blocks = {block.marker: dict(block.attrs) for block in projection.blocks}
    assert blocks["s1"]["align"] == "center" and blocks["s1"]["bold"] == "yes"
    assert blocks["id"]["muted"] == "yes"


def test_formatted_view_breaks_inline_paragraph_markers_onto_new_lines():
    projection = _formatted().project("\\p one \\q1 two")
    assert projection.text == "one \ntwo"
    generated = [s for s in projection.source_map.segments if s.role is SegmentRole.GENERATED]
    assert len(generated) == 1


def test_standard_view_keeps_every_marker_visible():
    projection = _standard().project(SOURCE)
    assert projection.text == SOURCE
    markers = [s for s in projection.source_map.segments if s.role is SegmentRole.MARKER]
    assert [SOURCE[s.source_start : s.source_end] for s in markers][:3] == ["\\id", "\\c", "\\s1"]


def test_typing_at_the_end_of_a_bold_word_stays_inside_the_style():
    projection = _formatted().project(SOURCE)
    position = projection.text.index("beginning") + len("beginning")
    result = _apply(SOURCE, plan_view_edit(projection.source_map, position, position, "s"))
    assert "\\bd beginnings\\bd*" in result


def test_deleting_across_hidden_markers_keeps_the_markers():
    projection = _formatted().project(SOURCE)
    start = projection.text.index("the begin")
    end = start + len("the begin")
    result = _apply(SOURCE, plan_view_edit(projection.source_map, start, end, ""))
    assert "In \\bd ning\\bd* God" in result


def test_typing_inside_a_protected_marker_is_rejected():
    projection = _standard().project(SOURCE)
    inside = projection.text.index("\\s1") + 1
    with pytest.raises(EditRejected):
        plan_view_edit(projection.source_map, inside, inside, "x")
    with pytest.raises(EditRejected):
        plan_view_edit(projection.source_map, inside - 1, inside + 2, "")


def test_random_view_edits_never_corrupt_markers():
    rng = random.Random(7)
    source = SOURCE
    view = _formatted()
    for _ in range(200):
        projection = view.project(source)
        length = len(projection.text)
        a = rng.randint(0, length)
        b = min(length, a + rng.randint(0, 6))
        text = rng.choice(["", "x", "yz ", " "])
        try:
            plan = plan_view_edit(projection.source_map, a, b, text)
        except EditRejected:
            continue
        source = _apply(source, plan)
        view.project(source).source_map.check()
    for marker in ("\\id", "\\c", "\\s1", "\\p", "\\v", "\\zz"):
        assert marker in source


def test_presentation_attrs_and_color_conversion():
    assert sty_color("255") == "#ff0000"
    assert sty_color("16711680") == "#0000ff"
    assert sty_color("x") is None
    attrs = presentation_attrs(STYLES, "s1", block=True)
    assert attrs["bold"] == "yes" and attrs["align"] == "center"


# --- semantic commands --------------------------------------------------------


def test_apply_and_remove_character_style_round_trip():
    source = "\\p In the beginning"
    start = source.index("beginning")
    styled = _apply(source, apply_character_style(source, start, start + 9, "\\bd"))
    assert styled == "\\p In the \\bd beginning\\bd*"
    removed = _apply(styled, remove_character_style(styled, styled.index("gin")))
    assert removed == source
    with pytest.raises(EditRejected):
        apply_character_style(source, 3, 3, "bd")
    with pytest.raises(EditRejected):
        remove_character_style(source, 4)


def test_change_paragraph_marker_and_enter_text():
    source = "\\p one\n\\q1 two"
    changed = _apply(source, change_paragraph_marker(source, source.index("two"), "q2", STYLES.registry))
    assert changed == "\\p one\n\\q2 two"
    assert paragraph_enter_text(source, source.index("two"), STYLES.registry) == "\n\\q1 "
    assert paragraph_enter_text("plain", 2, STYLES.registry) == "\n\\p "


def test_insert_verse_adds_separating_space():
    assert _apply("\\p text", insert_verse("\\p text", 7, "2")) == "\\p text \\v 2 "
    with pytest.raises(EditRejected):
        insert_verse("x", 0, "a")


def test_marker_choice_lists_come_from_the_registry():
    assert "bd" in character_markers(STYLES.registry) and "p" not in character_markers(STYLES.registry)
    assert "p" in paragraph_markers(STYLES.registry) and "q1" in paragraph_markers(STYLES.registry)


def test_view_commands_run_in_source_offsets():
    commands = {command.command_id: command for command in _formatted().view_commands()}
    source = "\\p In the beginning"
    plan = commands["bold"].run(source, 10, 19, None)
    assert _apply(source, plan) == "\\p In the \\bd beginning\\bd*"
    assert "bd" in commands["character_style"].choices()


# --- environments --------------------------------------------------------------


def test_environments_offer_their_view_providers():
    assert [p.key for p in environment_view_providers(UsfmEnvironment())] == ["sfm.standard", "sfm.formatted"]
    assert [p.key for p in environment_view_providers(SfmEnvironment())] == ["sfm.standard", "sfm.formatted"]
    assert [p.key for p in environment_view_providers(MarkdownEnvironment())] == ["markdown.rendered"]
    assert environment_view_providers(object()) == ()


# --- Markdown -------------------------------------------------------------------


def test_markdown_rendered_view_hides_syntax_and_formats():
    source = "# Title\nSome **bold** and *it* and `code` [link](http://x).\n- one\n> quoted\n```\nraw *x*\n```\n"
    projection = MarkdownRenderedView().project(source)
    assert projection.text == "Title\nSome bold and it and code link.\n• one\nquoted\n\nraw *x*\n\n"
    spans = {(s.marker, projection.text[s.view_start : s.view_end]) for s in projection.spans}
    assert {("strong", "bold"), ("em", "it"), ("code", "code"), ("link", "link")} <= spans
    blocks = {b.marker for b in projection.blocks}
    assert {"h1", "quote", "code"} <= blocks


def test_markdown_bullet_is_protected_and_enter_continues_lists():
    view = MarkdownRenderedView()
    source = "- one\n- two"
    projection = view.project(source)
    with pytest.raises(EditRejected):
        plan_view_edit(projection.source_map, 0, 1, "")
    assert view.enter_text(source, 5) == "\n- "
    assert view.enter_text("text", 2) == "\n"


def test_markdown_commands_wrap_and_set_headings():
    commands = {command.command_id: command for command in MarkdownRenderedView().view_commands()}
    assert _apply("a word", commands["bold"].run("a word", 2, 6, None)) == "a **word**"
    assert _apply("## t", commands["heading"].run("## t", 3, 3, "1")) == "# t"
    assert _apply("# t", commands["heading"].run("# t", 2, 2, "Body")) == "t"


def test_formatted_view_renders_notes_with_caller_and_brackets():
    source = "\\p In the beginning\\f + \\fr 1.1: \\ft Or, When\\f* God."
    projection = _formatted().project(source)
    projection.source_map.check()
    assert projection.text == "In the beginning+[1.1: Or, When] God."
    spans = {(s.marker, projection.text[s.view_start : s.view_end]): dict(s.attrs) for s in projection.spans}
    assert spans[("caller", "+")]["superscript"] == "yes"
    assert spans[("f", "+[1.1: Or, When]")]["muted"] == "yes"
    generated = [s for s in projection.source_map.segments if s.role is SegmentRole.GENERATED]
    assert [projection.text[s.view_start : s.view_end] for s in generated] == ["[", "]"]
    # Typing inside the note text edits the note's source.
    position = projection.text.index("When") + 4
    result = _apply(source, plan_view_edit(projection.source_map, position, position, "ever"))
    assert "\\ft Or, Whenever\\f*" in result


def test_formatted_view_lays_out_table_rows_with_tabs():
    source = "\\tr \\th1 Tribe \\th2 Count\n\\tr \\tc1 Judah \\tcr2 74,600\n"
    projection = _formatted().project(source)
    projection.source_map.check()
    assert projection.text == "Tribe \tCount\nJudah \t74,600\n"
    assert all(block.attrs.get("table_row") == "yes" for block in projection.blocks)
    bold = [projection.text[s.view_start : s.view_end] for s in projection.spans if s.attrs.get("bold") == "yes"]
    assert "Tribe " in bold and not any("Judah" in text for text in bold)
