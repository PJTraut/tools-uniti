from pathlib import Path

from uniti.core.document import Document
from uniti.core.history import EditOperation
from uniti.core.recovery import RecoveryJournal, load_recovery, replay_recovery


def test_history_save_and_recovery_flow(tmp_path: Path):
    source = tmp_path / "alpha.txt"
    journal_path = tmp_path / "alpha.uniti-recovery"
    source.write_bytes(b"one\ntwo\n")

    with Document.open(source) as document:
        document.replace(4, 7, "TWO")
        assert document.modified
        document.save()
        assert not document.modified
        document.undo()
        assert document.read_lines(0, 3) == ["one", "two", ""]
        assert document.modified
        document.redo()
        assert document.read_lines(0, 3) == ["one", "TWO", ""]
        assert not document.modified
    assert source.read_text(encoding="utf-8") == "one\nTWO\n"

    source.write_bytes(b"one\ntwo\n")

    with RecoveryJournal.create(journal_path, source, encoding="utf-8") as journal:
        journal.append(EditOperation(4, "two", "TWO"))
    session = load_recovery(journal_path)
    with Document.open(source) as recovered:
        replay_recovery(recovered, session)
        assert recovered.read_lines(0, recovered.line_count()) == ["one", "TWO", ""]
        assert recovered.modified
