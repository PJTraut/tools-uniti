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
        self._listeners: list[Callable[[TaskSystemSnapshot], None]] = []

    def add_listener(self, listener: Callable[[TaskSystemSnapshot], None]) -> None:
        with self._condition:
            if listener not in self._listeners:
                self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[TaskSystemSnapshot], None]) -> None:
        with self._condition:
            if listener in self._listeners:
                self._listeners.remove(listener)

    def _notify(self) -> None:
        snapshot = self.snapshot()
        with self._condition:
            listeners = tuple(self._listeners)
        for listener in listeners:
            listener(snapshot)

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
            deferred = self._background_paused and not spec.foreground
            if deferred:
                public_future: Future[T] = Future()
                handle._set_future(public_future)
                self._deferred[spec.task_id] = (handle, fn)
        if not deferred:
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
            token=handle.token,
        )
        if public_future is None:
            handle._set_future(worker_future)
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
            paused = self._background_paused
            handles = tuple(self._handles.values())
        return TaskSystemSnapshot(paused, tuple(handle.snapshot() for handle in handles))

    def cancel_all(self) -> None:
        with self._condition:
            handles = tuple(self._handles.values())
            self._condition.notify_all()
        for handle in handles:
            handle.cancel()
