from pathlib import Path

import pytest

from uniti.app.recovery_manager import RecoveryManager
from uniti.core.document import Document
from uniti.core.recovery import RecoverySourceMismatchError


def test_recovery_manager_is_lazy_and_tracks_undo_redo(tmp_path: Path):
    source = tmp_path / "doc.txt"
    source.write_text("abc", encoding="utf-8")
    manager = RecoveryManager(tmp_path / "recovery")
    document = Document.open(source)
    manager.attach(document)
    assert manager.discover() == ()

    document.insert(3, "X")
    candidates = manager.discover()
    assert len(candidates) == 1
    assert len(candidates[0].session.operations) == 1

    document.undo()
    candidates = manager.discover()
    assert len(candidates[0].session.operations) == 2
    document.redo()
    assert len(manager.discover()[0].session.operations) == 3

    manager.detach(document, clean=True)
    document.close()
    assert manager.discover() == ()


def test_recovery_manager_save_clears_journal_and_new_edit_restarts_it(tmp_path: Path):
    source = tmp_path / "saved.txt"
    source.write_text("abc", encoding="utf-8")
    manager = RecoveryManager(tmp_path / "recovery")
    with Document.open(source) as document:
        manager.attach(document)
        document.insert(3, "X")
        assert len(manager.discover()) == 1
        document.save()
        assert manager.discover() == ()
        document.insert(4, "Y")
        candidates = manager.discover()
        assert len(candidates) == 1
        assert len(candidates[0].session.operations) == 1
        manager.detach(document, clean=True)


def test_recovery_manager_discovers_and_replays_simulated_crash(tmp_path: Path):
    source = tmp_path / "crash.txt"
    source.write_text("abcdef", encoding="utf-8")
    recovery_dir = tmp_path / "recovery"

    first = RecoveryManager(recovery_dir)
    document = Document.open(source)
    first.attach(document)
    document.replace(1, 3, "X")
    document.insert(document.total_chars(), "!")
    first.detach(document, clean=False)
    document.close()

    second = RecoveryManager(recovery_dir)
    candidates = second.discover()
    assert len(candidates) == 1
    recovered = second.recover(candidates[0])
    try:
        assert recovered.read(0, recovered.total_chars()) == "aXdef!"
        assert recovered.modified
        # Recovery is immediately durable again if UNITI crashes a second time.
        assert len(second.discover()) == 1
    finally:
        second.detach(recovered, clean=True)
        recovered.close()
    assert second.discover() == ()


def test_recovery_manager_rejects_changed_source(tmp_path: Path):
    source = tmp_path / "changed.txt"
    source.write_text("abc", encoding="utf-8")
    recovery_dir = tmp_path / "recovery"
    manager = RecoveryManager(recovery_dir)
    document = Document.open(source)
    manager.attach(document)
    document.insert(1, "X")
    manager.detach(document, clean=False)
    document.close()

    source.write_text("someone else", encoding="utf-8")
    candidate = RecoveryManager(recovery_dir).discover()[0]
    with pytest.raises(RecoverySourceMismatchError):
        RecoveryManager(recovery_dir).recover(candidate)
