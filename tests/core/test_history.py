from uniti.core.history import EditHistory, EditOperation, EditTransaction


def tx(start: int, deleted: str, inserted: str) -> EditTransaction:
    return EditTransaction((EditOperation(start, deleted, inserted),))


def test_history_tracks_undo_redo_and_saved_revision():
    history = EditHistory()
    first = tx(1, "", "X")
    second = tx(2, "b", "Y")
    assert not history.modified
    history.record(first)
    history.record(second)
    assert history.modified
    assert history.can_undo
    assert not history.can_redo
    history.mark_saved()
    assert not history.modified
    assert history.undo() == second
    assert history.modified
    assert history.can_redo
    assert history.redo() == second
    assert not history.modified


def test_record_after_undo_truncates_redo_and_invalidates_saved_revision():
    history = EditHistory()
    first = tx(0, "", "A")
    second = tx(1, "", "B")
    replacement = tx(1, "", "C")
    history.record(first)
    history.record(second)
    history.mark_saved()
    assert history.undo() == second
    history.record(replacement)
    assert not history.can_redo
    assert history.modified
    assert history.undo() == replacement
    assert history.undo() == first


def test_transaction_groups_multiple_operations_as_one_history_step():
    history = EditHistory()
    transaction = EditTransaction(
        (
            EditOperation(1, "a", "A"),
            EditOperation(4, "b", "B"),
        )
    )
    history.record(transaction)
    assert history.undo() == transaction
    assert not history.can_undo
    assert history.redo() == transaction


def test_empty_transaction_is_not_recorded():
    history = EditHistory()
    history.record(EditTransaction(()))
    assert not history.can_undo
    assert not history.modified
