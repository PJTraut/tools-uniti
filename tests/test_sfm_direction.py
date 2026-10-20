"""Block direction in the SFM projections (text direction plan W2)."""

from __future__ import annotations

from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
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
