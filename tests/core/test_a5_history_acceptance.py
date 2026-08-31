from pathlib import Path

from uniti.core.document import Document
from uniti.core.history import EditOperation
from uniti.core.recovery import RecoveryJournal, load_recovery, replay_recovery


def test_history_save_and_recovery_flow(tmp_path: Path):
    source = tmp_path / "alpha.txt"
    saved = tmp_path / "alpha-saved.txt"
    journal_path = tmp_path / "alpha.uniti-recovery"
    source.write_text("one\ntwo\n", encoding="utf-8")

    with Document.open(source) as document:
        document.replace(4, 7, "TWO")
        assert document.modified
        document.save(saved)
        assert not document.modified
        document.undo()
        assert document.read_lines(0, 3) == ["one", "two", ""]
        assert document.modified
        document.redo()
        assert document.read_lines(0, 3) == ["one", "TWO", ""]
        assert not document.modified
    assert saved.read_text(encoding="utf-8") == "one\nTWO\n"

    with RecoveryJournal.create(journal_path, source, encoding="utf-8") as journal:
        journal.append(EditOperation(4, "two", "TWO"))
    session = load_recovery(journal_path)
    with Document.open(source) as recovered:
        replay_recovery(recovered, session)
        assert recovered.read_lines(0, recovered.line_count()) == ["one", "TWO", ""]
        assert recovered.modified
