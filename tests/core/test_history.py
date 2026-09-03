import pytest

from uniti.core.history import (
    EditHistory,
    EditOperation,
    EditTransaction,
    HistorySnapshot,
)


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


def test_history_retains_only_the_latest_fifty_transactions():
    history = EditHistory()
    changes = [tx(index, "", str(index)) for index in range(51)]

    for change in changes:
        history.record(change)

    assert [history.undo() for _ in range(50)] == list(reversed(changes[1:]))
    assert history.can_undo is False


def test_evicted_saved_revision_cannot_appear_clean_again():
    history = EditHistory(max_transactions=2)
    history.mark_saved()
    history.record(tx(0, "", "A"))
    history.record(tx(1, "", "B"))
    history.record(tx(2, "", "C"))

    history.undo()
    history.undo()

    assert history.modified is True


def test_history_rejects_non_positive_limit():
    with pytest.raises(ValueError, match="positive"):
        EditHistory(max_transactions=0)


def test_adjacent_typing_transactions_coalesce_into_one_undo_step():
    history = EditHistory()
    first = tx(0, "", "a")
    second = tx(1, "", "b")

    history.record(first, coalesce="typing")
    history.record(second, coalesce="typing")

    assert history.undo() == EditTransaction(first.operations + second.operations)
    assert history.can_undo is False


def test_break_coalescing_starts_a_new_undo_step():
    history = EditHistory()
    first = tx(0, "", "a")
    second = tx(1, "", "b")

    history.record(first, coalesce="typing")
    history.break_coalescing()
    history.record(second, coalesce="typing")

    assert history.undo() == second
    assert history.undo() == first


def test_history_snapshot_round_trips_undo_redo_and_saved_cursor():
    history = EditHistory()
    history.record(tx(0, "", "A"))
    history.mark_saved()
    history.record(tx(1, "", "B"))
    history.undo()

    snapshot = history.export_snapshot(max_bytes=1024)
    restored = EditHistory()
    restored.restore(snapshot)

    assert restored.cursor == 1
    assert restored.saved_cursor == 1
    assert restored.can_undo is True
    assert restored.can_redo is True
    assert restored.redo() == snapshot.transactions[1]


def test_history_export_uses_depth_or_bytes_whichever_is_first():
    history = EditHistory(max_transactions=100)
    for index in range(60):
        history.record(tx(index, "", "x" * 32))

    snapshot = history.export_snapshot(max_transactions=50, max_bytes=400)

    assert len(snapshot.transactions) < 50
    assert snapshot.decoded_bytes <= 400
    assert {item.reason for item in snapshot.truncations} == {
        "byte_limit",
        "depth_limit",
    }


def test_one_oversized_transaction_stays_live_but_is_not_persistable():
    history = EditHistory()
    history.record(tx(0, "", "x" * 2048))

    snapshot = history.export_snapshot(max_bytes=256)

    assert history.can_undo is True
    assert snapshot.transactions == ()
    assert snapshot.persistable is False
    assert snapshot.truncations[-1].reason == "transaction_over_limit"


def test_history_snapshot_retains_coalescing_boundary():
    history = EditHistory()
    history.record(tx(0, "", "a"), coalesce="typing")

    snapshot = history.export_snapshot()
    restored = EditHistory()
    restored.restore(snapshot)
    restored.record(tx(1, "", "b"), coalesce="typing")

    assert restored.undo() == EditTransaction(
        (EditOperation(0, "", "a"), EditOperation(1, "", "b"))
    )
    assert restored.can_undo is False


@pytest.mark.parametrize(
    "snapshot",
    [
        HistorySnapshot((), 1, 0, None, 0),
        HistorySnapshot((), 0, 1, None, 0),
        HistorySnapshot((), 0, 0, "typing", 0),
        HistorySnapshot((tx(0, "", "A"),), 1, 1, None, 1),
    ],
)
def test_history_restore_rejects_invalid_snapshot(snapshot: HistorySnapshot):
    with pytest.raises(ValueError):
        EditHistory().restore(snapshot)


def test_history_restore_refuses_to_replace_live_history():
    history = EditHistory()
    history.record(tx(0, "", "A"))

    with pytest.raises(ValueError, match="pristine"):
        history.restore(HistorySnapshot.empty())
