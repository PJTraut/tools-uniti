"""Spelling S2: finding words in USFM (plan 2026-10-13-usfm-spellcheck-plan)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from uniti.core.document import Document
from uniti.core.environments.sfm.spellcheck import START, CheckContext, SpellingCache, check_line
from uniti.core.environments.sfm.spelling import SpellingList, SpellingState, SpellingStatusData, load_spelling_list
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline


def _words(*correct: str, wrong: tuple[str, ...] = ()) -> SpellingList:
    data = SpellingStatusData()
    for word in correct:
        data.states[word.casefold()] = "R"
    for word in wrong:
        data.states[word.casefold()] = "W"
    return SpellingList(data, None)


_STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))


def _context(*correct: str, wrong=(), styles=_STYLES) -> CheckContext:
    return CheckContext(_words(*correct, wrong=wrong), styles)


def _flagged(line: str, context: CheckContext, state=START):
    spans, end = check_line(line, state, context)
    return [(line[span.start : span.end], span.spelling.state.name) for span in spans], end


def test_word_boundaries():
    context = _context("donʼt", "ay'ifyufyu", "well", "watered", "the", "end")

    found, _ = _flagged("\\p the end donʼt ay'ifyufyu well-watered 12 foo’s “bar”.", context)

    # Apostrophes, U+02BC and hyphens join letters; digits, quotes and punctuation split.
    assert found == [("foo’s", "UNKNOWN"), ("bar", "UNKNOWN")]


def test_zwj_joins_only_between_letters():
    context = _context("ab")

    assert _flagged("\\p a‍b ab‍", context)[0] == [("a‍b", "UNKNOWN")]


def test_only_translation_text_is_checked():
    context = _context("hello")
    lines = {
        "\\id GEN zzz comment": [],
        "\\rem zzz a remark": [],
        "\\c 12 zzz": ["zzz"],
        "\\v 3 zzz": ["zzz"],
        "\\v 3-4 hello zzz": ["zzz"],
        '\\p hello \\w zzz|lemma="qqq" x="yyy"\\w* zzz': ["zzz", "zzz"],
        '\\p \\fig Caption zzz|src="a.jpg" size="col"\\fig*': ["Caption", "zzz"],
        "\\p \\va 2\\va* \\vp 3b\\vp* hello": [],
        "\\qt-s |sid=\"q1\" who=\"zzz\"\\*hello": [],
        "\\h zzz": ["zzz"],
        "\\p hello \\f + \\fr 1.1 \\ft zzz\\f*": ["zzz"],
    }
    for line, expected in lines.items():
        assert [word for word, _state in _flagged(line, context)[0]] == expected, line


def test_a_character_marker_continues_onto_the_next_line_until_a_paragraph():
    context = _context("hello")
    rem = _flagged("\\p hello \\f + \\ft one", context)[1]
    assert rem.open == ("f", "ft")

    # Still inside the note on the next line; \f* closes it.
    assert _flagged("two\\f* three", context, rem)[0] == [("two", "UNKNOWN"), ("three", "UNKNOWN")]
    # A paragraph marker closes whatever was open.
    assert _flagged("\\q1 zzz", context, rem)[1].open == ()


def test_a_nonvernacular_paragraph_carries_to_its_continuation_lines():
    context = _context()
    state = _flagged("\\rem begins", context)[1]

    assert _flagged("continues zzz", context, state)[0] == []
    assert _flagged("\\p back zzz", context, state)[0] == [("back", "UNKNOWN"), ("zzz", "UNKNOWN")]


def test_a_project_stylesheet_can_make_a_marker_nonvernacular(tmp_path: Path):
    (tmp_path / "custom.sty").write_text(
        "\\Marker zq\n\\Name zq - note\n\\Endmarker zq*\n\\StyleType Character\n\\TextProperties publishable nonvernacular\n",
        encoding="utf-8",
    )
    styles = LayeredStyleRegistry(build_layers(load_usfm_baseline(), tmp_path / "01GEN.usfm"))
    context = _context(styles=styles)

    assert [w for w, _ in _flagged("\\p \\zq zzz\\zq* qqq", context)[0]] == ["qqq"]
    assert [w for w, _ in _flagged("\\p \\zq zzz\\zq* qqq", _context())[0]] == ["zzz", "qqq"]


def test_wrong_words_are_flagged_wrong():
    context = _context("fine", wrong=("bad",))

    assert _flagged("\\p fine bad Bad", context)[0] == [("bad", "WRONG"), ("Bad", "WRONG")]


_BOOK = "\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 In the begining God\r\n\\q1 created zzz\r\n\\p\r\n\\v 2 Now \\f + \\ft the\r\nearth\\f* was\r\n"


def _cache(tmp_path: Path, text: str = _BOOK) -> tuple[Document, SpellingCache]:
    path = tmp_path / "01GEN.usfm"
    path.write_bytes(text.encode("utf-8"))
    document = Document.open(path)
    context = _context("in", "the", "god", "created", "now", "was", "earth")
    return document, SpellingCache(document, context)


def test_the_cache_matches_checking_line_by_line(tmp_path: Path):
    document, cache = _cache(tmp_path)

    book = cache.book_spans()
    flagged = [document.read(span.start, span.end) for span in book]
    assert flagged == ["begining", "zzz"]
    # Each line's own spans, found from its paragraph rather than the top, agree.
    per_line = []
    for number in range(document.line_count()):
        base = document.line_start(number)
        per_line.extend(document.read(base + span.start, base + span.end) for span in cache.spans_for(number))
    assert per_line == flagged
    # The note's text on the continuation line is checked in its note state.
    assert cache.line_start_state(7).open == ("f", "ft")
    document.close()


def test_after_an_edit_only_the_changed_lines_are_checked_again(tmp_path: Path):
    document, cache = _cache(tmp_path)
    cache.book_spans()
    before = cache.checked

    cache.book_spans()
    assert cache.checked == before  # all from the cache

    start = document.line_start(4)
    document.insert(start, "qqq ")
    flagged = [document.read(span.start, span.end) for span in cache.book_spans()]

    assert cache.checked == before + 1 and flagged == ["begining", "qqq", "zzz"]
    document.close()


def test_changing_the_word_list_rechecks_everything(tmp_path: Path):
    document, cache = _cache(tmp_path)
    assert len(cache.book_spans()) == 2

    cache.set_context(_context("in", "the", "god", "created", "now", "was", "earth", "begining", "zzz"))

    assert len(cache.book_spans()) == 0
    document.close()


def test_book_spans_search_by_range(tmp_path: Path):
    document, cache = _cache(tmp_path)
    book = cache.book_spans()
    zzz = next(span for span in book if document.read(span.start, span.end) == "zzz")

    assert [document.read(s.start, s.end) for s in book.overlapping(zzz.start, zzz.end)] == ["zzz"]
    assert [document.read(s.start, s.end) for s in book.overlapping(0, document.total_chars())] == ["begining", "zzz"]
    assert book.overlapping(0, 3) == []
    document.close()


_PARATEXT = Path.home() / "Library/Application Support/paratextlite/Paratext8Projects"


@pytest.mark.skipif(not (_PARATEXT / "usNIVv3" / "01GENusNIVv3.SFM").exists(), reason="no local Paratext projects")
def test_a_real_book_checks_fast_and_flags_few_words(tmp_path: Path, capsys):
    project = _PARATEXT / "usNIVv3"
    document = Document.open(project / "01GENusNIVv3.SFM")
    styles = LayeredStyleRegistry(build_layers(load_usfm_baseline(), project / "01GENusNIVv3.SFM"))
    cache = SpellingCache(document, CheckContext(load_spelling_list(project), styles))

    started = time.perf_counter()
    book = cache.book_spans()
    cold = time.perf_counter() - started
    started = time.perf_counter()
    cache.book_spans()
    warm = time.perf_counter() - started

    words = sorted({document.read(span.start, span.end) for span in book})
    print(f"Genesis: cold {cold * 1000:.0f} ms, warm {warm * 1000:.1f} ms, {len(book)} flagged: {words[:20]}")
    assert cold < 1.0 and warm < 0.1 and len(book) < 200
    document.close()
