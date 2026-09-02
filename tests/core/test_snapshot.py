from __future__ import annotations

from pathlib import Path

import pytest

from uniti.core.document import Document


def _snapshot_text(snapshot) -> str:
    return "".join(text for _, text in snapshot.iter_text())


def test_snapshot_retains_revision_text_after_live_edit(tmp_path: Path):
    path = tmp_path / "snapshot.txt"
    path.write_text("alpha\nbeta\n", encoding="utf-8")
    with Document.open(path) as document:
        snapshot = document.snapshot()
        try:
            document.replace(0, 5, "ALPHA")

            assert snapshot.revision == 0
            assert _snapshot_text(snapshot) == "alpha\nbeta\n"
            assert document.read(0, 5) == "ALPHA"
        finally:
            snapshot.close()


def test_snapshot_freezes_edit_blocks_before_live_append(tmp_path: Path):
    path = tmp_path / "edits.txt"
    path.write_text("source", encoding="utf-8")
    with Document.open(path) as document:
        document.insert(6, " one")
        snapshot = document.snapshot()
        try:
            document.insert(10, " two")

            assert _snapshot_text(snapshot) == "source one"
            assert document.read(0, document.total_chars()) == "source one two"
        finally:
            snapshot.close()


def test_snapshot_fork_keeps_original_bytes_after_path_replacement(tmp_path: Path):
    path = tmp_path / "identity.txt"
    path.write_text("old", encoding="utf-8")
    with Document.open(path) as document:
        snapshot = document.snapshot()
        replacement = tmp_path / "replacement.txt"
        replacement.write_text("new", encoding="utf-8")
        replacement.replace(path)
        try:
            assert snapshot.read(0, 3) == "old"
            assert snapshot.disk_identity == document.disk_identity
        finally:
            snapshot.close()


def test_snapshot_remains_readable_after_live_document_closes(tmp_path: Path):
    path = tmp_path / "close-order.txt"
    path.write_text("independent", encoding="utf-8")
    document = Document.open(path)
    snapshot = document.snapshot()

    document.close()
    try:
        assert snapshot.read(0, 11) == "independent"
    finally:
        snapshot.close()


def test_closed_snapshot_rejects_reads_and_close_is_idempotent(tmp_path: Path):
    path = tmp_path / "closed.txt"
    path.write_text("text", encoding="utf-8")
    with Document.open(path) as document:
        snapshot = document.snapshot()

    snapshot.close()
    snapshot.close()

    with pytest.raises(ValueError, match="closed"):
        snapshot.read(0, 1)
