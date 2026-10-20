"""Block direction in the SFM projections (text direction plan W2, W4, W5, W6)."""

from __future__ import annotations

from uniti.core.environments.sfm.sty import parse_raw_stylesheet
from uniti.core.rich_views.source_map import ISOLATE, LRI, PDI, RLI, SegmentRole
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, StyleLayer, StyleOrigin, build_layers
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
from uniti.core.environments.sfm.views import SfmPreviewView, SfmStandardView, layout_projection

STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))
BOOK = (
    "\\id JHN\n\\c 1\n\\p\n\\v 1 Paul שלום\\f + \\ft A note\\f* עולם\n\\q1 \\v 2 Latin line\n"
    "\\s1 1\n\\p\nplain text\n"
)


def _directions(projection):
    return [block.attrs.get("direction") for block in projection.blocks]


def test_every_block_carries_the_direction_in_both_views():
    for show_markers in (True, False):
        projection = layout_projection(BOOK, STYLES, "k", show_markers=show_markers, direction="rtl")
        assert projection.blocks
        assert set(_directions(projection)) == {"rtl"}
        assert {block.marker for block in projection.blocks} >= {"c", "p", "q1"}


def test_the_notes_frame_blocks_carry_it_too():
    projection = layout_projection(BOOK, STYLES, "k", show_markers=False, direction="rtl")

    assert projection.notes
    for section in projection.notes:
        assert section.projection.blocks
        assert set(_directions(section.projection)) == {"rtl"}


def test_without_a_direction_no_block_has_the_attribute():
    for direction in (None, "", "auto", "sideways"):
        projection = layout_projection(BOOK, STYLES, "k", show_markers=False, direction=direction)
        assert set(_directions(projection)) == {None}
        assert all("direction" not in block.attrs for section in projection.notes for block in section.projection.blocks)


def test_the_direction_changes_no_text_and_no_source_mapping():
    plain = layout_projection(BOOK, STYLES, "k", show_markers=True)
    directed = layout_projection(BOOK, STYLES, "k", show_markers=True, direction="ltr")

    assert directed.text == plain.text
    assert directed.source_map.segments == plain.source_map.segments
    # A block with no formatting of its own (`\id`) is recorded for its direction.
    ranges = {(block.view_start, block.view_end) for block in directed.blocks}
    assert {(block.view_start, block.view_end) for block in plain.blocks} <= ranges


def test_the_views_project_with_a_direction():
    standard = SfmStandardView(lambda: STYLES)
    preview = SfmPreviewView(lambda: STYLES)

    assert set(_directions(standard.project_with(BOOK, direction="rtl"))) == {"rtl"}
    assert set(_directions(preview.project_with(BOOK, direction="ltr"))) == {"ltr"}
    assert set(_directions(standard.project_with(BOOK))) == {None}
    # The categories and hyphenation are Preview's: Standard ignores them.
    rtl_text = standard.project_with(BOOK, frozenset({"x"}), None, "rtl").text
    assert rtl_text.replace(LRI, "").replace(PDI, "") == standard.project(BOOK).text
    assert preview.project_with(BOOK).text == preview.project(BOOK).text


# --- `\Direction` on paragraph styles and rules (W5) ------------------------------

FRONT = "\\id FRT\n\\mt1 Title\n\\p English front matter\n\\q1 שלום\n\\q1 עולם\n\\p back\n"


def _styles(*sheets: tuple[str, StyleOrigin]) -> LayeredStyleRegistry:
    """The stock layers with `sheets` (text, origin) on top, lowest first."""

    layers = [StyleLayer(f"layer{index}.sty", origin, parse_raw_stylesheet(text)) for index, (text, origin) in enumerate(sheets)]
    return LayeredStyleRegistry(build_layers(load_usfm_baseline(), None, layers))


def _by_marker(projection) -> dict[str, list[str | None]]:
    result: dict[str, list[str | None]] = {}
    for block in projection.blocks:
        result.setdefault(block.marker, []).append(block.attrs.get("direction"))
    return result


def test_a_style_direction_beats_the_project_direction():
    styles = _styles(("\\Marker p\n\\Direction LTR\n", StyleOrigin.UNITI_PROJECT))
    directions = _by_marker(layout_projection(FRONT, styles, "k", show_markers=False, direction="rtl"))

    assert directions["p"] == ["ltr", "ltr"]
    assert directions["q1"] == ["rtl", "rtl"] and directions["mt1"] == ["rtl"]


def test_a_style_direction_applies_with_no_project_direction():
    styles = _styles(("\\Marker q1\n\\Direction rtl\n", StyleOrigin.UNITI_PROJECT))
    directions = _by_marker(layout_projection(FRONT, styles, "k", show_markers=True))

    assert directions["q1"] == ["rtl", "rtl"]
    assert directions["p"] == [None, None]


def test_auto_and_unknown_values_leave_the_lower_sources():
    for value in ("Auto", "sideways", ""):
        styles = _styles((f"\\Marker p\n\\Direction {value}\n", StyleOrigin.UNITI_PROJECT))
        directions = _by_marker(layout_projection(FRONT, styles, "k", show_markers=False, direction="rtl"))
        assert directions["p"] == ["rtl", "rtl"]


def test_a_rule_beats_the_marker_and_the_later_layer_wins():
    styles = _styles(
        ("\\Marker q1\n\\Direction LTR\n", StyleOrigin.PROJECT),
        ("\\Marker q1\n\\Direction RTL\n\n\\Marker p+q1\n\\Direction LTR\n", StyleOrigin.UNITI_PROJECT),
    )
    directions = _by_marker(layout_projection(FRONT, styles, "k", show_markers=False))

    # The first \q1 follows a \p (the rule); the second follows a \q1.
    assert directions["q1"] == ["ltr", "rtl"]


def test_a_character_style_direction_is_not_a_block_direction():
    """It isolates the span instead (W6)."""

    styles = _styles(("\\Marker nd\n\\Direction RTL\n", StyleOrigin.UNITI_PROJECT))
    projection = layout_projection("\\p the \\nd Lord\\nd* says\n", styles, "k", show_markers=False)

    assert [block.attrs.get("direction") for block in projection.blocks] == [None]
    assert all("direction" not in span.attrs for span in projection.spans)


def test_the_style_inspector_lists_the_field():
    styles = _styles(("\\Marker p\n\\Direction LTR\n", StyleOrigin.UNITI_PROJECT))

    fields = dict(styles.presentation("p"))
    assert fields["Direction"].value == "LTR" and fields["Direction"].origin_layer == "layer0.sty"


# --- Standard's tags in a right-to-left paragraph (W4) ---------------------------

TAGGED = (
    "\\id JHN\n\\c 1\n\\p\n\\v 1 שלום \\nd יהוה\\nd* עולם\\f + \\ft הערה\\f*\n"
    "\\q1 \\v 2 \\qt-s |who=\"x\"\\* אור\\qt-e\\*\n\\zz unknown\n"
)


def _isolates_around_every_tag(projection) -> bool:
    text = projection.text
    tags = [span for span in projection.spans if span.attrs.get("marker_token") == "yes"]
    markers = [segment for segment in projection.source_map.segments if segment.role is SegmentRole.MARKER]
    return bool(tags) and all(
        text[segment.view_start - 1] == LRI and text[segment.view_end] == PDI for segment in markers
    )


def test_every_tag_of_a_right_to_left_paragraph_is_isolated():
    projection = layout_projection(TAGGED, STYLES, "k", show_markers=True, direction="rtl")

    assert _isolates_around_every_tag(projection)
    isolates = [s for s in projection.source_map.segments if s.role is SegmentRole.GENERATED and s.marker == ISOLATE]
    markers = [s for s in projection.source_map.segments if s.role is SegmentRole.MARKER]
    assert len(isolates) == 2 * len(markers)
    # The tag's own colour covers its label, never the isolates.
    for span in projection.spans:
        if span.attrs.get("marker_token") == "yes":
            assert LRI not in projection.text[span.view_start : span.view_end]
            assert PDI not in projection.text[span.view_start : span.view_end]


def test_left_to_right_and_undirected_paragraphs_get_none():
    for direction in ("ltr", None):
        projection = layout_projection(TAGGED, STYLES, "k", show_markers=True, direction=direction)
        assert LRI not in projection.text and PDI not in projection.text


def test_a_style_direction_decides_per_paragraph():
    styles = _styles(("\\Marker q1\n\\Direction LTR\n", StyleOrigin.UNITI_PROJECT))
    projection = layout_projection(TAGGED, styles, "k", show_markers=True, direction="rtl")
    q1 = next(block for block in projection.blocks if block.marker == "q1")
    p = next(block for block in projection.blocks if block.marker == "p")

    assert LRI not in projection.text[q1.view_start : q1.view_end]
    assert LRI in projection.text[p.view_start : p.view_end]


def test_isolates_change_no_source_mapping():
    plain = layout_projection(TAGGED, STYLES, "k", show_markers=True, direction="ltr")
    rtl = layout_projection(TAGGED, STYLES, "k", show_markers=True, direction="rtl")
    rtl.source_map.check()

    assert rtl.text.replace(LRI, "").replace(PDI, "") == plain.text
    # Every source offset goes to the view and back as it does without them.
    for offset in range(len(TAGGED) + 1):
        for prefer_left in (True, False):
            assert rtl.source_map.view_to_source(
                rtl.source_map.source_to_view(offset), prefer_left=prefer_left
            ) == plain.source_map.view_to_source(plain.source_map.source_to_view(offset), prefer_left=prefer_left)


def test_preview_isolates_only_the_markers_it_shows():
    projection = layout_projection(TAGGED, STYLES, "k", show_markers=False, direction="rtl")

    # Only the undefined \\zz stays visible in Preview, and it is isolated.
    assert projection.text.count(LRI) == projection.text.count(PDI) == 1
    assert _isolates_around_every_tag(projection)


def test_the_view_only_positions_are_the_isolates():
    projection = layout_projection(TAGGED, STYLES, "k", show_markers=True, direction="rtl")
    positions = projection.source_map.view_only_positions(0, len(projection.text))

    assert {projection.text[position] for position in positions} == {LRI, PDI}
    assert len(positions) == projection.text.count(LRI) + projection.text.count(PDI)


def test_a_word_beside_a_tag_maps_onto_that_word_alone():
    """What spelling underlines and Find highlights see: a word's source
    range, mapped to the view, holds the word and no isolate."""

    projection = layout_projection(TAGGED, STYLES, "k", show_markers=True, direction="rtl")
    source_map = projection.source_map
    for word in ("שלום", "יהוה", "עולם", "הערה", "אור"):
        start = TAGGED.index(word)
        view_start, view_end = source_map.source_to_view(start), source_map.source_to_view(start + len(word))
        assert projection.text[view_start:view_end] == word


def test_an_offset_at_a_tag_maps_outside_its_isolate():
    """Two tags in a row: the second's offset is between the isolates."""

    source = "\\p שלום \\nd יהוה\\nd*\\f + \\ft הערה\\f*\n"
    projection = layout_projection(source, STYLES, "k", show_markers=True, direction="rtl")
    text = projection.text
    view = projection.source_map.source_to_view(source.index("\\f "))

    assert text[view - 1] == PDI and text[view] == LRI


# --- `\Direction` on character styles (W6) ----------------------------------------

INLINE = "\\id JHN\n\\c 1\n\\p\n\\v 1 سلام \\tl Paul,\\tl* عليكم\\f + \\ft حاشية \\tl Paul\\tl*\\f*\n\\p نهاية\n"
TL_LTR = ("\\Marker tl\n\\Direction LTR\n", StyleOrigin.UNITI_PROJECT)
ISOLATES = str.maketrans("", "", LRI + RLI + PDI)


def test_a_latin_span_in_an_arabic_paragraph_is_isolated():
    styles = _styles(TL_LTR)
    preview = layout_projection(INLINE, styles, "k", show_markers=False, direction="rtl")
    standard = layout_projection(INLINE, styles, "k", show_markers=True, direction="rtl")

    assert f"سلام {LRI}Paul,{PDI} عليكم" in preview.text
    # In Standard the isolate sits inside the tags, which have their own.
    assert f"\\tl {PDI}{LRI}Paul,{PDI}{LRI}\\tl*" in standard.text
    for projection in (preview, standard):
        projection.source_map.check()


def test_right_to_left_gives_an_rli_and_no_direction_gives_none():
    styles = _styles(("\\Marker tl\n\\Direction RTL\n", StyleOrigin.UNITI_PROJECT))
    projection = layout_projection(INLINE, styles, "k", show_markers=False)
    assert f"{RLI}Paul,{PDI}" in projection.text

    for value in ("Auto", "sideways"):
        styles = _styles((f"\\Marker tl\n\\Direction {value}\n", StyleOrigin.UNITI_PROJECT))
        projection = layout_projection(INLINE, styles, "k", show_markers=False, direction="rtl")
        assert projection.text == layout_projection(INLINE, STYLES, "k", show_markers=False, direction="rtl").text


def test_a_paragraph_style_direction_isolates_nothing():
    styles = _styles(("\\Marker p\n\\Direction LTR\n", StyleOrigin.UNITI_PROJECT))
    projection = layout_projection(INLINE, styles, "k", show_markers=False)

    assert not set(projection.text) & {LRI, RLI, PDI}


def test_nested_spans_nest_their_isolates():
    styles = _styles(TL_LTR, ("\\Marker nd\n\\Direction RTL\n", StyleOrigin.UNITI_PROJECT))
    source = "\\p سلام \\tl Paul \\+nd رب\\+nd* Silas\\tl* عليكم\n"
    projection = layout_projection(source, styles, "k", show_markers=False)

    assert f"{LRI}Paul {RLI}رب{PDI} Silas{PDI}" in projection.text


def test_an_unclosed_span_inside_one_gets_no_isolate_and_they_balance():
    """USFM leaves an unclosed `\\+nd` unpaired, so it styles nothing and is
    not isolated; the `\\tl` around it still closes."""

    styles = _styles(TL_LTR, ("\\Marker nd\n\\Direction RTL\n", StyleOrigin.UNITI_PROJECT))
    for show_markers in (True, False):
        source = "\\p سلام \\tl Paul \\+nd رب\\tl* عليكم\n"
        projection = layout_projection(source, styles, "k", show_markers=show_markers)
        assert RLI not in projection.text
        assert projection.text.count(PDI) == projection.text.count(LRI)


def test_isolates_end_with_their_paragraph():
    """An unclosed note-internal style (an unclosed note in Standard) ends
    on its own line, before the break."""

    styles = _styles(("\\Marker fq\n\\Direction LTR\n", StyleOrigin.UNITI_PROJECT))
    source = "\\p سلام\\f + \\fq Paul\n\\p نهاية\n"
    projection = layout_projection(source, styles, "k", show_markers=True)
    first, second = projection.text.split("\n")[:2]

    assert first.endswith(f"{LRI}Paul{PDI}")
    assert not set(second) & {LRI, PDI}


def test_preview_notes_isolate_their_spans_too():
    projection = layout_projection(INLINE, _styles(TL_LTR), "k", show_markers=False, direction="rtl")
    (section,) = projection.notes

    assert f"{LRI}Paul{PDI}" in section.projection.text
    section.projection.source_map.check()


def test_span_isolates_change_no_source_mapping():
    """Every source offset goes to the view and back as without them, or
    exactly back: just inside an isolate is the span's own edge, which
    Preview without it gives to the text beside the span."""

    for show_markers in (True, False):
        plain = layout_projection(INLINE, STYLES, "k", show_markers=show_markers, direction="rtl")
        isolated = layout_projection(INLINE, _styles(TL_LTR), "k", show_markers=show_markers, direction="rtl")
        assert isolated.text.replace(LRI, "").replace(PDI, "") == plain.text.replace(LRI, "").replace(PDI, "")
        for offset in range(len(INLINE) + 1):
            for prefer_left in (True, False):
                isolated.source_map.check()
                got = isolated.source_map.view_to_source(isolated.source_map.source_to_view(offset), prefer_left=prefer_left)
                expected = plain.source_map.view_to_source(plain.source_map.source_to_view(offset), prefer_left=prefer_left)
                assert got in (expected, offset)


def test_a_styled_word_maps_onto_itself():
    """Spelling underlines and Find highlights: the source range of a word
    in an isolated span holds the word and no isolate, at either edge."""

    for show_markers in (True, False):
        projection = layout_projection(INLINE, _styles(TL_LTR), "k", show_markers=show_markers, direction="rtl")
        source_map = projection.source_map
        for word in ("Paul,", "سلام", "عليكم"):
            start = INLINE.index(word)
            view = projection.text[source_map.source_to_view(start) : source_map.source_to_view(start + len(word))]
            assert view == word


def test_the_caret_just_past_a_spans_isolate_is_where_it_was_without_it():
    """Preview: just past the PDI is still the word's end (a selection
    ending there ends in the span), and just before the LRI the end of the
    text before it."""

    projection = layout_projection(INLINE, _styles(TL_LTR), "k", show_markers=False, direction="rtl")
    after = projection.text.index(f"Paul,{PDI}") + len(f"Paul,{PDI}")

    assert projection.source_map.view_to_source(after, prefer_left=True) == INLINE.index("Paul,") + len("Paul,")
    start = projection.text.index(f"{LRI}Paul,")
    assert projection.source_map.view_to_source(start, prefer_left=True) == INLINE.index("\\tl ")


def test_span_isolates_are_view_only():
    projection = layout_projection(INLINE, _styles(TL_LTR), "k", show_markers=False, direction="rtl")
    positions = projection.source_map.view_only_positions(0, len(projection.text))

    assert "".join(projection.text[position] for position in positions) == LRI + PDI
    assert projection.text.translate(ISOLATES) == layout_projection(INLINE, STYLES, "k", show_markers=False).text
