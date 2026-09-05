"""Qt-independent memory budgeting and pressure classification."""

from __future__ import annotations

import ctypes
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

MIB = 1 << 20
GIB = 1 << 30


def current_process_handle_count(
    *,
    platform: str = sys.platform,
    kernel32: object | None = None,
    proc_fd_root: Path = Path("/proc/self/fd"),
) -> int | None:
    """Return a reliable current handle/descriptor count when available."""

    if platform == "win32":
        if kernel32 is None:
            loader = getattr(ctypes, "WinDLL", None)
            if loader is None:
                return None
            try:
                kernel32 = loader("kernel32", use_last_error=True)
            except (OSError, TypeError):
                return None
        try:
            get_current = kernel32.GetCurrentProcess
            get_current.argtypes = []
            get_current.restype = ctypes.c_void_p
            query = kernel32.GetProcessHandleCount
            query.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32)]
            query.restype = ctypes.c_int
            count = ctypes.c_uint32()
            if not query(get_current(), ctypes.byref(count)):
                return None
            return int(count.value)
        except (AttributeError, OSError, TypeError, ValueError):
            return None
    if platform.startswith("linux"):
        try:
            with os.scandir(proc_fd_root) as entries:
                return sum(1 for _entry in entries)
        except (OSError, TypeError, ValueError):
            return None
    return None


def release_unused_heap_pages(
    *,
    platform: str = sys.platform,
    library: object | None = None,
) -> bool:
    """Ask a supported native allocator to return unused pages to the OS."""

    if platform != "darwin" and not platform.startswith("linux"):
        return False
    if library is None:
        try:
            library = ctypes.CDLL(None)
        except (OSError, TypeError):
            return False
    try:
        if platform == "darwin":
            pressure_relief = library.malloc_zone_pressure_relief
            pressure_relief.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            pressure_relief.restype = ctypes.c_size_t
            pressure_relief(None, 0)
            return True
        malloc_trim = library.malloc_trim
        malloc_trim.argtypes = [ctypes.c_size_t]
        malloc_trim.restype = ctypes.c_int
        malloc_trim(0)
        return True
    except (AttributeError, OSError, TypeError, ValueError):
        return False


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


class _WindowsMemoryStatus(ctypes.Structure):
    _fields_ = (
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    )


def _probe_with_windows(
    *,
    platform: str = sys.platform,
    kernel32: object | None = None,
) -> MemorySnapshot | None:
    """Read Windows memory capacity through one bounded native API call."""

    if platform != "win32":
        return None
    if kernel32 is None:
        loader = getattr(ctypes, "WinDLL", None)
        if loader is None:
            return None
        try:
            kernel32 = loader("kernel32", use_last_error=True)
        except (OSError, TypeError):
            return None
    try:
        query = kernel32.GlobalMemoryStatusEx
        query.argtypes = [ctypes.POINTER(_WindowsMemoryStatus)]
        query.restype = ctypes.c_int
        status = _WindowsMemoryStatus()
        status.dwLength = ctypes.sizeof(status)
        if not query(ctypes.byref(status)):
            return None
        physical = int(status.ullTotalPhys)
        available = int(status.ullAvailPhys)
    except (AttributeError, OSError, TypeError, ValueError):
        return None
    if physical <= 0 or available > physical:
        return None
    return MemorySnapshot(physical=physical, available=available)


def _parse_macos_memory(
    physical_output: str,
    vm_stat_output: str,
) -> MemorySnapshot | None:
    try:
        physical = int(physical_output.strip())
    except ValueError:
        return None
    page_match = re.search(r"page size of (\d+) bytes", vm_stat_output)
    if physical <= 0 or page_match is None:
        return None
    page_size = int(page_match.group(1))
    counts: dict[str, int] = {}
    for name, raw_value in re.findall(r"^Pages ([a-z ]+):\s+(\d+)\.", vm_stat_output, re.MULTILINE):
        counts[name.strip()] = int(raw_value)
    required = ("free", "inactive", "speculative", "purgeable")
    if not all(name in counts for name in required):
        return None
    available_pages = sum(counts[name] for name in required)
    available = min(physical, available_pages * page_size)
    return MemorySnapshot(physical=physical, available=available)


def _probe_with_macos() -> MemorySnapshot | None:
    if sys.platform != "darwin":
        return None
    try:
        physical = subprocess.run(
            ["sysctl", "-n", "hw.memsize"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
            shell=False,
        )
        virtual = subprocess.run(
            ["vm_stat"],
            text=True,
            capture_output=True,
            check=False,
            timeout=5,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if physical.returncode != 0 or virtual.returncode != 0:
        return None
    return _parse_macos_memory(physical.stdout, virtual.stdout)


def probe_memory(*, reclaimable_cache: int = 0) -> MemorySnapshot:
    """Probe host memory without making psutil a hard runtime dependency."""

    snapshot = (
        _probe_with_windows()
        or _probe_with_psutil()
        or _probe_with_macos()
        or _probe_with_sysconf()
        or MemorySnapshot(0, 0)
    )
    return MemorySnapshot(
        physical=snapshot.physical,
        available=snapshot.available,
        reclaimable_cache=reclaimable_cache,
    )
