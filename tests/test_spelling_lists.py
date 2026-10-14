"""Spelling S1: the word lists (plan 2026-10-13-usfm-spellcheck-plan)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from uniti.core.environments.sfm.spelling import (
    CORRECT,
    SpellingState,
    list_signature,
    lists_changed,
    load_hyphenated_words,
    load_spelling_list,
    load_spelling_status,
    spelling_list_for,
)

_XML = """﻿<?xml version="1.0" encoding="utf-8"?>
<SpellingStatus>
  <Status Word="the" State="R" />
  <Status Word="paul" State="R"><SpecificCase>Paul</SpecificCase></Status>
  <Status Word="i" State="R"><SpecificCase>I</SpecificCase></Status>
  <Status Word="teh" State="W"><Correction>the</Correction></Status>
  <Status Word="bad" State="W" />
  <Status Word="well" State="R" />
  <Status Word="watered" State="R" />
  <Status Word="donʼt" State="R" />
</SpellingStatus>
"""
_HYPH = '﻿#Hyphenated Word List v2.0\r\nHardHyphen = "-"\r\nSoftHyphen = "="\r\n*a=ro=se\r\nmoun=tain\r\ngo at\r\n'


def _project(tmp_path: Path, xml: str | None = _XML, hyph: str | None = _HYPH) -> Path:
    if xml is not None:
        (tmp_path / "SpellingStatus.xml").write_text(xml, encoding="utf-8")
    if hyph is not None:
        (tmp_path / "hyphenatedWords.txt").write_bytes(hyph.encode("utf-8"))
    return tmp_path


def test_rules_in_order(tmp_path: Path):
    words = load_spelling_list(_project(tmp_path))

    assert words.status("the") == CORRECT and words.status("THE") == CORRECT  # R, any case
    wrong = words.status("teh")
    assert wrong.state is SpellingState.WRONG and wrong.correction == "the"
    assert words.status("bad").state is SpellingState.WRONG and words.status("bad").correction is None
    assert words.status("Paul") == CORRECT and words.status("PAUL") == CORRECT  # a listed form, or all capitals
    case = words.status("paul")
    assert case.state is SpellingState.WRONG_CASE and case.forms == ("Paul",)
    assert words.status("I") == CORRECT and words.status("i").state is SpellingState.WRONG_CASE
    assert words.status("mountain") == CORRECT and words.status("arose") == CORRECT  # hyphenated list only adds
    assert words.status("zzzz").state is SpellingState.UNKNOWN
    assert words.status("go at").state is SpellingState.UNKNOWN  # word pairs aren't used


def test_status_decides_over_the_hyphenated_list(tmp_path: Path):
    words = load_spelling_list(_project(tmp_path, hyph="bad\n"))

    assert words.status("bad").state is SpellingState.WRONG


def test_hyphenated_words_are_checked_part_by_part(tmp_path: Path):
    words = load_spelling_list(_project(tmp_path))

    assert words.status("well-watered") == CORRECT
    assert words.status("well-zzzz").state is SpellingState.UNKNOWN
    assert words.status("bad-the").state is SpellingState.WRONG  # the worst part
    assert words.status("-").state is SpellingState.UNKNOWN


def test_apostrophes_are_compared_as_written(tmp_path: Path):
    words = load_spelling_list(_project(tmp_path))

    assert words.status("donʼt") == CORRECT
    assert words.status("don't").state is SpellingState.UNKNOWN


def test_normalization_and_case_folding(tmp_path: Path):
    words = load_spelling_list(_project(tmp_path, xml='<SpellingStatus><Status Word="café" State="R"/></SpellingStatus>'))

    assert words.status("café") == CORRECT  # NFD input
    assert words.status("CAFÉ") == CORRECT


def test_hyphenated_file_keeps_break_points_settings_and_skips_comments(tmp_path: Path):
    data = load_hyphenated_words(_project(tmp_path) / "hyphenatedWords.txt")

    assert data.settings == {"HardHyphen": "-", "SoftHyphen": "="}
    assert data.words["arose"] == "a=ro=se" and data.words["mountain"] == "moun=tain"
    assert "go at" not in data.words and not any(word.startswith("#") for word in data.words)


def test_a_missing_or_damaged_file_is_ignored_and_the_other_still_works(tmp_path: Path):
    (tmp_path / "a").mkdir()
    only_hyph = load_spelling_list(_project(tmp_path / "a", xml=None))
    assert only_hyph.available and only_hyph.status("mountain") == CORRECT

    (tmp_path / "b").mkdir()
    damaged = load_spelling_list(_project(tmp_path / "b", xml="<SpellingStatus><Status"))
    assert damaged.status_data is None and damaged.status("mountain") == CORRECT

    (tmp_path / "c").mkdir()
    assert not load_spelling_list(tmp_path / "c").available
    assert load_spelling_status(tmp_path / "nothing.xml") is None


def test_the_cache_rereads_a_changed_file(tmp_path: Path):
    folder = _project(tmp_path)
    first = spelling_list_for(folder)
    assert spelling_list_for(folder) is first and not lists_changed(folder)

    (folder / "SpellingStatus.xml").write_text(_XML.replace('"bad"', '"worse"'), encoding="utf-8")
    later = time.time() + 5
    os.utime(folder / "SpellingStatus.xml", (later, later))

    assert lists_changed(folder)
    second = spelling_list_for(folder)
    assert second is not first and second.status("worse").state is SpellingState.WRONG
    assert list_signature(folder)[1] is not None


_PARATEXT = Path.home() / "Library/Application Support/paratextlite/Paratext8Projects"


@pytest.mark.skipif(not (_PARATEXT / "usNIVv3").exists(), reason="no local Paratext projects")
def test_real_projects_load_quickly(capsys):
    for name, entries, wrong in (("usNIVv3", 15_522, 2), ("rnBKCv1", 79_086, 1_074)):
        if not (_PARATEXT / name).exists():
            continue
        started = time.perf_counter()
        words = load_spelling_list(_PARATEXT / name)
        elapsed = time.perf_counter() - started
        assert len(words.status_data.states) <= entries and sum(1 for s in words.status_data.states.values() if s == "W") >= wrong - 5
        assert elapsed < 2.0
        print(name, f"{elapsed * 1000:.0f} ms")
