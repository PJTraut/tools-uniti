"""Application-wide cache, memory-pressure, and worker ownership."""

from __future__ import annotations

import os
from collections.abc import Hashable

from .cache import CacheManager, CachePriority
from .memory import (
    MemorySnapshot,
    PressureState,
    automatic_cache_target,
    pressure_state,
    probe_memory,
)
from .workers import PriorityWorkerPool

_SEVERITY = {
    PressureState.GREEN: 0,
    PressureState.YELLOW: 1,
    PressureState.ORANGE: 2,
    PressureState.RED: 3,
}


class ResourceManager:
    """Own all disposable application cache and background worker capacity."""

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        initial_snapshot: MemorySnapshot | None = None,
    ) -> None:
        snapshot = initial_snapshot or probe_memory()
        budget = automatic_cache_target(snapshot)
        self.cache = CacheManager(budget_bytes=budget)
        workers = max_workers
        if workers is None:
            cpu = os.cpu_count() or 2
            workers = max(2, min(8, cpu - 1 if cpu > 2 else 2))
        self.workers = PriorityWorkerPool(
            max_workers=workers,
            thread_name_prefix="uniti-work",
        )
        self._pressure = pressure_state(snapshot)
        self._better_samples = 0
        self._entries: dict[tuple[Hashable, Hashable], tuple[Hashable, CachePriority, int]] = {}
        self._inactive_owners: set[Hashable] = set()
        self._shutdown = False

    @property
    def pressure(self) -> PressureState:
        return self._pressure

    @property
    def cache_budget_bytes(self) -> int:
        return self.cache.budget_bytes

    @property
    def worker_count(self) -> int:
        return self.workers.max_workers

    @staticmethod
    def _composite(owner: Hashable, key: Hashable) -> tuple[Hashable, Hashable]:
        return owner, key

    def put_cache(
        self,
        owner: Hashable,
        key: Hashable,
        value: object,
        *,
        size_bytes: int,
        priority: CachePriority,
    ) -> None:
        composite = self._composite(owner, key)
        effective = CachePriority.INACTIVE if owner in self._inactive_owners else priority
        self.cache.put(composite, value, size_bytes=size_bytes, priority=effective)
        self._entries[composite] = (owner, priority, size_bytes)

    def get_cache(self, owner: Hashable, key: Hashable, default=None):
        composite = self._composite(owner, key)
        value = self.cache.get(composite, default)
        if value is default and composite in self._entries:
            self._entries.pop(composite, None)
        return value

    def remove_cache(self, owner: Hashable, key: Hashable, default=None):
        composite = self._composite(owner, key)
        self._entries.pop(composite, None)
        return self.cache.remove(composite, default)

    def set_owner_active(self, owner: Hashable, active: bool) -> None:
        if active:
            self._inactive_owners.discard(owner)
        else:
            self._inactive_owners.add(owner)
        for composite, (entry_owner, base_priority, _size) in tuple(self._entries.items()):
            if entry_owner != owner:
                continue
            effective = base_priority if active else CachePriority.INACTIVE
            if not self.cache.set_priority(composite, effective):
                self._entries.pop(composite, None)

    def evict_owner(self, owner: Hashable) -> int:
        released = 0
        for composite, (entry_owner, _priority, size) in tuple(self._entries.items()):
            if entry_owner != owner:
                continue
            if self.cache.remove(composite) is not None:
                released += size
            self._entries.pop(composite, None)
        self._inactive_owners.discard(owner)
        return released

    def observe_memory(self, snapshot: MemorySnapshot | None = None) -> PressureState:
        raw_snapshot = snapshot or probe_memory()
        effective = MemorySnapshot(
            physical=raw_snapshot.physical,
            available=raw_snapshot.available,
            reclaimable_cache=self.cache.used_bytes,
        )
        candidate = pressure_state(effective)
        current_level = _SEVERITY[self._pressure]
        candidate_level = _SEVERITY[candidate]
        if candidate_level > current_level:
            self._pressure = candidate
            self._better_samples = 0
        elif candidate_level < current_level:
            self._better_samples += 1
            if self._better_samples >= 2:
                self._pressure = candidate
                self._better_samples = 0
        else:
            self._better_samples = 0

        target = automatic_cache_target(effective)
        if self._pressure is PressureState.GREEN:
            self.cache.set_budget(target)
        elif self._pressure is PressureState.YELLOW:
            self.cache.set_budget(min(self.cache.budget_bytes, max(self.cache.used_bytes, target)))
        elif self._pressure is PressureState.ORANGE:
            self.cache.evict_to(min(self.cache.used_bytes, target // 2))
        else:
            self.cache.clear_disposable()
        return self._pressure

    def shutdown(self, *, wait: bool = True) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self.cache.clear_disposable()
        self._entries.clear()
        self.workers.shutdown(wait=wait, cancel_pending=True)
