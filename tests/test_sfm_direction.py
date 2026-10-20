"""Block direction in the SFM projections (text direction plan W2, W5)."""

from __future__ import annotations

from uniti.core.environments.sfm.sty import parse_raw_stylesheet
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
    assert standard.project_with(BOOK, frozenset({"x"}), None, "rtl").text == standard.project(BOOK).text
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
    styles = _styles(("\\Marker nd\n\\Direction RTL\n", StyleOrigin.UNITI_PROJECT))
    projection = layout_projection("\\p the \\nd Lord\\nd* says\n", styles, "k", show_markers=False)

    assert [block.attrs.get("direction") for block in projection.blocks] == [None]
    assert all("direction" not in span.attrs for span in projection.spans)


def test_the_style_inspector_lists_the_field():
    styles = _styles(("\\Marker p\n\\Direction LTR\n", StyleOrigin.UNITI_PROJECT))

    fields = dict(styles.presentation("p"))
    assert fields["Direction"].value == "LTR" and fields["Direction"].origin_layer == "layer0.sty"
