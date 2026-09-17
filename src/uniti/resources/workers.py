"""Bounded priority worker scheduling without Qt dependencies."""

from __future__ import annotations

import itertools
import threading
from collections import OrderedDict, deque
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Any, Callable

from .cancel import CancellationToken


class WorkPriority(IntEnum):
    INTERACTIVE = 0
    VISIBLE = 10
    SEARCH = 20
    INDEX = 30
    SYNTAX = 40
    PREFETCH = 50


@dataclass(slots=True)
class _WorkItem:
    priority: int
    sequence: int
    future: Future | None
    fn: Callable[..., Any] | None
    args: tuple[Any, ...] = ()
    kwargs: dict[str, Any] = field(default_factory=dict)
    token: CancellationToken | None = None
    document_key: str | None = None


class PriorityWorkerPool:
    """Small priority queue feeding a fixed number of daemon worker threads."""

    _STOP_PRIORITY = 1_000_000

    def __init__(self, *, max_workers: int, thread_name_prefix: str = "uniti") -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        # {priority: {document_key: deque[_WorkItem]}}. Each priority tier's
        # OrderedDict round-robins across the documents with pending work at
        # that tier: a pop takes the front document's oldest item, then
        # rotates that document to the back so a burst from one document
        # can't starve another's item at the same tier (BF-040).
        self._tiers: dict[int, OrderedDict[str | None, deque[_WorkItem]]] = {}
        self._sequence = itertools.count()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._shutdown = False
        self._cancel_pending_on_shutdown = False
        self._max_workers = max_workers
        self._active_limit = max_workers
        self._active_count = 0
        self._queued_count = 0
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

    @property
    def active_limit(self) -> int:
        with self._lock:
            return self._active_limit

    @property
    def active_count(self) -> int:
        with self._lock:
            return self._active_count

    @property
    def queued_count(self) -> int:
        with self._lock:
            return self._queued_count

    def set_active_limit(self, limit: int) -> None:
        with self._condition:
            self._active_limit = min(self._max_workers, max(1, int(limit)))
            self._condition.notify_all()

    def submit(
        self,
        priority: WorkPriority,
        fn: Callable[..., Any],
        /,
        *args: Any,
        token: CancellationToken | None = None,
        document_key: str | None = None,
        **kwargs: Any,
    ) -> Future:
        if not callable(fn):
            raise TypeError("fn must be callable")
        with self._condition:
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
                document_key=document_key,
            )
            self._queued_count += 1
            self._enqueue_locked(item)
            self._condition.notify_all()
            return future

    def _enqueue_locked(self, item: _WorkItem) -> None:
        tier = self._tiers.setdefault(item.priority, OrderedDict())
        bucket = tier.get(item.document_key)
        if bucket is None:
            bucket = deque()
            tier[item.document_key] = bucket
        bucket.append(item)

    def _pop_next_locked(self) -> _WorkItem:
        priority = min(self._tiers)
        tier = self._tiers[priority]
        key = next(iter(tier))
        bucket = tier[key]
        item = bucket.popleft()
        if bucket:
            tier.move_to_end(key)
        else:
            del tier[key]
            if not tier:
                del self._tiers[priority]
        return item

    def _worker(self) -> None:
        while True:
            with self._condition:
                while not self._tiers:
                    self._condition.wait()
                item = self._pop_next_locked()
            active = False
            try:
                if item.fn is None:
                    return
                future = item.future
                assert future is not None
                with self._condition:
                    while (
                        self._active_count >= self._active_limit
                        and not self._cancel_pending_on_shutdown
                    ):
                        self._condition.wait()
                    self._queued_count -= 1
                    if self._cancel_pending_on_shutdown:
                        future.cancel()
                        continue
                    self._active_count += 1
                    active = True
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
                if item.fn is not None:
                    with self._condition:
                        if active:
                            self._active_count -= 1
                        self._condition.notify_all()

    def shutdown(self, *, wait: bool = True, cancel_pending: bool = False) -> None:
        with self._condition:
            if self._shutdown:
                threads = tuple(self._threads)
            else:
                self._shutdown = True
                self._cancel_pending_on_shutdown = cancel_pending
                if cancel_pending:
                    for tier in self._tiers.values():
                        for bucket in tier.values():
                            for item in bucket:
                                if item.future is not None:
                                    item.future.cancel()
                                    self._queued_count -= 1
                    self._tiers.clear()
                for _ in self._threads:
                    self._enqueue_locked(
                        _WorkItem(
                            priority=self._STOP_PRIORITY,
                            sequence=next(self._sequence),
                            future=None,
                            fn=None,
                        )
                    )
                threads = tuple(self._threads)
                self._condition.notify_all()
        if wait:
            for thread in threads:
                thread.join()
