from __future__ import annotations

from pathlib import Path

from uniti.core.environments.sfm.references import Reference, ReferenceMap, book_code, book_rank, scan_books

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
