import hashlib
import json
from pathlib import Path

import pytest

from uniti.core.document import Document
from uniti.core.history import (
    EditHistory,
    EditOperation,
    EditTransaction,
    HistorySnapshot,
)
from uniti.core.recovery import (
    FileIdentity,
    RecoveryCheckpoint,
    RecoveryEvent,
    RecoveryEventKind,
    RecoveryJournal,
    RecoveryLoadStatus,
    RecoverySourceMismatchError,
    load_recovery,
    load_recovery_candidate,
    replay_recovery,
)


def test_recovery_journal_round_trips_header_edits_and_clean_marker(tmp_path: Path):
    source = tmp_path / "source.txt"
    source.write_text("abcdef", encoding="utf-8")
    journal_path = tmp_path / "session.uniti-recovery"
    identity = FileIdentity.from_path(source)

    with RecoveryJournal.create(journal_path, source, encoding="utf-8") as journal:
        journal.append(EditOperation(2, "cd", "XY"))
        journal.append(EditOperation(6, "", "!"))
        journal.mark_clean()

    session = load_recovery(journal_path)
    assert session.source_path == source
    assert session.source_identity == identity
    assert session.encoding == "utf-8"
    assert session.operations == (
        EditOperation(2, "cd", "XY"),
        EditOperation(6, "", "!"),
    )
    assert session.clean


def test_recovery_replay_reconstructs_unsaved_document(tmp_path: Path):
    source = tmp_path / "replay.txt"
    source.write_text("abcdef", encoding="utf-8")
    journal_path = tmp_path / "replay.uniti-recovery"
    with RecoveryJournal.create(journal_path, source, encoding="utf-8") as journal:
        journal.append(EditOperation(1, "bc", "X"))
        journal.append(EditOperation(5, "", "!"))

    session = load_recovery(journal_path)
    with Document.open(source) as document:
        replay_recovery(document, session)
        assert document.read(0, document.total_chars()) == "aXdef!"
        assert document.modified
        assert document.can_undo


def test_recovery_refuses_source_identity_mismatch(tmp_path: Path):
    source = tmp_path / "mismatch.txt"
    source.write_text("abc", encoding="utf-8")
    journal_path = tmp_path / "mismatch.uniti-recovery"
    with RecoveryJournal.create(journal_path, source, encoding="utf-8") as journal:
        journal.append(EditOperation(1, "b", "B"))

    source.write_text("changed", encoding="utf-8")
    session = load_recovery(journal_path)
    with Document.open(source) as document:
        with pytest.raises(RecoverySourceMismatchError):
            replay_recovery(document, session)


def test_recovery_journal_size_tracks_edit_delta_not_source_size(tmp_path: Path):
    source = tmp_path / "large.dat"
    with source.open("wb") as handle:
        handle.seek(32 * 1024 * 1024)
        handle.write(b"X")
    journal_path = tmp_path / "small.uniti-recovery"
    with RecoveryJournal.create(journal_path, source, encoding="utf-8") as journal:
        journal.append(EditOperation(0, "", "small edit"))
    assert source.stat().st_size > 32 * 1024 * 1024
    assert journal_path.stat().st_size < 2048


def test_recovery_v2_round_trips_source_and_output_metadata(tmp_path: Path):
    source = tmp_path / "metadata.txt"
    source.write_bytes(b"caf\xe9")
    journal_path = tmp_path / "metadata.uniti-recovery"

    with RecoveryJournal.create(
        journal_path,
        source,
        source_encoding="windows-1252",
        output_encoding="utf-8",
        output_eol="CRLF",
    ) as journal:
        journal.append(EditOperation(4, "", "!"))

    session = load_recovery(journal_path)
    assert session.source_encoding == "windows-1252"
    assert session.output_encoding == "utf-8"
    assert session.output_eol == "CRLF"


def _create_v3_journal(tmp_path: Path, source: Path) -> RecoveryJournal:
    return RecoveryJournal.create_v3(
        tmp_path / "semantic.uniti-recovery",
        source_path=source,
        base_identity=FileIdentity.from_path(source),
        base_hash=hashlib.sha256(source.read_bytes()).hexdigest(),
        source_encoding="utf-8",
        output_encoding="utf-8",
        output_eol=None,
        base_history=HistorySnapshot.empty(),
    )


def test_recovery_v3_round_trips_transaction_undo_redo_and_save_point(
    tmp_path: Path,
):
    source = tmp_path / "doc.txt"
    source.write_text("abc", encoding="utf-8")
    journal = _create_v3_journal(tmp_path, source)
    transaction = EditTransaction((EditOperation(3, "", "X"),))
    journal.append_event(
        RecoveryEvent.transaction(
            1,
            transaction,
            cursor=1,
            saved_cursor=0,
            revision=1,
        )
    )
    journal.append_event(
        RecoveryEvent.cursor(
            2,
            RecoveryEventKind.UNDO,
            cursor=0,
            saved_cursor=0,
            revision=2,
        )
    )
    journal.append_event(
        RecoveryEvent.cursor(
            3,
            RecoveryEventKind.REDO,
            cursor=1,
            saved_cursor=0,
            revision=3,
        )
    )
    journal.append_event(
        RecoveryEvent.cursor(
            4,
            RecoveryEventKind.SAVE_POINT,
            cursor=1,
            saved_cursor=1,
            revision=3,
        )
    )
    journal.close()

    loaded = load_recovery_candidate(journal.path)

    assert loaded.status is RecoveryLoadStatus.COMPLETE
    assert loaded.error is None
    assert loaded.session is not None
    assert loaded.session.base_hash == hashlib.sha256(b"abc").hexdigest()
    assert loaded.session.durable_revision == 3
    assert [event.kind for event in loaded.durable_events] == [
        RecoveryEventKind.TRANSACTION,
        RecoveryEventKind.UNDO,
        RecoveryEventKind.REDO,
        RecoveryEventKind.SAVE_POINT,
    ]


def test_recovery_v3_truncated_final_record_returns_validated_prefix(
    tmp_path: Path,
):
    source = tmp_path / "prefix.txt"
    source.write_text("abc", encoding="utf-8")
    journal = _create_v3_journal(tmp_path, source)
    journal.append_event(
        RecoveryEvent.transaction(
            1,
            EditTransaction((EditOperation(3, "", "X"),)),
            cursor=1,
            saved_cursor=0,
            revision=1,
        )
    )
    journal.close()
    lines = journal.path.read_bytes().splitlines(keepends=True)
    assert len(lines) == 2

    for removed_bytes in range(1, len(lines[-1])):
        candidate = tmp_path / f"truncated-{removed_bytes}.uniti-recovery"
        candidate.write_bytes(lines[0] + lines[-1][:-removed_bytes])

        loaded = load_recovery_candidate(candidate)

        assert loaded.status is RecoveryLoadStatus.TRUNCATED_TAIL
        assert loaded.session is not None
        assert loaded.durable_events == ()


def test_recovery_v3_corrupt_middle_record_is_not_accepted_as_prefix(
    tmp_path: Path,
):
    source = tmp_path / "corrupt.txt"
    source.write_text("abc", encoding="utf-8")
    journal = _create_v3_journal(tmp_path, source)
    journal.append_event(
        RecoveryEvent.transaction(
            1,
            EditTransaction((EditOperation(3, "", "X"),)),
            cursor=1,
            saved_cursor=0,
            revision=1,
        )
    )
    journal.append_event(
        RecoveryEvent.cursor(
            2,
            RecoveryEventKind.UNDO,
            cursor=0,
            saved_cursor=0,
            revision=2,
        )
    )
    journal.close()
    lines = journal.path.read_bytes().splitlines(keepends=True)
    envelope = json.loads(lines[1])
    envelope["payload"]["cursor"] = 7
    lines[1] = (
        json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    journal.path.write_bytes(b"".join(lines))

    loaded = load_recovery_candidate(journal.path)

    assert loaded.status is RecoveryLoadStatus.CORRUPT
    assert loaded.session is None
    assert loaded.durable_events == ()


def test_recovery_future_header_is_preserved_and_reported_unsupported(
    tmp_path: Path,
):
    candidate = tmp_path / "future.uniti-recovery"
    original = b'{"format":99,"type":"header"}\n'
    candidate.write_bytes(original)

    loaded = load_recovery_candidate(candidate)

    assert loaded.status is RecoveryLoadStatus.UNSUPPORTED
    assert loaded.session is None
    assert candidate.read_bytes() == original


def test_recovery_v3_checkpoint_replaces_the_event_prefix(tmp_path: Path):
    source = tmp_path / "checkpoint.txt"
    source.write_text("abc", encoding="utf-8")
    history = EditHistory()
    history.record(EditTransaction((EditOperation(0, "", "saved"),)))
    base_history = history.export_snapshot()
    transaction = RecoveryEvent.transaction(
        1,
        EditTransaction((EditOperation(3, "", "X"),)),
        cursor=2,
        saved_cursor=1,
        revision=1,
    )
    journal = _create_v3_journal(tmp_path, source)
    journal.append_checkpoint(RecoveryCheckpoint(base_history, (transaction,)))
    journal.append_event(
        RecoveryEvent.cursor(
            2,
            RecoveryEventKind.UNDO,
            cursor=1,
            saved_cursor=1,
            revision=2,
        )
    )
    journal.close()

    loaded = load_recovery_candidate(journal.path)

    assert loaded.status is RecoveryLoadStatus.COMPLETE
    assert loaded.session is not None
    assert loaded.session.base_history == base_history
    assert loaded.durable_events == (
        transaction,
        RecoveryEvent.cursor(
            2,
            RecoveryEventKind.UNDO,
            cursor=1,
            saved_cursor=1,
            revision=2,
        ),
    )


def test_recovery_v3_replays_semantic_history_and_metadata(tmp_path: Path):
    source = tmp_path / "semantic-replay.txt"
    source.write_text("abc", encoding="utf-8")
    journal = _create_v3_journal(tmp_path, source)
    transaction = EditTransaction((EditOperation(3, "", "X"),))
    journal.append_event(
        RecoveryEvent.transaction(
            1,
            transaction,
            cursor=1,
            saved_cursor=0,
            revision=1,
        )
    )
    journal.append_event(
        RecoveryEvent.cursor(
            2,
            RecoveryEventKind.UNDO,
            cursor=0,
            saved_cursor=0,
            revision=2,
        )
    )
    journal.append_event(
        RecoveryEvent.cursor(
            3,
            RecoveryEventKind.REDO,
            cursor=1,
            saved_cursor=0,
            revision=3,
        )
    )
    journal.append_event(
        RecoveryEvent(
            sequence=4,
            kind=RecoveryEventKind.METADATA,
            transaction=None,
            cursor=1,
            saved_cursor=0,
            revision=3,
            metadata={"output_profile_key": "utf-8", "output_eol": "CRLF"},
        )
    )
    journal.close()

    loaded = load_recovery(journal.path)
    with Document.open(source) as document:
        replay_recovery(document, loaded)

        assert document.read(0, document.total_chars()) == "abcX"
        assert document.output_eol == "CRLF"
        assert document.can_undo
        assert not document.can_redo
        snapshot = document.export_history()
        assert snapshot.cursor == 1
        assert snapshot.saved_cursor == 0
