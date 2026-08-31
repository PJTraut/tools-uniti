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


def test_document_undo_redo_insert_delete_replace(tmp_path: Path):
    path = tmp_path / "history.txt"
    path.write_text("abc\ndef", encoding="utf-8")
    with Document.open(path) as doc:
        doc.insert(1, "X")
        doc.delete(3, 4)
        doc.replace(0, 1, "A")
        assert doc.read(0, doc.total_chars()) == "AXb\ndef"
        assert doc.can_undo
        doc.undo()
        assert doc.read(0, doc.total_chars()) == "aXb\ndef"
        doc.undo()
        assert doc.read(0, doc.total_chars()) == "aXbc\ndef"
        doc.undo()
        assert doc.read(0, doc.total_chars()) == "abc\ndef"
        assert not doc.can_undo
        assert doc.can_redo
        doc.redo()
        doc.redo()
        doc.redo()
        assert doc.read(0, doc.total_chars()) == "AXb\ndef"
        assert not doc.can_redo


def test_document_undo_redo_updates_line_navigation_and_unicode(tmp_path: Path):
    path = tmp_path / "history-lines.txt"
    path.write_text("éa\n中b", encoding="utf-8")
    with Document.open(path) as doc:
        doc.replace(1, 3, "X\r\nY")
        assert doc.read_lines(0, doc.line_count()) == ["éX", "Y中b"]
        doc.undo()
        assert doc.read_lines(0, doc.line_count()) == ["éa", "中b"]
        doc.redo()
        assert doc.read_lines(0, doc.line_count()) == ["éX", "Y中b"]


def test_document_saved_revision_tracks_undo_redo(tmp_path: Path):
    path = tmp_path / "saved-history.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as doc:
        doc.insert(3, "X")
        assert doc.modified
        doc.save()
        assert not doc.modified
        doc.insert(4, "Y")
        assert doc.modified
        doc.undo()
        assert not doc.modified
        doc.redo()
        assert doc.modified


def test_document_iter_text_is_bounded_and_progressive(tmp_path: Path):
    path = tmp_path / "iter-document.txt"
    path.write_text("0123456789" * 30_000, encoding="utf-8")
    with Document.open(path) as doc:
        assert list(doc.iter_text(5, 24, chunk_chars=8)) == [
            (5, "56789012"),
            (13, "34567890"),
            (21, "123"),
        ]
        assert not doc.offset_mapper.complete


def test_replace_many_is_one_undoable_transaction_with_length_changes(tmp_path: Path):
    path = tmp_path / "many.txt"
    path.write_text("aa bb cc", encoding="utf-8")
    with Document.open(path) as doc:
        count = doc.replace_many([(0, 2, "A"), (3, 5, "BBBB"), (6, 8, "C")])
        assert count == 3
        assert doc.read(0, doc.total_chars()) == "A BBBB C"
        doc.undo()
        assert doc.read(0, doc.total_chars()) == "aa bb cc"
        assert not doc.can_undo
        doc.redo()
        assert doc.read(0, doc.total_chars()) == "A BBBB C"


def test_read_line_window_does_not_materialize_single_huge_line(tmp_path: Path):
    path = tmp_path / "huge-line.txt"
    path.write_bytes(b"a" * (2 * 1024 * 1024))
    with Document.open(path, encoding="utf-8") as document:
        text = document.read_line_window(0, column_start=0, max_chars=1024)
        assert text == "a" * 1024
        assert not document.document_line_index.complete
        assert not document.offset_mapper.complete


def test_output_encoding_policy_marks_document_modified_until_save(tmp_path: Path):
    path = tmp_path / "encoding-policy.txt"
    target = tmp_path / "encoding-policy-out.txt"
    path.write_text("café", encoding="utf-8")
    with Document.open(path, encoding="utf-8") as document:
        assert not document.modified
        document.set_output_encoding("windows-1252")
        assert document.modified
        assert document.encoding_info.output_encoding == "windows-1252"
        document.save(target)
        assert not document.modified
    assert target.read_bytes() == b"caf\xe9"


def test_output_eol_policy_can_be_changed_and_reverted_without_text_edit(tmp_path: Path):
    path = tmp_path / "eol-policy.txt"
    path.write_text("a\nb\n", encoding="utf-8")
    with Document.open(path, encoding="utf-8") as document:
        document.set_output_eol("CRLF")
        assert document.output_eol == "CRLF"
        assert document.modified
        document.set_output_eol(None)
        assert document.output_eol is None
        assert not document.modified


def test_text_undo_does_not_clear_output_metadata_dirtiness(tmp_path: Path):
    path = tmp_path / "metadata-history.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path, encoding="utf-8") as document:
        document.set_output_eol("CRLF")
        document.insert(3, "x")
        document.undo()
        assert document.read(0, document.total_chars()) == "abc"
        assert document.modified


def test_invalid_output_eol_policy_is_rejected(tmp_path: Path):
    path = tmp_path / "bad-eol.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path, encoding="utf-8") as document:
        with pytest.raises(ValueError, match="EOL"):
            document.set_output_eol("BAD")  # type: ignore[arg-type]


def test_document_refuses_current_path_save_after_external_change(tmp_path: Path):
    from uniti.core.file_identity import ExternalFileChangedError

    path = tmp_path / "external.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as doc:
        baseline = doc.disk_identity
        doc.insert(3, "X")
        path.write_text("changed-on-disk", encoding="utf-8")
        with pytest.raises(ExternalFileChangedError):
            doc.save()
        assert doc.disk_identity == baseline
        assert path.read_text(encoding="utf-8") == "changed-on-disk"
        assert doc.modified


def test_document_save_as_allowed_after_atomic_external_replacement(tmp_path: Path):
    from uniti.core.file_identity import FileIdentity

    source = tmp_path / "source-external.txt"
    replacement = tmp_path / "replacement.txt"
    target = tmp_path / "safe-copy.txt"
    source.write_text("abc", encoding="utf-8")
    with Document.open(source) as doc:
        doc.insert(3, "X")
        replacement.write_text("external", encoding="utf-8")
        replacement.replace(source)
        result = doc.save(target)
        assert result == target
        assert target.read_text(encoding="utf-8") == "abcX"
        assert doc.path == target
        assert doc.disk_identity == FileIdentity.from_path(target)


def test_document_save_as_refuses_same_inode_source_mutation(tmp_path: Path):
    from uniti.core.file_identity import ExternalFileChangedError

    source = tmp_path / "source-mutated.txt"
    target = tmp_path / "unsafe-copy.txt"
    source.write_text("abc", encoding="utf-8")
    with Document.open(source) as doc:
        doc.insert(3, "X")
        source.write_text("external", encoding="utf-8")
        with pytest.raises(ExternalFileChangedError):
            doc.save(target)
        assert not target.exists()


def test_successful_save_refreshes_identity_baseline(tmp_path: Path):
    from uniti.core.file_identity import ExternalFileChangedError, FileIdentity

    path = tmp_path / "refresh-identity.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as doc:
        initial = doc.disk_identity
        doc.insert(3, "X")
        doc.save()
        refreshed = doc.disk_identity
        assert refreshed == FileIdentity.from_path(path)
        assert refreshed != initial
        doc.insert(4, "Y")
        path.write_text("someone-else", encoding="utf-8")
        with pytest.raises(ExternalFileChangedError):
            doc.save()
