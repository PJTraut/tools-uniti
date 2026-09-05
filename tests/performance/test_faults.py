from __future__ import annotations

import ast
from pathlib import Path

import pytest

from benchmarks.faults import (
    FAULT_CASE_ORDER,
    MAX_FAULT_IPC_BYTES,
    FaultCase,
    FaultResult,
    decode_fault_result,
    encode_fault_result,
    run_fault_case,
)
from benchmarks.models import ResultState
from benchmarks.sustained_models import ExecutionClass, SustainedFamilyResult
from benchmarks.sustained_workloads import attach_fault_evidence
from uniti.resources.policy import load_performance_policy


@pytest.mark.parametrize("case", FAULT_CASE_ORDER)
def test_named_fault_case_recovers_after_exact_child_termination(
    tmp_path: Path,
    case: FaultCase,
):
    result = run_fault_case(
        case,
        tmp_path / "fault-application",
        timeout_seconds=5.0,
    )

    assert result.case is case
    assert result.passed is True
    assert result.expected_termination is True
    assert result.barrier_valid is True
    assert result.exact_bytes is True
    assert result.exact_hash is True
    assert result.history_authority is True
    assert result.no_partial_mixture is True
    assert result.cleanup_ok is True
    assert result.message == ""
    assert not (tmp_path / "fault-application" / case.value).exists()


def test_fault_result_codec_is_bounded_and_rejects_unknown_fields():
    result = FaultResult(
        case=FaultCase.SAVE_STAGE,
        passed=True,
        expected_termination=True,
        barrier_valid=True,
        exact_bytes=True,
        exact_hash=True,
        history_authority=True,
        no_partial_mixture=True,
        cleanup_ok=True,
        message="",
    )
    payload = encode_fault_result(result)

    assert len(payload) <= MAX_FAULT_IPC_BYTES
    assert decode_fault_result(payload) == result
    with pytest.raises(ValueError, match="fields"):
        decode_fault_result(payload[:-1] + b',"extra":true}')
    with pytest.raises(ValueError, match="exceeds"):
        decode_fault_result(b"x" * (MAX_FAULT_IPC_BYTES + 1))
    with pytest.raises(ValueError, match="inconsistent"):
        FaultResult(
            FaultCase.SAVE_STAGE,
            True,
            False,
            True,
            True,
            True,
            True,
            True,
            True,
            "",
        )


def test_fault_controller_uses_shell_false_and_exact_process_termination():
    source = Path("benchmarks/faults.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    popen_calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "Popen"
    ]

    assert popen_calls
    assert all(
        any(
            keyword.arg == "shell"
            and isinstance(keyword.value, ast.Constant)
            and keyword.value.value is False
            for keyword in call.keywords
        )
        for call in popen_calls
    )
    assert any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "terminate"
        for node in ast.walk(tree)
    )


def test_fault_evidence_is_a_required_session_lifecycle_integrity_fact():
    family = SustainedFamilyResult(
        schema=2,
        family="session_lifecycle",
        profile="a22-v1",
        state=ResultState.PASS,
        warmup_cycles=1,
        measured_cycles=1,
        checkpoints=(),
        facts={"integrity_ok": True, "cleanup_ok": True},
        messages=(),
    )
    results = tuple(
        FaultResult(
            case,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            "",
        )
        for case in FAULT_CASE_ORDER
    )

    integrated = attach_fault_evidence(family, results)

    assert integrated.state is ResultState.PASS
    assert integrated.facts["crash_recovery_verified"] is True
    assert integrated.facts["fault_case_count"] == len(FAULT_CASE_ORDER)
    assert integrated.facts["expected_terminations"] == len(FAULT_CASE_ORDER)


def test_sustained_runner_invokes_injected_fault_controller_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    from benchmarks import sustained_runner

    policy = load_performance_policy()
    family = SustainedFamilyResult(
        schema=2,
        family="session_lifecycle",
        profile="a22-v1",
        state=ResultState.PASS,
        warmup_cycles=policy.sustained.warmup_cycles,
        measured_cycles=1,
        checkpoints=(),
        facts={"integrity_ok": True, "cleanup_ok": True},
        messages=(),
    )
    fault_results = tuple(
        FaultResult(
            case,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            True,
            "",
        )
        for case in FAULT_CASE_ORDER
    )
    calls = []

    monkeypatch.setattr(
        sustained_runner.subprocess,
        "run",
        lambda *args, **kwargs: type("Completed", (), {"returncode": 0})(),
    )
    monkeypatch.setattr(
        sustained_runner,
        "_read_family_result",
        lambda *args, **kwargs: family,
    )

    def fault_runner(root: Path, *, timeout_seconds: float):
        calls.append((root, timeout_seconds))
        return fault_results

    family_root = tmp_path / "family"
    family_root.mkdir()
    result = sustained_runner._run_family(
        "session_lifecycle",
        execution_class=ExecutionClass.HOSTED,
        cycles=1,
        family_root=family_root,
        fixture_size_bytes=1024,
        policy=policy,
        command_factory=lambda *args: ("fault-test-child",),
        fault_runner=fault_runner,
        child_timeout_seconds=5.0,
        repository=Path.cwd(),
    )

    assert result.facts["crash_recovery_verified"] is True
    assert calls == [
        (
            family_root / "application" / "fault-verification",
            float(policy.sustained.operation_timeout_seconds),
        )
    ]
