from __future__ import annotations

from uniti.core.environments.sfm.navigation import build_chapter_verse_index


def test_empty_text_yields_no_verses():
    assert build_chapter_verse_index("") == ()


def test_tracks_chapter_across_verses():
    text = "\\c 1\n\\v 1 First verse.\n\\v 2 Second verse.\n"

    locations = build_chapter_verse_index(text)

    assert [(loc.chapter, loc.verse) for loc in locations] == [("1", "1"), ("1", "2")]


def test_verse_before_any_chapter_has_no_chapter():
    text = "\\v 1 orphan verse\n"

    locations = build_chapter_verse_index(text)

    assert locations[0].chapter is None
    assert locations[0].verse == "1"


def test_chapter_changes_are_tracked():
    text = "\\c 1\n\\v 1 a\n\\c 2\n\\v 1 b\n"

    locations = build_chapter_verse_index(text)

    assert [(loc.chapter, loc.verse) for loc in locations] == [("1", "1"), ("2", "1")]


def test_bridged_verse_numbers_are_kept_as_raw_text():
    text = "\\c 1\n\\v 1-2 bridged verse\n"

    locations = build_chapter_verse_index(text)

    assert locations[0].verse == "1-2"


def test_verse_location_spans_marker_and_number_only():
    text = "\\v 1 text follows"

    locations = build_chapter_verse_index(text)

    location = locations[0]
    assert text[location.start : location.end] == "\\v 1"
