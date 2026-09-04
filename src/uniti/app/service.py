"""Process-lifetime UNITI service composition and Quit coordination."""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Callable
from dataclasses import dataclass, is_dataclass, replace
from enum import StrEnum
from pathlib import Path
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


@dataclass(frozen=True, slots=True)
class _RecoveryBinding:
    entry: object
    source: str
    payload: object


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
        self._last_recovery_errors: tuple[str, ...] = ()
        self._running = True
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.setQuitOnLastWindowClosed(False)
        except (ImportError, ModuleNotFoundError):
            pass

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
    def most_recent_window(self) -> object | None:
        return self.windows.most_recent_window

    def new_window(self, record=None):
        self._ensure_running()
        if record is not None:
            from uniti.app.session import WindowRecord

            if not isinstance(record, WindowRecord):
                raise TypeError("record must be a WindowRecord or None")
        from uniti.ui.main_window import UNITIMainWindow

        window = UNITIMainWindow(
            self,
            window_id=None if record is None else record.window_id,
        )
        if record is not None:
            window.restore_window_record(record)
        return window

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

    @property
    def last_recovery_errors(self) -> tuple[str, ...]:
        return self._last_recovery_errors

    @staticmethod
    def _candidate_entry_kind(candidate: object):
        from uniti.core.file_identity import FileMatch
        from uniti.core.recovery import RecoveryLoadStatus
        from uniti.ui.recovery_center import RecoveryEntryKind

        status = getattr(candidate, "load_status", None)
        match = getattr(candidate, "source_match", None)
        if status is RecoveryLoadStatus.CORRUPT:
            return RecoveryEntryKind.CORRUPT
        if status is RecoveryLoadStatus.UNSUPPORTED:
            return RecoveryEntryKind.UNSUPPORTED
        if match is FileMatch.CHANGED:
            return RecoveryEntryKind.CHANGED
        if match is FileMatch.MISSING:
            return RecoveryEntryKind.MISSING
        if status is RecoveryLoadStatus.TRUNCATED_TAIL:
            return RecoveryEntryKind.TRUNCATED
        return RecoveryEntryKind.RECOVERABLE

    @staticmethod
    def _problem_entry_kind(problem: object):
        from uniti.ui.recovery_center import RecoveryEntryKind

        kind = getattr(problem, "kind", "")
        if kind == "session_ready":
            return RecoveryEntryKind.SESSION_READY
        if kind in {"changed_source", "source_changed"}:
            return RecoveryEntryKind.CHANGED
        if kind in {"missing_source", "source_missing"}:
            return RecoveryEntryKind.MISSING
        if kind in {"truncated", "history_truncated"}:
            return RecoveryEntryKind.TRUNCATED
        if kind in {"degraded", "recovery_degraded"}:
            return RecoveryEntryKind.DEGRADED
        if "unsupported" in kind:
            return RecoveryEntryKind.UNSUPPORTED
        return RecoveryEntryKind.CORRUPT

    def _recovery_bindings(
        self,
        recovery_candidates: tuple[object, ...],
        session_problems: tuple[object, ...],
    ) -> tuple[_RecoveryBinding, ...]:
        from uniti.app.recovery_manager import RecoveryCandidate
        from uniti.app.session import SessionProblem
        from uniti.ui.recovery_center import MAX_RECOVERY_ENTRIES, RecoveryEntry

        if not isinstance(recovery_candidates, tuple) or any(
            not isinstance(item, RecoveryCandidate) for item in recovery_candidates
        ):
            raise TypeError("recovery candidates must be a tuple of RecoveryCandidate")
        if not isinstance(session_problems, tuple) or any(
            not isinstance(item, SessionProblem) for item in session_problems
        ):
            raise TypeError("session problems must be a tuple of SessionProblem")
        if len(recovery_candidates) + len(session_problems) > MAX_RECOVERY_ENTRIES:
            raise ValueError("too many recovery entries")

        ordered: list[tuple[str, object]] = [
            ("recovery", candidate)
            for candidate in sorted(
                recovery_candidates,
                key=lambda item: str(item.evidence_path),
            )
        ]
        ordered.extend(
            ("session", problem)
            for problem in sorted(
                session_problems,
                key=lambda item: str(item.evidence_path),
            )
        )
        bindings: list[_RecoveryBinding] = []
        for index, (source, payload) in enumerate(ordered):
            evidence_path = Path(getattr(payload, "evidence_path"))
            digest = hashlib.sha256(
                f"{source}\0{evidence_path}".encode("utf-8")
            ).hexdigest()[:20]
            entry_id = f"{source}-{index:04d}-{digest}"
            if source == "recovery":
                session = getattr(payload, "session", None)
                path = (
                    Path(getattr(session, "source_path"))
                    if session is not None
                    else evidence_path
                )
                entry_kind = self._candidate_entry_kind(payload)
                message = getattr(payload, "safe_error", None) or (
                    "UNITI found compatible recovery state for this document."
                )
            else:
                path = evidence_path
                entry_kind = self._problem_entry_kind(payload)
                message = getattr(payload, "safe_message")
            entry = RecoveryEntry.create(
                entry_id=entry_id,
                kind=entry_kind,
                path=path,
                message=message,
                evidence_path=evidence_path,
            )
            bindings.append(_RecoveryBinding(entry, source, payload))
        return tuple(bindings)

    def recovery_entries(
        self,
        recovery_candidates: tuple[object, ...] = (),
        session_problems: tuple[object, ...] = (),
    ) -> tuple[object, ...]:
        """Return a stable, bounded presentation of startup evidence."""

        return tuple(
            binding.entry
            for binding in self._recovery_bindings(
                recovery_candidates,
                session_problems,
            )
        )

    def _recovery_target(self, target: object | None) -> object:
        selected = target or self.most_recent_window
        return self.new_window() if selected is None else selected

    def _publish_recovered_state(self, recovered: object) -> None:
        if self._session_capture is None:
            return
        snapshot = self.capture_session(clean_shutdown=False)
        self.sessions.publish(snapshot)
        self.recovery.commit_recovery(recovered)

    def _recover_candidate(self, candidate: object, target: object) -> None:
        recovered = self.recovery.prepare_recovery(candidate)
        document = recovered.document
        opener = getattr(target, "open_existing_document", None)
        if not callable(opener):
            try:
                self.recovery.detach(document, clean=False)
            finally:
                document.close()
            raise TypeError("recovery target cannot open a recovered document")
        try:
            opener(document)
        except Exception:
            try:
                self.recovery.detach(document, clean=False)
            finally:
                document.close()
            raise
        self._publish_recovered_state(recovered)

    def _apply_candidate_action(
        self,
        candidate: object,
        decision: object,
        target: object,
    ) -> bool:
        from uniti.core.file_identity import FileIdentity, FileMatch, sha256_file
        from uniti.ui.recovery_center import RecoveryAction

        action = decision.action
        if action is RecoveryAction.SKIP:
            return False
        if action is RecoveryAction.DISCARD:
            self.recovery.discard(candidate)
            return False
        session = getattr(candidate, "session", None)
        if session is None:
            raise ValueError("recovery candidate has no usable session")
        if action is RecoveryAction.OPEN_DISK:
            opener = getattr(target, "open_path", None)
            if not callable(opener):
                raise TypeError("recovery target cannot open a disk file")
            opener(Path(session.source_path))
            return True
        selected = candidate
        if action is RecoveryAction.LOCATE_MATCH:
            expected_hash = getattr(session, "base_hash", None)
            if not isinstance(expected_hash, str):
                raise ValueError("recovery evidence has no exact saved-file hash")
            located_path = Path(decision.located_path)
            if sha256_file(located_path) != expected_hash:
                raise ValueError("located file does not match recovery evidence")
            if not is_dataclass(session):
                raise TypeError("recovery session cannot be relocated")
            relocated_session = replace(
                session,
                source_path=located_path,
                source_identity=FileIdentity.from_path(located_path),
            )
            selected = replace(
                candidate,
                session=relocated_session,
                source_match=FileMatch.EXACT_HASH,
            )
        if action in {RecoveryAction.RECOVER, RecoveryAction.LOCATE_MATCH}:
            self._recover_candidate(selected, target)
            return True
        raise ValueError("recovery action is unsupported for a journal")

    def _apply_session_problem_action(
        self,
        problem: object,
        decision: object,
        target: object,
    ) -> bool:
        from uniti.ui.recovery_center import RecoveryAction

        action = decision.action
        if action is RecoveryAction.SKIP:
            return False
        if action is RecoveryAction.DISCARD:
            document_id = getattr(problem, "document_id", None)
            if document_id is not None:
                self.sessions.discard(document_id)
            else:
                discard_evidence = getattr(self.sessions, "discard_evidence", None)
                if not callable(discard_evidence):
                    raise TypeError("session store cannot discard selected evidence")
                discard_evidence(problem.evidence_path)
            return False
        handler = getattr(self.sessions, "resolve_problem", None)
        if not callable(handler):
            raise TypeError("session problem cannot be resolved by this store")
        handler(problem, action=action, located_path=decision.located_path, target=target)
        return True

    def apply_recovery_decisions(
        self,
        decisions: tuple[object, ...],
        *,
        recovery_candidates: tuple[object, ...] = (),
        session_problems: tuple[object, ...] = (),
        target: object | None = None,
    ) -> int:
        """Apply each safe startup decision independently and preserve failures."""

        from uniti.ui.recovery_center import RecoveryAction, RecoveryDecision

        if not isinstance(decisions, tuple) or any(
            not isinstance(item, RecoveryDecision) for item in decisions
        ):
            raise TypeError("recovery decisions must be a tuple of RecoveryDecision")
        bindings = self._recovery_bindings(recovery_candidates, session_problems)
        by_id = {binding.entry.entry_id: binding for binding in bindings}
        if len({decision.entry_id for decision in decisions}) != len(decisions):
            raise ValueError("recovery decisions contain duplicate entry IDs")
        for decision in decisions:
            binding = by_id.get(decision.entry_id)
            if binding is None:
                raise ValueError("recovery decision references an unknown entry")
            if decision.action not in binding.entry.actions:
                raise ValueError("recovery decision is unsafe for its entry")

        selected_target = target
        completed = 0
        errors: list[str] = []
        for decision in decisions:
            binding = by_id[decision.entry_id]
            try:
                if decision.action in {
                    RecoveryAction.RECOVER,
                    RecoveryAction.OPEN_DISK,
                    RecoveryAction.LOCATE_MATCH,
                } and selected_target is None:
                    selected_target = self._recovery_target(None)
                if binding.source == "recovery":
                    opened = self._apply_candidate_action(
                        binding.payload,
                        decision,
                        selected_target,
                    )
                else:
                    opened = self._apply_session_problem_action(
                        binding.payload,
                        decision,
                        selected_target,
                    )
            except Exception:
                errors.append(
                    f"Could not recover {binding.entry.path}; "
                    "its saved evidence was preserved."
                )
                continue
            completed += int(opened)
        self._last_recovery_errors = tuple(errors)
        return completed

    def run_recovery_center(
        self,
        parent: object,
        *,
        recovery_candidates: tuple[object, ...] = (),
        session_problems: tuple[object, ...] = (),
    ) -> int:
        """Present one startup dialog and apply its independent decisions."""

        from PySide6.QtWidgets import QMessageBox

        from uniti.ui.recovery_center import RecoveryCenterDialog

        entries = self.recovery_entries(recovery_candidates, session_problems)
        if not entries:
            self._last_recovery_errors = ()
            return 0
        dialog = RecoveryCenterDialog(entries, parent)
        dialog.exec()
        recovered = self.apply_recovery_decisions(
            dialog.decisions(),
            recovery_candidates=recovery_candidates,
            session_problems=session_problems,
            target=parent,
        )
        if self._last_recovery_errors:
            visible = "\n".join(self._last_recovery_errors[:10])
            if len(self._last_recovery_errors) > 10:
                visible += "\nAdditional items were preserved for later."
            QMessageBox.warning(parent, "Recovery Incomplete", visible)
        return recovered

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
        for candidate_id, window in self.windows.items:
            sync = getattr(window, "set_global_panel_bindings_enabled", None)
            if callable(sync):
                sync(candidate_id == window_id)
            activate_resources = getattr(window, "set_service_window_active", None)
            if callable(activate_resources):
                activate_resources(candidate_id == window_id)
        if view_id is not None and self.documents.entry_for_view(view_id) is not None:
            self.documents.activate_view(view_id)
        if self._find_replace is not None:
            self._find_replace.target_changed()

    def focus_document(self, document_id: str) -> object | None:
        self._ensure_running()
        entry = self.documents.get(document_id)
        for view_id in entry.view_ids:
            window = self.windows.window_for_view(view_id)
            if window is None:
                continue
            panes = getattr(window, "panes", None)
            activate = getattr(panes, "activate_view", None)
            if callable(activate):
                activate(view_id)
            self.set_active_view(getattr(window, "window_id"), view_id)
            for method_name in ("show", "raise_", "activateWindow"):
                method = getattr(window, method_name, None)
                if callable(method):
                    method()
            resolver = getattr(window, "view_for_id", None)
            return resolver(view_id) if callable(resolver) else None
        return None

    def move_view_to_new_window(self, view_id: str):
        self._ensure_running()
        source = self.windows.window_for_view(view_id)
        if source is None:
            raise KeyError(view_id)
        take = getattr(source, "take_view_for_transfer", None)
        if not callable(take):
            raise TypeError("source window cannot transfer views")
        window = self.new_window()
        accept = getattr(window, "accept_transferred_view", None)
        if not callable(accept):
            raise TypeError("target window cannot accept views")
        view = None
        try:
            view = take(view_id)
            accept(view)
        except Exception:
            window.close()
            if view is not None:
                rollback = getattr(source, "accept_transferred_view", None)
                if callable(rollback):
                    rollback(view)
            raise
        window.show()
        return window

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

        if self._session_capture is not None:
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
        try:
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if isinstance(app, QApplication):
                app.quit()
        except (ImportError, ModuleNotFoundError):
            pass


__all__ = [
    "QuitChoice",
    "QuitDecision",
    "QuitPlan",
    "UNITIService",
]
