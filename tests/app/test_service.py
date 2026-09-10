from __future__ import annotations

import gc
import hashlib
import os
import threading
import time
import weakref
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from uniti.app.recovery_manager import (
    RecoveryCandidate,
    RecoveryDiagnostic,
    RecoveryHealth,
)
from uniti.app.dogfood import (
    CPUClass,
    RAMClass,
    DogfoodRecorder,
    HostFacts,
    Operation,
    OSFamily,
    Outcome,
)
from uniti.app.dogfood_store import ClearReport, DogfoodStore, StoreStatus
from uniti.app.session import MAX_WINDOWS, DockReturnRecord, SessionProblem
from uniti.app.service import QuitChoice, QuitDecision, UNITIService
from uniti.core.file_identity import FileIdentity, FileMatch
from uniti.core.history import HistorySnapshot
from uniti.core.recovery import RecoveryLoadStatus, RecoverySession
from uniti.core.document import Document
from uniti.core.durability import DurabilityLevel, DurabilityResult
from uniti.resources import ResourceManager, TaskKind, WorkPriority
from uniti.ui.recovery_center import RecoveryAction, RecoveryDecision, RecoveryEntryKind


class RecordingSessionStore:
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = events if events is not None else []
        self.publications: list[object] = []
        self.discarded: list[str] = []
        self.last_durability: DurabilityResult | None = None

    def publish(self, snapshot: object) -> object:
        self.events.append(("publish", snapshot))
        self.publications.append(snapshot)
        return snapshot

    def discard(self, document_id: str) -> None:
        self.events.append(("discard", document_id))
        self.discarded.append(document_id)


class RecordingRecoveryManager:
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = events if events is not None else []
        self.detached: list[tuple[Document, bool]] = []
        self.attached: list[Document] = []
        self.shutdown_count = 0

    def attach(self, document: Document) -> None:
        self.events.append(("attach", document.path.name))
        self.attached.append(document)

    def detach(self, document: Document, *, clean: bool) -> None:
        self.events.append(("detach", document.path.name, clean))
        self.detached.append((document, clean))

    def shutdown(self) -> None:
        self.events.append("recovery-shutdown")
        self.shutdown_count += 1

    def diagnostics(self) -> tuple[RecoveryDiagnostic, ...]:
        return ()


class RecordingResources:
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = events if events is not None else []
        self.shutdown_count = 0

    def shutdown(self, *, wait: bool = True) -> None:
        self.events.append(("resources-shutdown", wait))
        self.shutdown_count += 1


class RecordingDogfoodStore:
    def __init__(self, *, fail_publish: bool = False) -> None:
        self.fail_publish = fail_publish
        self.publications: list[object] = []
        self.exports: list[Path] = []
        self.clear_count = 0
        self.worker_threads: list[int] = []

    def publish(self, snapshot: object) -> object:
        self.worker_threads.append(threading.get_ident())
        self.publications.append(snapshot)
        if self.fail_publish:
            raise RuntimeError("private dogfood write failure")
        return snapshot

    def export(self, destination: Path) -> Path:
        self.worker_threads.append(threading.get_ident())
        selected = Path(destination)
        self.exports.append(selected)
        return selected

    def clear(self) -> ClearReport:
        self.worker_threads.append(threading.get_ident())
        self.clear_count += 1
        return ClearReport((), 0, ())

    def status(self) -> StoreStatus:
        return StoreStatus(True, len(self.publications), 0, None, None, None)


DOGFOOD_HOST = HostFacts(
    "v0.001a21",
    OSFamily.MACOS,
    CPUClass.C5_8,
    RAMClass.GIB_16_31,
)


class FakeView:
    def __init__(self, view_id: str, document: Document) -> None:
        self.view_id = view_id
        self.document = document


class FakeWindow:
    def __init__(
        self,
        *views: FakeView,
        events: list[object] | None = None,
        name: str = "window",
    ) -> None:
        self.view_ids = tuple(view.view_id for view in views)
        self._views = {view.view_id: view for view in views}
        self.events = events if events is not None else []
        self.name = name
        self.close_count = 0

    def view_for_id(self, view_id: str):
        return self._views.get(view_id)

    def close_for_service(self) -> None:
        self.events.append(("close-window", self.name))
        self.close_count += 1


def _document(tmp_path: Path, name: str = "doc.txt") -> Document:
    path = tmp_path / name
    path.write_text("abc", encoding="utf-8")
    return Document.open(path)


def _service(
    *,
    resources=None,
    sessions=None,
    recovery=None,
    capture=lambda clean_shutdown: ("snapshot", clean_shutdown),
    dogfood_recorder=None,
    dogfood_store=None,
) -> UNITIService:
    return UNITIService(
        resource_manager=resources or RecordingResources(),
        settings_store=object(),
        session_store=sessions or RecordingSessionStore(),
        recovery_manager=recovery or RecordingRecoveryManager(),
        session_capture=capture,
        dogfood_recorder=dogfood_recorder,
        dogfood_store=dogfood_store,
    )


def _desktop_service(tmp_path: Path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import SettingsStore

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(True)
    recovery = RecordingRecoveryManager()
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=RecordingSessionStore(),
        recovery_manager=recovery,
        session_capture=lambda clean: ("snapshot", clean),
    )
    return app, service, recovery


def _stop_desktop_service(app, service: UNITIService) -> None:
    if service.is_running:
        service.request_quit(lambda _entry: QuitChoice.DISCARD)
    app.processEvents()


def test_quit_prompts_once_per_modified_document_shared_by_views(tmp_path: Path):
    document = _document(tmp_path)
    service = _service()
    entry = service.documents.adopt(document)
    service.documents.bind_view(entry.document_id, "view-a")
    service.documents.bind_view(entry.document_id, "view-b")
    service.register_window(
        "window-a",
        FakeWindow(FakeView("view-a", document), FakeView("view-b", document)),
    )
    document.insert(0, "X")
    prompted: list[str] = []

    plan = service.build_quit_plan(
        lambda item: prompted.append(item.document_id) or QuitChoice.SAVE
    )

    assert prompted == [entry.document_id]
    assert plan is not None
    assert plan.decisions == (QuitDecision(entry.document_id, QuitChoice.SAVE),)
    service.documents.close_all()


def test_quit_prompt_order_is_window_then_view_order_with_registry_fallback(
    tmp_path: Path,
):
    service = _service()
    first = _document(tmp_path, "first.txt")
    second = _document(tmp_path, "second.txt")
    third = _document(tmp_path, "third.txt")
    first_entry = service.documents.adopt(first)
    second_entry = service.documents.adopt(second)
    third_entry = service.documents.adopt(third)
    service.documents.bind_view(first_entry.document_id, "view-a")
    service.documents.bind_view(second_entry.document_id, "view-b")
    for document in (first, second, third):
        document.insert(0, "X")
    service.register_window(
        "window-a",
        FakeWindow(FakeView("view-b", second), FakeView("view-a", first)),
    )
    prompted: list[str] = []

    service.build_quit_plan(
        lambda item: prompted.append(item.document_id) or QuitChoice.DISCARD
    )

    assert prompted == [
        second_entry.document_id,
        first_entry.document_id,
        third_entry.document_id,
    ]
    service.documents.close_all()


def test_cancel_collects_every_choice_without_partial_quit_effects(tmp_path: Path):
    events: list[object] = []
    sessions = RecordingSessionStore(events)
    recovery = RecordingRecoveryManager(events)
    resources = RecordingResources(events)
    service = _service(
        sessions=sessions,
        recovery=recovery,
        resources=resources,
        capture=lambda clean_shutdown: events.append(("capture", clean_shutdown)),
    )
    first = _document(tmp_path, "first.txt")
    second = _document(tmp_path, "second.txt")
    first_entry = service.documents.adopt(first)
    second_entry = service.documents.adopt(second)
    service.documents.bind_view(first_entry.document_id, "view-a")
    service.documents.bind_view(second_entry.document_id, "view-b")
    window = FakeWindow(
        FakeView("view-a", first),
        FakeView("view-b", second),
        events=events,
    )
    service.register_window("window-a", window)
    first.insert(0, "X")
    second.insert(0, "Y")
    choices = iter((QuitChoice.SAVE, QuitChoice.CANCEL))
    prompted: list[str] = []

    result = service.request_quit(
        lambda item: prompted.append(item.document_id) or next(choices)
    )

    assert result is False
    assert prompted == [first_entry.document_id, second_entry.document_id]
    assert first.modified is True
    assert second.modified is True
    assert first.path.read_text(encoding="utf-8") == "abc"
    assert second.path.read_text(encoding="utf-8") == "abc"
    assert first_entry.view_ids == ("view-a",)
    assert second_entry.view_ids == ("view-b",)
    assert window.close_count == 0
    assert sessions.publications == []
    assert sessions.discarded == []
    assert recovery.detached == []
    assert resources.shutdown_count == 0
    assert service.is_running is True
    service.documents.close_all()


def test_successful_quit_saves_then_publishes_before_retiring_and_closing(
    tmp_path: Path,
):
    events: list[object] = []
    sessions = RecordingSessionStore(events)
    recovery = RecordingRecoveryManager(events)
    resources = RecordingResources(events)
    document = _document(tmp_path)

    def capture(clean_shutdown: bool):
        assert document.modified is False
        events.append(("capture", clean_shutdown))
        return ("snapshot", clean_shutdown)

    service = _service(
        sessions=sessions,
        recovery=recovery,
        resources=resources,
        capture=capture,
    )
    entry = service.documents.adopt(document)
    service.documents.bind_view(entry.document_id, "view-a")
    window = FakeWindow(FakeView("view-a", document), events=events)
    service.register_window("window-a", window)
    document.insert(3, "X")

    assert service.request_quit(lambda _item: QuitChoice.SAVE) is True

    assert document.path.read_text(encoding="utf-8") == "abcX"
    assert events == [
        ("capture", True),
        ("publish", ("snapshot", True)),
        ("detach", "doc.txt", True),
        ("close-window", "window"),
        "recovery-shutdown",
        ("resources-shutdown", True),
    ]
    assert service.window_count == 0
    assert service.documents.count == 0
    assert service.is_running is False


def test_final_session_publication_runs_off_the_calling_thread():
    caller_thread = threading.get_ident()

    class ThreadRecordingStore(RecordingSessionStore):
        def __init__(self) -> None:
            super().__init__()
            self.publisher_threads: list[int] = []

        def publish(self, snapshot: object) -> object:
            self.publisher_threads.append(threading.get_ident())
            return super().publish(snapshot)

    sessions = ThreadRecordingStore()
    service = _service(
        resources=ResourceManager(max_workers=1),
        sessions=sessions,
    )

    assert service.request_quit(lambda _item: QuitChoice.DISCARD) is True
    assert len(sessions.publisher_threads) == 1
    assert sessions.publisher_threads[0] != caller_thread


def test_quit_releases_primary_instance_lease_before_application_exit():
    events: list[object] = []

    class Instance:
        def close(self):
            events.append("instance-close")

    service = UNITIService(
        resource_manager=RecordingResources(events),
        settings_store=object(),
        session_store=RecordingSessionStore(events),
        recovery_manager=RecordingRecoveryManager(events),
        session_capture=lambda clean: ("snapshot", clean),
        instance_service=Instance(),
    )

    assert service.request_quit(lambda _item: QuitChoice.DISCARD) is True
    assert events[-3:] == [
        "recovery-shutdown",
        ("resources-shutdown", True),
        "instance-close",
    ]


def test_last_window_can_close_while_service_remains_running():
    service = _service()
    window = FakeWindow()
    service.register_window("window-a", window)

    assert service.unregister_window("window-a") is window

    assert service.window_count == 0
    assert service.active_view is None
    assert service.is_running is True


def test_removed_document_releases_session_tracking_while_service_keeps_running(
    tmp_path: Path,
):
    service = _service()
    document = _document(tmp_path)
    document_reference = weakref.ref(document)
    entry = service.documents.adopt(document)
    service.track_document(entry, hash_saved=False)

    service.documents.close_all()
    del entry
    del document
    gc.collect()

    assert document_reference() is None
    assert service.is_running is True
    assert service.request_quit(lambda _entry: QuitChoice.DISCARD) is True


def test_last_window_close_keeps_one_service_dogfood_recorder_active():
    recorder = DogfoodRecorder(DOGFOOD_HOST, day=date(2026, 9, 5))
    store = RecordingDogfoodStore()
    service = _service(dogfood_recorder=recorder, dogfood_store=store)
    first = FakeWindow(name="first")
    second = FakeWindow(name="second")

    service.register_window("window-a", first)
    service.register_window("window-b", second)
    service.unregister_window("window-a")
    service.unregister_window("window-b")

    assert service.window_count == 0
    assert service.dogfood_recorder is recorder
    assert service.dogfood_store is store
    assert service.dogfood_is_active is True
    service.shutdown_dogfood()


def test_quit_requests_final_low_priority_dogfood_publish_and_ignores_failure():
    caller_thread = threading.get_ident()
    resources = ResourceManager(max_workers=1)
    submitted = []
    original_submit = resources.tasks.submit

    def submit(spec, work):
        submitted.append(spec)
        return original_submit(spec, work)

    resources.tasks.submit = submit
    store = RecordingDogfoodStore(fail_publish=True)
    recorder = DogfoodRecorder(DOGFOOD_HOST, day=date(2026, 9, 5))
    service = _service(
        resources=resources,
        dogfood_recorder=recorder,
        dogfood_store=store,
    )

    assert service.request_quit(lambda _item: QuitChoice.DISCARD) is True

    dogfood_specs = [
        spec
        for spec in submitted
        if spec.kind is TaskKind.CAPTURE_REPORT and not spec.foreground
    ]
    assert len(dogfood_specs) == 1
    assert dogfood_specs[0].priority is WorkPriority.PREFETCH
    assert len(store.publications) == 1
    assert store.worker_threads == [store.worker_threads[0]]
    assert store.worker_threads[0] != caller_thread
    assert service.is_running is False


def test_export_and_clear_dogfood_evidence_use_workers(tmp_path: Path):
    caller_thread = threading.get_ident()
    resources = ResourceManager(max_workers=1)
    store = RecordingDogfoodStore()
    recorder = DogfoodRecorder(DOGFOOD_HOST, day=date(2026, 9, 5))
    service = _service(
        resources=resources,
        dogfood_recorder=recorder,
        dogfood_store=store,
    )
    destination = tmp_path / "dogfood-export.json"

    exported = service.export_dogfood_evidence(destination)
    cleared = service.clear_dogfood_evidence()

    assert exported.future.result(timeout=5) == destination
    assert cleared.future.result(timeout=5) == ClearReport((), 0, ())
    assert store.exports == [destination]
    assert store.clear_count == 1
    assert store.worker_threads
    assert set(store.worker_threads) == {store.worker_threads[0]}
    assert store.worker_threads[0] != caller_thread
    service.request_quit(lambda _item: QuitChoice.DISCARD)


def test_service_merges_same_day_evidence_published_before_process_restart(
    tmp_path: Path,
):
    today = date.today()
    store = DogfoodStore(tmp_path / "dogfood")
    first = DogfoodRecorder(DOGFOOD_HOST, day=today)
    first.observe(Operation.EDIT_TRANSACTION, Outcome.SUCCESS)
    assert store.publish(first.snapshot()).published is True
    recorder = DogfoodRecorder(DOGFOOD_HOST, day=today)
    recorder.observe(Operation.EDIT_TRANSACTION, Outcome.SUCCESS)
    resources = ResourceManager(max_workers=1)
    service = _service(
        resources=resources,
        dogfood_recorder=recorder,
        dogfood_store=store,
    )

    first_handle = service.schedule_dogfood_publication()
    assert first_handle is not None
    first_handle.future.result(timeout=5)
    publish_handle = service.schedule_dogfood_publication()
    assert publish_handle is not None
    publish_handle.future.result(timeout=5)

    current = store.load_segments()[-1]
    assert current.for_operation(Operation.EDIT_TRANSACTION).count == 2
    service.shutdown_dogfood()
    resources.shutdown()


def test_service_publication_rolls_long_running_process_to_local_day(tmp_path: Path):
    today = date.today()
    yesterday = today - timedelta(days=1)
    store = DogfoodStore(tmp_path / "dogfood")
    recorder = DogfoodRecorder(DOGFOOD_HOST, day=yesterday)
    recorder.observe(Operation.EDIT_TRANSACTION, Outcome.SUCCESS)
    resources = ResourceManager(max_workers=1)
    service = _service(
        resources=resources,
        dogfood_recorder=recorder,
        dogfood_store=store,
    )

    first_handle = service.schedule_dogfood_publication()
    assert first_handle is not None
    first_handle.future.result(timeout=5)
    publish_handle = service.schedule_dogfood_publication()
    assert publish_handle is not None
    publish_handle.future.result(timeout=5)

    segments = store.load_segments()
    assert tuple(snapshot.day for snapshot in segments) == (yesterday, today)
    assert segments[0].for_operation(Operation.EDIT_TRANSACTION).count == 1
    assert segments[1].for_operation(Operation.EDIT_TRANSACTION).count == 0
    service.shutdown_dogfood()
    resources.shutdown()


def test_clear_dogfood_evidence_resets_process_counters(tmp_path: Path):
    today = date.today()
    store = DogfoodStore(tmp_path / "dogfood")
    recorder = DogfoodRecorder(DOGFOOD_HOST, day=today)
    recorder.observe(Operation.SAVE, Outcome.SUCCESS)
    resources = ResourceManager(max_workers=1)
    service = _service(
        resources=resources,
        dogfood_recorder=recorder,
        dogfood_store=store,
    )

    handle = service.clear_dogfood_evidence()
    handle.future.result(timeout=5)

    assert recorder.snapshot().for_operation(Operation.SAVE).count == 0
    assert store.load_segments() == ()
    service.shutdown_dogfood()
    resources.shutdown()


def test_active_view_routes_across_registered_windows(tmp_path: Path):
    first = _document(tmp_path, "first.txt")
    second = _document(tmp_path, "second.txt")
    service = _service()
    first_view = FakeView("view-a", first)
    second_view = FakeView("view-b", second)
    service.register_window("window-a", FakeWindow(first_view))
    service.register_window("window-b", FakeWindow(second_view))

    service.set_active_view("window-b", "view-b")

    assert service.active_view is second_view
    service.documents.close_all()


def test_find_replace_document_provider_lists_every_adopted_document(
    tmp_path: Path,
):
    app, service, _recovery = _desktop_service(tmp_path)
    try:
        first = _document(tmp_path, "first.txt")
        second = _document(tmp_path, "second.txt")
        service.documents.adopt(first)
        service.documents.adopt(second)

        provided = list(service.find_replace._document_provider())

        assert set(provided) == {first, second}
    finally:
        _stop_desktop_service(app, service)


def test_document_group_assignment_updates_registry_and_tab_icon(tmp_path: Path):
    from uniti.app.document_groups import DocumentGroup

    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "grouped.txt"
    path.write_text("abc", encoding="utf-8")
    window = service.new_window()
    try:
        view = window.open_path(path)
        assert view is not None
        window._groups = (DocumentGroup("A", "A", "#e06c75"),)
        entry = service.documents.entry_for_view(view.view_id)
        leaf = window.panes.leaf_for_view(view.view_id)
        index = leaf.index_of(view.view_id)

        window._set_document_group(entry.document_id, "A")

        assert entry.group_id == "A"
        assert not leaf.tabs.tabIcon(index).isNull()

        window._set_document_group(entry.document_id, None)

        assert entry.group_id is None
        assert leaf.tabs.tabIcon(index).isNull()
    finally:
        for _window_id, open_window in service.windows.items:
            open_window.close_all_documents(force=True)
            open_window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_group_menu_lists_groups_and_marks_the_assigned_one(
    tmp_path: Path, monkeypatch
):
    from PySide6.QtCore import QPoint
    from PySide6.QtWidgets import QMenu

    from uniti.app.document_groups import DocumentGroup

    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "menu.txt"
    path.write_text("abc", encoding="utf-8")
    window = service.new_window()
    captured: list[QMenu] = []
    monkeypatch.setattr(QMenu, "popup", lambda self, *a, **k: captured.append(self))
    try:
        view = window.open_path(path)
        window._groups = (
            DocumentGroup("A", "A", "#e06c75"),
            DocumentGroup("B", "B", "#61afef"),
        )
        entry = service.documents.entry_for_view(view.view_id)
        service.documents.set_group(entry.document_id, "B")

        window._show_group_menu(view.view_id, QPoint(10, 10))

        assert len(captured) == 1
        menu = captured[0]
        labels = [
            action.text() for action in menu.actions() if not action.isSeparator()
        ]
        assert labels == ["No Group", "A", "B", "Manage Groups…"]
        checked = {
            action.text(): action.isChecked()
            for action in menu.actions()
            if action.isCheckable()
        }
        assert checked == {"No Group": False, "A": False, "B": True}
    finally:
        for _window_id, open_window in service.windows.items:
            open_window.close_all_documents(force=True)
            open_window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_manage_groups_dialog_persists_and_clears_removed_group_assignment(
    tmp_path: Path, monkeypatch
):
    from uniti.app.document_groups import DocumentGroup

    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "manage.txt"
    path.write_text("abc", encoding="utf-8")
    window = service.new_window()
    try:
        view = window.open_path(path)
        window._groups = (DocumentGroup("A", "A", "#e06c75"),)
        entry = service.documents.entry_for_view(view.view_id)
        service.documents.set_group(entry.document_id, "A")

        class FakeEditor:
            def __init__(self, groups, parent=None) -> None:
                self._groups = groups

            def exec(self) -> bool:
                return True

            def groups(self):
                return ()

        monkeypatch.setattr(
            "uniti.ui.document_group_editor.DocumentGroupEditor", FakeEditor
        )

        window.show_document_group_editor()

        assert window._groups == ()
        assert entry.group_id is None
        assert window._group_store.load() == ()
    finally:
        for _window_id, open_window in service.windows.items:
            open_window.close_all_documents(force=True)
            open_window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_service_owns_one_lazy_find_replace_panel(tmp_path: Path):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    resources = ResourceManager(max_workers=1)
    service = _service(resources=resources)
    first = service.find_replace

    assert service.find_replace is first

    assert service.request_quit(lambda _item: QuitChoice.DISCARD) is True
    app.processEvents()


def test_global_find_replace_attachment_follows_active_window_and_survives_hosts(
    tmp_path: Path,
):
    app, service, _recovery = _desktop_service(tmp_path)
    first = service.new_window()
    second = service.new_window()
    panel = service.find_replace
    try:
        panel.find_input.set_text("needle")
        panel.replace_input.set_text("replacement")
        service.set_active_view(first.window_id, None)
        service.attach_find_replace()
        app.processEvents()

        assert panel.parentWidget() is first
        assert panel.placement == "attached"
        assert first.find_replace is second.find_replace is panel

        service.set_active_view(second.window_id, None)
        app.processEvents()

        assert service.find_replace is panel
        assert panel.parentWidget() is second
        assert panel.placement == "attached"
        assert panel.find_input.text() == "needle"
        assert panel.replace_input.text() == "replacement"

        second.close()
        app.processEvents()

        assert service.window_count == 1
        assert panel.parentWidget() is first
        assert panel.placement == "attached"

        first.close()
        app.processEvents()

        assert service.window_count == 1
        assert first.isVisible()
        assert panel.parentWidget() is first
        assert panel.placement == "attached"

        replacement_host = service.new_window()
        service.set_active_view(replacement_host.window_id, None)
        app.processEvents()
        assert panel.parentWidget() is replacement_host
        assert panel.placement == "attached"
    finally:
        _stop_desktop_service(app, service)


def test_detached_global_find_replace_stays_put_and_new_window_does_not_hide_it(
    tmp_path: Path,
):
    app, service, _recovery = _desktop_service(tmp_path)
    first = service.new_window()
    first.show()
    panel = service.find_replace
    try:
        service.set_active_view(first.window_id, None)
        toggle = first._command_actions["find.toggle_attachment"]
        toggle.trigger()
        assert panel.placement == "attached"
        toggle.trigger()
        assert panel.placement == "detached"
        panel.show()
        app.processEvents()
        detached_parent = panel.parentWidget()

        second = service.new_window()
        second.show()
        service.set_active_view(second.window_id, None)
        app.processEvents()

        assert service.find_replace is panel
        assert panel.placement == "detached"
        assert panel.parentWidget() is detached_parent
        assert panel.isVisible() is True
    finally:
        _stop_desktop_service(app, service)


class BlockingSessionStore(RecordingSessionStore):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def publish(self, snapshot: object) -> object:
        if not self.publications:
            self.started.set()
            assert self.release.wait(timeout=5)
        return super().publish(snapshot)


def test_publication_scheduler_keeps_active_and_only_latest_pending_snapshot():
    resources = ResourceManager(max_workers=1)
    sessions = BlockingSessionStore()
    captures = iter(("first", "superseded", "latest", "final"))
    service = _service(
        resources=resources,
        sessions=sessions,
        capture=lambda _clean: next(captures),
    )

    service.schedule_publication()
    assert sessions.started.wait(timeout=5)
    service.schedule_publication()
    service.schedule_publication()
    sessions.release.set()
    deadline = time.monotonic() + 5
    while len(sessions.publications) < 2 and time.monotonic() < deadline:
        time.sleep(0.01)

    assert sessions.publications == ["first", "latest"]
    assert service.request_quit(lambda _item: QuitChoice.DISCARD) is True


@pytest.mark.parametrize("queued_publication", [False, True])
def test_quit_completes_with_background_session_publication_paused(
    queued_publication: bool,
):
    resources = ResourceManager(max_workers=1)
    sessions = RecordingSessionStore()
    service = _service(
        resources=resources,
        sessions=sessions,
        capture=lambda clean: ("snapshot", clean),
    )
    resources.pause_background(True)
    if queued_publication:
        service.schedule_publication()
    finished = threading.Event()
    results = []

    def quit_service():
        try:
            results.append(service.request_quit(lambda _item: QuitChoice.DISCARD))
        finally:
            finished.set()

    thread = threading.Thread(target=quit_service, daemon=True)
    thread.start()
    try:
        assert finished.wait(2), "Quit waited indefinitely for paused session work"
        assert results == [True]
        assert sessions.publications == [("snapshot", True)]
        assert not service.is_running
    finally:
        resources.pause_background(False)
        thread.join(timeout=5)
        resources.shutdown()


def test_low_space_publication_warning_remains_until_later_durable_success():
    from uniti.app.session import PersistenceNotice

    class Storage(RecordingSessionStore):
        def publish(self, snapshot):
            super().publish(snapshot)
            truncations = (
                (PersistenceNotice("session", "low_space_history_suppressed"),)
                if len(self.publications) == 1
                else ()
            )
            return type("Result", (), {"truncations": truncations})()

    resources = ResourceManager(max_workers=1)
    sessions = Storage()
    service = _service(
        resources=resources,
        sessions=sessions,
        capture=lambda clean: ("snapshot", clean),
    )

    service.schedule_publication()
    deadline = time.monotonic() + 5
    while not service.recovery_degraded and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.recovery_degraded is True

    service.schedule_publication()
    deadline = time.monotonic() + 5
    while service.recovery_degraded and time.monotonic() < deadline:
        time.sleep(0.01)
    assert service.recovery_degraded is False
    assert service.request_quit(lambda _item: QuitChoice.DISCARD) is True


def test_service_exposes_latest_session_and_recovery_durability():
    session_durability = DurabilityResult(
        "session_publication",
        DurabilityLevel.FILE_SYNCED,
        True,
        True,
        False,
        "directory_sync_unavailable",
    )
    sessions = RecordingSessionStore()
    sessions.last_durability = session_durability

    class ReducedRecovery(RecordingRecoveryManager):
        def diagnostics(self) -> tuple[RecoveryDiagnostic, ...]:
            return (
                RecoveryDiagnostic(
                    document_id="doc-1",
                    health=RecoveryHealth.REDUCED,
                    durability=DurabilityLevel.FILE_SYNCED,
                    durable_revision=2,
                    observed_revision=2,
                    reason="directory sync unavailable",
                ),
            )

    service = _service(sessions=sessions, recovery=ReducedRecovery())

    assert service.session_durability is session_durability
    assert service.recovery_health is RecoveryHealth.REDUCED
    assert service.recovery_durability is DurabilityLevel.FILE_SYNCED

    assert service.request_quit(lambda _item: QuitChoice.DISCARD) is True


def test_one_service_owns_two_windows_one_document_and_one_find_panel(
    tmp_path: Path,
):
    app, service, recovery = _desktop_service(tmp_path)
    path = tmp_path / "shared.txt"
    path.write_text("shared document", encoding="utf-8")
    try:
        first = service.new_window()
        view_a = first.open_path(path)
        assert view_a is not None
        second = service.new_window()
        view_b = second.open_existing_document(view_a.document)

        assert view_a is not view_b
        assert view_a.document is view_b.document
        assert first.find_replace is second.find_replace is service.find_replace
        assert recovery.attached == [view_a.document]

        first.show()
        second.show()
        second.activateWindow()
        view_b.setFocus()
        app.processEvents()

        assert service.active_view is view_b
        assert service.find_replace._current_view() is view_b

        from PySide6.QtCore import QEvent
        from PySide6.QtWidgets import QApplication

        QApplication.sendEvent(first, QEvent(QEvent.Type.WindowActivate))
        assert service.active_view is view_a
        assert service.find_replace._current_view() is view_a

        first.close()
        second.close()
        app.processEvents()

        assert service.window_count == 1
        assert service.most_recent_window is second
        assert second.isVisible()
        assert second.views == ()
        assert service.is_running is True
        assert app.quitOnLastWindowClosed() is False
    finally:
        _stop_desktop_service(app, service)


def test_last_window_close_keeps_open_available_and_explicit_quit_exits(
    tmp_path: Path,
    monkeypatch,
):
    from PySide6.QtWidgets import QFileDialog

    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "reopen.txt"
    path.write_text("still available", encoding="utf-8")
    window = service.new_window()
    try:
        window.show()
        assert window.open_path(path) is not None
        window.close()
        app.processEvents()

        assert window.isVisible()
        assert window.views == ()
        assert service.most_recent_window is window
        assert service.is_running

        monkeypatch.setattr(
            QFileDialog,
            "getOpenFileName",
            lambda *_args, **_kwargs: (str(path), ""),
        )
        window._command_actions["file.open"].trigger()
        assert window.current_view is not None
        assert window.current_view.document.read(0, 15) == "still available"

        window._command_actions["file.quit"].trigger()
        assert not service.is_running
        assert service.window_count == 0
    finally:
        _stop_desktop_service(app, service)


def test_failed_quit_then_window_close_retains_a_usable_window(
    tmp_path: Path,
    monkeypatch,
):
    app, service, _recovery = _desktop_service(tmp_path)
    window = service.new_window()
    publish = service.sessions.publish

    def fail_final(snapshot):
        if snapshot == ("snapshot", True):
            raise OSError("injected session write failure")
        return publish(snapshot)

    try:
        window.show()
        service.schedule_publication()
        monkeypatch.setattr(service.sessions, "publish", fail_final)
        assert not window.request_quit()
        assert service.last_quit_error is not None

        window.close()
        app.processEvents()
        assert window.isVisible()
        assert service.most_recent_window is window
        path = tmp_path / "after-failure.txt"
        path.write_text("preserved", encoding="utf-8")
        assert window.open_path(path) is not None

        monkeypatch.setattr(service.sessions, "publish", publish)
        assert window.request_quit()
        assert not service.is_running
    finally:
        monkeypatch.setattr(service.sessions, "publish", publish)
        _stop_desktop_service(app, service)


def test_duplicate_open_splits_and_moves_keep_one_document_authority(
    tmp_path: Path,
):
    from PySide6.QtCore import QPoint

    app, service, recovery = _desktop_service(tmp_path)
    path = tmp_path / "split.txt"
    path.write_text("split me", encoding="utf-8")
    try:
        window = service.new_window()
        original = window.open_path(path)
        assert original is not None

        assert window.open_path(path) is original
        assert service.window_count == 1
        assert window.view_ids == (original.view_id,)

        right = window.split_right()
        assert right is not None
        down = window.split_down()
        assert down is not None
        assert right.document is original.document
        assert down.document is original.document
        assert window.panes.leaf_count == 3

        assert window.close_current_split() is True
        assert window.view_for_id(down.view_id) is None
        assert window.panes.leaf_count == 2
        down = window.split_down()
        assert down is not None

        moved = window.move_current_to_new_window()
        assert moved is not None
        assert moved.current_view is down
        assert window.view_for_id(down.view_id) is None
        assert len(service.documents.entries[0].view_ids) == 3

        window.panes.detach_view(right.view_id, QPoint(20, 30))
        app.processEvents()
        detached = service.most_recent_window
        assert detached is not None
        assert detached is not window and detached is not moved
        assert detached.current_view is right
        assert service.window_count == 3
        assert recovery.attached == [original.document]
    finally:
        for _window_id, open_window in service.windows.items:
            open_window.close_all_documents(force=True)
            open_window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_undock_records_exact_source_and_dock_returns_there(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    first_path = tmp_path / "first-tab.txt"
    second_path = tmp_path / "second-tab.txt"
    first_path.write_text("first", encoding="utf-8")
    second_path.write_text("second", encoding="utf-8")
    source = service.new_window()
    first = source.open_path(first_path)
    second = source.open_path(second_path)
    assert first is not None and second is not None
    before = source.view_location(first.view_id)
    entry = service.documents.entry_for_view(first.view_id)
    try:
        detached = service.undock_view(first.view_id)

        assert first.dock_return == DockReturnRecord(
            source.window_id,
            before.pane_id,
            before.tab_index,
        )
        assert detached.current_view is first
        assert detached.panes.first_leaf.controls.dock_button.accessibleName() == (
            "Dock Document"
        )

        returned = service.dock_view(first.view_id)

        assert returned is source
        assert source.view_location(first.view_id) == before
        assert first.dock_return is None
        assert detached not in service.windows.windows
        assert service.documents.entry_for_view(first.view_id) is entry
    finally:
        for _window_id, open_window in service.windows.items:
            open_window.close_all_documents(force=True)
            open_window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_dock_falls_back_from_missing_pane_then_missing_window(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "fallback.txt"
    path.write_text("fallback", encoding="utf-8")
    source = service.new_window()
    first = source.open_path(path)
    assert first is not None
    clone = source.split_right()
    assert clone is not None
    original_pane_id = source.view_location(clone.view_id).pane_id
    try:
        detached = service.undock_view(clone.view_id)
        assert source.panes.close_leaf(original_pane_id)

        service.dock_view(clone.view_id)

        assert source.view_location(clone.view_id).pane_id == source.panes.active_leaf.pane_id
        detached = service.undock_view(clone.view_id)
        other = service.new_window()
        source.close()
        app.processEvents()
        service.set_active_view(other.window_id, None)

        service.dock_view(clone.view_id)

        assert other.view_for_id(clone.view_id) is clone
        assert detached not in service.windows.windows
        assert clone.dock_return is None
    finally:
        for _window_id, open_window in service.windows.items:
            open_window.close_all_documents(force=True)
            open_window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_dock_clamps_stale_tab_index_to_the_live_pane_end(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    first_path = tmp_path / "stale-first.txt"
    second_path = tmp_path / "stale-second.txt"
    first_path.write_text("first", encoding="utf-8")
    second_path.write_text("second", encoding="utf-8")
    source = service.new_window()
    first = source.open_path(first_path)
    second = source.open_path(second_path)
    assert first is not None and second is not None
    try:
        service.undock_view(first.view_id)
        anchor = first.dock_return
        assert anchor is not None
        first.set_dock_return(
            DockReturnRecord(anchor.window_id, anchor.pane_id, 200)
        )

        service.dock_view(first.view_id)

        assert source.view_location(first.view_id).tab_index == 1
    finally:
        for _window_id, open_window in service.windows.items:
            open_window.close_all_documents(force=True)
            open_window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_dock_creates_a_window_when_no_other_destination_survives(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "new-fallback.txt"
    path.write_text("fallback", encoding="utf-8")
    source = service.new_window()
    view = source.open_path(path)
    assert view is not None
    detached = service.undock_view(view.view_id)
    source.close()
    app.processEvents()
    try:
        returned = service.dock_view(view.view_id)

        assert returned is not detached
        assert returned.view_for_id(view.view_id) is view
        assert service.window_count == 1
        assert view.dock_return is None
    finally:
        for _window_id, open_window in service.windows.items:
            open_window.close_all_documents(force=True)
            open_window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_failed_destination_acceptance_rolls_back_exactly(
    tmp_path: Path,
    monkeypatch,
):
    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "rollback.txt"
    path.write_text("rollback", encoding="utf-8")
    source = service.new_window()
    view = source.open_path(path)
    assert view is not None
    source.open_existing_document(view.document)
    before = source.view_location(view.view_id)
    target = service.new_window()
    entry = service.documents.entry_for_view(view.view_id)
    monkeypatch.setattr(
        target,
        "accept_transferred_view",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("refused")),
    )
    try:
        with pytest.raises(RuntimeError, match="refused"):
            service._transfer_view(view.view_id, target.window_id)

        assert source.view_location(view.view_id) == before
        assert view.dock_return is None
        assert service.documents.entry_for_view(view.view_id) is entry
    finally:
        monkeypatch.undo()
        for _window_id, open_window in service.windows.items:
            open_window.close_all_documents(force=True)
            open_window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_all_ui_detach_paths_route_to_one_service_operation(
    tmp_path: Path,
    monkeypatch,
):
    from PySide6.QtCore import QPoint

    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "routes.txt"
    path.write_text("routes", encoding="utf-8")
    window = service.new_window()
    view = window.open_path(path)
    assert view is not None
    calls: list[str] = []
    monkeypatch.setattr(service, "undock_view", calls.append)
    try:
        window.move_current_to_new_window()
        window.panes.detach_view(view.view_id, QPoint(20, 30))
        window.panes.first_leaf.controls.dock_button.click()

        assert calls == [view.view_id, view.view_id, view.view_id]
    finally:
        monkeypatch.undo()
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_window_limit_rejects_undock_before_source_removal(tmp_path: Path):
    from uniti.app.window_manager import ViewLocation

    class TransferView:
        view_id = "view-a"
        dock_return = None

        def set_dock_return(self, record):
            self.dock_return = record

    class TransferSource(FakeWindow):
        def __init__(self):
            self.window_id = "window-source"
            self.view = TransferView()
            self.view_ids = (self.view.view_id,)
            self.take_count = 0

        def view_for_id(self, view_id: str):
            return self.view if view_id == self.view.view_id else None

        def view_location(self, view_id: str):
            if view_id != self.view.view_id:
                raise KeyError(view_id)
            return ViewLocation(self.window_id, "pane-a", 0)

        def take_view_for_transfer(self, view_id: str):
            self.take_count += 1
            return self.view

    service = _service()
    source = TransferSource()
    service.register_window(source.window_id, source)
    for index in range(MAX_WINDOWS - 1):
        service.register_window(f"window-{index}", FakeWindow())

    with pytest.raises(ValueError, match="32 windows"):
        service.undock_view(source.view.view_id)

    assert source.take_count == 0
    assert source.view_ids == (source.view.view_id,)
    service.windows.clear()


def test_shared_view_closes_without_prompt_then_final_view_offers_save_cancel(
    tmp_path: Path,
    monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox

    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "choices.txt"
    path.write_text("body", encoding="utf-8")
    first = service.new_window()
    first_view = first.open_path(path)
    assert first_view is not None
    second = service.new_window()
    final_view = second.open_existing_document(first_view.document)
    final_view.state.move_document_end()
    final_view.state.insert_text(" changed")
    document = final_view.document
    try:
        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("a non-final shared view must not prompt")
            ),
        )
        assert first.close_current() is True
        assert document.read(0, document.total_chars()) == "body changed"
        assert service.documents.entries[0].view_ids == (final_view.view_id,)

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
        )
        assert second.close_current() is False
        assert second.current_view is final_view
        assert document.modified is True

        monkeypatch.setattr(
            QMessageBox,
            "warning",
            lambda *_args, **_kwargs: QMessageBox.StandardButton.Save,
        )
        assert second.close_current() is True
        assert path.read_text(encoding="utf-8") == "body changed"
        assert service.documents.entries[0].view_ids == ()
        assert document.read(0, 4) == "body"
    finally:
        first.close()
        second.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_discarding_the_final_view_retires_unsaved_document_and_recovery(
    tmp_path: Path,
    monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox

    app, service, recovery = _desktop_service(tmp_path)
    path = tmp_path / "discard.txt"
    path.write_text("disk", encoding="utf-8")
    window = service.new_window()
    view = window.open_path(path)
    assert view is not None
    document = view.document
    view.state.insert_text("local ")
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Discard,
    )
    try:
        assert window.close_current() is True
        assert service.documents.count == 0
        assert recovery.detached[-1] == (document, True)
        with pytest.raises(ValueError, match="closed"):
            document.read(0, 1)
        assert path.read_text(encoding="utf-8") == "disk"
    finally:
        window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_window_close_cancel_preserves_every_view_and_service_binding(
    tmp_path: Path,
    monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox

    app, service, _recovery = _desktop_service(tmp_path)
    dirty_path = tmp_path / "dirty.txt"
    clean_path = tmp_path / "clean.txt"
    dirty_path.write_text("dirty", encoding="utf-8")
    clean_path.write_text("clean", encoding="utf-8")
    window = service.new_window()
    dirty = window.open_path(dirty_path)
    clean = window.open_path(clean_path)
    assert dirty is not None and clean is not None
    dirty.state.insert_text("local ")
    before = window.view_ids
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *_args, **_kwargs: QMessageBox.StandardButton.Cancel,
    )
    try:
        window.show()
        assert window.close() is False
        app.processEvents()

        assert window.view_ids == before
        assert service.window_count == 1
        assert service.documents.entry_for_view(dirty.view_id) is not None
        assert service.documents.entry_for_view(clean.view_id) is not None
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()
        _stop_desktop_service(app, service)


def test_window_close_preserves_live_tabs_while_session_restore_is_pending(
    tmp_path: Path,
    monkeypatch,
):
    from PySide6.QtWidgets import QMessageBox
    from uniti.app.session import PaneRecord, WindowRecord

    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "live.txt"
    path.write_text("live", encoding="utf-8")
    record = WindowRecord(
        "pending-window",
        (30, 40, 700, 500),
        "normal",
        PaneRecord(
            "leaf",
            "pending-pane",
            view_ids=("pending-view",),
            selected_view_id="pending-view",
        ),
    )
    window = service.new_window(record)
    live = window.open_path(path)
    assert live is not None
    before = window.view_ids
    notices = []
    monkeypatch.setattr(
        QMessageBox,
        "information",
        lambda *_args: notices.append(True),
    )
    try:
        window.show()
        assert not window.close()
        assert window.view_ids == before
        assert window.view_for_id(live.view_id) is live
        assert window.isVisible()
        assert notices == [True]

        # Explicit Quit can still preserve the session and stop the service.
        assert window.request_quit()
        assert not service.is_running
    finally:
        _stop_desktop_service(app, service)


def test_new_window_restores_a_bounded_shell_and_quit_action_routes_to_service(
    tmp_path: Path,
    monkeypatch,
):
    from uniti.app.session import PaneRecord, WindowRecord

    app, service, _recovery = _desktop_service(tmp_path)
    record = WindowRecord(
        "restored-window",
        (30, 40, 700, 500),
        "normal",
        PaneRecord(
            "leaf",
            "restored-pane",
            view_ids=("pending-view",),
            selected_view_id="pending-view",
        ),
    )
    window = service.new_window(record)
    calls = []
    monkeypatch.setattr(
        service,
        "request_quit",
        lambda choose: calls.append(choose) or True,
    )
    try:
        assert window.window_id == record.window_id
        assert window.panes.export_state() == record.root
        assert window._tabs is window.panes.active_leaf.tabs

        window._command_actions["file.quit"].trigger()

        assert calls == [window._quit_choice]
    finally:
        monkeypatch.undo()
        _stop_desktop_service(app, service)


def _startup_candidate(
    evidence_path: Path,
    source_path: Path,
    *,
    status: RecoveryLoadStatus = RecoveryLoadStatus.COMPLETE,
    match: FileMatch | None = FileMatch.EXACT_HASH,
    base_hash: str | None = None,
) -> RecoveryCandidate:
    session = SimpleNamespace(source_path=source_path, base_hash=base_hash)
    return RecoveryCandidate(
        evidence_path,
        session,
        load_status=status,
        source_match=match,
        safe_error=None,
    )


class StartupRecoveryManager(RecordingRecoveryManager):
    def __init__(self, events: list[object] | None = None) -> None:
        super().__init__(events)
        self.fail_paths: set[Path] = set()
        self.prepared: list[RecoveryCandidate] = []
        self.committed: list[object] = []
        self.discarded: list[RecoveryCandidate] = []

    def prepare_recovery(self, candidate: RecoveryCandidate):
        self.events.append(("prepare", candidate.evidence_path.name))
        self.prepared.append(candidate)
        if candidate.evidence_path in self.fail_paths:
            raise OSError("private recovery failure details")
        document = Document.open(candidate.session.source_path)
        return SimpleNamespace(
            document=document,
            original=candidate,
            fresh_journal=candidate.evidence_path.with_suffix(".fresh"),
        )

    def commit_recovery(self, recovered: object) -> None:
        self.events.append(("commit", recovered.original.evidence_path.name))
        self.committed.append(recovered)

    def discard(self, candidate: RecoveryCandidate) -> None:
        self.events.append(("discard-recovery", candidate.evidence_path.name))
        self.discarded.append(candidate)


class StartupTarget:
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = events if events is not None else []
        self.opened: list[Document] = []

    def open_existing_document(self, document: Document):
        self.events.append(("open-recovered", document.path.name))
        self.opened.append(document)
        return object()

    def open_path(self, path: Path):
        self.events.append(("open-disk", Path(path).name))
        return object()


def test_recovery_entries_merge_candidates_and_session_problems_stably(tmp_path: Path):
    first_source = tmp_path / "b.txt"
    second_source = tmp_path / "a.txt"
    candidates = (
        _startup_candidate(tmp_path / "z.uniti-recovery", first_source),
        _startup_candidate(
            tmp_path / "a.uniti-recovery",
            second_source,
            status=RecoveryLoadStatus.TRUNCATED_TAIL,
        ),
    )
    problems = (
        SessionProblem(
            "unsupported_manifest",
            tmp_path / "future.json",
            "Session schema is newer or unsupported.",
        ),
    )
    service = _service(capture=None)

    entries = service.recovery_entries(candidates, problems)

    assert tuple(entry.path for entry in entries) == (
        second_source,
        first_source,
        tmp_path / "future.json",
    )
    assert tuple(entry.kind for entry in entries) == (
        RecoveryEntryKind.TRUNCATED,
        RecoveryEntryKind.RECOVERABLE,
        RecoveryEntryKind.UNSUPPORTED,
    )


def test_skip_preserves_corrupt_and_unsupported_evidence(tmp_path: Path):
    recovery_evidence = tmp_path / "broken.uniti-recovery"
    session_evidence = tmp_path / "future.invalid"
    recovery_evidence.write_bytes(b"broken recovery")
    session_evidence.write_bytes(b"future session")
    candidate = RecoveryCandidate(
        recovery_evidence,
        None,
        load_status=RecoveryLoadStatus.CORRUPT,
        safe_error="Recovery data is invalid or corrupt.",
    )
    problem = SessionProblem(
        "unsupported_manifest",
        session_evidence,
        "Session schema is newer or unsupported.",
    )
    recovery = StartupRecoveryManager()
    sessions = RecordingSessionStore()
    service = _service(recovery=recovery, sessions=sessions, capture=None)
    entries = service.recovery_entries((candidate,), (problem,))
    decisions = tuple(
        RecoveryDecision(entry.entry_id, RecoveryAction.SKIP) for entry in entries
    )

    assert service.apply_recovery_decisions(
        decisions,
        recovery_candidates=(candidate,),
        session_problems=(problem,),
        target=StartupTarget(),
    ) == 0

    assert recovery_evidence.read_bytes() == b"broken recovery"
    assert session_evidence.read_bytes() == b"future session"
    assert recovery.discarded == []
    assert sessions.discarded == []


def test_skip_without_an_editor_target_does_not_create_a_window(tmp_path: Path):
    evidence = tmp_path / "broken.uniti-recovery"
    candidate = RecoveryCandidate(
        evidence,
        None,
        load_status=RecoveryLoadStatus.CORRUPT,
        safe_error="Recovery data is invalid or corrupt.",
    )
    service = _service(capture=None)
    entry = service.recovery_entries((candidate,), ())[0]

    assert service.apply_recovery_decisions(
        (RecoveryDecision(entry.entry_id, RecoveryAction.SKIP),),
        recovery_candidates=(candidate,),
    ) == 0

    assert service.window_count == 0


def test_one_failed_recovery_does_not_block_another_candidate(tmp_path: Path):
    first_source = tmp_path / "first.txt"
    second_source = tmp_path / "second.txt"
    first_source.write_text("first", encoding="utf-8")
    second_source.write_text("second", encoding="utf-8")
    first = _startup_candidate(tmp_path / "first.uniti-recovery", first_source)
    second = _startup_candidate(tmp_path / "second.uniti-recovery", second_source)
    recovery = StartupRecoveryManager()
    recovery.fail_paths.add(first.evidence_path)
    service = _service(recovery=recovery)
    target = StartupTarget()
    entries = service.recovery_entries((first, second), ())
    decisions = tuple(
        RecoveryDecision(entry.entry_id, RecoveryAction.RECOVER)
        for entry in entries
    )

    assert service.apply_recovery_decisions(
        decisions,
        recovery_candidates=(first, second),
        target=target,
    ) == 1

    assert [document.path for document in target.opened] == [second_source]
    assert len(service.last_recovery_errors) == 1
    assert "private recovery failure details" not in service.last_recovery_errors[0]
    for document in target.opened:
        document.close()


def test_recovery_publishes_new_session_before_retiring_old_candidate(tmp_path: Path):
    events: list[object] = []
    source = tmp_path / "document.txt"
    source.write_text("body", encoding="utf-8")
    candidate = _startup_candidate(tmp_path / "document.uniti-recovery", source)
    recovery = StartupRecoveryManager(events)
    sessions = RecordingSessionStore(events)

    def capture(clean_shutdown: bool):
        events.append(("capture-recovery", clean_shutdown))
        return ("recovered-snapshot", clean_shutdown)

    service = _service(recovery=recovery, sessions=sessions, capture=None)
    service.capture_session = capture
    target = StartupTarget(events)
    entry = service.recovery_entries((candidate,), ())[0]

    assert service.apply_recovery_decisions(
        (RecoveryDecision(entry.entry_id, RecoveryAction.RECOVER),),
        recovery_candidates=(candidate,),
        target=target,
    ) == 1

    assert events == [
        ("prepare", "document.uniti-recovery"),
        ("open-recovered", "document.txt"),
        ("capture-recovery", False),
        ("publish", ("recovered-snapshot", False)),
        ("commit", "document.uniti-recovery"),
    ]
    target.opened[0].close()


def test_locate_matching_file_hashes_exact_bytes_before_recovery(tmp_path: Path):
    missing = tmp_path / "missing.txt"
    located = tmp_path / "located.txt"
    located.write_bytes(b"exact bytes")
    expected_hash = hashlib.sha256(b"different bytes").hexdigest()
    candidate = _startup_candidate(
        tmp_path / "missing.uniti-recovery",
        missing,
        match=FileMatch.MISSING,
        base_hash=expected_hash,
    )
    recovery = StartupRecoveryManager()
    service = _service(recovery=recovery)
    entry = service.recovery_entries((candidate,), ())[0]

    assert service.apply_recovery_decisions(
        (
            RecoveryDecision(
                entry.entry_id,
                RecoveryAction.LOCATE_MATCH,
                located_path=located,
            ),
        ),
        recovery_candidates=(candidate,),
        target=StartupTarget(),
    ) == 0

    assert recovery.prepared == []
    assert located.read_bytes() == b"exact bytes"
    assert candidate.evidence_path not in recovery.discarded
    assert service.last_recovery_errors == (
        f"Could not recover {missing}; its saved evidence was preserved.",
    )


def test_locate_exact_hash_retargets_recovery_without_removing_evidence(tmp_path: Path):
    missing = tmp_path / "missing.txt"
    located = tmp_path / "located.txt"
    located.write_bytes(b"exact bytes")
    expected_hash = hashlib.sha256(b"exact bytes").hexdigest()
    session = RecoverySession(
        source_path=missing,
        source_identity=FileIdentity(11, 1),
        source_encoding="utf-8",
        output_encoding="utf-8",
        output_eol=None,
        operations=(),
        clean=False,
        format_version=3,
        base_hash=expected_hash,
        base_history=HistorySnapshot.empty(),
    )
    candidate = RecoveryCandidate(
        tmp_path / "missing.uniti-recovery",
        session,
        source_match=FileMatch.MISSING,
    )
    recovery = StartupRecoveryManager()
    service = _service(recovery=recovery)
    target = StartupTarget()
    entry = service.recovery_entries((candidate,), ())[0]

    assert service.apply_recovery_decisions(
        (
            RecoveryDecision(
                entry.entry_id,
                RecoveryAction.LOCATE_MATCH,
                located_path=located,
            ),
        ),
        recovery_candidates=(candidate,),
        target=target,
    ) == 1

    assert recovery.prepared[0].session.source_path == located
    assert recovery.prepared[0].source_match is FileMatch.EXACT_HASH
    assert recovery.discarded == []
    assert target.opened[0].read(0, target.opened[0].total_chars()) == "exact bytes"
    target.opened[0].close()


def test_open_disk_keeps_changed_recovery_evidence_for_later(tmp_path: Path):
    source = tmp_path / "changed.txt"
    source.write_text("current disk", encoding="utf-8")
    candidate = _startup_candidate(
        tmp_path / "changed.uniti-recovery",
        source,
        match=FileMatch.CHANGED,
    )
    recovery = StartupRecoveryManager()
    service = _service(recovery=recovery, capture=None)
    target = StartupTarget()
    entry = service.recovery_entries((candidate,), ())[0]

    assert service.apply_recovery_decisions(
        (RecoveryDecision(entry.entry_id, RecoveryAction.OPEN_DISK),),
        recovery_candidates=(candidate,),
        target=target,
    ) == 1

    assert target.events == [("open-disk", "changed.txt")]
    assert recovery.discarded == []
    assert source.read_text(encoding="utf-8") == "current disk"


def test_reload_replaces_shared_document_authority_in_every_view(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    path = tmp_path / "reload-shared.txt"
    path.write_text("before", encoding="utf-8")
    first = service.new_window()
    first_view = first.open_path(path)
    assert first_view is not None
    second = service.new_window()
    second_view = second.open_existing_document(first_view.document)
    original = first_view.document
    path.write_text("after", encoding="utf-8")
    try:
        assert first.reload_current() is True

        replacement = first_view.document
        assert replacement is not original
        assert second_view.document is replacement
        assert service.documents.entries[0].document is replacement
        assert replacement.read(0, replacement.total_chars()) == "after"
        with pytest.raises(ValueError, match="closed"):
            original.read(0, 1)
    finally:
        first.close_all_documents(force=True)
        second.close_all_documents(force=True)
        first.close()
        second.close()
        app.processEvents()
        _stop_desktop_service(app, service)
