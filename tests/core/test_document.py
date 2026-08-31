from pathlib import Path

import pytest

from uniti.core.document import Document


def test_document_open_is_lazy_and_editable(tmp_path: Path):
    path = tmp_path / "large.txt"
    path.write_bytes(b"0123456789\n" * 20_000)
    doc = Document.open(path)
    try:
        assert not doc.offset_mapper.complete
        assert not doc.source_line_index.complete
        doc.insert(5, "X")
        assert doc.read(0, 12) == "01234X56789\n"
        assert not doc.offset_mapper.complete
        assert doc.modified
    finally:
        doc.close()


def test_document_encoding_override_is_explicit_metadata(tmp_path: Path):
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"Price \x96 10")
    with Document.open(path, encoding="windows-1252") as doc:
        assert doc.encoding_info.detected == "windows-1252"
        assert doc.encoding_info.user_override
        assert doc.encoding_info.confidence == 1.0
        assert doc.encoding_info.output_encoding == "windows-1252"
        assert doc.read(0, 10) == "Price – 10"


def test_document_context_manager_closes_source(tmp_path: Path):
    import pytest

    path = tmp_path / "close.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as doc:
        assert doc.read(0, 3) == "abc"
    with pytest.raises(ValueError, match="closed"):
        doc.read(0, 1)


def test_document_unicode_edits_are_character_based(tmp_path: Path):
    path = tmp_path / "unicode.txt"
    path.write_text("Aé中😀Z", encoding="utf-8")
    with Document.open(path) as doc:
        doc.insert(2, "Ω")
        doc.replace(4, 5, "!")
        assert doc.read(0, doc.total_chars()) == "AéΩ中!Z"


def test_total_chars_finishes_mapping_only_on_demand(tmp_path: Path):
    path = tmp_path / "count.txt"
    path.write_bytes(b"abc\n" * 50_000)
    with Document.open(path) as doc:
        assert not doc.offset_mapper.complete
        assert doc.total_chars() == path.stat().st_size
        assert doc.offset_mapper.complete


def test_empty_edits_do_not_mark_document_modified(tmp_path: Path):
    path = tmp_path / "noop.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as doc:
        doc.insert(1, "")
        doc.delete(2, 2)
        assert not doc.modified


def test_document_line_navigation_tracks_edits(tmp_path: Path):
    path = tmp_path / "lines.txt"
    path.write_text("aa\nbb\ncc\ndd", encoding="utf-8")
    with Document.open(path) as doc:
        assert doc.line_start(2) == 6
        assert doc.line_for_char(7) == 2
        doc.insert(5, "\nX")
        assert doc.line_count() == 5
        assert [doc.line_start(i) for i in range(5)] == [0, 3, 6, 8, 11]
        assert doc.read_line(0) == "aa"
        assert doc.read_line(1, keep_eol=True) == "bb\n"
        assert doc.read_lines(2, 3) == ["X", "cc", "dd"]
        doc.delete(5, 8)
        assert doc.read_lines(0, doc.line_count()) == ["aa", "bbcc", "dd"]
        doc.replace(3, 5, "B\r\nC")
        assert doc.read_lines(0, doc.line_count()) == ["aa", "B", "Ccc", "dd"]


def test_document_early_line_access_is_progressive(tmp_path: Path):
    path = tmp_path / "large-lines.txt"
    path.write_bytes(b"abc\n" * 100_000)
    with Document.open(path) as doc:
        assert doc.line_start(10) == 40
        assert doc.read_line(10) == "abc"
        assert not doc.document_line_index.complete
        assert not doc.offset_mapper.complete


def test_read_line_handles_mixed_eol_and_final_line(tmp_path: Path):
    path = tmp_path / "mixed-lines.txt"
    path.write_bytes(b"a\r\nb\nc\rd")
    with Document.open(path) as doc:
        assert doc.read_lines(0, 4) == ["a", "b", "c", "d"]
        assert doc.read_lines(0, 4, keep_eol=True) == ["a\r\n", "b\n", "c\r", "d"]


def test_document_save_writes_edits_and_clears_modified(tmp_path: Path):
    path = tmp_path / "save.txt"
    path.write_text("abc\n", encoding="utf-8")
    with Document.open(path) as doc:
        doc.insert(1, "X")
        assert doc.modified
        result = doc.save()
        assert result == path
        assert not doc.modified
    assert path.read_bytes() == b"aXbc\n"


def test_document_save_as_updates_logical_path_and_output_encoding(tmp_path: Path):
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("café\n", encoding="utf-8")
    with Document.open(source) as doc:
        result = doc.save(target, encoding="windows-1252", eol="CRLF")
        assert result == target
        assert doc.path == target
        assert doc.encoding_info.detected == "utf-8"
        assert doc.encoding_info.output_encoding == "windows-1252"
        assert doc.output_eol == "CRLF"
        doc.insert(doc.total_chars(), "fin")
        doc.save()
    assert target.read_bytes() == b"caf\xe9\r\nfin"


def test_failed_document_save_keeps_modified_state_and_path(tmp_path: Path):
    from uniti.core.save import UnrepresentableCharacterError

    source = tmp_path / "source-fail.txt"
    target = tmp_path / "target-fail.txt"
    source.write_text("abc", encoding="utf-8")
    with Document.open(source) as doc:
        doc.insert(3, " ₹")
        with pytest.raises(UnrepresentableCharacterError):
            doc.save(target, encoding="windows-1252")
        assert doc.modified
        assert doc.path == source
        assert not target.exists()
