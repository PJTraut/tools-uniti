"""Hyphenation in Preview (plan 2026-10-15-usfm-hyphenation-and-spelling-followups, H1/H2)."""

from __future__ import annotations

from pathlib import Path

from uniti.core.environments.sfm.hyphenation import SOFT_HYPHEN, rules_for
from uniti.core.environments.sfm.spelling import load_hyphenated_words
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
from uniti.core.environments.sfm.sty import parse_raw_stylesheet
from uniti.core.environments.sfm.style_layers import StyleLayer, StyleOrigin
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
from uniti.core.environments.sfm.views import SfmPreviewView, SfmStandardView, layout_projection

SHY = SOFT_HYPHEN
STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))

LIST = (
    "﻿#Hyphenated Word List v2.0\r\n"
    'HardHyphen = "-"\r\n'
    'SoftHyphen = "="\r\n'
    'HyphenatedMarkers = "p m q1"\r\n'
    "*aa=ronic\r\n"
    "un=der=stand\r\n"
    "com=plete=ly\r\n"
    "water=ed\r\n"
    "*a =ram\r\n"
    "go=\r\n"
)


def _rules(tmp_path: Path, text: str = LIST):
    path = tmp_path / "hyphenatedWords.txt"
    path.write_bytes(text.encode("utf-8"))
    return rules_for(load_hyphenated_words(path))


def test_break_points_follow_the_lists_equals_signs(tmp_path):
    rules = _rules(tmp_path)
    assert rules.break_points("understand") == (2, 5)
    assert rules.break_points("Understand") == (2, 5)  # case is ignored, offsets are kept
    assert rules.break_points("completely") == (3, 8)
    assert rules.break_points("Aaronic") == (2,)


def test_words_not_in_the_list_never_break(tmp_path):
    rules = _rules(tmp_path)
    assert rules.break_points("garden") == ()
    assert rules.break_points("go") == ()  # a trailing `=` is not a break


def test_a_hyphenated_word_breaks_in_its_listed_parts(tmp_path):
    rules = _rules(tmp_path)
    assert rules.break_points("well-watered") == (10,)  # only `watered` is listed
    assert rules.break_points("well-known") == ()
    assert rules.break_points("well-understand") == (7, 10)


def test_damaged_lines_with_a_space_are_ignored(tmp_path):
    rules = _rules(tmp_path)
    assert rules.break_points("ram") == ()


def test_points_find_every_word_in_a_text(tmp_path):
    rules = _rules(tmp_path)
    text = "We understand completely, Aaronic."
    assert rules.points(text) == [3 + 2, 3 + 5, 14 + 3, 14 + 8, 26 + 2]


def test_marker_defaults(tmp_path):
    rules = _rules(tmp_path)
    assert rules.marker_hyphenates("p", "VerseText") is True
    assert rules.marker_hyphenates("s1", "Section") is False
    unlisted = _rules(tmp_path, LIST.replace('HyphenatedMarkers = "p m q1"\r\n', ""))
    assert unlisted.markers is None
    assert unlisted.marker_hyphenates("li1", "VerseText") is True
    assert unlisted.marker_hyphenates("s1", "Section") is False


def test_rules_are_made_once_per_list(tmp_path):
    path = tmp_path / "hyphenatedWords.txt"
    path.write_bytes(LIST.encode("utf-8"))
    data = load_hyphenated_words(path)
    assert rules_for(data) is rules_for(data)
    assert rules_for(None) is None


SOURCE = (
    "\\id GEN\n\\c 1\n\\p\n\\v 1 We understand completely\\f + \\ft A note on understand.\\f* it.\n"
    "\\s1 Understand heading\n"
)


def _preview(tmp_path, source=SOURCE, styles=STYLES):
    rules = _rules(tmp_path)
    return layout_projection(source, styles, "sfm.preview", show_markers=False, hyphenation=rules), rules


def test_preview_puts_soft_hyphens_in_hyphenating_paragraphs(tmp_path):
    projection, _rules_ = _preview(tmp_path)
    assert f"un{SHY}der{SHY}stand com{SHY}plete{SHY}ly" in projection.text


def test_headings_stay_unhyphenated_and_so_do_notes_the_list_leaves_out(tmp_path):
    projection, _rules_ = _preview(tmp_path)
    assert f"Understand heading" in projection.text
    assert projection.text.count(SHY) == 4
    note_text = projection.notes[0].projection.text
    assert SHY not in note_text  # the list names `p m q1`, not `f`


def _note_text(rules, styles=STYLES) -> str:
    projection = layout_projection(SOURCE, styles, "sfm.preview", show_markers=False, hyphenation=rules)
    return projection.notes[0].projection.text


def test_notes_hyphenate_when_the_list_names_their_marker_or_no_markers(tmp_path):
    listed = _rules(tmp_path, LIST.replace('"p m q1"', '"p f"'))
    assert f"on un{SHY}der{SHY}stand." in _note_text(listed)
    unlisted = _rules(tmp_path, LIST.replace('HyphenatedMarkers = "p m q1"\r\n', ""))
    assert f"on un{SHY}der{SHY}stand." in _note_text(unlisted)


def test_a_notes_hyphenate_field_overrides_the_list(tmp_path):
    def styled(text: str) -> LayeredStyleRegistry:
        custom = parse_raw_stylesheet(text)
        return LayeredStyleRegistry(
            build_layers(load_usfm_baseline(), None) + (StyleLayer("custom.sty", StyleOrigin.PROJECT, custom),)
        )

    unlisted = _rules(tmp_path, LIST.replace('HyphenatedMarkers = "p m q1"\r\n', ""))
    assert SHY not in _note_text(unlisted, styled("\\Marker f\n\\Hyphenate -\n"))
    listed = _rules(tmp_path)
    assert f"un{SHY}der{SHY}stand" in _note_text(listed, styled("\\Marker f\n\\Hyphenate\n"))


def test_note_source_positions_skip_the_soft_hyphens(tmp_path):
    rules = _rules(tmp_path, LIST.replace('"p m q1"', '"p f"'))
    projection = layout_projection(SOURCE, STYLES, "sfm.preview", show_markers=False, hyphenation=rules)
    note = projection.notes[0].projection
    start = note.text.index(f"un{SHY}der")
    source_start = SOURCE.index("understand.")
    assert note.source_map.view_to_source(start) == source_start
    assert note.source_map.view_to_source(start + 3) == source_start + 2


def test_the_source_map_skips_the_soft_hyphens(tmp_path):
    projection, _rules_ = _preview(tmp_path)
    source_map = projection.source_map
    text = projection.text
    start = text.index(f"un{SHY}der")
    source_start = SOURCE.index("understand completely")
    assert source_map.view_to_source(start) == source_start
    # a position after the first soft hyphen maps to the character that follows it in the source
    assert source_map.view_to_source(start + 3) == source_start + 2
    assert source_map.source_to_view(source_start + 2) in (start + 2, start + 3)
    # the whole run, soft hyphens removed, is the source's text
    end = text.index("ly", start) + 2
    assert text[start:end].replace(SHY, "") == "understand completely"[: len("understand completely")]


def test_standard_is_never_hyphenated(tmp_path):
    rules = _rules(tmp_path)
    projection = layout_projection(SOURCE, STYLES, "sfm.standard", show_markers=True, hyphenation=rules)
    assert SHY not in projection.text


def test_hyphenate_field_overrides_the_lists_markers(tmp_path):
    custom = parse_raw_stylesheet("\\Marker p\n\\Hyphenate -\n\n\\Marker s1\n\\Hyphenate\n")
    styles = LayeredStyleRegistry(
        build_layers(load_usfm_baseline(), None) + (StyleLayer("custom.sty", StyleOrigin.PROJECT, custom),)
    )
    projection, _rules_ = _preview(tmp_path, styles=styles)
    assert f"un{SHY}der" not in projection.text.split("\n")[1]  # \p is off
    assert f"Un{SHY}der{SHY}stand" in projection.text  # \s1 is on


def test_without_rules_nothing_changes(tmp_path):
    plain = layout_projection(SOURCE, STYLES, "sfm.preview", show_markers=False)
    assert SHY not in plain.text
    view = SfmPreviewView(lambda: STYLES)
    assert view.project(SOURCE).text == plain.text
    assert view.project_filtered(SOURCE, frozenset({"x"}), None).text.count(SHY) == 0
    assert SfmStandardView(lambda: STYLES).project(SOURCE).text.count(SHY) == 0


def test_justification_values_including_start_and_end():
    from uniti.core.environments.sfm.views import formatting_attrs

    for written, expected in (
        ("Both", "justify"),
        ("justify", "justify"),
        ("Center", "center"),
        ("Right", "right"),
        ("Start", "start"),
        ("END", "end"),
    ):
        assert formatting_attrs(STYLES, {"justification": written}, block=True)["align"] == expected
    assert "align" not in formatting_attrs(STYLES, {"justification": "Sideways"}, block=True)
    assert "align" not in formatting_attrs(STYLES, {"justification": "Start"}, block=False)


def test_the_hyphenate_field_reads_as_a_flag():
    from uniti.core.environments.sfm.views import formatting_attrs

    assert formatting_attrs(STYLES, {"hyphenate": "yes"}, block=True)["hyphenate"] == "yes"
    assert formatting_attrs(STYLES, {"hyphenate": "No"}, block=True)["hyphenate"] == "no"
    assert formatting_attrs(STYLES, {"hyphenate": "-"}, block=True)["hyphenate"] == "no"
    assert "hyphenate" not in formatting_attrs(STYLES, {}, block=True)
