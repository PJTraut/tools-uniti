from __future__ import annotations

from pathlib import Path

import pytest

from uniti.core.environments.sfm.references import (
    Reference,
    ReferenceMap,
    book_code,
    book_rank,
    chapter_window,
    scan_books,
)

_GEN = (
    "\\id GEN Genesis\n\\c 1\n\\s1 Creation\n\\p\n\\v 1 In the beginning\n\\v 2 The earth\n"
    "\\c 2\n\\p\n\\v 1 Thus\n\\v 2-3 Bridged\n\\v 4a Split\n"
)


def test_book_code_reads_the_id_line():
    assert book_code(_GEN) == "GEN"
    assert book_code("\ufeff\\id rev - test") == "REV"
    assert book_code("\\c 1") is None
    assert book_code("\\id GENESIS") is None


def test_reference_at_tracks_chapter_and_verse():
    reference_map = ReferenceMap(_GEN)
    assert [chapter.label for chapter in reference_map.chapters] == ["1", "2"]
    assert reference_map.reference_at(_GEN.index("beginning")) == Reference("GEN", "1", "1")
    assert reference_map.reference_at(_GEN.index("earth")).verse == "2"
    # In a chapter's heading, before its first verse.
    heading = reference_map.reference_at(_GEN.index("Creation"))
    assert (heading.chapter, heading.verse) == ("1", None)
    assert reference_map.reference_at(0).chapter is None


def test_find_covers_bridges_and_partial_verses():
    reference_map = ReferenceMap(_GEN)
    assert reference_map.find("2", "3").label == "2-3"
    assert reference_map.find("2", "4").label == "4a"
    assert reference_map.find("1", "9") is None
    assert reference_map.find("2", None) is None


def test_verse_range_runs_to_the_next_verse_or_chapter():
    reference_map = ReferenceMap(_GEN)
    start, end = reference_map.verse_range(reference_map.find("1", "2"))
    assert _GEN[start:end] == "\\v 2 The earth\n"
    start, end = reference_map.verse_range(reference_map.find("2", "4"))
    assert _GEN[start:end] == "\\v 4a Split\n"


def test_heading_range_runs_from_the_chapter_to_its_first_verse():
    reference_map = ReferenceMap(_GEN)
    start, end = reference_map.heading_range("1")
    assert _GEN[start:end] == "\\c 1\n\\s1 Creation\n\\p\n"
    assert reference_map.heading_range("9") is None
    assert reference_map.heading_range(None) is None


def test_chapter_window_is_whole_lines_from_one_chapter_to_the_next():
    # \id … on lines 0-3, \c 1 on line 4, \c 2 on line 9, \c 3 on line 15; 20 lines.
    chapters = [4, 9, 15]
    assert chapter_window(chapters, 6, 20) == (0, 8)  # the header goes with chapter 1
    assert chapter_window(chapters, 0, 20) == (0, 8)
    assert chapter_window(chapters, 9, 20) == (9, 14)
    assert chapter_window(chapters, 14, 20) == (9, 14)
    assert chapter_window(chapters, 19, 20) == (15, 19)  # the last runs to the end
    assert chapter_window([4, 9, 9, 15], 10, 20) == (9, 14)  # two \c on one line
    assert chapter_window([], 3, 20) is None


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_chapter_lines_count_lines_as_the_document_does(tmp_path: Path, newline: str):
    from uniti.core.document import Document

    text = _GEN.replace("\n", newline)
    path = tmp_path / "gen.usfm"
    path.write_bytes(text.encode("utf-8"))
    reference_map = ReferenceMap(text)
    with Document.open(path, encoding="utf-8") as document:
        assert reference_map.chapter_lines == tuple(document.line_for_char(c.start) for c in reference_map.chapters)
        assert reference_map.line_count == document.line_count()
    assert reference_map.chapter_lines == (1, 6)


def test_scan_books_lists_matching_files_in_canonical_order(tmp_path: Path):
    (tmp_path / "41MATXX.SFM").write_text("\\id MAT\n", encoding="utf-8")
    (tmp_path / "01GENXX.usfm").write_text("\\id GEN\n", encoding="utf-8")
    (tmp_path / "02EXOXX.usfm").write_text("\ufeff\\id EXO\n", encoding="utf-8")
    (tmp_path / "notes.usfm").write_text("no id here", encoding="utf-8")
    (tmp_path / "readme.txt").write_text("\\id REV\n", encoding="utf-8")

    books = scan_books(tmp_path, ("usfm", "sfm"))

    assert [book.code for book in books] == ["GEN", "EXO", "MAT"]
    assert scan_books(tmp_path, ("usfm",))[-1].code == "EXO"
    assert scan_books(tmp_path / "missing", ("usfm",)) == ()
    assert book_rank("GEN") < book_rank("MAT") < book_rank("ZZZ")


def test_book_header_reads_id_and_h_from_the_header_block(tmp_path: Path):
    from uniti.core.environments.sfm.references import BookHeader, book_header, book_header_for_path

    assert book_header("\\id GEN Genesis NIV\n\\ide UTF-8\n\\h Genesis\n\\mt1 Genesis\n") == BookHeader("GEN", "Genesis")
    assert book_header("\\id GEN\n\\h   The First Book of Moses  \n").label == "GEN The First Book of Moses"
    # \h counts only within the first ten lines, and \h1 is not \h.
    assert book_header("\\id EXO\n" + "\\rem x\n" * 9 + "\\h Exodus\n").header is None
    assert book_header("\\id EXO\n" + "\\rem x\n" * 8 + "\\h Exodus\n").header == "Exodus"
    assert book_header("\\id LEV\n\\h1 Leviticus\n").label == "LEV"
    assert book_header("no id here\n\\h Something\n").label is None

    path = tmp_path / "GEN.usfm"
    path.write_text("\\id GEN\n\\h Genesis\n", encoding="utf-8")
    assert book_header_for_path(path).label == "GEN Genesis"
    path.write_text("\\id GEN\n\\h Bereshit\n", encoding="utf-8")
    import os

    stat = path.stat()
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))
    assert book_header_for_path(path).label == "GEN Bereshit"


def _tokenized_references(text: str):
    """The map's chapters and verses as found from a full `tokenize_sfm`
    (how `ReferenceMap` found them before 2026-10-09)."""

    from uniti.core.environments.sfm.tokenizer import tokenize_sfm
    from uniti.core.environments.sfm.tokens import SfmTokenKind

    found, tokens = [], tokenize_sfm(text)
    for index, token in enumerate(tokens):
        if token.kind is not SfmTokenKind.MARKER or token.text not in ("\\c", "\\v"):
            continue
        following = tokens[index + 1] if index + 1 < len(tokens) else None
        if following is None or following.kind is not SfmTokenKind.TEXT:
            continue
        label = following.text.split()
        if label:
            found.append((token.text, label[0], token.start))
    return found


def _mapped_references(text: str):
    reference_map = ReferenceMap(text)
    items = [("\\c", c.label, c.start) for c in reference_map.chapters] + [
        ("\\v", v.label, v.start) for v in reference_map.verses
    ]
    return sorted(items, key=lambda item: item[2])


@pytest.mark.parametrize(
    "text",
    [
        _GEN,
        "\\c 1\\v 1 a\\v2 b \\v \\v 3\\f + \\fr 1:3 \\ft n\\f*\\c\n\\c 2",
        "\\cl Psalm\\ca 2\\ca*\\cp B\\c* x\\c-s y\\c-e\\c-1 z\\c- w\\v-sx 1\\va 4\\va*\\vp 1a\\vp*\\+v 5",
        "\\\\c 1 \\\\\\v 2 \\v\\p 3 \\v\t\n7 \\c",
        "",
    ],
)
def test_reference_scan_finds_what_the_tokenizer_does(text: str):
    assert _mapped_references(text) == _tokenized_references(text)


def test_reference_scan_matches_the_tokenizer_on_random_text():
    import random

    pieces = ["\\", "c", "v", "\\c", "\\v", " ", "\n", "1", "12", "*", "-", "s", "e", "+", "a", "p", "l", "\\p", "\\c*"]
    generator = random.Random(20261009)
    for _ in range(3000):
        text = "".join(generator.choice(pieces) for _ in range(generator.randint(0, 40)))
        assert _mapped_references(text) == _tokenized_references(text), repr(text)
