"""Reusable real-application lifecycle primitives for sustained workloads."""

from __future__ import annotations

import gc
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from PySide6.QtCore import QCoreApplication, QEvent, QEventLoop
from PySide6.QtWidgets import QApplication

from benchmarks.checkpoints import collect_resource_checkpoint
from benchmarks.sustained_models import ResourceCheckpoint
from uniti.app.paths import AppPaths
from uniti.app.recovery_manager import RecoveryManager
from uniti.app.service import QuitChoice, UNITIService
from uniti.app.session_store import SessionStore
from uniti.app.settings import SettingsStore
from uniti.resources import (
    PerformancePolicy,
    ResourceManager,
    load_performance_policy,
    release_unused_heap_pages,
)


_EVENT_FLAGS = (
    QEventLoop.ProcessEventsFlag.AllEvents
    | QEventLoop.ProcessEventsFlag.WaitForMoreEvents
)

FINAL_SHUTDOWN_ORDER = (
    "views",
    "stores",
    "recovery_bindings",
    "windows",
    "documents",
    "tasks",
    "service",
)


class ApplicationWorkloadHarness:
    """Own one real UNITI composition for one sustained workload family."""

    def __init__(
        self,
        application_root: Path,
        *,
        policy: PerformancePolicy | None = None,
        operation_timeout_seconds: float | None = None,
    ) -> None:
        if not isinstance(application_root, Path):
            raise TypeError("application_root must be a Path")
        if application_root.is_symlink():
            raise ValueError("application_root must not be a symlink")
        root = application_root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError("application_root must resolve to a directory")
        selected_policy = policy or load_performance_policy()
        if not isinstance(selected_policy, PerformancePolicy):
            raise TypeError("policy must be a PerformancePolicy")
        timeout = (
            float(selected_policy.sustained.operation_timeout_seconds)
            if operation_timeout_seconds is None
            else float(operation_timeout_seconds)
        )
        if timeout <= 0:
            raise ValueError("operation timeout must be positive")

        self.application_root = root
        self.policy = selected_policy
        self.operation_timeout_seconds = timeout
        self.paths = AppPaths(
            config_dir=root / "config",
            data_dir=root / "data",
            state_dir=root / "state",
            cache_dir=root / "cache",
        )
        self.paths.ensure()
        self.application = QApplication.instance() or QApplication(
            ["uniti-sustained-workload"]
        )
        self.resources = ResourceManager(max_workers=2, policy=selected_policy)
        self.settings_store = SettingsStore(self.paths.settings_file)
        self.settings_store.prepare()
        self.session_store = SessionStore(self.paths.durable_session_dir)
        self.recovery_manager = RecoveryManager(
            self.paths.recovery_dir,
            resource_manager=self.resources,
        )
        self.service = UNITIService(
            resource_manager=self.resources,
            settings_store=self.settings_store,
            session_store=self.session_store,
            recovery_manager=self.recovery_manager,
            service_id=f"sustained-{uuid.uuid4().hex}",
            build_identity="a22-v1",
        )
        self.window = self.service.new_window()
        self._service_identity = id(self.service)
        self._shutdown_steps: tuple[str, ...] = ()

    @property
    def service_identity(self) -> int:
        return self._service_identity

    @property
    def shutdown_steps(self) -> tuple[str, ...]:
        return self._shutdown_steps

    def __enter__(self) -> "ApplicationWorkloadHarness":
        if not self.service.is_running:
            raise RuntimeError("UNITI workload harness is stopped")
        return self

    def __exit__(self, _exc_type, _exc, _traceback) -> None:
        self.shutdown()

    def _deadline(self, timeout_seconds: float | None) -> float:
        timeout = (
            self.operation_timeout_seconds
            if timeout_seconds is None
            else float(timeout_seconds)
        )
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        return time.monotonic() + timeout

    def pump_until(
        self,
        predicate: Callable[[], bool],
        *,
        timeout_seconds: float | None = None,
    ) -> None:
        """Pump queued Qt work until a condition succeeds or its deadline expires."""

        if not callable(predicate):
            raise TypeError("predicate must be callable")
        deadline = self._deadline(timeout_seconds)
        while not predicate():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("timed out waiting for Qt condition")
            self.application.processEvents(
                _EVENT_FLAGS,
                max(1, min(10, int(remaining * 1000))),
            )

    def await_operation(
        self,
        operation: object,
        *,
        timeout_seconds: float | None = None,
    ) -> Any:
        """Await a TaskHandle or FileOperationHandle while servicing Qt events."""

        task = getattr(operation, "task", operation)
        if not hasattr(task, "done"):
            raise TypeError("operation must expose task completion state")
        deadline = self._deadline(timeout_seconds)
        while not bool(getattr(task, "done")):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                cancel = getattr(operation, "cancel", None)
                if callable(cancel):
                    cancel()
                raise TimeoutError("timed out waiting for UNITI operation")
            self.application.processEvents(
                _EVENT_FLAGS,
                max(1, min(10, int(remaining * 1000))),
            )
        future = getattr(task, "future", None)
        if future is None or not callable(getattr(future, "result", None)):
            raise TypeError("completed operation must expose a result future")
        result = future.result()
        self.application.processEvents(_EVENT_FLAGS, 10)
        return result

    def _owned_fixture(self, fixture_path: Path) -> Path:
        if not isinstance(fixture_path, Path):
            raise TypeError("fixture_path must be a Path")
        resolved = fixture_path.resolve(strict=True)
        if not resolved.is_file() or not resolved.is_relative_to(self.application_root):
            raise ValueError("fixture must be a file beneath application_root")
        return resolved

    def open_owned_fixture(self, fixture_path: Path):
        """Open a benchmark-owned file through the public main-window API."""

        if not self.service.is_running:
            raise RuntimeError("UNITI workload harness is stopped")
        selected_window = self.service.most_recent_window
        if selected_window is None:
            selected_window = self.service.new_window()
        view = selected_window.open_path(self._owned_fixture(fixture_path))
        if view is None:
            raise RuntimeError("owned fixture open was cancelled")
        self.pump_until(
            lambda: self.service.documents.entry_for_view(view.view_id) is not None
        )
        return view

    def capture_checkpoint(
        self,
        cycle: int,
        *,
        result_stores: int = 0,
        replacement_plans: int = 0,
        snapshots: int = 0,
    ) -> ResourceCheckpoint:
        def resources_idle() -> bool:
            tasks = self.resources.tasks.snapshot()
            return (
                tasks.active_count == 0
                and tasks.queued_count == 0
                and self.resources.workers.active_count == 0
            )

        for _pass in range(2):
            QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
            self.application.processEvents()
        self.pump_until(resources_idle)
        gc.collect()
        self.pump_until(resources_idle)
        release_unused_heap_pages()
        return collect_resource_checkpoint(
            cycle,
            service=self.service,
            owned_root=self.application_root,
            policy=self.policy,
            tracked_counts={
                "result_stores": result_stores,
                "replacement_plans": replacement_plans,
                "snapshots": snapshots,
            },
        )

    def close_cycle(self) -> bool:
        """Close every view while retaining clean document authority in the service."""

        for _window_id, window in tuple(self.service.windows.items):
            if not window.close_all_documents(force=True):
                return False
        self.pump_until(lambda: not tuple(self.service.windows.ordered_view_ids))
        return True

    def shutdown(self) -> None:
        """Use UNITI's public Quit authority, then verify every owned layer is idle."""

        if self._shutdown_steps:
            return
        if not self.service.is_running:
            self._shutdown_steps = FINAL_SHUTDOWN_ORDER
            return
        if not self.close_cycle():
            raise RuntimeError("UNITI workload views could not be closed")
        if not self.service.request_quit(lambda _entry: QuitChoice.DISCARD):
            raise RuntimeError(self.service.last_quit_error or "UNITI Quit was cancelled")
        self.application.processEvents(_EVENT_FLAGS, 10)
        task_snapshot = self.resources.tasks.snapshot()
        if (
            self.service.documents.count
            or self.service.windows.count
            or task_snapshot.active_count
            or task_snapshot.queued_count
            or self.recovery_manager.diagnostics()
            or self.service.is_running
        ):
            raise RuntimeError("UNITI workload teardown left owned application state")
        self._shutdown_steps = FINAL_SHUTDOWN_ORDER


__all__ = ["ApplicationWorkloadHarness", "FINAL_SHUTDOWN_ORDER"]
