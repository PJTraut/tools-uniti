from __future__ import annotations

from pathlib import Path

import pytest

from uniti.core.document import Document
from uniti.core.file_identity import FileIdentity
from uniti.core.save import StaleDocumentRevisionError
from uniti.core.save_job import prepare_document_save


class ImmediateTaskContext:
    def __init__(self) -> None:
        self.progress: list[tuple[str, int, int | None]] = []

    def check_cancelled(self) -> None:
        return None

    def report(self, phase: str, completed: int, total: int | None) -> None:
        self.progress.append((phase, completed, total))


class CancellingTaskContext(ImmediateTaskContext):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled = False

    def check_cancelled(self) -> None:
        if self.cancelled:
            raise RuntimeError("cancelled by test")

    def report(self, phase: str, completed: int, total: int | None) -> None:
        super().report(phase, completed, total)
        if phase == "Writing" and completed > 0:
            self.cancelled = True


def test_prepare_save_verifies_temp_without_replacing_destination(tmp_path: Path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "target.txt"
    source.write_text("new text\n", encoding="utf-8", newline="")
    destination.write_text("original\n", encoding="utf-8", newline="")

    with Document.open(source) as document:
        request = document.create_save_request(
            destination,
            document.output_format,
            expected_destination_identity=FileIdentity.from_path(destination),
        )
        context = ImmediateTaskContext()
        prepared = prepare_document_save(request, context)
        try:
            assert destination.read_text(encoding="utf-8") == "original\n"
            assert prepared.staged.temporary.exists()
            assert prepared.staged.verified
            assert context.progress
        finally:
            prepared.discard()

    assert not prepared.staged.temporary.exists()


def test_stale_prepared_save_cannot_replace_destination(tmp_path: Path):
    source = tmp_path / "stale.txt"
    source.write_text("before\n", encoding="utf-8", newline="")

    with Document.open(source) as document:
        request = document.create_save_request(source, document.output_format)
        prepared = prepare_document_save(request, ImmediateTaskContext())
        document.insert(0, "edited ")
        try:
            with pytest.raises(StaleDocumentRevisionError):
                document.commit_prepared_save(prepared)
        finally:
            prepared.discard()

    assert source.read_text(encoding="utf-8") == "before\n"


def test_cancelled_preparation_removes_temp_and_preserves_target(tmp_path: Path):
    source = tmp_path / "cancel.txt"
    target = tmp_path / "target.txt"
    source.write_bytes((b"source text\n" * 100_000))
    target.write_bytes(b"original")

    with Document.open(source) as document:
        request = document.create_save_request(
            target,
            document.output_format,
            expected_destination_identity=FileIdentity.from_path(target),
        )
        with pytest.raises(RuntimeError, match="cancelled by test"):
            prepare_document_save(request, CancellingTaskContext())

    assert target.read_bytes() == b"original"
    assert list(tmp_path.glob(".target.txt.*.uniti-tmp")) == []


def test_prepared_export_commit_keeps_source_document_identity(tmp_path: Path):
    source = tmp_path / "source.txt"
    destination = tmp_path / "copy.txt"
    source.write_text("copy me\n", encoding="utf-8", newline="")

    with Document.open(source) as document:
        request = document.create_save_request(
            destination,
            document.output_format,
            expected_destination_identity=None,
        )
        prepared = prepare_document_save(request, ImmediateTaskContext())
        try:
            assert document.commit_prepared_export(prepared) == destination
        finally:
            prepared.discard()
        assert document.path == source
        assert document.modified is False

    assert destination.read_text(encoding="utf-8") == "copy me\n"
