from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from benchmarks.host import (
    collect_host_preflight,
    evaluate_host_eligibility,
    host_fingerprints_compatible,
    probe_sparse_file_support,
)
from benchmarks.models import ResultState
from uniti.resources.policy import load_performance_policy


def test_sparse_probe_cleans_up_its_artifact(tmp_path: Path):
    before = set(tmp_path.iterdir())

    supported = probe_sparse_file_support(tmp_path)

    assert isinstance(supported, bool)
    assert set(tmp_path.iterdir()) == before


def test_real_preflight_reports_required_local_facts(tmp_path: Path):
    preflight = collect_host_preflight(tmp_path)
    payload = preflight.as_dict()

    assert payload["schema"] == 1
    assert payload["cpu_model"]
    assert payload["logical_cores"] >= 1
    assert payload["python_version"]
    assert payload["uniti_version"]
    assert payload["filesystem_type"]
    assert payload["free_disk"] >= 0


def test_insufficient_memory_is_not_run_but_busy_baseline_is_invalid(tmp_path: Path):
    policy = load_performance_policy()
    preflight = collect_host_preflight(tmp_path)

    insufficient = evaluate_host_eligibility(
        replace(preflight, available_memory=0),
        policy,
        tier="routine",
        mode="real-world",
    )
    contended = evaluate_host_eligibility(
        replace(preflight, load_per_logical_core=1.0),
        policy,
        tier="routine",
        mode="baseline",
    )

    assert insufficient.state is ResultState.NOT_RUN
    assert contended.state is ResultState.INVALID


def test_real_world_mode_records_contention_without_invalidating(tmp_path: Path):
    policy = load_performance_policy()
    preflight = collect_host_preflight(tmp_path)
    eligible = replace(
        preflight,
        physical_memory=max(preflight.physical_memory, 16 << 30),
        available_memory=max(preflight.available_memory, 8 << 30),
        free_disk=max(preflight.free_disk, 8 << 30),
        load_per_logical_core=1.0,
    )

    result = evaluate_host_eligibility(
        eligible,
        policy,
        tier="routine",
        mode="real-world",
    )

    assert result.state is ResultState.PASS
    assert any("contended" in message for message in result.messages)


def test_baseline_compatibility_uses_stable_host_classes():
    baseline = {
        "architecture": "arm64",
        "platform": "darwin",
        "physical_cores": 12,
        "physical_memory": 48 << 30,
        "python_version": "3.12.4",
        "qt_version": "6.11.2",
        "corpus_schema": 1,
    }

    assert host_fingerprints_compatible(
        baseline,
        {**baseline, "python_version": "3.12.9", "qt_version": "6.11.7"},
    )
    assert not host_fingerprints_compatible(
        baseline,
        {**baseline, "physical_cores": 10},
    )
