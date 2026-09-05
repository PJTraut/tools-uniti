"""Fixed-vocabulary phase observation for deterministic durability tests."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol


class OperationId(StrEnum):
    DOCUMENT_SAVE = "document_save"
    SESSION_PUBLICATION = "session_publication"
    RECOVERY_WRITE = "recovery_write"
    RECOVERY_COMPACTION = "recovery_compaction"


class PhaseId(StrEnum):
    STAGE = "stage"
    SYNC = "sync"
    VERIFY = "verify"
    IDENTITY = "identity"
    REPLACE = "replace"
    PACK = "pack"
    MANIFEST = "manifest"
    POINTER = "pointer"
    APPEND = "append"
    FSYNC = "fsync"
    COMPACTION = "compaction"


class PhaseBoundary(StrEnum):
    BEFORE = "before"
    AFTER = "after"


class OwnedObjectCategory(StrEnum):
    DOCUMENT_OUTPUT = "document_output"
    SESSION_PACK = "session_pack"
    SESSION_MANIFEST = "session_manifest"
    SESSION_POINTER = "session_pointer"
    RECOVERY_JOURNAL = "recovery_journal"


@dataclass(frozen=True, slots=True)
class PhaseEvent:
    operation_id: OperationId
    phase_id: PhaseId
    boundary: PhaseBoundary
    owned_category: OwnedObjectCategory

    def __post_init__(self) -> None:
        if not isinstance(self.operation_id, OperationId):
            raise TypeError("phase operation ID must be an OperationId")
        if not isinstance(self.phase_id, PhaseId):
            raise TypeError("phase ID must be a PhaseId")
        if not isinstance(self.boundary, PhaseBoundary):
            raise TypeError("phase boundary must be a PhaseBoundary")
        if not isinstance(self.owned_category, OwnedObjectCategory):
            raise TypeError("owned category must be an OwnedObjectCategory")


class PhaseObserver(Protocol):
    def observe(self, event: PhaseEvent) -> None: ...


class _NoOpPhaseObserver:
    __slots__ = ()

    def observe(self, event: PhaseEvent) -> None:
        if not isinstance(event, PhaseEvent):
            raise TypeError("phase observer requires a PhaseEvent")


NO_OP_PHASE_OBSERVER: PhaseObserver = _NoOpPhaseObserver()


def notify_phase(observer: PhaseObserver, event: PhaseEvent) -> None:
    if not isinstance(event, PhaseEvent):
        raise TypeError("phase notification requires a PhaseEvent")
    observe = getattr(observer, "observe", None)
    if not callable(observe):
        raise TypeError("phase observer must provide observe()")
    observe(event)


def emit_phase(
    observer: PhaseObserver,
    operation_id: OperationId,
    phase_id: PhaseId,
    boundary: PhaseBoundary,
    owned_category: OwnedObjectCategory,
) -> None:
    notify_phase(
        observer,
        PhaseEvent(operation_id, phase_id, boundary, owned_category),
    )


__all__ = [
    "NO_OP_PHASE_OBSERVER",
    "OperationId",
    "OwnedObjectCategory",
    "PhaseBoundary",
    "PhaseEvent",
    "PhaseId",
    "PhaseObserver",
    "emit_phase",
    "notify_phase",
]
