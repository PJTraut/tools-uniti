"""Application-wide resource, cache, worker, and task ownership."""

from __future__ import annotations

import shutil
import tempfile
from collections.abc import Callable, Hashable
from dataclasses import dataclass, replace
from pathlib import Path

from .cache import CacheManager, CachePriority
from .memory import MemorySnapshot, PressureState, probe_memory
from .policy import (
    PerformancePolicy,
    ResourceState,
    classify_resource_state,
    load_performance_policy,
)
from .tasks import TaskCoordinator
from .telemetry import (
    HostResourceProfile,
    ResourceSampler,
    ResourceSnapshot,
    probe_host_profile,
)
from .workers import PriorityWorkerPool


_SEVERITY = {
    ResourceState.NORMAL: 0,
    ResourceState.BUSY: 1,
    ResourceState.CONSTRAINED: 2,
    ResourceState.CRITICAL: 3,
}
_LEGACY_PRESSURE = {
    ResourceState.NORMAL: PressureState.GREEN,
    ResourceState.BUSY: PressureState.YELLOW,
    ResourceState.CONSTRAINED: PressureState.ORANGE,
    ResourceState.CRITICAL: PressureState.RED,
}


@dataclass(frozen=True, slots=True)
class ResourceStatus:
    state: ResourceState
    physical_memory: int
    available_memory: int
    process_rss: int
    load_per_logical_core: float | None
    free_disk: int
    cache_used: int
    cache_budget: int
    cache_baseline: int
    active_workers: int
    active_worker_limit: int
    queued_tasks: int
    background_paused: bool
    captured_at: float


class ResourceManager:
    """Own all disposable cache, background capacity, and task state."""

    def __init__(
        self,
        *,
        max_workers: int | None = None,
        initial_snapshot: MemorySnapshot | None = None,
        policy: PerformancePolicy | None = None,
        sampler: ResourceSampler | None = None,
    ) -> None:
        self.policy = policy or load_performance_policy()
        memory = initial_snapshot or probe_memory()
        temp_root = Path(tempfile.gettempdir()).resolve()
        if sampler is None:
            profile = replace(
                probe_host_profile(temp_root),
                physical_memory=memory.physical,
            )
            self._sampler = ResourceSampler(profile)
        else:
            profile = sampler.profile
            self._sampler = sampler
        logical_cores = profile.logical_cores
        workers = max_workers
        if workers is None:
            workers = max(
                1,
                min(8, logical_cores - self.policy.resources.gui_core_reserve),
            )
        self._baseline_cache_cap = self._cache_cap(memory.physical)
        self._hard_cache_cap = self._baseline_cache_cap
        self._focused = True
        self.cache = CacheManager(budget_bytes=self._hard_cache_cap)
        self.workers = PriorityWorkerPool(
            max_workers=workers,
            thread_name_prefix="uniti-work",
        )
        try:
            free_disk = max(0, shutil.disk_usage(temp_root).free)
        except OSError:
            free_disk = 0
        initial_resources = ResourceSnapshot(
            physical_memory=memory.physical,
            available_memory=memory.effective_available,
            process_rss=0,
            load_per_logical_core=None,
            free_disk=free_disk,
            cache_used=0,
            active_workers=0,
            queued_tasks=0,
            captured_at=0.0,
        )
        self._state = classify_resource_state(initial_resources, self.policy)
        self._better_samples = 0
        self._entries: dict[
            tuple[Hashable, Hashable], tuple[Hashable, CachePriority, int]
        ] = {}
        self._inactive_owners: set[Hashable] = set()
        self._shutdown = False
        self._listeners: list[Callable[[ResourceStatus], None]] = []
        self._status = self._make_status(initial_resources)
        self.tasks = TaskCoordinator(self.workers, lambda: self._status)
        self._apply_state()
        self._status = self._make_status(initial_resources)

    def _cache_cap(self, physical_memory: int) -> int:
        limits = self.policy.resources
        absolute = limits.max_cache_mib << 20
        minimum = limits.min_visible_cache_mib << 20
        if physical_memory <= 0:
            return minimum
        proportional = int(physical_memory * limits.physical_ram_fraction)
        return max(minimum, min(absolute, proportional))

    def _balloon_ceiling(self) -> int:
        return int(self._baseline_cache_cap * self.policy.resources.balloon_max_multiplier)

    def _update_balloon(self, raw: ResourceSnapshot) -> None:
        """Opportunistically grow the effective cache ceiling, one tiered
        grab at a time, while focused and NORMAL; snap back to baseline
        immediately the moment either condition stops holding.

        Each grab is a fixed fraction (`balloon_grab_fraction`, e.g. 10%) of
        the *total* baseline-to-ceiling range, not of whatever happens to be
        available -- available memory can be many times the whole range, so
        sizing the step off it directly would jump straight to the ceiling
        in one sample instead of ramping up over several, defeating the
        point of a tiered grab. The step is still capped by what's actually
        free, as a defensive floor. Release is never tiered: losing focus or
        NORMAL drops straight back to baseline so a sudden need for RAM
        elsewhere is never left waiting on this cache to give it back
        gradually."""

        ceiling = self._balloon_ceiling()
        if self._focused and self._state is ResourceState.NORMAL:
            balloon_range = ceiling - self._baseline_cache_cap
            step = int(balloon_range * self.policy.resources.balloon_grab_fraction)
            step = max(0, min(step, max(0, raw.available_memory)))
            self._hard_cache_cap = min(ceiling, self._hard_cache_cap + step)
        else:
            self._hard_cache_cap = self._baseline_cache_cap
        self._hard_cache_cap = max(
            self._baseline_cache_cap, min(self._hard_cache_cap, ceiling)
        )

    def set_focused(self, focused: bool) -> None:
        """Record whether UNITI is the OS-focused application.

        Losing focus releases any ballooned cache back to baseline
        immediately (not gradually) on the next sample; grabbing more only
        ever resumes gradually, one grab at a time, once refocused."""

        focused = bool(focused)
        if focused == self._focused:
            return
        self._focused = focused
        if not focused and self._hard_cache_cap > self._baseline_cache_cap:
            self._hard_cache_cap = self._baseline_cache_cap
            self._apply_state()
            self._status = replace(
                self._status,
                cache_used=self.cache.used_bytes,
                cache_budget=self.cache.budget_bytes,
                cache_baseline=self._baseline_cache_cap,
            )
            self._notify()

    @property
    def state(self) -> ResourceState:
        return self._state

    @property
    def status(self) -> ResourceStatus:
        return self._status

    @property
    def host_profile(self) -> HostResourceProfile:
        return self._sampler.profile

    @property
    def pressure(self) -> PressureState:
        return _LEGACY_PRESSURE[self._state]

    @property
    def cache_budget_bytes(self) -> int:
        return self.cache.budget_bytes

    @property
    def worker_count(self) -> int:
        return self.workers.max_workers

    def sample_resources(self) -> ResourceSnapshot:
        """Collect one live local sample without changing resource policy."""

        return self._sampler.sample(
            cache_used_bytes=self.cache.used_bytes,
            active_workers=self.workers.active_count,
            queued_tasks=self.workers.queued_count,
        )

    def add_listener(self, listener: Callable[[ResourceStatus], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[ResourceStatus], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self) -> None:
        for listener in tuple(self._listeners):
            listener(self._status)

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
        for composite, (entry_owner, base_priority, _size) in tuple(
            self._entries.items()
        ):
            if entry_owner != owner:
                continue
            effective = base_priority if active else CachePriority.INACTIVE
            if not self.cache.set_priority(composite, effective):
                self._entries.pop(composite, None)

    def evict_owner(self, owner: Hashable) -> int:
        released = 0
        for composite, (entry_owner, _priority, size) in tuple(
            self._entries.items()
        ):
            if entry_owner != owner:
                continue
            if self.cache.remove(composite) is not None:
                released += size
            self._entries.pop(composite, None)
        self._inactive_owners.discard(owner)
        return released

    def _apply_state(self) -> None:
        pressure = self.policy.pressure
        if self._state is ResourceState.NORMAL:
            active_limit = self.workers.max_workers
            cache_target = self._hard_cache_cap
        elif self._state is ResourceState.BUSY:
            active_limit = max(
                1,
                int(self.workers.max_workers * pressure.busy_worker_fraction),
            )
            cache_target = int(self._hard_cache_cap * pressure.busy_cache_fraction)
        elif self._state is ResourceState.CONSTRAINED:
            active_limit = pressure.constrained_worker_limit
            cache_target = int(
                self._hard_cache_cap * pressure.constrained_cache_fraction
            )
        else:
            active_limit = 1
            cache_target = self.policy.resources.min_visible_cache_mib << 20
            self.cache.clear_disposable()
        self.workers.set_active_limit(active_limit)
        self.cache.set_budget(min(self._hard_cache_cap, max(0, cache_target)))

    def _make_status(self, snapshot: ResourceSnapshot) -> ResourceStatus:
        tasks = self.tasks.snapshot() if hasattr(self, "tasks") else None
        return ResourceStatus(
            state=self._state,
            physical_memory=snapshot.physical_memory,
            available_memory=snapshot.available_memory,
            process_rss=snapshot.process_rss,
            load_per_logical_core=snapshot.load_per_logical_core,
            free_disk=snapshot.free_disk,
            cache_used=self.cache.used_bytes,
            cache_budget=self.cache.budget_bytes,
            cache_baseline=self._baseline_cache_cap,
            active_workers=self.workers.active_count,
            active_worker_limit=self.workers.active_limit,
            queued_tasks=self.workers.queued_count,
            background_paused=False if tasks is None else tasks.background_paused,
            captured_at=snapshot.captured_at,
        )

    def observe_resources(
        self,
        snapshot: ResourceSnapshot | None = None,
    ) -> ResourceState:
        raw = snapshot or self.sample_resources()
        self._baseline_cache_cap = self._cache_cap(raw.physical_memory)
        candidate = classify_resource_state(raw, self.policy)
        current_level = _SEVERITY[self._state]
        candidate_level = _SEVERITY[candidate]
        if candidate_level > current_level:
            self._state = candidate
            self._better_samples = 0
        elif candidate_level < current_level:
            self._better_samples += 1
            if (
                self._better_samples
                >= self.policy.pressure.healthier_samples_before_recovery
            ):
                self._state = candidate
                self._better_samples = 0
        else:
            self._better_samples = 0
        self._update_balloon(raw)
        self._apply_state()
        self._status = self._make_status(raw)
        self._notify()
        return self._state

    def observe_memory(self, snapshot: MemorySnapshot | None = None) -> PressureState:
        memory = snapshot or probe_memory()
        current = self._status
        resource_snapshot = ResourceSnapshot(
            physical_memory=memory.physical,
            available_memory=memory.effective_available,
            process_rss=current.process_rss,
            load_per_logical_core=None,
            free_disk=current.free_disk,
            cache_used=self.cache.used_bytes,
            active_workers=self.workers.active_count,
            queued_tasks=self.workers.queued_count,
            captured_at=current.captured_at,
        )
        return _LEGACY_PRESSURE[self.observe_resources(resource_snapshot)]

    def pause_background(self, paused: bool) -> None:
        self.tasks.pause_background(paused)
        self._status = replace(self._status, background_paused=bool(paused))
        self._notify()

    def shutdown(self, *, wait: bool = True) -> None:
        if self._shutdown:
            return
        self._shutdown = True
        self.tasks.cancel_all()
        self.cache.clear_disposable()
        self._entries.clear()
        self.workers.shutdown(wait=wait, cancel_pending=True)
