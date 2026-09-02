from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from uniti.resources.policy import (
    ResourceState,
    classify_resource_state,
    load_performance_policy,
)


@dataclass(frozen=True)
class _Snapshot:
    physical_memory: int
    available_memory: int
    load_per_logical_core: float | None


def test_packaged_policy_has_approved_a18_values():
    policy = load_performance_policy()

    assert policy.schema == 1
    assert policy.tiers["quick"].size_mib == 10
    assert policy.tiers["routine"].size_mib == 100
    assert policy.tiers["design_target"].sparse_size_gib == 1
    assert policy.gates["open_to_usable_ms"].fail == 1000
    assert policy.gates["gui_heartbeat_max_ms"].fail == 100
    assert policy.gates["peak_rss_mib"].physical_ram_fraction_fail == 0.125
    assert policy.resources.max_cache_mib == 512
    assert policy.resources.physical_ram_fraction == 0.125
    assert policy.pressure.healthier_samples_before_recovery == 2
    assert policy.comparison.regression_failure_percent == 25


def test_policy_rejects_inverted_warn_and_fail(tmp_path: Path):
    source = Path("src/uniti/resources/performance_policy.toml").read_text(
        encoding="utf-8"
    )
    bad = tmp_path / "bad.toml"
    bad.write_text(
        source.replace("warn = 500\nfail = 1000", "warn = 1001\nfail = 1000", 1),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="warn must not exceed fail"):
        load_performance_policy(bad)


def test_unknown_policy_schema_is_refused(tmp_path: Path):
    path = tmp_path / "future.toml"
    path.write_text("schema = 2\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported performance policy schema"):
        load_performance_policy(path)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda text: text + "\nunknown = 1\n", "unknown policy keys"),
        (lambda text: text.replace("max_cache_mib = 512\n", "", 1), "missing policy keys"),
    ],
)
def test_policy_rejects_unknown_or_missing_keys(tmp_path: Path, mutation, message: str):
    source = Path("src/uniti/resources/performance_policy.toml").read_text(
        encoding="utf-8"
    )
    bad = tmp_path / "bad.toml"
    bad.write_text(mutation(source), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
        load_performance_policy(bad)


@pytest.mark.parametrize(
    ("available", "load", "expected"),
    [
        (8 << 30, 0.10, ResourceState.NORMAL),
        (3 << 30, 0.10, ResourceState.BUSY),
        (2 << 30, 0.10, ResourceState.CONSTRAINED),
        (1 << 30, 0.10, ResourceState.CRITICAL),
        (8 << 30, 0.75, ResourceState.BUSY),
        (8 << 30, 1.00, ResourceState.CONSTRAINED),
    ],
)
def test_resource_state_uses_the_worst_memory_or_cpu_signal(
    available: int,
    load: float,
    expected: ResourceState,
):
    policy = load_performance_policy()

    assert classify_resource_state(
        _Snapshot(physical_memory=16 << 30, available_memory=available, load_per_logical_core=load),
        policy,
    ) is expected


def test_resource_state_is_critical_without_physical_memory_evidence():
    policy = load_performance_policy()

    assert classify_resource_state(
        _Snapshot(physical_memory=0, available_memory=0, load_per_logical_core=None),
        policy,
    ) is ResourceState.CRITICAL
