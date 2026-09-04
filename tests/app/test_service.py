from __future__ import annotations

import os
import threading
import time
from pathlib import Path

import pytest

from uniti.app.service import QuitChoice, QuitDecision, UNITIService
from uniti.core.document import Document
from uniti.resources import ResourceManager


class RecordingSessionStore:
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = events if events is not None else []
        self.publications: list[object] = []
        self.discarded: list[str] = []

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
        self.shutdown_count = 0

    def detach(self, document: Document, *, clean: bool) -> None:
        self.events.append(("detach", document.path.name, clean))
        self.detached.append((document, clean))

    def shutdown(self) -> None:
        self.events.append("recovery-shutdown")
        self.shutdown_count += 1


class RecordingResources:
    def __init__(self, events: list[object] | None = None) -> None:
        self.events = events if events is not None else []
        self.shutdown_count = 0

    def shutdown(self, *, wait: bool = True) -> None:
        self.events.append(("resources-shutdown", wait))
        self.shutdown_count += 1


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
) -> UNITIService:
    return UNITIService(
        resource_manager=resources or RecordingResources(),
        settings_store=object(),
        session_store=sessions or RecordingSessionStore(),
        recovery_manager=recovery or RecordingRecoveryManager(),
        session_capture=capture,
    )


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


def test_last_window_can_close_while_service_remains_running():
    service = _service()
    window = FakeWindow()
    service.register_window("window-a", window)

    assert service.unregister_window("window-a") is window

    assert service.window_count == 0
    assert service.active_view is None
    assert service.is_running is True


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
