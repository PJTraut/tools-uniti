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
    balloon_max_multiplier: float
    balloon_grab_fraction: float


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
    required_failure_confirmations: int = 2


@dataclass(frozen=True, slots=True)
class SustainedLimits:
    warmup_cycles: int
    hosted_cycles: int
    controlled_cycles: int
    fixture_mib: int
    max_fixture_mib: int
    rss_growth_warn_mib: int
    rss_growth_fail_mib: int
    handle_growth_warn: int
    handle_growth_fail: int
    operation_timeout_seconds: int


@dataclass(frozen=True, slots=True)
class EvidenceLimits:
    family_max_decoded_mib: int
    suite_max_decoded_mib: int
    failure_retention_days: int


@dataclass(frozen=True, slots=True)
class DogfoodLimits:
    retention_days: int
    aggregate_max_mib: int
    publish_interval_seconds: int


@dataclass(frozen=True, slots=True)
class PerformancePolicy:
    schema: int
    tiers: Mapping[str, TierPolicy]
    host_requirements: Mapping[str, HostRequirement]
    gates: Mapping[str, GateLimit]
    resources: ResourceLimits
    pressure: PressureLimits
    comparison: ComparisonLimits
    sustained: SustainedLimits
    evidence: EvidenceLimits
    dogfood: DogfoodLimits


class ResourceSnapshotLike(Protocol):
    physical_memory: int
    available_memory: int
    load_per_logical_core: float | None


_SCHEMA_1_TOP_LEVEL_KEYS = {
    "schema",
    "tiers",
    "host_requirements",
    "gates",
    "resources",
    "pressure",
    "comparison",
}
_SCHEMA_2_TOP_LEVEL_KEYS = _SCHEMA_1_TOP_LEVEL_KEYS | {
    "sustained",
    "evidence",
    "dogfood",
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
        "balloon_max_multiplier",
        "balloon_grab_fraction",
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
        balloon_max_multiplier=_number(
            values["balloon_max_multiplier"],
            "resources.balloon_max_multiplier",
            minimum=1.0,
        ),
        balloon_grab_fraction=_fraction(
            values["balloon_grab_fraction"], "resources.balloon_grab_fraction"
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


def _parse_comparison(raw: object, *, schema: int) -> ComparisonLimits:
    values = _table(raw, "comparison")
    keys = {"regression_warning_percent", "regression_failure_percent"}
    if schema == 2:
        keys.add("required_failure_confirmations")
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
        required_failure_confirmations=(
            _integer(
                values["required_failure_confirmations"],
                "comparison.required_failure_confirmations",
                minimum=1,
            )
            if schema == 2
            else 2
        ),
    )
    if result.regression_warning_percent > result.regression_failure_percent:
        raise ValueError("comparison warning percent must not exceed failure percent")
    return result


_SCHEMA_1_SUSTAINED_DEFAULTS = SustainedLimits(
    warmup_cycles=1,
    hosted_cycles=5,
    controlled_cycles=50,
    fixture_mib=1,
    max_fixture_mib=10,
    rss_growth_warn_mib=16,
    rss_growth_fail_mib=32,
    handle_growth_warn=4,
    handle_growth_fail=16,
    operation_timeout_seconds=30,
)
_SCHEMA_1_EVIDENCE_DEFAULTS = EvidenceLimits(
    family_max_decoded_mib=2,
    suite_max_decoded_mib=8,
    failure_retention_days=7,
)
_SCHEMA_1_DOGFOOD_DEFAULTS = DogfoodLimits(
    retention_days=7,
    aggregate_max_mib=16,
    publish_interval_seconds=300,
)


def _parse_sustained(raw: object) -> SustainedLimits:
    values = _table(raw, "sustained")
    keys = {
        "warmup_cycles",
        "hosted_cycles",
        "controlled_cycles",
        "fixture_mib",
        "max_fixture_mib",
        "rss_growth_warn_mib",
        "rss_growth_fail_mib",
        "handle_growth_warn",
        "handle_growth_fail",
        "operation_timeout_seconds",
    }
    _exact_keys(values, required=keys, name="sustained")
    result = SustainedLimits(
        warmup_cycles=_integer(
            values["warmup_cycles"], "sustained.warmup_cycles", minimum=1
        ),
        hosted_cycles=_integer(
            values["hosted_cycles"], "sustained.hosted_cycles", minimum=1
        ),
        controlled_cycles=_integer(
            values["controlled_cycles"], "sustained.controlled_cycles", minimum=1
        ),
        fixture_mib=_integer(
            values["fixture_mib"], "sustained.fixture_mib", minimum=1
        ),
        max_fixture_mib=_integer(
            values["max_fixture_mib"], "sustained.max_fixture_mib", minimum=1
        ),
        rss_growth_warn_mib=_integer(
            values["rss_growth_warn_mib"],
            "sustained.rss_growth_warn_mib",
            minimum=1,
        ),
        rss_growth_fail_mib=_integer(
            values["rss_growth_fail_mib"],
            "sustained.rss_growth_fail_mib",
            minimum=1,
        ),
        handle_growth_warn=_integer(
            values["handle_growth_warn"],
            "sustained.handle_growth_warn",
            minimum=0,
        ),
        handle_growth_fail=_integer(
            values["handle_growth_fail"],
            "sustained.handle_growth_fail",
            minimum=1,
        ),
        operation_timeout_seconds=_integer(
            values["operation_timeout_seconds"],
            "sustained.operation_timeout_seconds",
            minimum=1,
        ),
    )
    if result.hosted_cycles > result.controlled_cycles:
        raise ValueError("sustained hosted cycles must not exceed controlled cycles")
    if result.fixture_mib > result.max_fixture_mib:
        raise ValueError("sustained fixture must not exceed its maximum")
    if result.max_fixture_mib > 10:
        raise ValueError("sustained max fixture must not exceed 10 MiB")
    if result.rss_growth_warn_mib > result.rss_growth_fail_mib:
        raise ValueError("sustained RSS warning must not exceed failure growth")
    if result.handle_growth_warn > result.handle_growth_fail:
        raise ValueError("sustained handle warning must not exceed failure growth")
    if result.operation_timeout_seconds > 300:
        raise ValueError("sustained operation timeout must not exceed 300 seconds")
    return result


def _parse_evidence(raw: object) -> EvidenceLimits:
    values = _table(raw, "evidence")
    keys = {
        "family_max_decoded_mib",
        "suite_max_decoded_mib",
        "failure_retention_days",
    }
    _exact_keys(values, required=keys, name="evidence")
    result = EvidenceLimits(
        family_max_decoded_mib=_integer(
            values["family_max_decoded_mib"],
            "evidence.family_max_decoded_mib",
            minimum=1,
        ),
        suite_max_decoded_mib=_integer(
            values["suite_max_decoded_mib"],
            "evidence.suite_max_decoded_mib",
            minimum=1,
        ),
        failure_retention_days=_integer(
            values["failure_retention_days"],
            "evidence.failure_retention_days",
            minimum=1,
        ),
    )
    if result.family_max_decoded_mib > 2:
        raise ValueError("family evidence must not exceed 2 MiB")
    if result.suite_max_decoded_mib > 8:
        raise ValueError("suite evidence must not exceed 8 MiB")
    if result.family_max_decoded_mib > result.suite_max_decoded_mib:
        raise ValueError("family evidence must not exceed suite evidence")
    if result.failure_retention_days > 7:
        raise ValueError("failure evidence retention must not exceed 7 days")
    return result


def _parse_dogfood(raw: object) -> DogfoodLimits:
    values = _table(raw, "dogfood")
    keys = {"retention_days", "aggregate_max_mib", "publish_interval_seconds"}
    _exact_keys(values, required=keys, name="dogfood")
    result = DogfoodLimits(
        retention_days=_integer(
            values["retention_days"], "dogfood.retention_days", minimum=1
        ),
        aggregate_max_mib=_integer(
            values["aggregate_max_mib"], "dogfood.aggregate_max_mib", minimum=1
        ),
        publish_interval_seconds=_integer(
            values["publish_interval_seconds"],
            "dogfood.publish_interval_seconds",
            minimum=1,
        ),
    )
    if result.retention_days > 7:
        raise ValueError("dogfood retention must not exceed 7 days")
    if result.aggregate_max_mib > 16:
        raise ValueError("dogfood evidence must not exceed 16 MiB")
    if result.publish_interval_seconds > 3600:
        raise ValueError("dogfood publication interval must not exceed one hour")
    return result


def _parse_schema_1(raw: dict[str, object]) -> PerformancePolicy:
    _exact_keys(raw, required=_SCHEMA_1_TOP_LEVEL_KEYS, name="root")
    return PerformancePolicy(
        schema=1,
        tiers=_parse_tiers(raw["tiers"]),
        host_requirements=_parse_host_requirements(raw["host_requirements"]),
        gates=_parse_gates(raw["gates"]),
        resources=_parse_resources(raw["resources"]),
        pressure=_parse_pressure(raw["pressure"]),
        comparison=_parse_comparison(raw["comparison"], schema=1),
        sustained=_SCHEMA_1_SUSTAINED_DEFAULTS,
        evidence=_SCHEMA_1_EVIDENCE_DEFAULTS,
        dogfood=_SCHEMA_1_DOGFOOD_DEFAULTS,
    )


def _parse_schema_2(raw: dict[str, object]) -> PerformancePolicy:
    _exact_keys(raw, required=_SCHEMA_2_TOP_LEVEL_KEYS, name="root")
    policy = PerformancePolicy(
        schema=2,
        tiers=_parse_tiers(raw["tiers"]),
        host_requirements=_parse_host_requirements(raw["host_requirements"]),
        gates=_parse_gates(raw["gates"]),
        resources=_parse_resources(raw["resources"]),
        pressure=_parse_pressure(raw["pressure"]),
        comparison=_parse_comparison(raw["comparison"], schema=2),
        sustained=_parse_sustained(raw["sustained"]),
        evidence=_parse_evidence(raw["evidence"]),
        dogfood=_parse_dogfood(raw["dogfood"]),
    )
    retained_failure = policy.gates["retained_rss_mib"].fail
    if policy.sustained.rss_growth_fail_mib >= retained_failure:
        raise ValueError(
            "sustained RSS failure growth must remain below retained RSS failure gate"
        )
    return policy


def load_performance_policy(path: Path | None = None) -> PerformancePolicy:
    """Load and fully validate a compatible UNITI shared policy table."""

    if path is None:
        text = files("uniti.resources").joinpath("performance_policy.toml").read_text(
            encoding="utf-8"
        )
    else:
        text = path.read_text(encoding="utf-8")
    raw = tomllib.loads(text)
    schema = raw.get("schema")
    if schema == 1:
        return _parse_schema_1(raw)
    if schema == 2:
        return _parse_schema_2(raw)
    raise ValueError(f"unsupported performance policy schema: {schema!r}")


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
