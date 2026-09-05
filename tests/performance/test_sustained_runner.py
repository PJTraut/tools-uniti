from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from benchmarks.models import ResultState
from benchmarks.sustained_models import (
    CandidateEvidence,
    ExecutionClass,
    SustainedSuiteResult,
    decode_candidate_evidence,
    decode_suite_result,
)
from benchmarks.sustained_runner import (
    SUSTAINED_FAMILY_ORDER,
    run_sustained_suite,
)
from uniti.resources.policy import load_performance_policy


_FAKE_CHILD = r"""
import sys
import time
from pathlib import Path

from benchmarks.models import ResultState
from benchmarks.sustained_models import ResourceCheckpoint, SustainedFamilyResult, encode_family_result

family, profile, cycles_text, result_text, application_text, log_text, mode = sys.argv[1:]
cycles = int(cycles_text)
result_path = Path(result_text)
family_root = Path(application_text).parent
run_root = family_root.parent
log_path = Path(log_text)
with log_path.open("a", encoding="utf-8") as handle:
    live_roots = sum(path.is_dir() for path in run_root.iterdir())
    handle.write(f"{family}:{live_roots}\n")
if mode == "timeout":
    time.sleep(3)
if mode == "exit":
    raise SystemExit(7)
if mode == "missing":
    raise SystemExit(0)
if mode == "oversized":
    result_path.write_bytes(b"x" * ((2 << 20) + 1))
    raise SystemExit(0)
if mode == "malformed":
    result_path.write_bytes(b"{not-json")
    raise SystemExit(0)
selected_family = "wrong-family" if mode == "mismatch" else family
checkpoints = tuple(
    ResourceCheckpoint(
        cycle,
        {"rss_mib": 100.0, "daily_cycle_ms": 1.0},
        {
            "documents": 0,
            "views": 0,
            "active_workers": 0,
            "active_tasks": 0,
            "queued_tasks": 0,
            "result_stores": 0,
            "replacement_plans": 0,
            "snapshots": 0,
            "temp_paths": 0,
        },
        ("handle_count",),
    )
    for cycle in range(1, cycles + 1)
)
result = SustainedFamilyResult(
    2,
    selected_family,
    "a22-v1",
    ResultState.PASS,
    1,
    cycles,
    checkpoints,
    {"integrity_ok": True, "cleanup_ok": True},
    (),
)
result_path.write_bytes(
    encode_family_result(result, max_bytes=2 << 20, max_checkpoints=cycles)
)
"""


def _host(*, architecture: str = "x86_64") -> dict[str, object]:
    return {
        "architecture": architecture,
        "platform": "linux",
        "physical_cores": 8,
        "physical_memory": 16 << 30,
        "python_version": "3.12.4",
        "qt_version": "6.11.2",
        "corpus_schema": 2,
        "git_commit": "candidate-abc",
        "contended": False,
    }


def _command_factory(
    log_path: Path,
    modes: dict[str, str] | None = None,
):
    selected_modes = modes or {}

    def build(
        family: str,
        execution_class: ExecutionClass,
        cycles: int,
        manifest_path: Path,
        result_path: Path,
        application_root: Path,
    ) -> tuple[str, ...]:
        assert manifest_path.is_file()
        return (
            sys.executable,
            "-c",
            _FAKE_CHILD,
            family,
            execution_class.value,
            str(cycles),
            str(result_path),
            str(application_root),
            str(log_path),
            selected_modes.get(family, "pass"),
        )

    return build


def _decode_suite(path: Path) -> SustainedSuiteResult:
    policy = load_performance_policy()
    return decode_suite_result(
        path.read_bytes(),
        max_bytes=policy.evidence.suite_max_decoded_mib << 20,
        family_max_bytes=policy.evidence.family_max_decoded_mib << 20,
        max_checkpoints=policy.sustained.controlled_cycles,
    )


def test_sustained_families_run_in_fixed_order_with_one_owned_root(tmp_path: Path):
    log_path = tmp_path / "children.log"
    run_parent = tmp_path / "runs"
    run_parent.mkdir()

    suite = run_sustained_suite(
        "hosted",
        temp_root=run_parent,
        host_fingerprint=_host(),
        fixture_size_bytes=1024,
        command_factory=_command_factory(log_path),
    )

    assert tuple(family.family for family in suite.families) == SUSTAINED_FAMILY_ORDER
    assert all(family.state is ResultState.PASS for family in suite.families)
    assert log_path.read_text(encoding="utf-8").splitlines() == [
        f"{family}:1" for family in SUSTAINED_FAMILY_ORDER
    ]
    assert not tuple(run_parent.iterdir())


def test_failed_and_timed_out_children_do_not_stop_later_families(tmp_path: Path):
    log_path = tmp_path / "children.log"
    run_parent = tmp_path / "runs"
    run_parent.mkdir()
    modes = {
        SUSTAINED_FAMILY_ORDER[0]: "exit",
        SUSTAINED_FAMILY_ORDER[1]: "timeout",
    }

    suite = run_sustained_suite(
        "hosted",
        temp_root=run_parent,
        host_fingerprint=_host(),
        fixture_size_bytes=1024,
        command_factory=_command_factory(log_path, modes),
        child_timeout_seconds=1.0,
    )

    assert tuple(family.state for family in suite.families) == (
        ResultState.FAIL,
        ResultState.FAIL,
        ResultState.PASS,
        ResultState.PASS,
    )
    assert [line.split(":", 1)[0] for line in log_path.read_text().splitlines()] == list(
        SUSTAINED_FAMILY_ORDER
    )


@pytest.mark.parametrize(
    ("mode", "message"),
    [
        ("missing", "no result"),
        ("oversized", "exceeds"),
        ("malformed", "valid JSON"),
        ("mismatch", "identity mismatch"),
    ],
)
def test_missing_oversized_malformed_or_mismatched_child_fails_closed(
    tmp_path: Path,
    mode: str,
    message: str,
):
    family = SUSTAINED_FAMILY_ORDER[0]
    run_parent = tmp_path / "runs"
    run_parent.mkdir()

    suite = run_sustained_suite(
        "hosted",
        family_names=(family,),
        temp_root=run_parent,
        host_fingerprint=_host(),
        fixture_size_bytes=1024,
        command_factory=_command_factory(tmp_path / "children.log", {family: mode}),
    )

    assert suite.families[0].state is ResultState.FAIL
    assert any(message in item for item in suite.families[0].messages)
    assert not tuple(run_parent.iterdir())


def test_compare_requires_a_compatible_clean_controlled_anchor(tmp_path: Path):
    first_path = tmp_path / "anchor.json"
    run_parent = tmp_path / "runs"
    run_parent.mkdir()
    run_sustained_suite(
        "controlled",
        output=first_path,
        temp_root=run_parent,
        host_fingerprint=_host(),
        fixture_size_bytes=1024,
        command_factory=_command_factory(tmp_path / "first.log"),
    )

    compared = run_sustained_suite(
        "hosted",
        compare=first_path,
        temp_root=run_parent,
        host_fingerprint=_host(),
        fixture_size_bytes=1024,
        command_factory=_command_factory(tmp_path / "second.log"),
    )
    assert compared.state is ResultState.PASS

    with pytest.raises(ValueError, match="incompatible"):
        run_sustained_suite(
            "hosted",
            compare=first_path,
            temp_root=run_parent,
            host_fingerprint=_host(architecture="arm64"),
            fixture_size_bytes=1024,
            command_factory=_command_factory(tmp_path / "third.log"),
        )


def test_controlled_confirmation_writes_two_run_candidate_without_overwrite(
    tmp_path: Path,
):
    first_path = tmp_path / "first.json"
    confirmed_path = tmp_path / "confirmed.json"
    run_parent = tmp_path / "runs"
    run_parent.mkdir()
    run_sustained_suite(
        "controlled",
        output=first_path,
        temp_root=run_parent,
        host_fingerprint=_host(),
        fixture_size_bytes=1024,
        command_factory=_command_factory(tmp_path / "first.log"),
    )
    original = first_path.read_bytes()

    run_sustained_suite(
        "controlled",
        output=confirmed_path,
        candidate=first_path,
        temp_root=run_parent,
        host_fingerprint=_host(),
        fixture_size_bytes=1024,
        command_factory=_command_factory(tmp_path / "second.log"),
    )

    policy = load_performance_policy()
    evidence = decode_candidate_evidence(
        confirmed_path.read_bytes(),
        max_bytes=policy.evidence.suite_max_decoded_mib << 20,
        family_max_bytes=policy.evidence.family_max_decoded_mib << 20,
        max_checkpoints=policy.sustained.controlled_cycles,
    )
    assert isinstance(evidence, CandidateEvidence)
    assert len(evidence.suites) == 2
    assert first_path.read_bytes() == original


def test_cli_refuses_mixed_point_and_sustained_options():
    for arguments in (
        ("--suite", "sustained", "--profile", "hosted", "--tier", "quick"),
        ("--suite", "point", "--tier", "quick", "--profile", "hosted"),
        ("--suite", "sustained", "--profile", "hosted", "--mode", "baseline"),
    ):
        completed = subprocess.run(
            [sys.executable, "scripts/performance_suite.py", *arguments],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )

        assert completed.returncode == 2
        assert "cannot be combined" in completed.stderr


def test_candidate_is_controlled_only_and_requires_distinct_output(tmp_path: Path):
    candidate = tmp_path / "candidate.json"
    completed = subprocess.run(
        [
            sys.executable,
            "scripts/performance_suite.py",
            "--suite",
            "sustained",
            "--profile",
            "hosted",
            "--candidate",
            str(candidate),
            "--output",
            str(candidate),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 2
    assert "controlled" in completed.stderr or "distinct" in completed.stderr
