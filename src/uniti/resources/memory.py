"""Qt-independent memory budgeting and pressure classification."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import Enum

MIB = 1 << 20
GIB = 1 << 30


class PressureState(Enum):
    GREEN = "green"
    YELLOW = "yellow"
    ORANGE = "orange"
    RED = "red"


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    physical: int
    available: int
    reclaimable_cache: int = 0

    def __post_init__(self) -> None:
        if self.physical < 0 or self.available < 0 or self.reclaimable_cache < 0:
            raise ValueError("memory values must be non-negative")

    @property
    def effective_available(self) -> int:
        return self.available + self.reclaimable_cache


def automatic_cache_target(snapshot: MemorySnapshot) -> int:
    """Return Architecture v0.1's aggressive automatic cache target."""

    if snapshot.physical <= 0:
        return 128 * MIB
    reserve = max(2 * GIB, min(8 * GIB, snapshot.physical // 10))
    claimable = max(0, snapshot.effective_available - reserve)
    return min(snapshot.physical // 2, claimable * 7 // 10)


def pressure_state(snapshot: MemorySnapshot) -> PressureState:
    if snapshot.physical <= 0:
        return PressureState.RED
    ratio = snapshot.effective_available / snapshot.physical
    if ratio >= 0.25:
        return PressureState.GREEN
    if ratio >= 0.15:
        return PressureState.YELLOW
    if ratio >= 0.08:
        return PressureState.ORANGE
    return PressureState.RED


def _probe_with_psutil() -> MemorySnapshot | None:
    try:
        import psutil  # type: ignore[import-not-found]
    except ImportError:
        return None
    memory = psutil.virtual_memory()
    return MemorySnapshot(physical=int(memory.total), available=int(memory.available))


def _probe_with_sysconf() -> MemorySnapshot | None:
    try:
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
        physical_pages = int(os.sysconf("SC_PHYS_PAGES"))
        available_pages = int(os.sysconf("SC_AVPHYS_PAGES"))
    except (AttributeError, OSError, ValueError):
        return None
    if page_size <= 0 or physical_pages < 0 or available_pages < 0:
        return None
    return MemorySnapshot(
        physical=page_size * physical_pages,
        available=page_size * available_pages,
    )


def probe_memory(*, reclaimable_cache: int = 0) -> MemorySnapshot:
    """Probe host memory without making psutil a hard runtime dependency."""

    snapshot = _probe_with_psutil() or _probe_with_sysconf() or MemorySnapshot(0, 0)
    return MemorySnapshot(
        physical=snapshot.physical,
        available=snapshot.available,
        reclaimable_cache=reclaimable_cache,
    )
