"""Process-lifetime UNITI service composition and Quit coordination."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from uniti.resources.tasks import TaskHandle, TaskKind, TaskSpec

from .document_registry import DocumentEntry, DocumentRegistry
from .window_manager import WindowManager

if TYPE_CHECKING:
    from uniti.app.recovery_manager import RecoveryManager
    from uniti.app.session import SessionSnapshot
    from uniti.app.session_store import SessionStore
    from uniti.app.settings import SettingsStore
    from uniti.resources.manager import ResourceManager
    from uniti.ui.find_replace import FindReplaceWindow


class QuitChoice(StrEnum):
    SAVE = "save"
    DISCARD = "discard"
    CANCEL = "cancel"


@dataclass(frozen=True, slots=True)
class QuitDecision:
    document_id: str
    choice: QuitChoice

    def __post_init__(self) -> None:
        if not isinstance(self.document_id, str) or not self.document_id:
            raise ValueError("Quit decision document ID must be nonempty")
        if not isinstance(self.choice, QuitChoice):
            raise TypeError("Quit decision choice must be a QuitChoice")


@dataclass(frozen=True, slots=True)
class QuitPlan:
    decisions: tuple[QuitDecision, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.decisions, tuple) or any(
            not isinstance(item, QuitDecision) for item in self.decisions
        ):
            raise TypeError("Quit plan decisions must be a tuple of QuitDecision values")
        document_ids = tuple(item.document_id for item in self.decisions)
        if len(set(document_ids)) != len(document_ids):
            raise ValueError("Quit plan contains duplicate documents")


@dataclass(frozen=True, slots=True)
class _PublicationRequest:
    generation: int
    snapshot: object


class _PublicationQueue:
    """Serialize publication and retain only the newest queued snapshot."""

    def __init__(self, resource_manager: object, session_store: object) -> None:
        coordinator = getattr(resource_manager, "tasks", None)
        if coordinator is None or not callable(getattr(coordinator, "submit", None)):
            raise TypeError("resource manager must provide a task coordinator")
        if not callable(getattr(session_store, "publish", None)):
            raise TypeError("session store must provide publish()")
        self._coordinator = coordinator
        self._session_store = session_store
        self._condition = threading.Condition(threading.RLock())
        self._active: _PublicationRequest | None = None
        self._pending: _PublicationRequest | None = None
        self._closed = False
        self._last_error: Exception | None = None

    @property
    def last_error(self) -> Exception | None:
        with self._condition:
            return self._last_error

    def request(self, request: _PublicationRequest) -> None:
        with self._condition:
            if self._closed:
                raise RuntimeError("session publication queue is closed")
            if self._active is not None:
                self._pending = request
                return
            self._active = request
        self._submit(request)

    def _submit(self, request: _PublicationRequest) -> None:
        spec = TaskSpec.create(TaskKind.SESSION, foreground=False)
        try:
            handle = self._coordinator.submit(
                spec,
                lambda _context: self._session_store.publish(request.snapshot),
            )
        except Exception as exc:
            self._submission_failed(request, exc)
            return
        handle.future.add_done_callback(
            lambda _future: self._finished(request, handle)
        )

    def _submission_failed(
        self,
        request: _PublicationRequest,
        error: Exception,
    ) -> None:
        next_request: _PublicationRequest | None = None
        with self._condition:
            if self._active is not request:
                return
            self._last_error = error
            self._active = None
            if not self._closed:
                next_request = self._pending
            self._pending = None
            if next_request is not None:
                self._active = next_request
            else:
                self._condition.notify_all()
        if next_request is not None:
            self._submit(next_request)

    def _finished(
        self,
        request: _PublicationRequest,
        handle: TaskHandle[Any],
    ) -> None:
        try:
            handle.future.result()
        except Exception as exc:
            error: Exception | None = exc
        else:
            error = None
        next_request: _PublicationRequest | None = None
        with self._condition:
            if self._active is not request:
                return
            self._last_error = error
            self._active = None
            if not self._closed:
                next_request = self._pending
            self._pending = None
            if next_request is not None:
                self._active = next_request
            else:
                self._condition.notify_all()
        if next_request is not None:
            self._submit(next_request)

    def close_before_final_publication(self) -> None:
        """Drop superseded queued state and wait for an active atomic publish."""

        with self._condition:
            self._closed = True
            self._pending = None
            while self._active is not None:
                self._condition.wait()


class UNITIService:
    """Own application services independently of editor-window lifetime."""

    def __init__(
        self,
        *,
        resource_manager: ResourceManager,
        settings_store: SettingsStore,
        session_store: SessionStore,
        recovery_manager: RecoveryManager,
        session_capture: Callable[[bool], SessionSnapshot] | None = None,
        documents: DocumentRegistry | None = None,
        windows: WindowManager | None = None,
    ) -> None:
        if session_capture is not None and not callable(session_capture):
            raise TypeError("session capture must be callable")
        self.resources = resource_manager
        self.settings = settings_store
        self.sessions = session_store
        self.recovery = recovery_manager
        self.documents = documents or DocumentRegistry()
        self.windows = windows or WindowManager()
        self._session_capture = session_capture
        self._find_replace: FindReplaceWindow | None = None
        self._publication_queue: _PublicationQueue | None = None
        self._publication_generation = 0
        self._running = True

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def window_count(self) -> int:
        return self.windows.count

    @property
    def active_view(self) -> object | None:
        return self.windows.resolve_active_view()

    @property
    def find_replace(self) -> FindReplaceWindow:
        if self._find_replace is None:
            if not self._running:
                raise RuntimeError("UNITI service is stopped")
            from PySide6.QtWidgets import QApplication

            from uniti.ui.find_replace import FindReplaceWindow

            app = QApplication.instance()
            if not isinstance(app, QApplication):
                raise RuntimeError(
                    "Find/Replace requires an existing QApplication"
                )
            self._find_replace = FindReplaceWindow(
                lambda: self.active_view,
                resource_manager=self.resources,
            )
        return self._find_replace

    @property
    def last_publication_error(self) -> Exception | None:
        queue = self._publication_queue
        return None if queue is None else queue.last_error

    def _ensure_running(self) -> None:
        if not self._running:
            raise RuntimeError("UNITI service is stopped")

    def register_window(self, window_id: str, window: object) -> None:
        self._ensure_running()
        self.windows.register(window_id, window)

    def unregister_window(self, window_id: str) -> object:
        self._ensure_running()
        window = self.windows.unregister(window_id)
        if self._find_replace is not None:
            self._find_replace.target_changed()
            if self.window_count == 0:
                self._find_replace.hide()
        return window

    def set_active_view(self, window_id: str, view_id: str | None) -> None:
        self._ensure_running()
        self.windows.activate(window_id, view_id)
        if view_id is not None and self.documents.entry_for_view(view_id) is not None:
            self.documents.activate_view(view_id)
        if self._find_replace is not None:
            self._find_replace.target_changed()

    def capture_session(self, clean_shutdown: bool = False) -> SessionSnapshot:
        if not isinstance(clean_shutdown, bool):
            raise TypeError("clean_shutdown must be bool")
        capture = self._session_capture
        if capture is None:
            raise RuntimeError("session capture is not configured")
        return capture(clean_shutdown)

    def schedule_publication(self, clean_shutdown: bool = False) -> int:
        self._ensure_running()
        snapshot = self.capture_session(clean_shutdown)
        if self._publication_queue is None:
            self._publication_queue = _PublicationQueue(
                self.resources,
                self.sessions,
            )
        self._publication_generation += 1
        request = _PublicationRequest(self._publication_generation, snapshot)
        self._publication_queue.request(request)
        return request.generation

    def _modified_documents_in_prompt_order(self) -> tuple[DocumentEntry, ...]:
        ordered: list[DocumentEntry] = []
        seen: set[str] = set()
        for view_id in self.windows.ordered_view_ids:
            entry = self.documents.entry_for_view(view_id)
            if (
                entry is not None
                and entry.document.modified
                and entry.document_id not in seen
            ):
                ordered.append(entry)
                seen.add(entry.document_id)
        for entry in self.documents.entries:
            if entry.document.modified and entry.document_id not in seen:
                ordered.append(entry)
                seen.add(entry.document_id)
        return tuple(ordered)

    def build_quit_plan(
        self,
        choose: Callable[[DocumentEntry], QuitChoice],
    ) -> QuitPlan | None:
        self._ensure_running()
        if not callable(choose):
            raise TypeError("Quit choice provider must be callable")
        decisions: list[QuitDecision] = []
        cancelled = False
        for entry in self._modified_documents_in_prompt_order():
            choice = choose(entry)
            if not isinstance(choice, QuitChoice):
                raise TypeError("Quit choice provider must return a QuitChoice")
            decisions.append(QuitDecision(entry.document_id, choice))
            cancelled = cancelled or choice is QuitChoice.CANCEL
        if cancelled:
            return None
        return QuitPlan(tuple(decisions))

    def request_quit(
        self,
        choose: Callable[[DocumentEntry], QuitChoice],
    ) -> bool:
        if not self._running:
            return True
        plan = self.build_quit_plan(choose)
        if plan is None:
            return False
        self._execute_quit(plan)
        return True

    def _execute_quit(self, plan: QuitPlan) -> None:
        for decision in plan.decisions:
            if decision.choice is QuitChoice.SAVE:
                self.documents.get(decision.document_id).document.save()

        if self._publication_queue is not None:
            self._publication_queue.close_before_final_publication()
        final_snapshot = self.capture_session(clean_shutdown=True)
        self.sessions.publish(final_snapshot)

        for entry in self.documents.entries:
            self.recovery.detach(entry.document, clean=True)

        panel = self._find_replace
        if panel is not None:
            panel.hide()
            panel.shutdown()
            panel.deleteLater()
            self._find_replace = None

        for _window_id, window in self.windows.items:
            close = getattr(window, "close_for_service", None)
            if not callable(close):
                close = getattr(window, "close", None)
            if callable(close):
                close()

        self.documents.close_all()
        self.windows.clear()
        self.recovery.shutdown()
        self.resources.shutdown(wait=True)
        self._running = False


__all__ = [
    "QuitChoice",
    "QuitDecision",
    "QuitPlan",
    "UNITIService",
]
