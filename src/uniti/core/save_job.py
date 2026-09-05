"""Snapshot-backed preparation for verified document saves."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

from uniti.app.phase_control import (
    NO_OP_PHASE_OBSERVER,
    OperationId,
    OwnedObjectCategory,
    PhaseBoundary,
    PhaseId,
    PhaseObserver,
    emit_phase,
)

from .file_identity import ExternalFileChangedError, FileIdentity
from .save import (
    StagedSave,
    discard_staged_document,
    stage_document,
    verify_staged_document,
)
from .snapshot import DocumentReadSnapshot
from .text_format import OutputFormat


class SaveTaskContext(Protocol):
    def check_cancelled(self) -> None: ...

    def report(
        self,
        phase: str,
        completed: int,
        total: int | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class DocumentSaveRequest:
    snapshot: DocumentReadSnapshot
    destination: Path
    output_format: OutputFormat
    expected_destination_identity: FileIdentity | None
    in_place: bool


@dataclass(slots=True)
class PreparedDocumentSave:
    request: DocumentSaveRequest
    staged: StagedSave
    _discarded: bool = field(default=False, init=False, repr=False)

    def discard(self) -> None:
        if self._discarded:
            return
        discard_staged_document(self.staged)
        self.request.snapshot.close()
        self._discarded = True


class ImmediateSaveContext:
    """No-op context used by compatibility synchronous save methods."""

    progressive = False

    def check_cancelled(self) -> None:
        return None

    def report(self, phase: str, completed: int, total: int | None) -> None:
        return None


def prepare_document_save(
    request: DocumentSaveRequest,
    context: SaveTaskContext,
    *,
    stage: Callable = stage_document,
    verify: Callable = verify_staged_document,
    phase_observer: PhaseObserver = NO_OP_PHASE_OBSERVER,
) -> PreparedDocumentSave:
    """Write and verify a sibling temporary without replacing its target."""

    context.check_cancelled()
    staged: StagedSave | None = None
    progressive = bool(getattr(context, "progressive", True))
    progress = (
        lambda phase, completed, total: context.report(
            phase, completed, total
        )
    )

    def cancelled() -> bool:
        context.check_cancelled()
        return False

    try:
        stage_kwargs = {
            "source_profile": request.snapshot.source_profile,
            "destination": request.destination,
            "output_format": request.output_format,
        }
        if stage is stage_document:
            stage_kwargs["phase_observer"] = phase_observer
        if progressive:
            stage_kwargs.update(progress=progress, cancelled=cancelled)
        staged = stage(
            request.snapshot.source,
            request.snapshot.piece_table,
            **stage_kwargs,
        )
        emit_phase(
            phase_observer,
            OperationId.DOCUMENT_SAVE,
            PhaseId.IDENTITY,
            PhaseBoundary.BEFORE,
            OwnedObjectCategory.DOCUMENT_OUTPUT,
        )
        if staged.target_identity != request.expected_destination_identity:
            raise ExternalFileChangedError(
                request.destination,
                request.expected_destination_identity,
                staged.target_identity,
            )
        emit_phase(
            phase_observer,
            OperationId.DOCUMENT_SAVE,
            PhaseId.IDENTITY,
            PhaseBoundary.AFTER,
            OwnedObjectCategory.DOCUMENT_OUTPUT,
        )
        context.check_cancelled()
        verify_kwargs = {}
        if verify is verify_staged_document:
            verify_kwargs["phase_observer"] = phase_observer
        if progressive:
            verify_kwargs.update(progress=progress, cancelled=cancelled)
        verify(staged, request.snapshot.iter_text(), **verify_kwargs)
        context.check_cancelled()
        return PreparedDocumentSave(request, staged)
    except Exception:
        if staged is not None:
            discard_staged_document(staged)
        request.snapshot.close()
        raise


__all__ = [
    "DocumentSaveRequest",
    "ImmediateSaveContext",
    "PreparedDocumentSave",
    "SaveTaskContext",
    "prepare_document_save",
]
