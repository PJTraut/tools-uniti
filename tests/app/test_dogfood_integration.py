from __future__ import annotations

import threading
import time
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from uniti.app.dogfood import (
    CPUClass,
    RAMClass,
    DogfoodRecorder,
    Durability,
    HostFacts,
    Operation,
    OSFamily,
    Outcome,
    ResourceBand,
    encode_dogfood_snapshot,
)
from uniti.app.dogfood_store import ClearReport, StoreStatus
from uniti.app.service import QuitChoice, UNITIService
from uniti.app.recovery_manager import RecoveryManager
from uniti.app.session_controller import SessionController
from uniti.core.document import Document
from uniti.core.durability import DurabilityLevel, DurabilityResult
from uniti.resources import ResourceManager


_HOST = HostFacts(
    "v0.001a22",
    OSFamily.MACOS,
    CPUClass.C5_8,
    RAMClass.GIB_16_31,
)


class _RecordingSink:
    def __init__(self, *, fail_observe: bool = False) -> None:
        self._recorder = DogfoodRecorder(_HOST, day=date.today())
        self.calls: list[tuple[object, object, dict[str, object]]] = []
        self.fail_observe = fail_observe

    def observe(self, operation, outcome, **facts) -> None:
        self.calls.append((operation, outcome, dict(facts)))
        if self.fail_observe:
            raise RuntimeError("private-recorder-failure")
        self._recorder.observe(operation, outcome, **facts)

    def snapshot(self):
        return self._recorder.snapshot()

    def rollover(self, selected_day):
        return self._recorder.rollover(selected_day)

    def reset(self, *, day):
        self._recorder.reset(day=day)


class _DogfoodStore:
    def __init__(self) -> None:
        self.publications: list[object] = []

    def publish(self, snapshot):
        self.publications.append(snapshot)
        return SimpleNamespace(published=True)

    def export(self, destination: Path) -> Path:
        return destination

    def clear(self) -> ClearReport:
        return ClearReport((), 0, ())

    def status(self) -> StoreStatus:
        return StoreStatus(True, len(self.publications), 0, None, None, None)

    def load_segments(self):
        return ()


class _SessionStore:
    def __init__(self, level: DurabilityLevel = DurabilityLevel.FULL) -> None:
        self.level = level
        self.last_durability = None

    def publish(self, snapshot):
        self.last_durability = DurabilityResult(
            "session_publication",
            self.level,
            True,
            True,
            self.level is DurabilityLevel.FULL,
            None if self.level is DurabilityLevel.FULL else "directory sync unavailable",
        )
        return SimpleNamespace(
            truncations=(),
            durability=self.last_durability,
        )


class _Recovery:
    def __init__(self) -> None:
        self.observer = None

    def set_dogfood_observer(self, observer) -> None:
        self.observer = observer

    def attach(self, _document) -> None:
        return None

    def detach(self, _document, *, clean: bool) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def diagnostics(self):
        return ()


class _Window:
    view_ids = ()

    def close_for_service(self) -> None:
        return None


def _wait(predicate, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.001)
    assert predicate()


def _service(sink: _RecordingSink, *, session_level=DurabilityLevel.FULL):
    resources = ResourceManager(max_workers=2)
    recovery = _Recovery()
    service = UNITIService(
        resource_manager=resources,
        settings_store=object(),
        session_store=_SessionStore(session_level),
        recovery_manager=recovery,
        session_capture=lambda clean: ("session", clean),
        dogfood_recorder=sink,
        dogfood_store=_DogfoodStore(),
    )
    return service, recovery


def test_service_lifecycle_records_only_fixed_content_free_facts(tmp_path: Path):
    sink = _RecordingSink()
    service, recovery = _service(sink)
    source = tmp_path / "private-source-name.txt"
    source.write_text("private source body", encoding="utf-8")
    document = Document.open(source)
    entry = service.documents.adopt(document)

    service.register_window("private-window-id", _Window())
    service.unregister_window("private-window-id")
    service.track_document(entry, hash_saved=False)
    document.insert(0, "secret edit")
    generation = service.schedule_publication()
    assert generation == 1
    _wait(lambda: service.sessions.last_durability is not None)
    assert service.request_quit(lambda _entry: QuitChoice.DISCARD) is True

    observed = {(operation, outcome) for operation, outcome, _facts in sink.calls}
    assert (Operation.WINDOW_OPEN, Outcome.SUCCESS) in observed
    assert (Operation.WINDOW_CLOSE, Outcome.SUCCESS) in observed
    assert (Operation.DOCUMENT_OPEN, Outcome.SUCCESS) in observed
    assert (Operation.EDIT_TRANSACTION, Outcome.SUCCESS) in observed
    assert (Operation.SESSION_PUBLISH, Outcome.SUCCESS) in observed
    assert (Operation.DISCARD, Outcome.DISCARDED) in observed
    assert (Operation.DOCUMENT_CLOSE, Outcome.SUCCESS) in observed
    assert (Operation.QUIT, Outcome.SUCCESS) in observed
    assert recovery.observer == service.record_dogfood

    forbidden = {
        str(source),
        source.name,
        "private-window-id",
        entry.document_id,
        "private source body",
        "secret edit",
    }
    for operation, outcome, facts in sink.calls:
        assert isinstance(operation, Operation)
        assert isinstance(outcome, Outcome)
        assert set(facts) == {
            "elapsed_ms",
            "durability",
            "peak_resource",
            "retained_resource",
        }
        assert isinstance(facts["elapsed_ms"], (int, float, type(None)))
        assert isinstance(facts["durability"], Durability)
        assert isinstance(facts["peak_resource"], ResourceBand)
        assert isinstance(facts["retained_resource"], ResourceBand)
        assert forbidden.isdisjoint(map(str, (operation, outcome, *facts.values())))
    exported = encode_dogfood_snapshot(sink.snapshot()).decode("utf-8")
    assert all(value not in exported for value in forbidden)


def test_reduced_session_durability_uses_fixed_outcome():
    sink = _RecordingSink()
    service, _recovery = _service(
        sink,
        session_level=DurabilityLevel.FILE_SYNCED,
    )
    try:
        service.schedule_publication()
        _wait(
            lambda: any(
                operation is Operation.SESSION_PUBLISH
                for operation, _outcome, _facts in sink.calls
            )
        )
        call = next(
            call
            for call in sink.calls
            if call[0] is Operation.SESSION_PUBLISH
        )
        assert call[1] is Outcome.REDUCED_DURABILITY
        assert call[2]["durability"] is Durability.FILE_SYNCED
    finally:
        service.request_quit(lambda _entry: QuitChoice.DISCARD)


def test_recording_failure_never_changes_service_results():
    sink = _RecordingSink(fail_observe=True)
    service, _recovery = _service(sink)
    try:
        window = _Window()
        assert service.register_window("window", window) is None
        assert service.unregister_window("window") is window
        assert service.schedule_publication() == 1
        _wait(lambda: service.sessions.last_durability is not None)
        assert service.request_quit(lambda _entry: QuitChoice.DISCARD) is True
    finally:
        if service.is_running:
            service.request_quit(lambda _entry: QuitChoice.DISCARD)


def test_observation_is_in_memory_and_does_not_run_store_io_on_caller_thread():
    sink = _RecordingSink()
    service, _recovery = _service(sink)
    caller = threading.get_ident()
    before = len(service.dogfood_store.publications)
    service.record_dogfood(Operation.FIND_NEXT, Outcome.SUCCESS, elapsed_ms=2.0)

    assert sink.calls[-1][0:2] == (Operation.FIND_NEXT, Outcome.SUCCESS)
    assert threading.get_ident() == caller
    assert len(service.dogfood_store.publications) == before
    count = len(sink.calls)
    service.record_dogfood("private/path", Outcome.SUCCESS)
    service.record_dogfood(Operation.FIND_NEXT, "private outcome")
    assert len(sink.calls) == count
    service.request_quit(lambda _entry: QuitChoice.DISCARD)


def test_recovery_reports_recovered_without_source_or_evidence_identity(
    tmp_path: Path,
):
    source = tmp_path / "private-recovery-source.txt"
    source.write_text("private recovery body", encoding="utf-8")
    recovery_root = tmp_path / "recovery"
    first = RecoveryManager(recovery_root)
    original = Document.open(source)
    first.attach(original)
    original.insert(original.total_chars(), " private change")
    first.detach(original, clean=False)
    original.close()
    first.shutdown()

    calls = []
    second = RecoveryManager(recovery_root)
    second.set_dogfood_observer(
        lambda operation, outcome, **facts: calls.append(
            (operation, outcome, facts)
        )
    )
    recovered = second.recover(second.discover()[0])
    try:
        assert recovered.read(0, recovered.total_chars()).endswith(" private change")
        call = next(item for item in calls if item[0] is Operation.RECOVERY)
        assert call[1] is Outcome.RECOVERED
        assert set(call[2]) == {"elapsed_ms", "durability"}
        assert str(source) not in repr(call)
        assert str(recovery_root) not in repr(call)
        assert "private recovery body" not in repr(call)
    finally:
        second.detach(recovered, clean=True)
        recovered.close()
        second.shutdown()


def test_session_restore_reports_fixed_success_and_failure_outcomes():
    calls = []

    class Service:
        def _ensure_running(self):
            return None

        def record_dogfood(self, operation, outcome, **facts):
            calls.append((operation, outcome, facts))

    controller = SessionController(Service(), session_capture=lambda clean: clean)
    controller._manifest = SimpleNamespace(active_view_id="private-view-id")
    controller._views = {
        "private-view-id": SimpleNamespace(document_id="private-document-id")
    }
    controller._restore_manifest_focus = lambda: None
    controller._repair_pointer_after_usable_restore = lambda: None
    restored = object()
    controller._run_restore = lambda *_args, **_kwargs: restored

    assert controller.restore_active() is restored
    controller._run_restore = lambda *_args, **_kwargs: (_ for _ in ()).throw(
        RuntimeError("private restore failure")
    )
    controller._record_restore_failure = lambda _document_id: None
    assert controller.restore_active() is None

    restore_calls = [call for call in calls if call[0] is Operation.SESSION_RESTORE]
    assert [call[1] for call in restore_calls] == [Outcome.SUCCESS, Outcome.FAILED]
    for call in restore_calls:
        assert set(call[2]) == {"elapsed_ms"}
        assert "private-view-id" not in repr(call)
        assert "private-document-id" not in repr(call)
        assert "private restore failure" not in repr(call)
