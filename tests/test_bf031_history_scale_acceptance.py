"""BF-031: no benchmark coverage existed for large cut/paste or undo/redo
at scale.

"LARGE" is already a concrete, enforced boundary in the code, just
untested against it: per-document Undo/Redo retention is bounded at 50
transactions or 32 MiB decoded (`uniti.core.history.EditHistory`),
whichever is hit first, after which the oldest transactions are pruned.
These tests exercise a large single paste (as one real operation, through
`Document`/`EditorState`'s own public API) and undo/redo at and past both
boundaries -- not merely correctness at trivial size, which is all the
existing suite covered before this.

The multi-document variant approaching the separate 256 MiB *aggregate*
cap (BF-030's shared-resource concern) lives in
`tests/app/test_session_store.py`, next to the mechanism it exercises.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

from uniti.app.editor_state import EditorState
from uniti.core.document import Document
from uniti.core.history import EditHistory, EditOperation, EditTransaction


def _open(path: Path, text: str = "") -> Document:
    path.write_text(text, encoding="utf-8")
    return Document.open(path)


def test_large_single_paste_round_trips_with_fast_undo_redo(tmp_path: Path):
    path = tmp_path / "large-paste.txt"
    with _open(path) as document:
        state = EditorState(document)
        # 24 MiB: a real, large single paste, comfortably under the 32 MiB
        # single-transaction persistence cap.
        payload = os.urandom(12 * 1024 * 1024).hex()
        assert len(payload.encode("utf-8")) == 24 * 1024 * 1024

        state.paste_text(payload)
        assert document.read(0, document.total_chars()) == payload

        undo_start = time.monotonic()
        state.undo()
        undo_seconds = time.monotonic() - undo_start
        assert document.read(0, document.total_chars()) == ""

        redo_start = time.monotonic()
        state.redo()
        redo_seconds = time.monotonic() - redo_start
        assert document.read(0, document.total_chars()) == payload

        # Generous scale sanity bounds, not a strict perf-regression gate:
        # a 24 MiB single-transaction undo/redo must not be anywhere near
        # quadratic or otherwise pathological at this size.
        assert undo_seconds < 2.0
        assert redo_seconds < 2.0

        snapshot = document.export_history()
        assert snapshot.persistable is True
        assert snapshot.truncations == ()
        # `estimate_transaction_bytes` adds a fixed 56-byte transaction/
        # operation overhead on top of the raw inserted text length.
        assert snapshot.decoded_bytes == 24 * 1024 * 1024 + 56


def test_paste_exceeding_the_single_transaction_cap_is_reported_not_silently_dropped(
    tmp_path: Path,
):
    path = tmp_path / "over-cap-paste.txt"
    with _open(path) as document:
        state = EditorState(document)
        # 40 MiB: a single paste larger than the 32 MiB per-document
        # persistence cap on its own.
        payload = os.urandom(20 * 1024 * 1024).hex()
        assert len(payload.encode("utf-8")) == 40 * 1024 * 1024

        state.paste_text(payload)

        # Live editing is never bounded by the persistence cap: undo/redo
        # must still work correctly for a paste this large.
        assert document.can_undo
        state.undo()
        assert document.read(0, document.total_chars()) == ""
        state.redo()
        assert document.read(0, document.total_chars()) == payload

        # Only the save-time snapshot must flag this as too large to
        # persist -- silently dropping it, or persisting it unbounded,
        # would both be wrong.
        snapshot = document.export_history()
        assert snapshot.persistable is False
        assert snapshot.transactions == ()
        over_limit = [
            t for t in snapshot.truncations if t.reason == "transaction_over_limit"
        ]
        assert len(over_limit) == 1
        assert over_limit[0].dropped_transactions == 1
        assert over_limit[0].dropped_bytes >= 40 * 1024 * 1024


def test_sixty_large_edits_enforce_the_fifty_transaction_depth_limit_live(
    tmp_path: Path,
):
    path = tmp_path / "many-edits.txt"
    with _open(path) as document:
        state = EditorState(document)
        # Each edit is a distinct ~100 KB append at a growing offset, kept
        # well under the 32 MiB aggregate cap (~6 MB total) so this
        # isolates the 50-transaction depth limit from the byte limit.
        # `insert_text` only ever coalesces a *single* inserted character,
        # so each multi-character append here is already its own
        # transaction.
        chunk = "x" * 100_000
        for _ in range(60):
            state.cursor = document.total_chars()
            state.anchor = state.cursor
            state.insert_text(chunk)

        assert document.total_chars() == 60 * len(chunk)
        # The 50-transaction depth limit is enforced live, at record time
        # -- not only at export -- so a generous export budget still only
        # ever sees the 50 most recent transactions.
        snapshot = document.export_history(max_transactions=1000, max_bytes=1 << 40)
        assert len(snapshot.transactions) == 50

        for _ in range(50):
            assert document.can_undo
            document.undo()
        assert not document.can_undo
        # The oldest 10 edits were evicted from *undo history* only; the
        # document's actual content still reflects all 60.
        assert document.total_chars() == 10 * len(chunk)


def test_history_near_the_32mib_boundary_truncates_oldest_transactions_and_restores(
    tmp_path: Path,
):
    path = tmp_path / "near-boundary.txt"
    with _open(path) as document:
        state = EditorState(document)
        # Five 8 MiB transactions: 40 MiB decoded total, over the 32 MiB
        # export cap, but each individually well under the per-transaction
        # cap -- isolates the byte limit from the depth and
        # per-transaction limits.
        chunks = [os.urandom(4 * 1024 * 1024).hex() for _ in range(5)]
        for chunk in chunks:
            state.cursor = document.total_chars()
            state.anchor = state.cursor
            state.insert_text(chunk)

        full_text = "".join(chunks)
        assert document.read(0, document.total_chars()) == full_text

        snapshot = document.export_history()
        assert snapshot.persistable is True
        assert snapshot.decoded_bytes <= 32 * 1024 * 1024
        byte_limit = [t for t in snapshot.truncations if t.reason == "byte_limit"]
        assert len(byte_limit) == 1
        # At least the oldest transaction had to go to fit under 32 MiB.
        assert 0 < len(snapshot.transactions) < len(chunks)

        # The *current* saved content is the full concatenation regardless
        # of how much undo history survived -- dropping the oldest
        # transactions bounds how far back undo can reach, it never
        # changes the document's actual saved text.
        restored_path = tmp_path / "restored.txt"
        with _open(restored_path, text=full_text) as restored:
            restored.restore_history(snapshot)
            for _ in range(len(snapshot.transactions)):
                assert restored.can_undo
                restored.undo()
            assert not restored.can_undo


def test_history_export_snapshot_is_fast_near_the_boundary():
    history = EditHistory()
    payload = os.urandom(15 * 1024 * 1024).hex()
    for index in range(3):
        history.record(EditTransaction((EditOperation(0, "", f"{index}:{payload}"),)))
    start = time.monotonic()
    snapshot = history.export_snapshot()
    elapsed = time.monotonic() - start
    assert elapsed < 1.0
    assert snapshot.decoded_bytes <= 32 * 1024 * 1024
