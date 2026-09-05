"""Process-lifetime scheduling for bounded local dogfood evidence."""

from __future__ import annotations

import threading
from collections.abc import Callable
from datetime import date
from pathlib import Path
from typing import Any

from uniti.resources.tasks import (
    TaskHandle,
    TaskKind,
    TaskSpec,
    WorkPriority,
)

from .dogfood import (
    Durability,
    Operation,
    Outcome,
    ResourceBand,
    latency_bucket,
    merge_dogfood_snapshots,
)
from .dogfood_store import StoreFailureCode, StoreStatus


class DogfoodRuntime:
    """Own recorder cadence and worker-only store access for one process."""

    def __init__(
        self,
        resource_manager: object,
        recorder: object | None,
        store: object | None,
        *,
        publish_interval_seconds: int,
    ) -> None:
        if (recorder is None) != (store is None):
            raise TypeError("dogfood recorder and store must be provided together")
        if recorder is not None and not callable(getattr(recorder, "snapshot", None)):
            raise TypeError("dogfood recorder must provide snapshot()")
        if store is not None and any(
            not callable(getattr(store, method, None))
            for method in ("publish", "export", "clear", "status")
        ):
            raise TypeError("dogfood store must provide publication controls")
        if (
            type(publish_interval_seconds) is not int
            or not 1 <= publish_interval_seconds <= 3600
        ):
            raise ValueError("dogfood publication interval is invalid")
        self._resources = resource_manager
        self._recorder = recorder
        self._store = store
        self._publish_interval_seconds = publish_interval_seconds
        self._lock = threading.RLock()
        self._io_lock = threading.Lock()
        self._task: TaskHandle[Any] | None = None
        self._timer = None
        self._closed = False
        self._baseline = None
        self._baseline_loaded = False
        self._status = StoreStatus(store is not None, 0, 0, None, None, None)
        self._start()

    @property
    def recorder(self) -> object | None:
        return self._recorder

    @property
    def store(self) -> object | None:
        return self._store

    @property
    def active(self) -> bool:
        with self._lock:
            return self._recorder is not None and not self._closed

    @property
    def status(self) -> StoreStatus:
        with self._lock:
            return self._status

    def observe(
        self,
        operation: Operation,
        outcome: Outcome,
        *,
        elapsed_ms: float | None = None,
        durability: Durability = Durability.NOT_APPLICABLE,
        peak_resource: ResourceBand = ResourceBand.NORMAL,
        retained_resource: ResourceBand = ResourceBand.NORMAL,
    ) -> None:
        """Update in-memory aggregates without allowing telemetry to affect work."""

        if (
            not isinstance(operation, Operation)
            or not isinstance(outcome, Outcome)
            or not isinstance(durability, Durability)
            or not isinstance(peak_resource, ResourceBand)
            or not isinstance(retained_resource, ResourceBand)
        ):
            return
        if elapsed_ms is not None:
            try:
                latency_bucket(elapsed_ms)
            except (TypeError, ValueError):
                return
        with self._lock:
            recorder = None if self._closed else self._recorder
        observe = getattr(recorder, "observe", None)
        if not callable(observe):
            return
        try:
            observe(
                operation,
                outcome,
                elapsed_ms=elapsed_ms,
                durability=durability,
                peak_resource=peak_resource,
                retained_resource=retained_resource,
            )
        except Exception:
            # Aggregate evidence is explicitly subordinate to editor behavior.
            return

    def _start(self) -> None:
        if self._recorder is None:
            return
        self._task = self._submit(
            self._refresh_status_worker,
            kind=TaskKind.PREFETCH,
            foreground=False,
        )
        if self._task is None:
            return
        try:
            from PySide6.QtCore import QTimer
            from PySide6.QtWidgets import QApplication

            app = QApplication.instance()
            if not isinstance(app, QApplication):
                return
            timer = QTimer()
            timer.setInterval(self._publish_interval_seconds * 1000)
            timer.timeout.connect(self.schedule_publication)
            timer.start()
            self._timer = timer
        except (ImportError, ModuleNotFoundError):
            return

    def _submit(
        self,
        work: Callable[[object], object],
        *,
        kind: TaskKind,
        foreground: bool,
    ) -> TaskHandle[Any] | None:
        coordinator = getattr(self._resources, "tasks", None)
        submit = getattr(coordinator, "submit", None)
        if not callable(submit):
            self._mark_unavailable()
            return None
        try:
            handle = submit(
                TaskSpec.create(
                    kind,
                    foreground=foreground,
                    priority=WorkPriority.PREFETCH,
                ),
                work,
            )
        except Exception:
            self._mark_unavailable()
            return None
        handle.future.add_done_callback(
            lambda _future, selected=handle: self._task_finished(selected)
        )
        return handle

    def _task_finished(self, handle: TaskHandle[Any]) -> None:
        try:
            handle.future.result()
        except Exception:
            self._mark_unavailable()
        with self._lock:
            if self._task is handle:
                self._task = None

    def _mark_unavailable(self) -> None:
        with self._lock:
            current = self._status
            self._status = StoreStatus(
                False,
                current.segment_count,
                current.byte_count,
                current.oldest_day,
                current.newest_day,
                StoreFailureCode.INVALID_STATE,
            )

    def _set_status(self, status: object) -> None:
        if not isinstance(status, StoreStatus):
            self._mark_unavailable()
            return
        with self._lock:
            self._status = status

    def _load_baseline_worker(self) -> None:
        if self._baseline_loaded:
            return
        self._baseline_loaded = True
        load = getattr(self._store, "load_segments", None)
        if not callable(load) or self._recorder is None:
            return
        try:
            segments = tuple(load())
            current = self._recorder.snapshot()
        except Exception:
            return
        if not segments:
            return
        candidate = segments[-1]
        if (
            getattr(candidate, "day", None) == getattr(current, "day", None)
            and getattr(candidate, "host", None) == getattr(current, "host", None)
        ):
            self._baseline = candidate

    def _snapshots_worker(self) -> tuple[object, ...]:
        if self._recorder is None:
            raise RuntimeError("dogfood recorder is unavailable")
        self._load_baseline_worker()
        rollover = getattr(self._recorder, "rollover", None)
        completed = rollover(date.today()) if callable(rollover) else None
        current = self._recorder.snapshot()
        baseline = self._baseline
        if completed is None:
            if baseline is not None:
                current = merge_dogfood_snapshots(baseline, current)
            return (current,)
        if baseline is not None:
            completed = merge_dogfood_snapshots(baseline, completed)
        self._baseline = None
        return completed, current

    def _refresh_status_worker(self, _context: object) -> object:
        if self._store is None:
            raise RuntimeError("dogfood store is unavailable")
        with self._io_lock:
            self._load_baseline_worker()
            status = self._store.status()
        self._set_status(status)
        return status

    def _publish_worker(self, _context: object) -> object:
        if self._store is None:
            raise RuntimeError("dogfood store is unavailable")
        with self._io_lock:
            result = None
            for snapshot in self._snapshots_worker():
                result = self._store.publish(snapshot)
                if getattr(result, "published", True) is False:
                    break
            status = self._store.status()
        self._set_status(status)
        return result

    def schedule_publication(self) -> TaskHandle[Any] | None:
        with self._lock:
            if self._closed or self._recorder is None:
                return None
            active = self._task
            if active is not None and not active.done:
                return active
            handle = self._submit(
                self._publish_worker,
                kind=TaskKind.PREFETCH,
                foreground=False,
            )
            self._task = handle
            return handle

    def export(self, destination: Path) -> TaskHandle[Any]:
        selected = Path(destination)
        if not selected.is_absolute():
            raise ValueError("dogfood export destination must be absolute")
        with self._lock:
            if self._closed or self._store is None:
                raise RuntimeError("dogfood evidence is unavailable")

        def export_worker(_context: object) -> object:
            assert self._store is not None
            with self._io_lock:
                for snapshot in self._snapshots_worker():
                    publication = self._store.publish(snapshot)
                    if getattr(publication, "published", True) is False:
                        break
                result = self._store.export(selected)
                status = self._store.status()
            self._set_status(status)
            return result

        handle = self._submit(
            export_worker,
            kind=TaskKind.CAPTURE_REPORT,
            foreground=True,
        )
        if handle is None:
            raise RuntimeError("dogfood evidence is unavailable")
        return handle

    def clear(self) -> TaskHandle[Any]:
        with self._lock:
            if self._closed or self._store is None:
                raise RuntimeError("dogfood evidence is unavailable")

        def clear_worker(_context: object) -> object:
            assert self._store is not None
            with self._io_lock:
                result = self._store.clear()
                reset = getattr(self._recorder, "reset", None)
                if callable(reset):
                    reset(day=date.today())
                self._baseline = None
                self._baseline_loaded = True
                status = self._store.status()
            self._set_status(status)
            return result

        handle = self._submit(
            clear_worker,
            kind=TaskKind.CAPTURE_REPORT,
            foreground=True,
        )
        if handle is None:
            raise RuntimeError("dogfood evidence is unavailable")
        return handle

    def _stop_timer(self) -> None:
        timer = self._timer
        self._timer = None
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            active = self._task
            self._task = None
        self._stop_timer()
        if active is not None and not active.done:
            active.cancel()

    def finalize(self) -> None:
        with self._lock:
            if self._closed or self._recorder is None:
                return
            self._closed = True
            active = self._task
            self._task = None
        self._stop_timer()
        if active is not None and not active.done:
            coordinator = getattr(self._resources, "tasks", None)
            paused = getattr(coordinator, "kind_is_paused", None)
            if callable(paused) and paused(TaskKind.PREFETCH):
                active.cancel()
            try:
                active.future.result()
            except Exception:
                pass
        handle = self._submit(
            self._publish_worker,
            kind=TaskKind.CAPTURE_REPORT,
            foreground=False,
        )
        if handle is None:
            return
        try:
            handle.future.result()
        except Exception:
            pass


__all__ = ["DogfoodRuntime"]
