from __future__ import annotations

import threading

import pytest

from uniti.app.phase_control import (
    NO_OP_PHASE_OBSERVER,
    OperationId,
    OwnedObjectCategory,
    PhaseBoundary,
    PhaseEvent,
    PhaseId,
    notify_phase,
)


def _event() -> PhaseEvent:
    return PhaseEvent(
        OperationId.DOCUMENT_SAVE,
        PhaseId.STAGE,
        PhaseBoundary.BEFORE,
        OwnedObjectCategory.DOCUMENT_OUTPUT,
    )


def test_phase_events_are_immutable_fixed_vocabulary_and_noop_is_inert():
    event = _event()

    assert notify_phase(NO_OP_PHASE_OBSERVER, event) is None
    assert event.operation_id is OperationId.DOCUMENT_SAVE
    with pytest.raises((AttributeError, TypeError)):
        event.phase_id = PhaseId.VERIFY
    with pytest.raises(TypeError):
        PhaseEvent(
            "document_save",
            PhaseId.STAGE,
            PhaseBoundary.BEFORE,
            OwnedObjectCategory.DOCUMENT_OUTPUT,
        )


def test_injected_observer_can_pause_and_release_one_phase_exactly_once():
    event = _event()

    class BlockingObserver:
        def __init__(self) -> None:
            self.arrived = threading.Event()
            self.release = threading.Event()
            self.events: list[PhaseEvent] = []
            self.blocked = False

        def observe(self, observed: PhaseEvent) -> None:
            self.events.append(observed)
            if observed == event and not self.blocked:
                self.blocked = True
                self.arrived.set()
                if not self.release.wait(1):
                    raise TimeoutError("phase release was not received")

    observer = BlockingObserver()
    worker = threading.Thread(target=notify_phase, args=(observer, event))
    worker.start()
    assert observer.arrived.wait(1)
    assert worker.is_alive()

    observer.release.set()
    worker.join(1)
    assert not worker.is_alive()
    notify_phase(observer, event)

    assert observer.events == [event, event]
