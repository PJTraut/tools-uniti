"""Footnote category filter, core (plan 2026-10-14-footnote-category-filter)."""

from __future__ import annotations

from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
from uniti.core.environments.sfm.views import (
    NO_CATEGORY,
    SfmPreviewView,
    SfmStandardView,
    layout_projection,
    note_categories,
    note_is_hidden,
    source_note_categories,
)

_STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))
_BOOK = (
    "\\id GEN\n\\c 1\n\\p\n\\v 1 Alpha\\f + \\cat aa bb\\cat* \\ft first note\\f* beta"
    "\\f + \\ft plain note\\f* gamma\\f + \\cat cc\\cat* \\ft third note\\f* delta"
    "\\x - \\cat aa\\cat* \\xt Gen 2:1\\x* end.\n"
)


def _preview(hidden=frozenset()):
    return layout_projection(_BOOK, _STYLES, "sfm.preview", show_markers=False, hidden_categories=frozenset(hidden))


def _text(projection) -> str:
    return projection.text


def _notes(projection) -> dict[str, str]:
    return {section.key: section.projection.text for section in projection.notes}


def test_every_word_inside_cat_is_a_category_and_none_is_its_own():
    assert note_categories(" + \\cat aa bb cc\\cat* \\ft x") == ("aa", "bb", "cc")
    assert note_categories(" + \\ft x") == (NO_CATEGORY,)
    assert note_categories(" + \\cat aa\\cat* \\cat bb aa\\cat* \\ft x") == ("aa", "bb")  # no repeats
    assert source_note_categories(_BOOK) == ("aa", "bb", "cc", NO_CATEGORY)


def test_a_note_is_hidden_only_when_all_its_categories_are():
    assert not note_is_hidden(" + \\cat aa bb\\cat*", frozenset())
    assert not note_is_hidden(" + \\cat aa bb\\cat*", frozenset({"aa"}))
    assert note_is_hidden(" + \\cat aa bb\\cat*", frozenset({"aa", "bb"}))
    assert note_is_hidden(" + \\ft x", frozenset({NO_CATEGORY}))
    assert not note_is_hidden(" + \\ft x", frozenset({"aa"}))


def test_nothing_hidden_is_exactly_todays_projection():
    assert _text(_preview()) == _text(
        layout_projection(_BOOK, _STYLES, "sfm.preview", show_markers=False)
    )


def test_hiding_a_category_removes_the_notes_caller_and_body():
    everything = _preview()
    assert "first note" in _notes(everything)["f"] and "plain note" in _notes(everything)["f"]

    filtered = _preview({"aa", "bb"})  # the first note and the cross reference go

    notes = _notes(filtered)
    assert "first note" not in notes["f"] and "plain note" in notes["f"] and "third note" in notes["f"]
    assert "x" not in notes  # the only cross reference was aa
    assert len(_text(filtered)) < len(_text(everything))


def test_a_note_with_two_categories_stays_while_one_is_shown():
    filtered = _preview({"aa"})

    assert "first note" in _notes(filtered)["f"]  # bb is still shown
    assert "x" not in _notes(filtered)  # but the cross reference was only aa


def test_none_hides_the_uncategorized_notes():
    notes = _notes(_preview({NO_CATEGORY}))

    assert "plain note" not in notes["f"] and "first note" in notes["f"]


def test_callers_number_as_if_hidden_notes_were_not_there():
    def callers(projection) -> str:
        return "".join(
            projection.text[segment.view_start : segment.view_end]
            for segment in projection.source_map.segments
            if segment.role.name == "GENERATED" and projection.text[segment.view_start : segment.view_end].strip() in ("a", "b", "c")
        )

    assert callers(_preview()) == "abc"
    # The first footnote is hidden: the other two take a and b, not b and c.
    assert callers(_preview({"aa", "bb"})) == "ab"


def test_the_filter_is_preview_only_standard_keeps_every_note():
    standard = SfmStandardView(lambda: _STYLES)

    assert not hasattr(standard, "project_filtered")
    assert "first note" in standard.project(_BOOK).text
    preview = SfmPreviewView(lambda: _STYLES)
    assert "first note" not in "".join(s.projection.text for s in preview.project_filtered(_BOOK, frozenset({"aa", "bb"})).notes)


def test_source_offsets_still_map_with_a_hidden_note():
    projection = _preview({"aa", "bb"})
    source_map = projection.source_map
    gamma = _BOOK.index("gamma")

    view = source_map.source_to_view(gamma)

    assert projection.text[view : view + 5] == "gamma"
    assert source_map.view_to_source(view) == gamma
