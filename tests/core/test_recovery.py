from pathlib import Path

import pytest

from uniti.core.document import Document
from uniti.core.history import EditOperation
from uniti.core.recovery import (
    FileIdentity,
    RecoveryJournal,
    RecoverySourceMismatchError,
    load_recovery,
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
