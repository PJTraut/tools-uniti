"""Byte-accounted disposable cache primitives."""

from __future__ import annotations

import itertools
import threading
from dataclasses import dataclass
from enum import IntEnum
from typing import Hashable


class CachePriority(IntEnum):
    VISIBLE = 1
    NEARBY = 2
    SEARCH = 3
    INDEX = 4
    RECENT = 5
    INACTIVE = 6
    STALE = 7


@dataclass(slots=True)
class _CacheEntry:
    value: object
    size_bytes: int
    priority: CachePriority
    last_access: int


class CacheManager:
    """Thread-safe cache with priority-first, LRU-within-priority eviction."""

    def __init__(self, *, budget_bytes: int) -> None:
        if budget_bytes < 0:
            raise ValueError("budget_bytes must be non-negative")
        self._budget_bytes = budget_bytes
        self._used_bytes = 0
        self._entries: dict[Hashable, _CacheEntry] = {}
        self._clock = itertools.count()
        self._lock = threading.RLock()

    @property
    def budget_bytes(self) -> int:
        return self._budget_bytes

    @property
    def used_bytes(self) -> int:
        with self._lock:
            return self._used_bytes

    def put(
        self,
        key: Hashable,
        value: object,
        *,
        size_bytes: int,
        priority: CachePriority,
    ) -> None:
        if size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        with self._lock:
            previous = self._entries.pop(key, None)
            if previous is not None:
                self._used_bytes -= previous.size_bytes
            self._entries[key] = _CacheEntry(
                value=value,
                size_bytes=size_bytes,
                priority=priority,
                last_access=next(self._clock),
            )
            self._used_bytes += size_bytes
            self._evict_locked(self._budget_bytes)

    def get(self, key: Hashable, default=None):
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                return default
            entry.last_access = next(self._clock)
            return entry.value

    def remove(self, key: Hashable, default=None):
        with self._lock:
            entry = self._entries.pop(key, None)
            if entry is None:
                return default
            self._used_bytes -= entry.size_bytes
            return entry.value

    def evict_to(self, target_bytes: int) -> int:
        if target_bytes < 0:
            raise ValueError("target_bytes must be non-negative")
        with self._lock:
            return self._evict_locked(target_bytes)

    def _evict_locked(self, target_bytes: int) -> int:
        evicted = 0
        while self._used_bytes > target_bytes and self._entries:
            key, entry = max(
                self._entries.items(),
                key=lambda item: (int(item[1].priority), -item[1].last_access),
            )
            del self._entries[key]
            self._used_bytes -= entry.size_bytes
            evicted += entry.size_bytes
        return evicted

    def clear_disposable(self) -> int:
        with self._lock:
            released = self._used_bytes
            self._entries.clear()
            self._used_bytes = 0
            return released
