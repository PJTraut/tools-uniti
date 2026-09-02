"""Read-only local preflight and eligibility for performance runs."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import uniti

from benchmarks.models import ResultState
from uniti.app.sparse import deallocate_file_range
from uniti.resources import (
    PerformancePolicy,
    current_process_rss_bytes,
    probe_host_profile,
    probe_memory,
)


@dataclass(frozen=True, slots=True)
class HostPreflight:
    schema: int
    cpu_model: str
    architecture: str
    physical_cores: int
    logical_cores: int
    physical_memory: int
    available_memory: int
    process_rss: int
    load_per_logical_core: float | None
    platform: str
    platform_release: str
    python_version: str
    qt_version: str | None
    uniti_version: str
    git_commit: str | None
    filesystem_type: str
    free_disk: int
    temp_root: str
    sparse_files: bool
    display_scale: float | None = None
    display_refresh_hz: float | None = None
    power_state: str | None = None
    thermal_state: str | None = None

    def as_dict(self) -> dict[str, object]:
        return {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
        }


@dataclass(frozen=True, slots=True)
class HostEligibility:
    state: ResultState
    messages: tuple[str, ...]


def _run_text(arguments: list[str], *, cwd: Path | None = None) -> str | None:
    try:
        result = subprocess.run(
            arguments,
            cwd=cwd,
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
    return result.stdout.strip() or None


def _filesystem_type(path: Path) -> str:
    if sys.platform == "darwin":
        value = _run_text(["stat", "-f", "%T", str(path)])
    elif sys.platform.startswith("linux"):
        value = _run_text(["stat", "-f", "-c", "%T", str(path)])
    else:
        value = None
    return value or "unknown"


def probe_sparse_file_support(root: Path) -> bool:
    """Probe holes in an owned temporary file and always remove the artifact."""

    root.mkdir(parents=True, exist_ok=True)
    descriptor, raw_path = tempfile.mkstemp(prefix="uniti-sparse-probe-", dir=root)
    path = Path(raw_path)
    try:
        with os.fdopen(descriptor, "r+b") as handle:
            handle.write(b"start")
            handle.seek((8 << 20) - 1)
            handle.write(b"x")
            handle.flush()
            os.fsync(handle.fileno())
            deallocate_file_range(
                handle.fileno(),
                4096,
                (8 << 20) - 8192,
            )
            os.fsync(handle.fileno())
        stat = path.stat()
        blocks = getattr(stat, "st_blocks", None)
        if blocks is None:
            return stat.st_size == 8 << 20
        return blocks * 512 < stat.st_size // 2
    except OSError:
        return False
    finally:
        path.unlink(missing_ok=True)


def _load_per_core(logical_cores: int) -> float | None:
    try:
        return max(0.0, float(os.getloadavg()[0])) / logical_cores
    except (AttributeError, OSError, ValueError):
        return None


def _qt_version() -> str | None:
    try:
        import PySide6
    except ImportError:
        return None
    return str(PySide6.__version__)


def _display_facts(enabled: bool) -> tuple[float | None, float | None]:
    if not enabled:
        return None, None
    try:
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance() or QApplication([])
        screen = app.primaryScreen()
        if screen is None:
            return None, None
        return float(screen.devicePixelRatio()), float(screen.refreshRate())
    except (ImportError, RuntimeError):
        return None, None


def collect_host_preflight(
    temp_root: Path,
    *,
    native_gui: bool = False,
) -> HostPreflight:
    """Collect all reliable local facts before creating benchmark corpora."""

    resolved = temp_root.expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    profile = probe_host_profile(resolved)
    memory = probe_memory()
    scale, refresh = _display_facts(native_gui)
    repository = Path(__file__).resolve().parents[1]
    return HostPreflight(
        schema=1,
        cpu_model=profile.cpu_model,
        architecture=profile.architecture,
        physical_cores=profile.physical_cores,
        logical_cores=profile.logical_cores,
        physical_memory=memory.physical,
        available_memory=memory.available,
        process_rss=current_process_rss_bytes(),
        load_per_logical_core=_load_per_core(profile.logical_cores),
        platform=sys.platform,
        platform_release=platform.release(),
        python_version=platform.python_version(),
        qt_version=_qt_version(),
        uniti_version=uniti.__version__,
        git_commit=_run_text(["git", "rev-parse", "HEAD"], cwd=repository),
        filesystem_type=_filesystem_type(resolved),
        free_disk=max(0, shutil.disk_usage(resolved).free),
        temp_root=str(resolved),
        sparse_files=probe_sparse_file_support(resolved),
        display_scale=scale,
        display_refresh_hz=refresh,
    )


def evaluate_host_eligibility(
    preflight: HostPreflight,
    policy: PerformancePolicy,
    *,
    tier: str,
    mode: str,
) -> HostEligibility:
    """Distinguish unsafe capacity from an uncontrolled baseline host."""

    if mode not in {"baseline", "real-world"}:
        raise ValueError(f"unknown performance mode: {mode}")
    requirement = policy.host_requirements.get(tier)
    if requirement is None:
        return HostEligibility(ResultState.PASS, ())
    gib = 1 << 30
    capacity: list[str] = []
    if (
        requirement.min_physical_memory_gib is not None
        and preflight.physical_memory < requirement.min_physical_memory_gib * gib
    ):
        capacity.append("physical memory is below the tier requirement")
    if (
        requirement.min_available_memory_gib is not None
        and preflight.available_memory < requirement.min_available_memory_gib * gib
    ):
        capacity.append("available memory is below the tier requirement")
    if (
        requirement.min_free_disk_gib is not None
        and preflight.free_disk < requirement.min_free_disk_gib * gib
    ):
        capacity.append("free disk is below the tier requirement")
    if requirement.requires_sparse_files and not preflight.sparse_files:
        capacity.append("sparse files are unavailable")
    if capacity:
        return HostEligibility(ResultState.NOT_RUN, tuple(capacity))

    maximum_load = requirement.max_load_per_logical_core
    contended = maximum_load is not None and (
        preflight.load_per_logical_core is None
        or preflight.load_per_logical_core > maximum_load
    )
    if contended and mode == "baseline":
        return HostEligibility(
            ResultState.INVALID,
            ("controlled baseline host is contended or load evidence is unavailable",),
        )
    if contended:
        return HostEligibility(
            ResultState.PASS,
            ("real-world run is contended; throughput is diagnostic only",),
        )
    return HostEligibility(ResultState.PASS, ())


def _major_minor(value: object) -> tuple[int, int] | None:
    try:
        parts = str(value).split(".")
        return int(parts[0]), int(parts[1])
    except (IndexError, ValueError):
        return None


def _ram_class(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        return None
    gib = int(value) // (1 << 30)
    return ((gib + 7) // 8) * 8


def host_fingerprints_compatible(
    baseline: Mapping[str, object],
    current: Mapping[str, object],
) -> bool:
    """Compare only stable host classes used for throughput baselines."""

    exact = ("architecture", "platform", "physical_cores", "corpus_schema")
    if any(baseline.get(key) != current.get(key) for key in exact):
        return False
    if _ram_class(baseline.get("physical_memory")) != _ram_class(
        current.get("physical_memory")
    ):
        return False
    for key in ("python_version", "qt_version"):
        if _major_minor(baseline.get(key)) != _major_minor(current.get(key)):
            return False
    return True
