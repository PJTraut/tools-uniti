"""Observable, cancellable task coordination without Qt dependencies."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, Protocol, TypeVar

from .cancel import CancellationToken, WorkCancelled
from .policy import ResourceState
from .workers import PriorityWorkerPool, WorkPriority


T = TypeVar("T")


class TaskAdmissionError(RuntimeError):
    """Raised before work starts when its declared resource estimate is unsafe."""


class TaskKind(StrEnum):
    SAVE = "save"
    RECOVERY = "recovery"
    NAVIGATION = "navigation"
    SEARCH = "search"
    REPLACE = "replace"
    INDEX = "index"
    EOL = "eol"
    PREFETCH = "prefetch"
    REGEX_ANALYSIS = "regex_analysis"
    CAPTURE_REPORT = "capture_report"


class TaskState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


_PRIORITIES = {
    TaskKind.SAVE: WorkPriority.INTERACTIVE,
    TaskKind.RECOVERY: WorkPriority.VISIBLE,
    TaskKind.NAVIGATION: WorkPriority.INTERACTIVE,
    TaskKind.SEARCH: WorkPriority.SEARCH,
    TaskKind.REPLACE: WorkPriority.SEARCH,
    TaskKind.INDEX: WorkPriority.INDEX,
    TaskKind.EOL: WorkPriority.INDEX,
    TaskKind.PREFETCH: WorkPriority.PREFETCH,
    TaskKind.REGEX_ANALYSIS: WorkPriority.INTERACTIVE,
    TaskKind.CAPTURE_REPORT: WorkPriority.VISIBLE,
}
_BACKGROUND_KINDS = {TaskKind.INDEX, TaskKind.EOL, TaskKind.PREFETCH}


@dataclass(frozen=True, slots=True)
class TaskSpec:
    task_id: str
    kind: TaskKind
    priority: WorkPriority
    foreground: bool
    document_key: str | None
    revision: int | None
    estimated_memory_bytes: int
    estimated_disk_bytes: int

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("task_id must be nonempty")
        if self.revision is not None and self.revision < 0:
            raise ValueError("revision must be non-negative")
        if self.estimated_memory_bytes < 0 or self.estimated_disk_bytes < 0:
            raise ValueError("task resource estimates must be non-negative")

    @classmethod
    def create(
        cls,
        kind: TaskKind,
        *,
        foreground: bool,
        priority: WorkPriority | None = None,
        document_key: str | None = None,
        revision: int | None = None,
        estimated_memory_bytes: int = 0,
        estimated_disk_bytes: int = 0,
    ) -> "TaskSpec":
        return cls(
            task_id=uuid.uuid4().hex,
            kind=kind,
            priority=_PRIORITIES[kind] if priority is None else priority,
            foreground=foreground,
            document_key=document_key,
            revision=revision,
            estimated_memory_bytes=estimated_memory_bytes,
            estimated_disk_bytes=estimated_disk_bytes,
        )


@dataclass(frozen=True, slots=True)
class TaskProgress:
    task_id: str
    phase: str
    completed: int
    total: int | None
    updated_at: float
    cancellable: bool

    def __post_init__(self) -> None:
        if self.completed < 0 or (self.total is not None and self.total < 0):
            raise ValueError("task progress values must be non-negative")
        if self.total is not None and self.completed > self.total:
            raise ValueError("completed progress must not exceed total")


@dataclass(frozen=True, slots=True)
class TaskSnapshot:
    spec: TaskSpec
    state: TaskState
    progress: TaskProgress | None


@dataclass(frozen=True, slots=True)
class TaskSystemSnapshot:
    generation: int
    background_paused: bool
    tasks: tuple[TaskSnapshot, ...]

    @property
    def active_count(self) -> int:
        return sum(task.state is TaskState.RUNNING for task in self.tasks)

    @property
    def queued_count(self) -> int:
        return sum(task.state is TaskState.QUEUED for task in self.tasks)


class ResourceCapacity(Protocol):
    state: ResourceState
    available_memory: int
    free_disk: int


class TaskHandle(Generic[T]):
    def __init__(
        self,
        spec: TaskSpec,
        token: CancellationToken,
        clock: Callable[[], float],
        changed: Callable[[], None],
    ) -> None:
        self.spec = spec
        self.token = token
        self._clock = clock
        self._changed = changed
        self._condition = threading.Condition()
        self._state = TaskState.QUEUED
        self._progress: TaskProgress | None = None
        self._future: Future[T] | None = None

    @property
    def future(self) -> Future[T]:
        if self._future is None:
            raise RuntimeError("task has not been submitted")
        return self._future

    @property
    def state(self) -> TaskState:
        with self._condition:
            return self._state

    @property
    def progress(self) -> TaskProgress | None:
        with self._condition:
            return self._progress

    @property
    def done(self) -> bool:
        return self._future is not None and self._future.done()

    def cancel(self) -> None:
        self.token.cancel()
        future = self._future
        if future is not None and future.cancel():
            self._set_state(TaskState.CANCELLED)

    def wait_for_progress(self, timeout: float | None = None) -> TaskProgress:
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._condition:
            while self._progress is None:
                if self.done:
                    raise TimeoutError("task completed without reporting progress")
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise TimeoutError("timed out waiting for task progress")
                self._condition.wait(remaining)
            return self._progress

    def _set_future(self, future: Future[T]) -> None:
        self._future = future
        future.add_done_callback(self._future_done)

    def _future_done(self, future: Future[T]) -> None:
        if future.cancelled():
            self._set_state(TaskState.CANCELLED)

    def _set_state(self, state: TaskState) -> None:
        with self._condition:
            self._state = state
            self._condition.notify_all()
        self._changed()

    def _set_progress(
        self,
        phase: str,
        completed: int,
        total: int | None,
        cancellable: bool,
    ) -> None:
        progress = TaskProgress(
            self.spec.task_id,
            phase,
            completed,
            total,
            self._clock(),
            cancellable,
        )
        with self._condition:
            self._progress = progress
            self._condition.notify_all()
        self._changed()

    def snapshot(self) -> TaskSnapshot:
        with self._condition:
            return TaskSnapshot(self.spec, self._state, self._progress)


class TaskContext:
    def __init__(self, handle: TaskHandle, token: CancellationToken) -> None:
        self._handle = handle
        self.token = token

    def report(
        self,
        phase: str,
        completed: int,
        total: int | None,
        *,
        cancellable: bool = True,
    ) -> None:
        self.check_cancelled()
        self._handle._set_progress(phase, completed, total, cancellable)

    def check_cancelled(self) -> None:
        self.token.raise_if_cancelled()


class TaskCoordinator:
    def __init__(
        self,
        pool: PriorityWorkerPool,
        capacity: Callable[[], ResourceCapacity],
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._pool = pool
        self._capacity = capacity
        self._clock = clock
        self._condition = threading.Condition()
        self._background_paused = False
        self._handles: dict[str, TaskHandle] = {}
        self._deferred: dict[
            str, tuple[TaskHandle, Callable[[TaskContext], object]]
        ] = {}
        self._generation = 0
        self._latest_snapshot = TaskSystemSnapshot(0, False, ())
        self._listeners: list[Callable[[], None]] = []

    def add_listener(self, listener: Callable[[], None]) -> None:
        with self._condition:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[], None]) -> None:
        with self._condition:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _notify(self) -> None:
        with self._condition:
            self._generation += 1
            self._latest_snapshot = TaskSystemSnapshot(
                self._generation,
                self._background_paused,
                tuple(handle.snapshot() for handle in self._handles.values()),
            )
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener()

    def submit(
        self,
        spec: TaskSpec,
        fn: Callable[[TaskContext], T],
    ) -> TaskHandle[T]:
        capacity = self._capacity()
        if spec.estimated_memory_bytes > capacity.available_memory:
            raise TaskAdmissionError("task memory estimate exceeds available memory")
        if spec.estimated_disk_bytes > capacity.free_disk:
            raise TaskAdmissionError("task disk estimate exceeds available disk")
        token = CancellationToken()
        handle: TaskHandle[T] = TaskHandle(spec, token, self._clock, self._notify)
        with self._condition:
            self._handles[spec.task_id] = handle
            deferred = self._background_paused and spec.kind in _BACKGROUND_KINDS
            if deferred:
                public_future: Future[T] = Future()
                handle._set_future(public_future)
                self._deferred[spec.task_id] = (handle, fn)
        if deferred:
            public_future.add_done_callback(
                lambda completed: self._remove_cancelled(handle, completed)
            )
        else:
            self._dispatch(handle, fn)
        self._notify()
        return handle

    def _dispatch(
        self,
        handle: TaskHandle[T],
        fn: Callable[[TaskContext], T],
        *,
        public_future: Future[T] | None = None,
    ) -> None:
        worker_future = self._pool.submit(
            handle.spec.priority,
            self._run,
            handle,
            fn,
        )
        if public_future is None:
            handle._set_future(worker_future)
            worker_future.add_done_callback(
                lambda completed: self._remove_cancelled(handle, completed)
            )
            return

        def transfer(completed: Future[T]) -> None:
            if public_future.done():
                return
            if completed.cancelled():
                public_future.cancel()
                return
            error = completed.exception()
            if error is not None:
                public_future.set_exception(error)
            else:
                public_future.set_result(completed.result())

        worker_future.add_done_callback(transfer)

    def _remove_cancelled(
        self,
        handle: TaskHandle[object],
        future: Future[object],
    ) -> None:
        """Forget a canceled future whose worker wrapper may never execute."""
        if not future.cancelled():
            return
        with self._condition:
            if self._handles.get(handle.spec.task_id) is not handle:
                return
            self._handles.pop(handle.spec.task_id, None)
            self._deferred.pop(handle.spec.task_id, None)
        self._notify()

    def _run(self, handle: TaskHandle[T], fn: Callable[[TaskContext], T]) -> T:
        try:
            handle.token.raise_if_cancelled()
            handle._set_state(TaskState.RUNNING)
            result = fn(TaskContext(handle, handle.token))
            handle.token.raise_if_cancelled()
        except WorkCancelled:
            handle._set_state(TaskState.CANCELLED)
            raise
        except BaseException:
            handle._set_state(TaskState.FAILED)
            raise
        else:
            handle._set_state(TaskState.COMPLETED)
            return result
        finally:
            with self._condition:
                self._handles.pop(handle.spec.task_id, None)
            self._notify()

    def pause_background(self, paused: bool) -> None:
        with self._condition:
            self._background_paused = bool(paused)
            self._condition.notify_all()
            deferred = tuple(self._deferred.values()) if not paused else ()
            if not paused:
                self._deferred.clear()
        for handle, fn in deferred:
            if handle.token.cancelled:
                with self._condition:
                    self._handles.pop(handle.spec.task_id, None)
                continue
            self._dispatch(handle, fn, public_future=handle.future)
        self._notify()

    def kind_is_paused(self, kind: TaskKind) -> bool:
        with self._condition:
            return self._background_paused and kind in _BACKGROUND_KINDS

    def snapshot(self) -> TaskSystemSnapshot:
        with self._condition:
            return self._latest_snapshot

    def cancel_all(self) -> None:
        with self._condition:
            handles = tuple(self._handles.values())
            self._condition.notify_all()
        for handle in handles:
            handle.cancel()


@dataclass(frozen=True, slots=True)
class _LatestTaskRequest(Generic[T]):
    generation: int
    spec: TaskSpec
    work: Callable[[TaskContext], T]
    discard: Callable[[], None]


class LatestTaskSlot(Generic[T]):
    """Serialize one active task and retain only the newest pending request."""

    def __init__(
        self,
        coordinator: TaskCoordinator,
        completed: Callable[[int, TaskHandle[T]], None],
    ) -> None:
        self._coordinator = coordinator
        self._completed = completed
        self._lock = threading.Lock()
        self._active: _LatestTaskRequest[T] | None = None
        self._active_handle: TaskHandle[T] | None = None
        self._active_cancel_requested = False
        self._pending: _LatestTaskRequest[T] | None = None
        self._closed = False

    def request(
        self,
        generation: int,
        spec: TaskSpec,
        work: Callable[[TaskContext], T],
        *,
        discard: Callable[[], None] = lambda: None,
    ) -> None:
        request = _LatestTaskRequest(generation, spec, work, discard)
        start = False
        reject = False
        old_pending: _LatestTaskRequest[T] | None = None
        active_handle: TaskHandle[T] | None = None
        with self._lock:
            if self._closed:
                reject = True
            elif self._active is None:
                self._active = request
                self._active_cancel_requested = False
                start = True
            else:
                old_pending = self._pending
                self._pending = request
                self._active_cancel_requested = True
                active_handle = self._active_handle
        if reject:
            request.discard()
            return
        if old_pending is not None:
            old_pending.discard()
        if active_handle is not None:
            active_handle.cancel()
        if start:
            self._submit(request)

    def cancel(self) -> None:
        with self._lock:
            pending = self._pending
            self._pending = None
            self._active_cancel_requested = self._active is not None
            active_handle = self._active_handle
        if pending is not None:
            pending.discard()
        if active_handle is not None:
            active_handle.cancel()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            pending = self._pending
            self._pending = None
            self._active_cancel_requested = self._active is not None
            active_handle = self._active_handle
        if pending is not None:
            pending.discard()
        if active_handle is not None:
            active_handle.cancel()

    def _submit(self, request: _LatestTaskRequest[T]) -> None:
        with self._lock:
            if self._active is not request:
                return
            if self._closed:
                self._active = None
                self._active_cancel_requested = False
                discard = True
            else:
                discard = False
        if discard:
            request.discard()
            return

        started = threading.Event()

        def run(context: TaskContext) -> T:
            started.set()
            return request.work(context)

        try:
            handle = self._coordinator.submit(request.spec, run)
        except TaskAdmissionError:
            self._rejected(request)
            return
        with self._lock:
            if self._active is not request:
                cancel_now = True
            else:
                self._active_handle = handle
                cancel_now = self._closed or self._active_cancel_requested
        handle.future.add_done_callback(
            lambda _future: self._finished(request, handle, started.is_set())
        )
        if cancel_now:
            handle.cancel()

    def _rejected(self, request: _LatestTaskRequest[T]) -> None:
        with self._lock:
            if self._active is not request:
                return
            self._active = None
            self._active_handle = None
            self._active_cancel_requested = False
            pending = None if self._closed else self._pending
            self._pending = None
            if pending is not None:
                self._active = pending
        request.discard()
        if pending is not None:
            self._submit(pending)

    def _finished(
        self,
        request: _LatestTaskRequest[T],
        handle: TaskHandle[T],
        started: bool,
    ) -> None:
        with self._lock:
            if self._active is not request:
                return
            self._active = None
            self._active_handle = None
            self._active_cancel_requested = False
            pending = None if self._closed else self._pending
            self._pending = None
            if pending is not None:
                self._active = pending
        try:
            if started:
                self._completed(request.generation, handle)
            else:
                request.discard()
        finally:
            if pending is not None:
                self._submit(pending)
