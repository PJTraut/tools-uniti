import os
from pathlib import Path

import pytest

from uniti.core.document import Document
from uniti.core.durability import DurabilityError, DurabilityLevel
from uniti.core.history import EditOperation, HistoryEventKind
from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile


class InjectedDocumentDurabilityAdapter:
    def __init__(
        self,
        *,
        fail_file_sync: bool = False,
        fail_replace: bool = False,
    ) -> None:
        self.fail_file_sync = fail_file_sync
        self.fail_replace = fail_replace

    def sync_file(self, _descriptor: int) -> None:
        if self.fail_file_sync:
            raise OSError("injected file-sync failure")

    def replace(self, source: Path, destination: Path) -> None:
        if self.fail_replace:
            raise OSError("injected replace failure")
        os.replace(source, destination)

    def sync_directory(self, _directory: Path) -> bool:
        return False


def test_document_records_exact_bom_profile(tmp_path: Path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xef\xbb\xbfhello\r\n")
    with Document.open(path) as document:
        assert document.source_profile.key == "utf-8-bom"
        assert document.saved_output_format == OutputFormat(
            encoding_profile("utf-8-bom"), EOLPolicy.PRESERVE
        )
        assert document.output_format == document.saved_output_format
        assert document.source_eol_report is not None
        assert document.source_eol_report.kind == "CRLF"


def test_complete_output_format_controls_metadata_dirty_state(tmp_path: Path):
    path = tmp_path / "format.txt"
    path.write_bytes(b"a\nb\n")
    with Document.open(path) as document:
        saved = document.saved_output_format
        changed = OutputFormat(encoding_profile("utf-16-be-bom"), EOLPolicy.CRLF)
        document.set_output_format(changed)
        assert document.modified is True
        document.set_output_format(saved)
        assert document.modified is False


def test_profile_override_is_exact_even_without_bom(tmp_path: Path):
    path = tmp_path / "utf16.txt"
    path.write_bytes("Привет".encode("utf-16-le"))
    with Document.open(path, profile=encoding_profile("utf-16-le")) as document:
        assert document.source_profile.key == "utf-16-le"
        assert document.encoding_info.user_override is True
        assert document.read(0, document.total_chars()) == "Привет"


def test_document_rejects_profile_and_legacy_encoding_together(tmp_path: Path):
    path = tmp_path / "ambiguous.txt"
    path.write_bytes(b"abc")
    with pytest.raises(ValueError, match="profile.*encoding"):
        Document.open(
            path,
            encoding="utf-8",
            profile=encoding_profile("utf-8"),
        )


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
    path.write_text("aa\nbb\ncc\ndd", encoding="utf-8", newline="")
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
        assert [doc.line_terminator(line) for line in range(4)] == [
            "\r\n",
            "\n",
            "\r",
            "",
        ]


def test_document_save_writes_edits_and_clears_modified(tmp_path: Path):
    path = tmp_path / "save.txt"
    path.write_text("abc\n", encoding="utf-8", newline="")
    with Document.open(path) as doc:
        doc.insert(1, "X")
        assert doc.modified
        result = doc.save()
        assert result == path
        assert not doc.modified
    assert path.read_bytes() == b"aXbc\n"


def test_verified_in_place_save_updates_format_and_save_point(tmp_path: Path):
    path = tmp_path / "document.txt"
    path.write_bytes(b"a\nb\n")
    with Document.open(path) as document:
        document.replace(0, 1, "A")
        selected = OutputFormat(
            encoding_profile("utf-16-be-bom"),
            EOLPolicy.CRLF,
        )
        result = document.save(output_format=selected)
        assert result == path
        assert document.path == path
        assert document.source_profile == selected.encoding
        assert document.output_format == selected
        assert document.saved_output_format == selected
        assert document.modified is False
        assert document.read(0, document.total_chars()) == "A\r\nb\r\n"
    assert path.read_bytes() == b"\xfe\xff" + "A\r\nb\r\n".encode("utf-16-be")


def test_export_copy_leaves_source_document_state_unchanged(tmp_path: Path):
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("abc\n", encoding="utf-8", newline="")
    with Document.open(source) as document:
        document.insert(3, "!")
        before = (
            document.path,
            document.disk_identity,
            document.revision,
            document.can_undo,
            document.can_redo,
            document.modified,
            document.source_profile,
            document.output_format,
            document.saved_output_format,
        )
        selected = OutputFormat(encoding_profile("utf-8"), EOLPolicy.CRLF)
        result = document.export_copy(target, output_format=selected)
        after = (
            document.path,
            document.disk_identity,
            document.revision,
            document.can_undo,
            document.can_redo,
            document.modified,
            document.source_profile,
            document.output_format,
            document.saved_output_format,
        )
        assert result == target
        assert after == before
    assert target.read_bytes() == b"abc!\r\n"


def test_export_copy_rejects_current_document_path(tmp_path: Path):
    path = tmp_path / "same.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as document:
        with pytest.raises(ValueError, match="in-place Save"):
            document.export_copy(path, output_format=document.output_format)
    assert path.read_bytes() == b"abc"


def test_export_copy_rejects_destination_changed_since_ui_preflight(tmp_path: Path):
    from uniti.core.file_identity import ExternalFileChangedError, FileIdentity

    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("source", encoding="utf-8")
    target.write_text("old", encoding="utf-8")
    expected = FileIdentity.from_path(target)
    target.write_text("external change", encoding="utf-8")

    with Document.open(source) as document:
        with pytest.raises(ExternalFileChangedError):
            document.export_copy(
                target,
                output_format=document.output_format,
                expected_destination_identity=expected,
            )

    assert target.read_text(encoding="utf-8") == "external change"


def test_save_no_longer_accepts_a_destination_argument(tmp_path: Path):
    path = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as document:
        with pytest.raises(TypeError):
            document.save(target)
    assert not target.exists()


def test_export_copy_writes_selected_format_without_retargeting_source(tmp_path: Path):
    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source.write_text("café\n", encoding="utf-8", newline="")
    with Document.open(source) as doc:
        selected = OutputFormat(
            encoding_profile("windows-1252"),
            EOLPolicy.CRLF,
        )
        result = doc.export_copy(target, output_format=selected)
        assert result == target
        assert doc.path == source
        assert doc.encoding_info.detected == "utf-8"
        assert doc.output_format == doc.saved_output_format
        doc.insert(doc.total_chars(), "fin")
        doc.save()
    assert target.read_bytes() == b"caf\xe9\r\n"
    assert source.read_bytes() == b"caf\xc3\xa9\nfin"


def test_failed_document_save_keeps_modified_state_and_path(tmp_path: Path):
    from uniti.core.save import UnrepresentableCharacterError

    source = tmp_path / "source-fail.txt"
    target = tmp_path / "target-fail.txt"
    source.write_text("abc", encoding="utf-8")
    with Document.open(source) as doc:
        doc.insert(3, " ₹")
        with pytest.raises(UnrepresentableCharacterError):
            doc.export_copy(
                target,
                output_format=OutputFormat(
                    encoding_profile("windows-1252"),
                    EOLPolicy.PRESERVE,
                ),
            )
        assert doc.modified
        assert doc.path == source
        assert not target.exists()


def test_document_undo_redo_insert_delete_replace(tmp_path: Path):
    path = tmp_path / "history.txt"
    path.write_text("abc\ndef", encoding="utf-8", newline="")
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
    path.write_text("éa\n中b", encoding="utf-8", newline="")
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


def test_document_emits_one_semantic_event_per_history_action(tmp_path: Path):
    path = tmp_path / "semantic-history.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as document:
        events = []
        document.add_history_listener(events.append)

        document.insert(3, "X", coalesce="typing")
        document.undo()
        document.redo()
        document.save()

        assert [event.kind for event in events] == [
            HistoryEventKind.TRANSACTION,
            HistoryEventKind.UNDO,
            HistoryEventKind.REDO,
            HistoryEventKind.SAVE_POINT,
        ]
        assert events[0].coalesce == "typing"
        assert events[0].transaction is not None
        assert events[0].transaction.operations == (EditOperation(3, "", "X"),)


def test_document_history_round_trip_restores_undo_without_changing_text(
    tmp_path: Path,
):
    path = tmp_path / "restored-history.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as original:
        original.insert(3, "X")
        original.save()
        original.insert(4, "Y")
        original.undo()
        snapshot = original.export_history()
        expected_text = original.read(0, original.total_chars())

    with Document.open(path) as restored:
        restored.restore_history(snapshot)

        assert restored.read(0, restored.total_chars()) == expected_text
        assert restored.can_undo is True
        assert restored.can_redo is True
        restored.undo()
        assert restored.read(0, restored.total_chars()) == "abc"
        restored.redo()
        assert restored.read(0, restored.total_chars()) == "abcX"


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
    path.write_text("café", encoding="utf-8")
    with Document.open(path, encoding="utf-8") as document:
        assert not document.modified
        document.set_output_encoding("windows-1252")
        assert document.modified
        assert document.encoding_info.output_encoding == "windows-1252"
        document.save()
        assert not document.modified
    assert path.read_bytes() == b"caf\xe9"


def test_output_eol_policy_can_be_changed_and_reverted_without_text_edit(tmp_path: Path):
    path = tmp_path / "eol-policy.txt"
    path.write_text("a\nb\n", encoding="utf-8", newline="")
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
    source = tmp_path / "source-external.txt"
    replacement = tmp_path / "replacement.txt"
    target = tmp_path / "safe-copy.txt"
    source.write_text("abc", encoding="utf-8")
    with Document.open(source) as doc:
        baseline = doc.disk_identity
        doc.insert(3, "X")
        replacement.write_text("external", encoding="utf-8")
        replacement.replace(source)
        result = doc.export_copy(target, output_format=doc.output_format)
        assert result == target
        assert target.read_text(encoding="utf-8") == "abcX"
        assert doc.path == source
        assert doc.disk_identity == baseline
        assert doc.modified is True


def test_document_save_as_refuses_same_inode_source_mutation(tmp_path: Path):
    from uniti.core.file_identity import ExternalFileChangedError

    source = tmp_path / "source-mutated.txt"
    target = tmp_path / "unsafe-copy.txt"
    source.write_text("abc", encoding="utf-8")
    with Document.open(source) as doc:
        doc.insert(3, "X")
        source.write_text("external", encoding="utf-8")
        with pytest.raises(ExternalFileChangedError):
            doc.export_copy(target, output_format=doc.output_format)
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


def test_document_save_returns_path_and_exposes_reduced_durability(
    tmp_path: Path,
    monkeypatch,
):
    import uniti.core.save as save_module

    path = tmp_path / "durability.txt"
    path.write_text("abc", encoding="utf-8")
    adapter = InjectedDocumentDurabilityAdapter()
    monkeypatch.setattr(save_module, "NativeDurabilityAdapter", lambda: adapter)
    with Document.open(path) as document:
        assert document.last_save_durability is None
        document.insert(3, "X")

        result = document.save()

        assert result == path
        assert document.last_save_durability is not None
        assert document.last_save_durability.level is DurabilityLevel.FILE_SYNCED
        assert document.modified is False
    assert path.read_text(encoding="utf-8") == "abcX"


def test_document_replace_failure_preserves_all_precommit_state(
    tmp_path: Path,
    monkeypatch,
):
    import uniti.core.save as save_module

    path = tmp_path / "unsafe-save.txt"
    path.write_text("abc", encoding="utf-8")
    adapter = InjectedDocumentDurabilityAdapter(fail_replace=True)
    monkeypatch.setattr(save_module, "NativeDurabilityAdapter", lambda: adapter)
    with Document.open(path) as document:
        document.insert(3, "X")
        before = (
            document.path,
            document.disk_identity,
            document.revision,
            document.export_history(),
            document.modified,
            document.read(0, document.total_chars()),
        )

        with pytest.raises(DurabilityError) as caught:
            document.save()

        assert caught.value.result.level is DurabilityLevel.UNSAFE
        assert document.last_save_durability is None
        assert (
            document.path,
            document.disk_identity,
            document.revision,
            document.export_history(),
            document.modified,
            document.read(0, document.total_chars()),
        ) == before
    assert path.read_text(encoding="utf-8") == "abc"
    assert not list(tmp_path.glob(".unsafe-save.txt.*.uniti-tmp"))


def test_document_file_sync_failure_preserves_all_precommit_state(
    tmp_path: Path,
    monkeypatch,
):
    import uniti.core.save as save_module

    path = tmp_path / "unsafe-file-sync.txt"
    path.write_text("abc", encoding="utf-8")
    adapter = InjectedDocumentDurabilityAdapter(fail_file_sync=True)
    monkeypatch.setattr(save_module, "NativeDurabilityAdapter", lambda: adapter)
    with Document.open(path) as document:
        document.insert(3, "X")
        before = (
            document.path,
            document.disk_identity,
            document.revision,
            document.export_history(),
            document.modified,
            document.read(0, document.total_chars()),
        )

        with pytest.raises(DurabilityError) as caught:
            document.save()

        assert caught.value.result.level is DurabilityLevel.UNSAFE
        assert caught.value.result.file_synced is False
        assert document.last_save_durability is None
        assert (
            document.path,
            document.disk_identity,
            document.revision,
            document.export_history(),
            document.modified,
            document.read(0, document.total_chars()),
        ) == before
    assert path.read_text(encoding="utf-8") == "abc"
    assert not list(tmp_path.glob(".unsafe-file-sync.txt.*.uniti-tmp"))


@pytest.mark.parametrize(
    ("encoding", "bom", "payload"),
    [
        ("utf-16-le", b"\xff\xfe", "A\r\n".encode("utf-16-le")),
        ("utf-16-be", b"\xfe\xff", "A\r\n".encode("utf-16-be")),
        ("utf-32-le", b"\xff\xfe\x00\x00", "A\n".encode("utf-32-le")),
        ("utf-32-be", b"\x00\x00\xfe\xff", "A\n".encode("utf-32-be")),
    ],
)
def test_explicit_unicode_decoder_preserves_matching_bom_on_save(
    tmp_path: Path, encoding: str, bom: bytes, payload: bytes
):
    path = tmp_path / f"explicit-{encoding}.txt"
    path.write_bytes(bom + payload)
    with Document.open(path, encoding=encoding) as document:
        assert document.encoding_info.bom == bom
        assert document.read(0, document.total_chars()).startswith("A")
        document.insert(1, "X")
        document.save()
    assert path.read_bytes().startswith(bom)


def test_document_revision_changes_on_edit_undo_and_redo(tmp_path: Path):
    path = tmp_path / "revision.txt"
    path.write_text("abc", encoding="utf-8")
    with Document.open(path) as document:
        assert document.revision == 0
        document.insert(1, "X")
        assert document.revision == 1
        document.undo()
        assert document.revision == 2
        document.redo()
        assert document.revision == 3
        document.replace(0, 1, "a")
        assert document.revision == 3


def test_assert_safe_overwrite_detects_external_atomic_replacement(tmp_path: Path):
    from uniti.core.file_identity import ExternalFileChangedError

    source = tmp_path / "assert-safe.txt"
    replacement = tmp_path / "assert-safe-new.txt"
    source.write_text("abc", encoding="utf-8")
    with Document.open(source) as document:
        document.assert_safe_overwrite()
        replacement.write_text("external", encoding="utf-8")
        replacement.replace(source)
        with pytest.raises(ExternalFileChangedError):
            document.assert_safe_overwrite()


def test_document_rejects_staged_save_after_revision_changes(
    tmp_path: Path,
    monkeypatch,
):
    import uniti.core.save as save_module
    from uniti.core.save import StaleDocumentRevisionError

    path = tmp_path / "stale-save.txt"
    path.write_text("abc", encoding="utf-8")
    original_verify = save_module.verify_staged_document

    with Document.open(path) as document:
        document.insert(3, "X")

        def verify_then_edit(staged, chunks):
            original_verify(staged, chunks)
            document.insert(document.total_chars(), "Y")

        monkeypatch.setattr(
            "uniti.core.document.verify_staged_document",
            verify_then_edit,
        )
        with pytest.raises(StaleDocumentRevisionError):
            document.save()
        assert document.read(0, document.total_chars()) == "abcXY"
        assert document.modified is True

    assert path.read_bytes() == b"abc"
    assert list(tmp_path.glob(".stale-save.txt.*.uniti-tmp")) == []


def test_export_rejects_destination_replaced_after_staging(
    tmp_path: Path,
    monkeypatch,
):
    from uniti.core.file_identity import ExternalFileChangedError
    from uniti.core.save import verify_staged_document as real_verify

    source = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    replacement = tmp_path / "replacement.txt"
    source.write_text("source", encoding="utf-8")
    target.write_text("original target", encoding="utf-8")
    replacement.write_text("external replacement", encoding="utf-8")

    def verify_then_replace(staged, chunks):
        real_verify(staged, chunks)
        replacement.replace(target)

    monkeypatch.setattr(
        "uniti.core.document.verify_staged_document",
        verify_then_replace,
    )
    with Document.open(source) as document:
        with pytest.raises(ExternalFileChangedError):
            document.export_copy(target, output_format=document.output_format)
        assert document.path == source
        assert document.modified is False

    assert target.read_text(encoding="utf-8") == "external replacement"
    assert list(tmp_path.glob(".target.txt.*.uniti-tmp")) == []
