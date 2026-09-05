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

    assert policy.schema == 2
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
    assert policy.comparison.required_failure_confirmations == 2
    assert policy.sustained.warmup_cycles == 1
    assert policy.sustained.hosted_cycles == 5
    assert policy.sustained.controlled_cycles == 50
    assert policy.sustained.max_fixture_mib == 10
    assert policy.sustained.rss_growth_warn_mib == 16
    assert policy.sustained.rss_growth_fail_mib == 32
    assert (
        policy.sustained.rss_growth_fail_mib
        < policy.gates["retained_rss_mib"].fail
    )
    assert policy.sustained.handle_growth_warn == 4
    assert policy.sustained.handle_growth_fail == 16
    assert policy.sustained.operation_timeout_seconds > 0
    assert policy.evidence.family_max_decoded_mib == 2
    assert policy.evidence.suite_max_decoded_mib == 8
    assert policy.evidence.failure_retention_days == 7
    assert policy.dogfood.retention_days == 7
    assert policy.dogfood.aggregate_max_mib == 16
    assert 0 < policy.dogfood.publish_interval_seconds <= 3600


def test_schema_1_policy_loads_with_safe_sustained_defaults(tmp_path: Path):
    source = Path("src/uniti/resources/performance_policy.toml").read_text(
        encoding="utf-8"
    )
    schema_1 = source.replace("schema = 2", "schema = 1", 1)
    schema_1 = schema_1.replace("required_failure_confirmations = 2\n", "", 1)
    schema_1 = schema_1.split("\n[sustained]\n", 1)[0] + "\n"
    path = tmp_path / "schema-1.toml"
    path.write_text(schema_1, encoding="utf-8")

    policy = load_performance_policy(path)

    assert policy.schema == 1
    assert policy.sustained.hosted_cycles == 5
    assert policy.sustained.controlled_cycles == 50
    assert policy.evidence.family_max_decoded_mib == 2
    assert policy.dogfood.aggregate_max_mib == 16
    assert policy.comparison.required_failure_confirmations == 2


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
    path.write_text("schema = 3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="unsupported performance policy schema"):
        load_performance_policy(path)


def test_schema_2_policy_rejects_unknown_section_fields(tmp_path: Path):
    source = Path("src/uniti/resources/performance_policy.toml").read_text(
        encoding="utf-8"
    ).replace("schema = 1", "schema = 2", 1)
    path = tmp_path / "unknown-schema-2-field.toml"
    path.write_text(
        source.replace(
            "warmup_cycles = 1\n",
            "warmup_cycles = 1\nunbounded_samples = true\n",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown policy keys in sustained"):
        load_performance_policy(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("hosted_cycles = 5", "hosted_cycles = 51", "hosted cycles"),
        ("max_fixture_mib = 10", "max_fixture_mib = 11", "10 MiB"),
        (
            "rss_growth_warn_mib = 16",
            "rss_growth_warn_mib = 33",
            "RSS warning",
        ),
        (
            "rss_growth_fail_mib = 32",
            "rss_growth_fail_mib = 64",
            "retained RSS failure gate",
        ),
        (
            "handle_growth_warn = 4",
            "handle_growth_warn = 17",
            "handle warning",
        ),
        (
            "operation_timeout_seconds = 30",
            "operation_timeout_seconds = 301",
            "operation timeout",
        ),
        (
            "family_max_decoded_mib = 2",
            "family_max_decoded_mib = 3",
            "family evidence",
        ),
        (
            "suite_max_decoded_mib = 8",
            "suite_max_decoded_mib = 9",
            "suite evidence",
        ),
        (
            "failure_retention_days = 7",
            "failure_retention_days = 8",
            "failure evidence retention",
        ),
        ("\nretention_days = 7", "\nretention_days = 8", "dogfood retention"),
        (
            "aggregate_max_mib = 16",
            "aggregate_max_mib = 17",
            "dogfood evidence",
        ),
        (
            "publish_interval_seconds = 300",
            "publish_interval_seconds = 3601",
            "publication interval",
        ),
    ],
)
def test_schema_2_policy_rejects_unsafe_sustained_evidence_or_dogfood_limits(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
):
    source = Path("src/uniti/resources/performance_policy.toml").read_text(
        encoding="utf-8"
    )
    assert old in source
    path = tmp_path / "unsafe-schema-2.toml"
    path.write_text(source.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(ValueError, match=message):
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
