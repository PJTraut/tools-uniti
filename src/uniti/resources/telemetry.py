"""Local-only host profiling and lightweight live resource samples."""

from __future__ import annotations

import math
import os
import platform as platform_module
import shutil
import subprocess
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .memory import MemorySnapshot, probe_memory


@dataclass(frozen=True, slots=True)
class HostResourceProfile:
    cpu_model: str
    architecture: str
    physical_cores: int
    logical_cores: int
    physical_memory: int
    platform: str
    platform_release: str
    temp_root: Path

    def __post_init__(self) -> None:
        if self.physical_cores < 1 or self.logical_cores < 1:
            raise ValueError("core counts must be positive")
        if self.physical_cores > self.logical_cores:
            raise ValueError("physical cores must not exceed logical cores")
        if self.physical_memory < 0:
            raise ValueError("physical memory must be non-negative")
        if not self.cpu_model or not self.architecture:
            raise ValueError("CPU model and architecture must be nonempty")


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    physical_memory: int
    available_memory: int
    process_rss: int
    load_per_logical_core: float | None
    free_disk: int
    cache_used: int
    active_workers: int
    queued_tasks: int
    captured_at: float

    def __post_init__(self) -> None:
        values = (
            self.physical_memory,
            self.available_memory,
            self.process_rss,
            self.free_disk,
            self.cache_used,
            self.active_workers,
            self.queued_tasks,
            self.captured_at,
        )
        if any(value < 0 for value in values):
            raise ValueError("resource measurements must be non-negative")
        if self.load_per_logical_core is not None and (
            self.load_per_logical_core < 0
            or not math.isfinite(self.load_per_logical_core)
        ):
            raise ValueError("resource measurements must be finite and non-negative")


def _run_text(arguments: list[str]) -> str | None:
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    output = result.stdout.strip()
    return output or None


def _sysctl(name: str) -> str | None:
    if sys.platform != "darwin":
        return None
    return _run_text(["sysctl", "-n", name])


def _positive_int(value: str | None) -> int | None:
    try:
        result = int(value or "")
    except ValueError:
        return None
    return result if result > 0 else None


def _linux_cpu_model() -> str | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        name, separator, value = line.partition(":")
        if separator and name.strip().lower() in {"model name", "hardware"}:
            cleaned = value.strip()
            if cleaned:
                return cleaned
    return None


def _linux_physical_cores() -> int | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        text = Path("/proc/cpuinfo").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    pairs: set[tuple[str, str]] = set()
    for block in text.split("\n\n"):
        fields: dict[str, str] = {}
        for line in block.splitlines():
            key, separator, value = line.partition(":")
            if separator:
                fields[key.strip().lower()] = value.strip()
        if "physical id" in fields and "core id" in fields:
            pairs.add((fields["physical id"], fields["core id"]))
    return len(pairs) or None


def probe_host_profile(temp_root: Path) -> HostResourceProfile:
    """Collect bounded, read-only host facts without making network requests."""

    logical = max(1, os.cpu_count() or 1)
    physical = (
        _positive_int(_sysctl("hw.physicalcpu"))
        or _linux_physical_cores()
        or logical
    )
    physical = min(logical, max(1, physical))
    architecture = platform_module.machine().strip() or "unknown"
    cpu_model = (
        _sysctl("machdep.cpu.brand_string")
        or _sysctl("hw.model")
        or _linux_cpu_model()
        or platform_module.processor().strip()
        or architecture
    )
    memory = probe_memory()
    return HostResourceProfile(
        cpu_model=cpu_model,
        architecture=architecture,
        physical_cores=physical,
        logical_cores=logical,
        physical_memory=memory.physical,
        platform=sys.platform,
        platform_release=platform_module.release(),
        temp_root=temp_root.expanduser().resolve(),
    )


def _linux_current_rss_bytes() -> int | None:
    if not sys.platform.startswith("linux"):
        return None
    try:
        fields = Path("/proc/self/statm").read_text(encoding="ascii").split()
        resident_pages = int(fields[1])
        page_size = int(os.sysconf("SC_PAGE_SIZE"))
    except (OSError, ValueError, IndexError, AttributeError):
        return None
    return max(0, resident_pages * page_size)


def _macos_current_rss_bytes() -> int | None:
    if sys.platform != "darwin":
        return None
    value = _run_text(["ps", "-o", "rss=", "-p", str(os.getpid())])
    try:
        return max(0, int(value or "") * 1024)
    except ValueError:
        return None


def _windows_process_memory_bytes(*, peak: bool) -> int | None:
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes

        class ProcessMemoryCounters(ctypes.Structure):
            _fields_ = [
                ("cb", wintypes.DWORD),
                ("PageFaultCount", wintypes.DWORD),
                ("PeakWorkingSetSize", ctypes.c_size_t),
                ("WorkingSetSize", ctypes.c_size_t),
                ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPagedPoolUsage", ctypes.c_size_t),
                ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
                ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                ("PagefileUsage", ctypes.c_size_t),
                ("PeakPagefileUsage", ctypes.c_size_t),
            ]

        counters = ProcessMemoryCounters()
        counters.cb = ctypes.sizeof(counters)
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        success = ctypes.windll.psapi.GetProcessMemoryInfo(
            handle,
            ctypes.byref(counters),
            counters.cb,
        )
        if not success:
            return None
        value = counters.PeakWorkingSetSize if peak else counters.WorkingSetSize
        return max(0, int(value))
    except (AttributeError, OSError, ValueError):
        return None


def _resource_peak_rss_bytes() -> int | None:
    try:
        import resource

        value = int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    except (ImportError, OSError, ValueError):
        return None
    multiplier = 1 if sys.platform == "darwin" else 1024
    return max(0, value * multiplier)


def current_process_rss_bytes() -> int:
    """Return current resident bytes, or a conservative bounded fallback."""

    value = (
        _linux_current_rss_bytes()
        or _macos_current_rss_bytes()
        or _windows_process_memory_bytes(peak=False)
        or _resource_peak_rss_bytes()
        or 0
    )
    return max(0, value)


def peak_process_rss_bytes() -> int:
    """Return peak resident bytes observed for the current process."""

    peak = _windows_process_memory_bytes(peak=True) or _resource_peak_rss_bytes() or 0
    return max(peak, current_process_rss_bytes())


def _system_load() -> float | None:
    try:
        return float(os.getloadavg()[0])
    except (AttributeError, OSError, ValueError):
        return None


class ResourceSampler:
    """Capture one cheap live snapshot using replaceable local probes."""

    def __init__(
        self,
        profile: HostResourceProfile,
        *,
        memory_probe: Callable[[], MemorySnapshot] = probe_memory,
        rss_probe: Callable[[], int] = current_process_rss_bytes,
        load_probe: Callable[[], float | None] = _system_load,
        disk_probe: Callable[[Path], int] | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.profile = profile
        self._memory_probe = memory_probe
        self._rss_probe = rss_probe
        self._load_probe = load_probe
        self._disk_probe = disk_probe or (lambda path: shutil.disk_usage(path).free)
        self._clock = clock

    def sample(
        self,
        *,
        cache_used_bytes: int,
        active_workers: int,
        queued_tasks: int,
    ) -> ResourceSnapshot:
        memory = self._memory_probe()
        raw_load = self._load_probe()
        load = (
            None
            if raw_load is None
            else max(0.0, float(raw_load)) / self.profile.logical_cores
        )
        return ResourceSnapshot(
            physical_memory=memory.physical,
            available_memory=memory.available,
            process_rss=max(0, int(self._rss_probe())),
            load_per_logical_core=load,
            free_disk=max(0, int(self._disk_probe(self.profile.temp_root))),
            cache_used=max(0, int(cache_used_bytes)),
            active_workers=max(0, int(active_workers)),
            queued_tasks=max(0, int(queued_tasks)),
            captured_at=max(0.0, float(self._clock())),
        )
