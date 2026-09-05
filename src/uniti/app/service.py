"""Process-lifetime UNITI service composition and Quit coordination."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, is_dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from uniti.core.durability import DurabilityLevel, DurabilityResult
from uniti.resources.tasks import TaskHandle, TaskKind, TaskSpec

from .document_registry import DocumentEntry, DocumentRegistry
from .dogfood import Durability, Operation, Outcome, ResourceBand
from .session import MAX_VIEWS, MAX_WINDOWS, DockReturnRecord
from .window_manager import ViewLocation, WindowManager


_UNCHANGED_DOCK_RETURN = object()

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


class _QuitExecutionError(RuntimeError):
    pass


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
    started_at: float


@dataclass(frozen=True, slots=True)
class _RecoveryBinding:
    entry: object
    source: str
    payload: object


class _PublicationQueue:
    """Serialize publication and retain only the newest queued snapshot."""

    def __init__(
        self,
        resource_manager: object,
        session_store: object,
        on_result: Callable[[object, object, float], None],
        on_failure: Callable[[float], None] | None = None,
    ) -> None:
        coordinator = getattr(resource_manager, "tasks", None)
        if coordinator is None or not callable(getattr(coordinator, "submit", None)):
            raise TypeError("resource manager must provide a task coordinator")
        if not callable(getattr(session_store, "publish", None)):
            raise TypeError("session store must provide publish()")
        if not callable(on_result):
            raise TypeError("publication result callback must be callable")
        if on_failure is not None and not callable(on_failure):
            raise TypeError("publication failure callback must be callable or None")
        self._coordinator = coordinator
        self._session_store = session_store
        self._on_result = on_result
        self._on_failure = on_failure
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
        if self._on_failure is not None:
            try:
                self._on_failure(request.started_at)
            except Exception:
                pass
        if next_request is not None:
            self._submit(next_request)

    def _finished(
        self,
        request: _PublicationRequest,
        handle: TaskHandle[Any],
    ) -> None:
        try:
            result = handle.future.result()
        except Exception as exc:
            error: Exception | None = exc
            result = None
        else:
            error = None
        if error is None:
            try:
                self._on_result(result, request.snapshot, request.started_at)
            except Exception:
                # A durable publication must not be reclassified by observers.
                pass
        elif self._on_failure is not None:
            try:
                self._on_failure(request.started_at)
            except Exception:
                pass
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
        service_id: str | None = None,
        build_identity: str | None = None,
        instance_service: object | None = None,
        dogfood_recorder: object | None = None,
        dogfood_store: object | None = None,
        dogfood_publish_interval_seconds: int = 300,
    ) -> None:
        if session_capture is not None and not callable(session_capture):
            raise TypeError("session capture must be callable")
        if instance_service is not None and not callable(
            getattr(instance_service, "close", None)
        ):
            raise TypeError("instance service must provide close()")
        self.resources = resource_manager
        self.settings = settings_store
        self.sessions = session_store
        self.recovery = recovery_manager
        self.documents = documents or DocumentRegistry()
        self.windows = windows or WindowManager()
        self._instance_service = instance_service
        self._session_capture = session_capture
        from .session_controller import SessionController

        self._session_controller = SessionController(
            self,
            session_capture=session_capture,
            service_id=service_id,
            build_identity=build_identity,
        )
        self._last_quit_error: str | None = None
        self._quitting = False
        self._find_replace: FindReplaceWindow | None = None
        self._find_replace_placement = "detached"
        self._publication_queue: _PublicationQueue | None = None
        self._publication_generation = 0
        from .dogfood_runtime import DogfoodRuntime

        self._dogfood = DogfoodRuntime(
            resource_manager,
            dogfood_recorder,
            dogfood_store,
            publish_interval_seconds=dogfood_publish_interval_seconds,
        )
        set_recovery_observer = getattr(
            self.recovery,
            "set_dogfood_observer",
            None,
        )
        if callable(set_recovery_observer):
            set_recovery_observer(self.record_dogfood)
        self._last_recovery_errors: tuple[str, ...] = ()
        self._recovery_degraded = False
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
    def dogfood_recorder(self) -> object | None:
        return self._dogfood.recorder

    @property
    def dogfood_store(self) -> object | None:
        return self._dogfood.store

    @property
    def dogfood_is_active(self) -> bool:
        return self._dogfood.active

    @property
    def dogfood_status(self) -> object:
        return self._dogfood.status

    @staticmethod
    def _dogfood_durability(
        result: DurabilityResult | None,
    ) -> tuple[Outcome, Durability]:
        if result is None:
            return Outcome.SUCCESS, Durability.NOT_APPLICABLE
        if result.level is DurabilityLevel.FULL:
            return Outcome.SUCCESS, Durability.FULL
        if result.level is DurabilityLevel.FILE_SYNCED:
            return Outcome.REDUCED_DURABILITY, Durability.FILE_SYNCED
        return Outcome.FAILED, Durability.UNSAFE

    def _dogfood_resource_band(self) -> ResourceBand:
        try:
            return ResourceBand(self.resources.status.state.value)
        except (AttributeError, TypeError, ValueError):
            return ResourceBand.NORMAL

    def record_dogfood(
        self,
        operation: Operation,
        outcome: Outcome,
        *,
        elapsed_ms: float | None = None,
        durability: Durability = Durability.NOT_APPLICABLE,
    ) -> None:
        """Accept only fixed aggregate facts and never alter caller results."""

        if (
            not isinstance(operation, Operation)
            or not isinstance(outcome, Outcome)
            or not isinstance(durability, Durability)
        ):
            return
        band = self._dogfood_resource_band()
        self._dogfood.observe(
            operation,
            outcome,
            elapsed_ms=elapsed_ms,
            durability=durability,
            peak_resource=band,
            retained_resource=band,
        )

    def schedule_dogfood_publication(self) -> TaskHandle[Any] | None:
        return self._dogfood.schedule_publication()

    def export_dogfood_evidence(self, destination: Path) -> TaskHandle[Any]:
        return self._dogfood.export(destination)

    def clear_dogfood_evidence(self) -> TaskHandle[Any]:
        return self._dogfood.clear()

    def shutdown_dogfood(self) -> None:
        self._dogfood.shutdown()

    def _finalize_dogfood(self) -> None:
        self._dogfood.finalize()

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
        if self.window_count >= MAX_WINDOWS:
            raise ValueError(f"UNITI cannot exceed {MAX_WINDOWS} windows")
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
                dogfood_observer=self.record_dogfood,
            )
            self._find_replace.placementChanged.connect(
                self._record_find_replace_placement
            )
            load_settings = getattr(self.settings, "load", None)
            if callable(load_settings):
                settings = load_settings()
                self._find_replace.set_zoom_percent(
                    settings.find_replace_zoom_percent
                )
                self._find_replace.set_report_location(
                    settings.find_replace_report_location
                )
                if settings.find_replace_geometry is not None:
                    self._find_replace.setGeometry(
                        *settings.find_replace_geometry
                    )
            self._find_replace.hide()
        return self._find_replace

    def _record_find_replace_placement(self, placement: str) -> None:
        if placement not in {"attached", "detached"}:
            raise ValueError(f"unsupported find/replace placement: {placement}")
        self._find_replace_placement = placement

    def attach_find_replace(self) -> None:
        self._ensure_running()
        self._find_replace_placement = "attached"
        self._sync_find_replace_host()

    def detach_find_replace(self) -> None:
        self._ensure_running()
        self._find_replace_placement = "detached"
        panel = self.find_replace
        was_hidden = panel.isHidden()
        panel.detach()
        if was_hidden:
            panel.hide()

    def toggle_find_replace_attachment(self) -> None:
        if self._find_replace_placement == "attached":
            self.detach_find_replace()
        else:
            self.attach_find_replace()

    def _sync_find_replace_host(self) -> None:
        panel = self._find_replace
        if panel is None or self._find_replace_placement != "attached":
            return
        window = self.windows.active_window or self.windows.most_recent_window
        if window is None:
            parent = panel.parentWidget()
            release = getattr(parent, "release_find_replace", None)
            if callable(release):
                release(panel)
            else:
                panel.hide()
                panel.setParent(None)
            return
        host = getattr(window, "host_find_replace", None)
        if callable(host):
            host(panel)

    def focus_find(self) -> None:
        panel = self.find_replace
        self._sync_find_replace_host()
        panel.focus_find()

    def focus_replace(self) -> None:
        panel = self.find_replace
        self._sync_find_replace_host()
        panel.focus_replace()

    @property
    def last_publication_error(self) -> Exception | None:
        queue = self._publication_queue
        return None if queue is None else queue.last_error

    @property
    def last_recovery_errors(self) -> tuple[str, ...]:
        return self._last_recovery_errors

    @property
    def recovery_degraded(self) -> bool:
        return self._recovery_degraded

    @property
    def session_durability(self) -> DurabilityResult | None:
        result = getattr(self.sessions, "last_durability", None)
        return result if isinstance(result, DurabilityResult) else None

    @property
    def recovery_health(self):
        from .recovery_manager import RecoveryHealth

        diagnostics = getattr(self.recovery, "diagnostics", None)
        if not callable(diagnostics):
            return RecoveryHealth.OK
        observed = tuple(diagnostics())
        if any(
            getattr(item, "health", RecoveryHealth.OK)
            is RecoveryHealth.DEGRADED
            for item in observed
        ):
            return RecoveryHealth.DEGRADED
        if any(
            getattr(item, "health", RecoveryHealth.OK)
            is RecoveryHealth.REDUCED
            for item in observed
        ):
            return RecoveryHealth.REDUCED
        return RecoveryHealth.OK

    @property
    def recovery_durability(self) -> DurabilityLevel:
        diagnostics = getattr(self.recovery, "diagnostics", None)
        if not callable(diagnostics):
            return DurabilityLevel.FULL
        levels = tuple(
            getattr(item, "durability", DurabilityLevel.FULL)
            for item in diagnostics()
        )
        if DurabilityLevel.UNSAFE in levels:
            return DurabilityLevel.UNSAFE
        if DurabilityLevel.FILE_SYNCED in levels:
            return DurabilityLevel.FILE_SYNCED
        return DurabilityLevel.FULL

    def _publication_finished(
        self,
        result: object,
        snapshot: object,
        started_at: float,
    ) -> None:
        durability_result = getattr(result, "durability", None)
        outcome, durability = self._dogfood_durability(
            durability_result
            if isinstance(durability_result, DurabilityResult)
            else None
        )
        self.record_dogfood(
            Operation.SESSION_PUBLISH,
            outcome,
            elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            durability=durability,
        )
        truncations = tuple(getattr(result, "truncations", ()))
        low_space = any(
            getattr(item, "reason", "") == "low_space_history_suppressed"
            for item in truncations
        )
        self._recovery_degraded = low_space
        rebased = self._session_controller.publication_durable(snapshot)
        if not low_space:
            return
        compact = getattr(self.recovery, "compact", None)
        if not callable(compact):
            return
        for entry in self.documents.entries:
            if (
                not entry.document.modified
                or entry.document_id in rebased
            ):
                continue
            try:
                compact(entry.document)
            except (RuntimeError, ValueError):
                continue

    @property
    def last_quit_error(self) -> str | None:
        return self._last_quit_error

    @property
    def is_quitting(self) -> bool:
        return self._quitting

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
        unique_session_problems: list[object] = []
        seen_session_problems: set[tuple[object, ...]] = set()
        for problem in session_problems:
            key = (
                ("document", problem.document_id)
                if problem.document_id is not None
                else ("evidence", problem.kind, problem.evidence_path)
            )
            if key not in seen_session_problems:
                seen_session_problems.add(key)
                unique_session_problems.append(problem)
        if (
            len(recovery_candidates) + len(unique_session_problems)
            > MAX_RECOVERY_ENTRIES
        ):
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
                unique_session_problems,
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

    def _publish_snapshot_durably(self, snapshot: object) -> object:
        """Run serialization and durable storage away from the GUI thread."""

        started_at = time.monotonic()
        coordinator = getattr(self.resources, "tasks", None)
        submit = getattr(coordinator, "submit", None)
        try:
            if not callable(submit):
                result = self.sessions.publish(snapshot)
            else:
                handle = submit(
                    TaskSpec.create(TaskKind.SESSION, foreground=True),
                    lambda _context: self.sessions.publish(snapshot),
                )
                result = handle.future.result()
        except Exception:
            self.record_dogfood(
                Operation.SESSION_PUBLISH,
                Outcome.FAILED,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            )
            raise
        durability_result = getattr(result, "durability", None)
        outcome, durability = self._dogfood_durability(
            durability_result
            if isinstance(durability_result, DurabilityResult)
            else None
        )
        self.record_dogfood(
            Operation.SESSION_PUBLISH,
            outcome,
            elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            durability=durability,
        )
        return result

    def _publish_recovered_state(self, recovered: object) -> None:
        snapshot = self.capture_session(clean_shutdown=False)
        self._publish_snapshot_durably(snapshot)
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
                self._session_controller.discard_document(document_id)
            else:
                discard_evidence = getattr(self.sessions, "discard_evidence", None)
                if not callable(discard_evidence):
                    raise TypeError("session store cannot discard selected evidence")
                discard_evidence(problem.evidence_path)
            return False
        if getattr(problem, "document_id", None) is None and action is RecoveryAction.RECOVER:
            return False
        self._session_controller.resolve_problem(
            problem,
            action=action,
            located_path=decision.located_path,
        )
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
        started_at = time.monotonic()
        self._ensure_running()
        self.windows.register(window_id, window)
        self._sync_find_replace_host()
        self.record_dogfood(
            Operation.WINDOW_OPEN,
            Outcome.SUCCESS,
            elapsed_ms=(time.monotonic() - started_at) * 1000.0,
        )

    def unregister_window(self, window_id: str) -> object:
        started_at = time.monotonic()
        self._ensure_running()
        window = self.windows.unregister(window_id)
        if self._find_replace is not None:
            if self._find_replace_placement == "attached" and self.window_count:
                self._sync_find_replace_host()
            elif self._find_replace.parentWidget() is window:
                release = getattr(window, "release_find_replace", None)
                if callable(release):
                    release(self._find_replace)
            self._find_replace.target_changed()
            if self.window_count == 0:
                self._find_replace.hide()
        self.record_dogfood(
            Operation.WINDOW_CLOSE,
            Outcome.SUCCESS,
            elapsed_ms=(time.monotonic() - started_at) * 1000.0,
        )
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
            self._sync_find_replace_host()
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

    def track_document(
        self,
        entry: DocumentEntry,
        *,
        hash_saved: bool = True,
        observe_open: bool = True,
    ) -> None:
        started_at = time.monotonic()
        self._session_controller.track_document(entry, hash_saved=hash_saved)
        if observe_open:
            self.record_dogfood(
                Operation.DOCUMENT_OPEN,
                Outcome.SUCCESS,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            )

    def _complete_saved_hash(self, document_id: str) -> None:
        self._session_controller.complete_saved_hash(document_id)

    @staticmethod
    def _window_active_pane_id(window: object) -> str:
        panes = getattr(window, "panes", None)
        active_leaf = getattr(panes, "active_leaf", None)
        pane_id = getattr(active_leaf, "pane_id", None)
        if not isinstance(pane_id, str) or not pane_id:
            raise TypeError("window has no active editor pane")
        return pane_id

    def _resolve_dock_destination(
        self,
        source: object,
        anchor: DockReturnRecord,
    ) -> tuple[ViewLocation, bool]:
        windows = dict(self.windows.items)
        original = windows.get(anchor.window_id)
        if original is not None and original is not source:
            panes = getattr(original, "panes", None)
            pane_ids = getattr(panes, "pane_ids", ())
            if anchor.pane_id in pane_ids:
                return ViewLocation(
                    anchor.window_id,
                    anchor.pane_id,
                    anchor.tab_index,
                ), False
            return ViewLocation(
                anchor.window_id,
                self._window_active_pane_id(original),
                anchor.tab_index,
            ), False
        for window in self.windows.windows_by_recency:
            if window is source:
                continue
            window_id = getattr(window, "window_id", None)
            if not isinstance(window_id, str) or not window_id:
                continue
            return ViewLocation(
                window_id,
                self._window_active_pane_id(window),
                anchor.tab_index,
            ), False
        window = self.new_window()
        return ViewLocation(
            window.window_id,
            self._window_active_pane_id(window),
            anchor.tab_index,
        ), True

    def _transfer_view(
        self,
        view_id: str,
        target_window_id: str,
        *,
        pane_id: str | None = None,
        index: int | None = None,
        dock_return: object = _UNCHANGED_DOCK_RETURN,
        close_empty_source: bool = False,
        close_failed_target: bool = False,
    ):
        self._ensure_running()
        source = self.windows.window_for_view(view_id)
        if source is None:
            raise KeyError(view_id)
        target = dict(self.windows.items).get(target_window_id)
        if target is None:
            raise KeyError(target_window_id)
        if target is source:
            raise ValueError("source and destination windows must differ")
        locate = getattr(source, "view_location", None)
        take = getattr(source, "take_view_for_transfer", None)
        accept = getattr(target, "accept_transferred_view", None)
        if not callable(locate) or not callable(take):
            raise TypeError("source window cannot transfer views with a location")
        if not callable(accept):
            raise TypeError("target window cannot accept views")
        source_location = locate(view_id)
        if not isinstance(source_location, ViewLocation):
            raise TypeError("source window returned an invalid view location")
        validate = getattr(target, "validate_transfer_destination", None)
        selected_pane_id = pane_id
        if callable(validate):
            selected_pane_id = validate(pane_id)
        else:
            target_view_ids = getattr(target, "view_ids", ())
            if len(tuple(target_view_ids)) >= MAX_VIEWS:
                raise ValueError(f"pane tree cannot exceed {MAX_VIEWS} views")
        view = getattr(source, "view_for_id")(view_id)
        if view is None:
            raise KeyError(view_id)
        old_anchor = getattr(view, "dock_return", None)
        new_anchor = old_anchor if dock_return is _UNCHANGED_DOCK_RETURN else dock_return
        view = None
        try:
            view = take(view_id)
            setter = getattr(view, "set_dock_return", None)
            if not callable(setter):
                raise TypeError("view cannot retain a dock return location")
            setter(new_anchor)
            accept(view, pane_id=selected_pane_id, index=index)
        except Exception:
            if view is not None:
                target_resolver = getattr(target, "view_for_id", None)
                target_take = getattr(target, "take_view_for_transfer", None)
                if (
                    callable(target_resolver)
                    and target_resolver(view_id) is view
                    and callable(target_take)
                ):
                    target_take(view_id)
                setter = getattr(view, "set_dock_return", None)
                if callable(setter):
                    setter(old_anchor)
                rollback = getattr(source, "accept_transferred_view", None)
                if callable(rollback):
                    rollback(
                        view,
                        pane_id=source_location.pane_id,
                        index=source_location.tab_index,
                    )
                    self.set_active_view(source_location.window_id, view_id)
            if close_failed_target and not tuple(getattr(target, "view_ids", ())):
                close = getattr(target, "close", None)
                if callable(close):
                    close()
            raise
        self.set_active_view(target_window_id, view_id)
        if close_empty_source and not tuple(getattr(source, "view_ids", ())):
            close = getattr(source, "close", None)
            if callable(close):
                close()
        return target

    def undock_view(self, view_id: str):
        self._ensure_running()
        source = self.windows.window_for_view(view_id)
        if source is None:
            raise KeyError(view_id)
        view = getattr(source, "view_for_id")(view_id)
        if view is None:
            raise KeyError(view_id)
        if getattr(view, "dock_return", None) is not None:
            raise ValueError("view is already undocked")
        location = getattr(source, "view_location")(view_id)
        window = self.new_window()
        anchor = DockReturnRecord(
            location.window_id,
            location.pane_id,
            location.tab_index,
        )
        try:
            result = self._transfer_view(
                view_id,
                window.window_id,
                dock_return=anchor,
                close_failed_target=True,
            )
        except Exception:
            if window in self.windows.windows and not tuple(window.view_ids):
                window.close()
            raise
        result.show()
        return result

    def dock_view(self, view_id: str):
        self._ensure_running()
        source = self.windows.window_for_view(view_id)
        if source is None:
            raise KeyError(view_id)
        view = getattr(source, "view_for_id")(view_id)
        if view is None:
            raise KeyError(view_id)
        anchor = getattr(view, "dock_return", None)
        if not isinstance(anchor, DockReturnRecord):
            raise ValueError("view is not undocked")
        destination, created = self._resolve_dock_destination(source, anchor)
        return self._transfer_view(
            view_id,
            destination.window_id,
            pane_id=destination.pane_id,
            index=destination.tab_index,
            dock_return=None,
            close_empty_source=True,
            close_failed_target=created,
        )

    def move_view_to_new_window(self, view_id: str):
        return self.undock_view(view_id)

    def capture_session(self, clean_shutdown: bool = False) -> SessionSnapshot:
        return self._session_controller.capture(clean_shutdown)

    def _capture_session_snapshot(
        self,
        clean_shutdown: bool,
        *,
        excluded_document_ids: frozenset[str],
    ) -> SessionSnapshot:
        return self._session_controller.capture(
            clean_shutdown,
            excluded_document_ids=excluded_document_ids,
        )

    @property
    def restore_problems(self) -> tuple[object, ...]:
        return self._session_controller.problems

    def restore_shell(
        self,
        manifest: object,
        *,
        packs: tuple[object, ...] = (),
        find_replace_pack: object | None = None,
        pack_loader: Callable[[str], object] | None = None,
        pointer_repair_required: bool = False,
    ) -> None:
        self._session_controller.restore_shell(
            manifest,
            packs=packs,
            find_replace_pack=find_replace_pack,
            pack_loader=pack_loader,
            pointer_repair_required=pointer_repair_required,
        )

    def restore_active(self) -> object | None:
        return self._session_controller.restore_active()

    def schedule_lazy_restore(self) -> tuple[object, ...]:
        return self._session_controller.schedule_lazy_restore()

    def promote_restore(self, view_id: str) -> None:
        self._session_controller.promote_restore(view_id)

    def schedule_publication(self, clean_shutdown: bool = False) -> int:
        self._ensure_running()
        snapshot = self.capture_session(clean_shutdown)
        if self._publication_queue is None:
            self._publication_queue = _PublicationQueue(
                self.resources,
                self.sessions,
                self._publication_finished,
                lambda started_at: self.record_dogfood(
                    Operation.SESSION_PUBLISH,
                    Outcome.FAILED,
                    elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                ),
            )
        self._publication_generation += 1
        request = _PublicationRequest(
            self._publication_generation,
            snapshot,
            time.monotonic(),
        )
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
            self._last_quit_error = None
            self.record_dogfood(
                Operation.QUIT,
                Outcome.CANCELLED,
            )
            return False
        started_at = time.monotonic()
        try:
            self._execute_quit(plan)
        except _QuitExecutionError as error:
            self._last_quit_error = str(error)
            self._quitting = False
            self.record_dogfood(
                Operation.QUIT,
                Outcome.FAILED,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            )
            return False
        except Exception:
            self._last_quit_error = (
                "Could not preserve session state; Quit was cancelled."
            )
            self._quitting = False
            self.record_dogfood(
                Operation.QUIT,
                Outcome.FAILED,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            )
            return False
        self._last_quit_error = None
        return True

    def _execute_quit(self, plan: QuitPlan) -> None:
        quit_started_at = time.monotonic()
        self._quitting = True
        closed_documents = sum(
            bool(entry.view_ids) or entry.closed_at is None
            for entry in self.documents.entries
        )
        for decision in plan.decisions:
            if decision.choice is QuitChoice.SAVE:
                entry = self.documents.get(decision.document_id)
                save_started_at = time.monotonic()
                try:
                    entry.document.save()
                    if self._session_capture is None:
                        self._complete_saved_hash(decision.document_id)
                except Exception as error:
                    from uniti.core.file_identity import ExternalFileChangedError

                    self.record_dogfood(
                        Operation.SAVE,
                        (
                            Outcome.REFUSED_EXTERNAL_CHANGE
                            if isinstance(error, ExternalFileChangedError)
                            else Outcome.FAILED
                        ),
                        elapsed_ms=(time.monotonic() - save_started_at) * 1000.0,
                    )
                    raise _QuitExecutionError(
                        f"Could not save {entry.canonical_path.name}; Quit was cancelled."
                    ) from error
                outcome, durability = self._dogfood_durability(
                    entry.document.last_save_durability
                )
                self.record_dogfood(
                    Operation.SAVE,
                    outcome,
                    elapsed_ms=(time.monotonic() - save_started_at) * 1000.0,
                    durability=durability,
                )

        discarded_ids = frozenset(
            decision.document_id
            for decision in plan.decisions
            if decision.choice is QuitChoice.DISCARD
        )
        try:
            if self._publication_queue is not None:
                self._publication_queue.close_before_final_publication()
            final_snapshot = self._capture_session_snapshot(
                True,
                excluded_document_ids=discarded_ids,
            )
            self._publish_snapshot_durably(final_snapshot)
        except Exception as error:
            raise _QuitExecutionError(
                "Could not preserve session state; Quit was cancelled."
            ) from error

        for document_id in discarded_ids:
            entry = self.documents.get(document_id)
            for view_id in tuple(entry.view_ids):
                window = self.windows.window_for_view(view_id)
                close_view = getattr(window, "_close_view_id", None)
                if callable(close_view):
                    close_view(view_id, force=True)
            self.record_dogfood(Operation.DISCARD, Outcome.DISCARDED)

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
        for _index in range(closed_documents):
            self.record_dogfood(Operation.DOCUMENT_CLOSE, Outcome.SUCCESS)
        self.windows.clear()
        self._session_controller.shutdown()
        self.recovery.shutdown()
        self.record_dogfood(
            Operation.QUIT,
            Outcome.SUCCESS,
            elapsed_ms=(time.monotonic() - quit_started_at) * 1000.0,
        )
        self._finalize_dogfood()
        self.resources.shutdown(wait=True)
        if self._instance_service is not None:
            self._instance_service.close()
            self._instance_service = None
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
