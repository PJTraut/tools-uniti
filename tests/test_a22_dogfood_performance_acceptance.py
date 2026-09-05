from __future__ import annotations

import ast
from pathlib import Path

from benchmarks.sustained_workloads import SUSTAINED_FAMILY_ORDER
from uniti.resources.policy import load_performance_policy


def test_a22_policy_owns_bounded_cycles_evidence_and_dogfood_storage():
    policy = load_performance_policy()

    assert policy.sustained.hosted_cycles == 5
    assert policy.sustained.controlled_cycles == 50
    assert policy.sustained.warmup_cycles == 1
    assert policy.sustained.fixture_mib == 1
    assert policy.evidence.family_max_decoded_mib == 2
    assert policy.evidence.suite_max_decoded_mib == 8
    assert policy.evidence.failure_retention_days == 7
    assert policy.dogfood.retention_days == 7
    assert policy.dogfood.aggregate_max_mib == 16
    assert policy.comparison.required_failure_confirmations == 2
    assert SUSTAINED_FAMILY_ORDER == (
        "daily_editing",
        "format_integrity",
        "regex_replacement",
        "session_lifecycle",
    )


def test_a22_each_family_owns_one_service_and_has_no_automatic_promotion():
    harness = Path("benchmarks/application_harness.py").read_text(encoding="utf-8")
    runner = Path("benchmarks/sustained_runner.py").read_text(encoding="utf-8")
    dogfood = Path("src/uniti/app/dogfood_runtime.py").read_text(encoding="utf-8")

    assert harness.count("self.service = UNITIService(") == 1
    assert "for index, family in enumerate(names)" in runner
    assert "ApplicationWorkloadHarness(" not in runner
    assert "upload" not in dogfood.lower()
    assert "network" not in dogfood.lower()
    assert "promote" not in runner.lower()
    assert "_write_new" in runner


def test_a22_workflow_adds_failure_only_sustained_artifact_after_a21_phases():
    source = Path(".github/workflows/a21-cross-platform.yml").read_text(
        encoding="utf-8"
    )

    a21_upload = source.index("name: a21-${{ matrix.id }}")
    a22_run = source.index("python scripts/a22_ci.py run")
    assert a21_upload < a22_run
    assert source.count("python scripts/a22_ci.py run") == 1
    assert source.count("python scripts/a22_ci.py sanitize") == 1
    assert "id: a22_sustained" in source
    assert (
        "if: ${{ failure() && steps.a22_sustained.outcome == 'failure' }}"
        in source
    )
    assert "name: a22-${{ matrix.id }}" in source
    assert "path: ci-results/sanitized" in source
    assert "retention-days: 7" in source
    assert "timeout-minutes: 12" in source


def test_a22_tests_never_construct_real_low_disk_pressure():
    forbidden_calls = {"truncate", "ftruncate", "posix_fallocate", "fallocate"}
    for path in Path("tests").rglob("*.py"):
        if "test_a22" not in path.name and "performance" not in path.parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function = node.func
            name = (
                function.id
                if isinstance(function, ast.Name)
                else function.attr
                if isinstance(function, ast.Attribute)
                else ""
            )
            assert name not in forbidden_calls, f"real disk pressure in {path}"
    assert not any(path.name.upper() == "LOWDISK" for path in Path(".").rglob("*"))
