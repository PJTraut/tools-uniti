from __future__ import annotations

from pathlib import Path

import pytest

from uniti.core.document import Document
from uniti.core.index_jobs import build_line_index_batch
from uniti.resources import WorkCancelled


class _RecordingContext:
    def __init__(self) -> None:
        self.progress: list[tuple[str, int, int | None]] = []

    def check_cancelled(self) -> None:
        return

    def report(self, phase: str, completed: int, total: int | None, **_kwargs) -> None:
        self.progress.append((phase, completed, total))


class _CancellingContext(_RecordingContext):
    def check_cancelled(self) -> None:
        if self.progress:
            raise WorkCancelled("cancelled")


def test_line_index_batch_publishes_only_for_expected_revision(tmp_path: Path):
    path = tmp_path / "batch.txt"
    path.write_text("a\r\nb\nc\rd", encoding="utf-8", newline="")

    with Document.open(path, encoding="utf-8") as document:
        with document.snapshot() as snapshot:
            context = _RecordingContext()
            batch = build_line_index_batch(
                snapshot,
                start_char=0,
                max_chars=1 << 20,
                context=context,
            )

        index = document.document_line_index
        assert index.publish(batch, expected_revision=document.revision)
        assert index.total_lines() == 4
        assert [index.line_start(line) for line in range(4)] == [0, 3, 5, 7]
        assert context.progress
        assert context.progress[-1][1] == len("a\r\nb\nc\rd")

        document.insert(0, "changed\n")
        assert not index.publish(batch, expected_revision=document.revision)


def test_line_index_batch_preserves_crlf_across_chunk_boundary(tmp_path: Path):
    path = tmp_path / "split-crlf.txt"
    path.write_text("x\r\ny", encoding="utf-8", newline="")

    with Document.open(path, encoding="utf-8") as document:
        with document.snapshot() as snapshot:
            batch = build_line_index_batch(
                snapshot,
                start_char=0,
                max_chars=100,
                context=_RecordingContext(),
                chunk_chars=2,
            )
        assert document.document_line_index.publish(
            batch,
            expected_revision=document.revision,
        )
        assert document.line_count() == 2
        assert document.line_start(1) == 3


def test_line_index_batch_checks_cancellation_between_chunks(tmp_path: Path):
    path = tmp_path / "cancel.txt"
    path.write_text("line\n" * 10_000, encoding="utf-8", newline="")

    with Document.open(path, encoding="utf-8") as document:
        with document.snapshot() as snapshot:
            with pytest.raises(WorkCancelled):
                build_line_index_batch(
                    snapshot,
                    start_char=0,
                    max_chars=1 << 20,
                    context=_CancellingContext(),
                    chunk_chars=128,
                )
