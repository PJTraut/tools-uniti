"""Spelling follow-ups: the user's list, suggestions, word pairs, affixes
(plan 2026-10-15-usfm-hyphenation-and-spelling-followups, F1-F5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from uniti.core.environments.sfm.paratext_project import ParatextProject
from uniti.core.environments.sfm.spellcheck import START, CheckContext, check_line, describe
from uniti.core.environments.sfm.spelling import (
    SpellingList,
    SpellingState,
    SpellingStatusData,
    effective_spelling_list,
    load_spelling_list,
)
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
from uniti.core.environments.sfm.user_words import UserWords, user_words_for, user_words_path
from uniti.core.environments.user_config import set_user_config_root

_STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))


def _list(*correct: str, wrong: tuple[str, ...] = (), forms: dict[str, tuple[str, ...]] | None = None) -> SpellingList:
    data = SpellingStatusData()
    for word in correct:
        data.states[word.casefold()] = "R"
    for word in wrong:
        data.states[word.casefold()] = "W"
    data.forms.update(forms or {})
    return SpellingList(data, None)


def _flagged(line: str, words: SpellingList):
    spans, _end = check_line(line, START, CheckContext(words, _STYLES))
    return [(line[span.start : span.end], span.spelling) for span in spans]


@pytest.fixture(autouse=True)
def _no_user_data():
    set_user_config_root(None)
    yield
    set_user_config_root(None)


# --- F1: the user's own list ------------------------------------------------------


def test_approving_and_rejecting_decide_before_paratext_does():
    base = _list("god", "paul", wrong=("beginning",))
    words = base.derive(approved=["Beginning", "Zerubbabel"], rejected=["God"])

    assert words.status("beginning").state is SpellingState.CORRECT  # approved over Paratext's W
    assert words.status("Zerubbabel").state is SpellingState.CORRECT  # unknown, approved
    wrong = words.status("God")
    assert wrong.state is SpellingState.WRONG and wrong.user  # rejected over Paratext's R
    assert words.status("Paul").state is SpellingState.CORRECT  # untouched


def test_the_user_lists_wording_in_the_tooltip():
    words = _list("god").derive(rejected=["god"])

    assert describe(words.status("god"), "NIV") == "Marked wrong in your spelling list"


def test_user_words_are_kept_in_a_file_per_project(tmp_path: Path):
    set_user_config_root(tmp_path)
    path = user_words_path("NIV")
    assert path == tmp_path / "Environments" / "USFM" / "Spelling" / "NIV.json"

    words = UserWords(path)
    words.approve("Zerubbabel")
    words.reject("teh")
    words.approve("teh")  # changing its mind moves it
    words.reject("Colour")

    again = UserWords(path)
    assert again.approved == ("teh", "Zerubbabel") and again.rejected == ("Colour",)
    assert json.loads(path.read_text(encoding="utf-8")) == {"approved": ["teh", "Zerubbabel"], "rejected": ["Colour"]}
    assert again.is_approved("ZERUBBABEL") and "colour" in again


def test_forgetting_a_word_and_a_damaged_file(tmp_path: Path):
    path = tmp_path / "list.json"
    words = UserWords(path)
    words.approve("alpha")
    words.forget("ALPHA")
    assert words.approved == () and words.version >= 2

    path.write_text("{not json", encoding="utf-8")
    broken = UserWords(path)
    assert broken.approved == () and not broken.load()  # ignored, no exception
    broken.approve("beta")  # and replaced on the next change
    assert UserWords(path).approved == ("beta",)


def test_another_process_changing_the_file_is_read_again(tmp_path: Path):
    path = tmp_path / "list.json"
    words = UserWords(path)
    words.approve("alpha")
    path.write_text(json.dumps({"approved": ["alpha", "gamma"], "rejected": []}), encoding="utf-8")
    import os, time

    later = time.time() + 5
    os.utime(path, (later, later))

    assert words.reload_if_changed() and words.is_approved("gamma")
    assert not words.reload_if_changed()


def test_without_a_user_data_folder_the_list_is_in_memory_only():
    words = UserWords(user_words_path("NIV"))
    words.approve("alpha")

    assert words.path is None and words.is_approved("alpha")


def test_effective_list_is_one_object_until_something_changes(tmp_path: Path):
    set_user_config_root(tmp_path / "data")
    folder = tmp_path / "proj"
    folder.mkdir()
    (folder / "SpellingStatus.xml").write_text('<S><Status Word="god" State="R"/></S>', encoding="utf-8")
    project = ParatextProject(folder, "EFF")

    first = effective_spelling_list(project)
    assert effective_spelling_list(project) is first
    user_words_for("EFF").approve("zerubbabel")
    second = effective_spelling_list(project)
    assert second is not first and second.status("Zerubbabel").state is SpellingState.CORRECT
    assert effective_spelling_list(project) is second


# --- F2: suggestions --------------------------------------------------------------


def test_suggestions_are_the_nearest_listed_words():
    words = _list("the", "then", "they", "them", "ten", "tea", "beginning", wrong=("thex",))

    assert words.suggestions("teh") == ["tea", "ten", "the"]  # a swap and a change, alphabetical
    assert words.suggestions("begining") == ["beginning"]  # a missing letter
    assert words.suggestions("zzzzzz") == []
    assert "thex" not in words.suggestions("thexe")  # wrong words are never offered


def test_suggestions_keep_the_words_capitalization():
    words = _list("then", "paul", forms={"paul": ("Paul",)})

    assert words.suggestions("Thn") == ["Then"]
    assert words.suggestions("THN") == ["THEN"]
    assert words.suggestions("pual") == ["Paul"]  # a SpecificCase form is used as Paratext spells it


def test_longer_words_allow_two_edits_and_at_most_the_limit():
    words = _list("hallelujah", "halleluiah", "hallelujahs")

    assert words.suggestions("hallelujha") == ["hallelujah", "halleluiah", "hallelujahs"]  # one swap, then two edits
    assert _list("hallelujah").suggestions("hallelujahxxx") == []  # three edits is too far
    assert len(_list(*[f"ab{c}" for c in "cdefghijk"]).suggestions("abz", limit=3)) == 3


# --- F3: word pairs ---------------------------------------------------------------


def _pair_list() -> SpellingList:
    folder_list = load_spelling_list  # (the real loader reads the pair entries)
    del folder_list
    data = SpellingStatusData()
    for word in ("grain", "field", "the", "and"):
        data.states[word] = "R"
    data.states["grain field"] = "W"
    data.wrong_pairs[("grain", "field")] = "grainfield"
    return SpellingList(data, None)


def test_a_wrong_pair_flags_both_words_once():
    found = _flagged("\\p the grain field and the grain  field", _pair_list())

    assert [(text, spelling.pair, spelling.correction) for text, spelling in found] == [("grain field", True, "grainfield")]
    assert describe(found[0][1], "NIV") == "Paratext marks these two words wrong together: use grainfield"


def test_the_loader_reads_wrong_pairs_and_a_right_pair_does_nothing(tmp_path: Path):
    (tmp_path / "SpellingStatus.xml").write_text(
        '<S><Status Word="grain field" State="W"><Correction>grainfield</Correction></Status>'
        '<Status Word="go at" State="R"/><Status Word="go" State="R"/><Status Word="at" State="R"/></S>',
        encoding="utf-8",
    )
    words = load_spelling_list(tmp_path)

    assert words.wrong_pairs == {("grain", "field"): "grainfield"}
    assert _flagged("\\p go at", words) == []


# --- F5: word affixes -------------------------------------------------------------


def test_settings_xml_affixes_are_read(tmp_path: Path):
    (tmp_path / "Settings.xml").write_text(
        "<ScriptureText><Name>NIV</Name><WordPrefixes /><WordSuffixes>ʼs\ns\nʼ\ned \ning</WordSuffixes></ScriptureText>",
        encoding="utf-8",
    )
    project = ParatextProject.load(tmp_path)

    assert project.word_prefixes == () and project.word_suffixes == ("ʼs", "s", "ʼ", "ed", "ing")


def test_a_word_is_correct_when_a_listed_affix_leaves_a_correct_word():
    words = _list("paul", "walk", "un").derive(suffixes=["ʼs", "ing"], prefixes=["re"])

    assert words.status("Paulʼs").state is SpellingState.CORRECT
    assert words.status("walking").state is SpellingState.CORRECT
    assert words.status("rewalk").state is SpellingState.CORRECT
    assert words.status("Pauls").state is SpellingState.UNKNOWN  # `s` isn't one of the affixes
    assert words.status("ʼs").state is SpellingState.UNKNOWN  # nothing left of it
    assert words.status("talking").state is SpellingState.UNKNOWN  # `talk` isn't a word here


# --- F3 (later): approving and rejecting a word pair --------------------------------


def test_an_approved_pair_is_no_longer_flagged_and_its_words_are_judged_singly():
    words = _pair_list().derive(approved=["Grain Field"])

    assert words.wrong_pairs == {}
    assert _flagged("\\p the grain field", words) == []
    assert words.status("grain").state is SpellingState.CORRECT


def test_a_rejected_pair_flags_both_words_as_the_users_own():
    base = _list("go", "at", "the")
    words = base.derive(rejected=["go at"])

    found = _flagged("\\p the go at the go", words)

    assert [(text, spelling.pair, spelling.user) for text, spelling in found] == [("go at", True, True)]
    assert describe(found[0][1], "NIV") == "Marked wrong in your spelling list"
    assert words.status("go").state is SpellingState.CORRECT  # the words alone are untouched


def test_a_rejected_pair_overrides_the_list_and_removing_it_brings_paratexts_back():
    words = _pair_list().derive(rejected=["grain field"])
    assert words.wrong_pairs == {("grain", "field"): None}  # the user's, without Paratext's correction

    assert _pair_list().derive(rejected=[]).wrong_pairs == {("grain", "field"): "grainfield"}


def test_entries_of_more_than_two_words_are_ignored():
    words = _list("a", "b", "c").derive(rejected=["a b c", " ", "a  b"])

    assert words.wrong_pairs == {} and words.rejected == frozenset()


def test_pairs_ride_in_the_user_file_beside_the_words(tmp_path: Path):
    set_user_config_root(tmp_path)
    user = user_words_for("NIV")
    user.reject("go at")
    user.approve("Zerubbabel")

    saved = json.loads(user_words_path("NIV").read_text(encoding="utf-8"))
    assert saved == {"approved": ["Zerubbabel"], "rejected": ["go at"]}
