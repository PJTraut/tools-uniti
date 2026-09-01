"""Bounded priority worker scheduling without Qt dependencies."""

from __future__ import annotations

import itertools
import threading
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import IntEnum
from queue import Empty, PriorityQueue
from typing import Any, Callable

from .cancel import CancellationToken


class WorkPriority(IntEnum):
    INTERACTIVE = 0
    VISIBLE = 10
    SEARCH = 20
    INDEX = 30
    SYNTAX = 40
    PREFETCH = 50


@dataclass(order=True, slots=True)
class _WorkItem:
    priority: int
    sequence: int
    future: Future | None = field(compare=False)
    fn: Callable[..., Any] | None = field(compare=False)
    args: tuple[Any, ...] = field(compare=False, default=())
    kwargs: dict[str, Any] = field(compare=False, default_factory=dict)
    token: CancellationToken | None = field(compare=False, default=None)


class PriorityWorkerPool:
    """Small priority queue feeding a fixed number of daemon worker threads."""

    _STOP_PRIORITY = 1_000_000

    def __init__(self, *, max_workers: int, thread_name_prefix: str = "uniti") -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        self._queue: PriorityQueue[_WorkItem] = PriorityQueue()
        self._sequence = itertools.count()
        self._lock = threading.Lock()
        self._shutdown = False
        self._max_workers = max_workers
        self._threads = [
            threading.Thread(
                target=self._worker,
                name=f"{thread_name_prefix}-{index + 1}",
                daemon=True,
            )
            for index in range(max_workers)
        ]
        for thread in self._threads:
            thread.start()

    @property
    def max_workers(self) -> int:
        return self._max_workers

    def submit(
        self,
        priority: WorkPriority,
        fn: Callable[..., Any],
        /,
        *args: Any,
        token: CancellationToken | None = None,
        **kwargs: Any,
    ) -> Future:
        if not callable(fn):
            raise TypeError("fn must be callable")
        with self._lock:
            if self._shutdown:
                raise RuntimeError("worker pool is shut down")
            future: Future = Future()
            item = _WorkItem(
                priority=int(priority),
                sequence=next(self._sequence),
                future=future,
                fn=fn,
                args=args,
                kwargs=kwargs,
                token=token,
            )
            self._queue.put(item)
            return future

    def _worker(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item.fn is None:
                    return
                future = item.future
                assert future is not None
                if not future.set_running_or_notify_cancel():
                    continue
                try:
                    if item.token is not None:
                        item.token.raise_if_cancelled()
                    result = item.fn(*item.args, **item.kwargs)
                except BaseException as exc:
                    future.set_exception(exc)
                else:
                    future.set_result(result)
            finally:
                self._queue.task_done()

    def shutdown(self, *, wait: bool = True, cancel_pending: bool = False) -> None:
        with self._lock:
            if self._shutdown:
                threads = tuple(self._threads)
            else:
                self._shutdown = True
                if cancel_pending:
                    while True:
                        try:
                            item = self._queue.get_nowait()
                        except Empty:
                            break
                        try:
                            if item.future is not None:
                                item.future.cancel()
                        finally:
                            self._queue.task_done()
                for _ in self._threads:
                    self._queue.put(
                        _WorkItem(
                            priority=self._STOP_PRIORITY,
                            sequence=next(self._sequence),
                            future=None,
                            fn=None,
                        )
                    )
                threads = tuple(self._threads)
        if wait:
            for thread in threads:
                thread.join()
