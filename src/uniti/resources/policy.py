"""Validated performance and resource policy shared by UNITI and its UX suite."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from enum import StrEnum
from importlib.resources import files
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Protocol


class ResourceState(StrEnum):
    NORMAL = "normal"
    BUSY = "busy"
    CONSTRAINED = "constrained"
    CRITICAL = "critical"


@dataclass(frozen=True, slots=True)
class GateLimit:
    warn: float
    fail: float
    physical_ram_fraction_fail: float | None = None


@dataclass(frozen=True, slots=True)
class TierPolicy:
    repetitions: int
    size_mib: int | None = None
    sparse_size_gib: int | None = None


@dataclass(frozen=True, slots=True)
class HostRequirement:
    min_physical_memory_gib: int | None = None
    min_available_memory_gib: int | None = None
    min_free_disk_gib: int | None = None
    max_load_per_logical_core: float | None = None
    requires_sparse_files: bool = False


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_cache_mib: int
    physical_ram_fraction: float
    min_visible_cache_mib: int
    gui_core_reserve: int


@dataclass(frozen=True, slots=True)
class PressureLimits:
    memory_normal_min_fraction: float
    memory_busy_min_fraction: float
    memory_constrained_min_fraction: float
    cpu_busy_load_per_logical_core: float
    cpu_constrained_load_per_logical_core: float
    busy_worker_fraction: float
    busy_cache_fraction: float
    constrained_worker_limit: int
    constrained_cache_fraction: float
    healthier_samples_before_recovery: int


@dataclass(frozen=True, slots=True)
class ComparisonLimits:
    regression_warning_percent: float
    regression_failure_percent: float


@dataclass(frozen=True, slots=True)
class PerformancePolicy:
    schema: int
    tiers: Mapping[str, TierPolicy]
    host_requirements: Mapping[str, HostRequirement]
    gates: Mapping[str, GateLimit]
    resources: ResourceLimits
    pressure: PressureLimits
    comparison: ComparisonLimits


class ResourceSnapshotLike(Protocol):
    physical_memory: int
    available_memory: int
    load_per_logical_core: float | None


_TOP_LEVEL_KEYS = {
    "schema",
    "tiers",
    "host_requirements",
    "gates",
    "resources",
    "pressure",
    "comparison",
}
_TIER_NAMES = {"quick", "routine", "design_target"}
_HOST_REQUIREMENT_NAMES = {"routine", "design_target"}
_GATE_NAMES = {
    "open_to_usable_ms",
    "gui_heartbeat_p95_ms",
    "gui_heartbeat_max_ms",
    "interaction_p95_ms",
    "interaction_max_ms",
    "cancel_normal_ms",
    "cancel_timeout_bound_ms",
    "first_progress_ms",
    "progress_gap_ms",
    "peak_rss_mib",
    "retained_rss_mib",
}


def _table(value: object, name: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a table")
    return value


def _exact_keys(
    table: Mapping[str, object],
    *,
    required: set[str],
    optional: set[str] | None = None,
    name: str,
) -> None:
    optional = optional or set()
    missing = required - table.keys()
    if missing:
        raise ValueError(f"missing policy keys in {name}: {sorted(missing)}")
    unknown = table.keys() - required - optional
    if unknown:
        raise ValueError(f"unknown policy keys in {name}: {sorted(unknown)}")


def _number(value: object, name: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a number")
    result = float(value)
    if result < minimum:
        raise ValueError(f"{name} must be at least {minimum:g}")
    return result


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{name} must be an integer")
    if value < minimum:
        raise ValueError(f"{name} must be at least {minimum}")
    return value


def _fraction(value: object, name: str) -> float:
    result = _number(value, name)
    if result > 1.0:
        raise ValueError(f"{name} must not exceed 1")
    return result


def _parse_tiers(raw: object) -> Mapping[str, TierPolicy]:
    table = _table(raw, "tiers")
    _exact_keys(table, required=_TIER_NAMES, name="tiers")
    parsed: dict[str, TierPolicy] = {}
    for name in sorted(_TIER_NAMES):
        values = _table(table[name], f"tiers.{name}")
        size_key = "sparse_size_gib" if name == "design_target" else "size_mib"
        _exact_keys(values, required={size_key, "repetitions"}, name=f"tiers.{name}")
        size = _integer(values[size_key], f"tiers.{name}.{size_key}", minimum=1)
        parsed[name] = TierPolicy(
            repetitions=_integer(
                values["repetitions"], f"tiers.{name}.repetitions", minimum=1
            ),
            size_mib=size if size_key == "size_mib" else None,
            sparse_size_gib=size if size_key == "sparse_size_gib" else None,
        )
    return MappingProxyType(parsed)


def _parse_host_requirements(raw: object) -> Mapping[str, HostRequirement]:
    table = _table(raw, "host_requirements")
    _exact_keys(table, required=_HOST_REQUIREMENT_NAMES, name="host_requirements")
    parsed: dict[str, HostRequirement] = {}
    allowed = {
        "min_physical_memory_gib",
        "min_available_memory_gib",
        "min_free_disk_gib",
        "max_load_per_logical_core",
        "requires_sparse_files",
    }
    for name in sorted(_HOST_REQUIREMENT_NAMES):
        values = _table(table[name], f"host_requirements.{name}")
        required = (
            {
                "min_physical_memory_gib",
                "min_available_memory_gib",
                "min_free_disk_gib",
                "max_load_per_logical_core",
            }
            if name == "routine"
            else {"min_available_memory_gib", "requires_sparse_files"}
        )
        _exact_keys(
            values,
            required=required,
            optional=allowed - required,
            name=f"host_requirements.{name}",
        )
        sparse = values.get("requires_sparse_files", False)
        if not isinstance(sparse, bool):
            raise ValueError(
                f"host_requirements.{name}.requires_sparse_files must be a boolean"
            )
        parsed[name] = HostRequirement(
            min_physical_memory_gib=(
                _integer(
                    values["min_physical_memory_gib"],
                    f"host_requirements.{name}.min_physical_memory_gib",
                )
                if "min_physical_memory_gib" in values
                else None
            ),
            min_available_memory_gib=(
                _integer(
                    values["min_available_memory_gib"],
                    f"host_requirements.{name}.min_available_memory_gib",
                )
                if "min_available_memory_gib" in values
                else None
            ),
            min_free_disk_gib=(
                _integer(
                    values["min_free_disk_gib"],
                    f"host_requirements.{name}.min_free_disk_gib",
                )
                if "min_free_disk_gib" in values
                else None
            ),
            max_load_per_logical_core=(
                _number(
                    values["max_load_per_logical_core"],
                    f"host_requirements.{name}.max_load_per_logical_core",
                )
                if "max_load_per_logical_core" in values
                else None
            ),
            requires_sparse_files=sparse,
        )
    return MappingProxyType(parsed)


def _parse_gates(raw: object) -> Mapping[str, GateLimit]:
    table = _table(raw, "gates")
    _exact_keys(table, required=_GATE_NAMES, name="gates")
    parsed: dict[str, GateLimit] = {}
    for name in sorted(_GATE_NAMES):
        values = _table(table[name], f"gates.{name}")
        optional = {"physical_ram_fraction_fail"} if name == "peak_rss_mib" else set()
        _exact_keys(
            values,
            required={"warn", "fail"},
            optional=optional,
            name=f"gates.{name}",
        )
        warn = _number(values["warn"], f"gates.{name}.warn")
        fail = _number(values["fail"], f"gates.{name}.fail")
        if warn > fail:
            raise ValueError(f"{name}: warn must not exceed fail")
        fraction = (
            _fraction(
                values["physical_ram_fraction_fail"],
                f"gates.{name}.physical_ram_fraction_fail",
            )
            if "physical_ram_fraction_fail" in values
            else None
        )
        parsed[name] = GateLimit(warn, fail, fraction)
    return MappingProxyType(parsed)


def _parse_resources(raw: object) -> ResourceLimits:
    values = _table(raw, "resources")
    keys = {
        "max_cache_mib",
        "physical_ram_fraction",
        "min_visible_cache_mib",
        "gui_core_reserve",
    }
    _exact_keys(values, required=keys, name="resources")
    result = ResourceLimits(
        max_cache_mib=_integer(values["max_cache_mib"], "resources.max_cache_mib", minimum=1),
        physical_ram_fraction=_fraction(
            values["physical_ram_fraction"], "resources.physical_ram_fraction"
        ),
        min_visible_cache_mib=_integer(
            values["min_visible_cache_mib"],
            "resources.min_visible_cache_mib",
            minimum=1,
        ),
        gui_core_reserve=_integer(
            values["gui_core_reserve"], "resources.gui_core_reserve", minimum=1
        ),
    )
    if result.min_visible_cache_mib > result.max_cache_mib:
        raise ValueError("resources.min_visible_cache_mib must not exceed max_cache_mib")
    return result


def _parse_pressure(raw: object) -> PressureLimits:
    values = _table(raw, "pressure")
    keys = {
        "memory_normal_min_fraction",
        "memory_busy_min_fraction",
        "memory_constrained_min_fraction",
        "cpu_busy_load_per_logical_core",
        "cpu_constrained_load_per_logical_core",
        "busy_worker_fraction",
        "busy_cache_fraction",
        "constrained_worker_limit",
        "constrained_cache_fraction",
        "healthier_samples_before_recovery",
    }
    _exact_keys(values, required=keys, name="pressure")
    result = PressureLimits(
        memory_normal_min_fraction=_fraction(
            values["memory_normal_min_fraction"], "pressure.memory_normal_min_fraction"
        ),
        memory_busy_min_fraction=_fraction(
            values["memory_busy_min_fraction"], "pressure.memory_busy_min_fraction"
        ),
        memory_constrained_min_fraction=_fraction(
            values["memory_constrained_min_fraction"],
            "pressure.memory_constrained_min_fraction",
        ),
        cpu_busy_load_per_logical_core=_number(
            values["cpu_busy_load_per_logical_core"],
            "pressure.cpu_busy_load_per_logical_core",
        ),
        cpu_constrained_load_per_logical_core=_number(
            values["cpu_constrained_load_per_logical_core"],
            "pressure.cpu_constrained_load_per_logical_core",
        ),
        busy_worker_fraction=_fraction(
            values["busy_worker_fraction"], "pressure.busy_worker_fraction"
        ),
        busy_cache_fraction=_fraction(
            values["busy_cache_fraction"], "pressure.busy_cache_fraction"
        ),
        constrained_worker_limit=_integer(
            values["constrained_worker_limit"],
            "pressure.constrained_worker_limit",
            minimum=1,
        ),
        constrained_cache_fraction=_fraction(
            values["constrained_cache_fraction"],
            "pressure.constrained_cache_fraction",
        ),
        healthier_samples_before_recovery=_integer(
            values["healthier_samples_before_recovery"],
            "pressure.healthier_samples_before_recovery",
            minimum=1,
        ),
    )
    if not (
        result.memory_normal_min_fraction
        > result.memory_busy_min_fraction
        > result.memory_constrained_min_fraction
        > 0
    ):
        raise ValueError("pressure memory fractions must descend from normal to constrained")
    if (
        result.cpu_busy_load_per_logical_core
        >= result.cpu_constrained_load_per_logical_core
    ):
        raise ValueError("pressure busy CPU load must be below constrained CPU load")
    return result


def _parse_comparison(raw: object) -> ComparisonLimits:
    values = _table(raw, "comparison")
    keys = {"regression_warning_percent", "regression_failure_percent"}
    _exact_keys(values, required=keys, name="comparison")
    result = ComparisonLimits(
        regression_warning_percent=_number(
            values["regression_warning_percent"],
            "comparison.regression_warning_percent",
        ),
        regression_failure_percent=_number(
            values["regression_failure_percent"],
            "comparison.regression_failure_percent",
        ),
    )
    if result.regression_warning_percent > result.regression_failure_percent:
        raise ValueError("comparison warning percent must not exceed failure percent")
    return result


def _parse_schema_1(raw: dict[str, object]) -> PerformancePolicy:
    _exact_keys(raw, required=_TOP_LEVEL_KEYS, name="root")
    return PerformancePolicy(
        schema=1,
        tiers=_parse_tiers(raw["tiers"]),
        host_requirements=_parse_host_requirements(raw["host_requirements"]),
        gates=_parse_gates(raw["gates"]),
        resources=_parse_resources(raw["resources"]),
        pressure=_parse_pressure(raw["pressure"]),
        comparison=_parse_comparison(raw["comparison"]),
    )


def load_performance_policy(path: Path | None = None) -> PerformancePolicy:
    """Load and fully validate schema 1 of UNITI's shared policy table."""

    if path is None:
        text = files("uniti.resources").joinpath("performance_policy.toml").read_text(
            encoding="utf-8"
        )
    else:
        text = path.read_text(encoding="utf-8")
    raw = tomllib.loads(text)
    schema = raw.get("schema")
    if schema != 1:
        raise ValueError(f"unsupported performance policy schema: {schema!r}")
    return _parse_schema_1(raw)


def classify_resource_state(
    snapshot: ResourceSnapshotLike,
    policy: PerformancePolicy,
) -> ResourceState:
    """Classify the worst current memory/CPU signal under the shared policy."""

    if snapshot.physical_memory <= 0:
        memory_state = ResourceState.CRITICAL
    else:
        ratio = max(0, snapshot.available_memory) / snapshot.physical_memory
        pressure = policy.pressure
        if ratio >= pressure.memory_normal_min_fraction:
            memory_state = ResourceState.NORMAL
        elif ratio >= pressure.memory_busy_min_fraction:
            memory_state = ResourceState.BUSY
        elif ratio >= pressure.memory_constrained_min_fraction:
            memory_state = ResourceState.CONSTRAINED
        else:
            memory_state = ResourceState.CRITICAL

    load = snapshot.load_per_logical_core
    if load is None or load < policy.pressure.cpu_busy_load_per_logical_core:
        cpu_state = ResourceState.NORMAL
    elif load < policy.pressure.cpu_constrained_load_per_logical_core:
        cpu_state = ResourceState.BUSY
    else:
        cpu_state = ResourceState.CONSTRAINED

    severity = {
        ResourceState.NORMAL: 0,
        ResourceState.BUSY: 1,
        ResourceState.CONSTRAINED: 2,
        ResourceState.CRITICAL: 3,
    }
    return max((memory_state, cpu_state), key=severity.__getitem__)
