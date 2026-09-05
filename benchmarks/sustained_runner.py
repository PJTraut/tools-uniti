"""Parent orchestration for sustained UNITI workload families."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from benchmarks.corpus import CorpusSpec, generate_corpus
from benchmarks.faults import FaultResult, run_fault_suite
from benchmarks.host import collect_host_preflight, host_fingerprints_compatible
from benchmarks.models import ResultState
from benchmarks.sustained_evaluate import evaluate_sustained_suite
from benchmarks.sustained_models import (
    CandidateEvidence,
    ExecutionClass,
    SustainedEvaluation,
    SustainedFamilyResult,
    SustainedSuiteResult,
    decode_family_result,
    decode_suite_result,
    encode_candidate_evidence,
    encode_suite_result,
)
from benchmarks.sustained_workloads import (
    SUSTAINED_FAMILY_ORDER,
    attach_fault_evidence,
    corpus_kind_for_sustained_family,
)
from uniti.resources.policy import PerformancePolicy, load_performance_policy


CommandFactory = Callable[
    [str, ExecutionClass, int, Path, Path, Path], Sequence[str]
]
FaultRunner = Callable[..., tuple[FaultResult, ...]]


def _execution_class(profile: str) -> ExecutionClass:
    try:
        return ExecutionClass(profile)
    except ValueError as exc:
        raise ValueError(f"unknown sustained profile: {profile}") from exc


def _stable_host_fingerprint(root: Path) -> dict[str, object]:
    preflight = collect_host_preflight(root, native_gui=False)
    policy = load_performance_policy()
    routine = policy.host_requirements["routine"]
    load = preflight.load_per_logical_core
    contended = (
        load is None
        or routine.max_load_per_logical_core is None
        or load > routine.max_load_per_logical_core
    )
    return {
        "architecture": preflight.architecture,
        "platform": preflight.platform,
        "physical_cores": preflight.physical_cores,
        "physical_memory": preflight.physical_memory,
        "python_version": preflight.python_version,
        "qt_version": preflight.qt_version,
        "corpus_schema": 2,
        "git_commit": preflight.git_commit,
        "contended": contended,
    }


def _default_command_factory(
    family: str,
    execution_class: ExecutionClass,
    cycles: int,
    manifest_path: Path,
    result_path: Path,
    application_root: Path,
) -> tuple[str, ...]:
    return (
        sys.executable,
        "-m",
        "benchmarks.runner",
        "--sustained-child",
        family,
        "--profile",
        execution_class.value,
        "--cycles",
        str(cycles),
        "--owned-root",
        str(application_root),
        str(manifest_path),
        str(result_path),
    )


def _selected_families(family_names: Sequence[str] | None) -> tuple[str, ...]:
    if family_names is None:
        return SUSTAINED_FAMILY_ORDER
    requested = tuple(family_names)
    if len(set(requested)) != len(requested):
        raise ValueError("sustained family names must be unique")
    unknown = set(requested) - set(SUSTAINED_FAMILY_ORDER)
    if unknown:
        raise ValueError(f"unknown sustained families: {sorted(unknown)}")
    return tuple(name for name in SUSTAINED_FAMILY_ORDER if name in requested)


def _failed_family(
    family: str,
    *,
    cycles: int,
    message: str,
) -> SustainedFamilyResult:
    return SustainedFamilyResult(
        schema=2,
        family=family,
        profile="a22-v1",
        state=ResultState.FAIL,
        warmup_cycles=1,
        measured_cycles=cycles,
        checkpoints=(),
        facts={"integrity_ok": False, "cleanup_ok": False},
        messages=(message[:1024],),
    )


def _remove_family_root(run_root: Path, family_root: Path) -> None:
    resolved_run = run_root.resolve(strict=True)
    resolved_family = family_root.resolve(strict=False)
    if resolved_family.parent != resolved_run:
        raise RuntimeError("refusing cleanup outside the exact sustained run root")
    if family_root.is_symlink():
        family_root.unlink()
    elif family_root.exists():
        shutil.rmtree(family_root)


def _read_family_result(
    result_path: Path,
    *,
    family: str,
    cycles: int,
    policy: PerformancePolicy,
) -> SustainedFamilyResult:
    maximum = policy.evidence.family_max_decoded_mib << 20
    if not result_path.exists():
        raise ValueError("child produced no result")
    if result_path.is_symlink() or not result_path.is_file():
        raise ValueError("child result is not an owned regular file")
    if result_path.stat().st_size > maximum:
        raise ValueError(f"family payload exceeds {maximum} bytes")
    result = decode_family_result(
        result_path.read_bytes(),
        max_bytes=maximum,
        max_checkpoints=cycles,
    )
    if (
        result.family != family
        or result.profile != "a22-v1"
        or result.warmup_cycles != policy.sustained.warmup_cycles
        or result.measured_cycles != cycles
    ):
        raise ValueError("child result identity mismatch")
    return result


def _run_family(
    family: str,
    *,
    execution_class: ExecutionClass,
    cycles: int,
    family_root: Path,
    fixture_size_bytes: int,
    policy: PerformancePolicy,
    command_factory: CommandFactory,
    fault_runner: FaultRunner | None,
    child_timeout_seconds: float,
    repository: Path,
) -> SustainedFamilyResult:
    application_root = family_root / "application"
    application_root.mkdir(parents=True)
    manifest = generate_corpus(
        CorpusSpec(
            corpus_kind_for_sustained_family(family),
            size_bytes=fixture_size_bytes,
            seed=22,
        ),
        family_root / "corpus",
    )
    manifest_path = family_root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest.as_dict(), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    result_path = family_root / "result.json"
    command = tuple(
        command_factory(
            family,
            execution_class,
            cycles,
            manifest_path,
            result_path,
            application_root,
        )
    )
    if not command or not all(isinstance(item, str) and item for item in command):
        raise ValueError("sustained child command must contain nonempty strings")
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    try:
        completed = subprocess.run(
            list(command),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=child_timeout_seconds,
            shell=False,
            env=environment,
            cwd=repository,
        )
    except subprocess.TimeoutExpired:
        return _failed_family(family, cycles=cycles, message="child timed out")
    except OSError as exc:
        return _failed_family(
            family,
            cycles=cycles,
            message=f"child launch failed: {type(exc).__name__}",
        )
    try:
        result = _read_family_result(
            result_path,
            family=family,
            cycles=cycles,
            policy=policy,
        )
    except (OSError, ValueError) as exc:
        return _failed_family(family, cycles=cycles, message=str(exc))
    if completed.returncode != 0 and result.state in {ResultState.PASS, ResultState.WARN}:
        return _failed_family(
            family,
            cycles=cycles,
            message=f"child exited unexpectedly with status {completed.returncode}",
        )
    if (
        family == "session_lifecycle"
        and fault_runner is not None
        and result.state in {ResultState.PASS, ResultState.WARN}
    ):
        fault_results = fault_runner(
            application_root / "fault-verification",
            timeout_seconds=policy.sustained.operation_timeout_seconds,
        )
        result = attach_fault_evidence(result, fault_results)
    return result


def _load_suite(path: Path, policy: PerformancePolicy) -> SustainedSuiteResult:
    maximum = policy.evidence.suite_max_decoded_mib << 20
    if path.stat().st_size > maximum:
        raise ValueError(f"suite payload exceeds {maximum} bytes")
    return decode_suite_result(
        path.read_bytes(),
        max_bytes=maximum,
        family_max_bytes=policy.evidence.family_max_decoded_mib << 20,
        max_checkpoints=policy.sustained.controlled_cycles,
    )


def _validate_anchor(
    anchor: SustainedSuiteResult,
    *,
    profile: str,
    host: Mapping[str, object],
) -> None:
    if (
        anchor.execution_class is not ExecutionClass.CONTROLLED
        or anchor.profile != "a22-v1"
        or anchor.state not in {ResultState.PASS, ResultState.WARN}
        or not host_fingerprints_compatible(anchor.host, host)
    ):
        raise ValueError(f"{profile} comparison anchor is incompatible or not clean")


def _write_new(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(payload)
    except FileExistsError as exc:
        raise ValueError("sustained output path already exists") from exc


def run_sustained_suite(
    profile: str,
    output: Path | None = None,
    compare: Path | None = None,
    candidate: Path | None = None,
    *,
    family_names: Sequence[str] | None = None,
    temp_root: Path | None = None,
    host_fingerprint: Mapping[str, object] | None = None,
    fixture_size_bytes: int | None = None,
    command_factory: CommandFactory = _default_command_factory,
    fault_runner: FaultRunner | None = None,
    child_timeout_seconds: float | None = None,
) -> SustainedSuiteResult:
    """Run every selected family in an isolated, sequential owned root."""

    execution_class = _execution_class(profile)
    policy = load_performance_policy()
    cycles = (
        policy.sustained.hosted_cycles
        if execution_class is ExecutionClass.HOSTED
        else policy.sustained.controlled_cycles
    )
    size_bytes = (
        policy.sustained.fixture_mib << 20
        if fixture_size_bytes is None
        else fixture_size_bytes
    )
    if (
        isinstance(size_bytes, bool)
        or not isinstance(size_bytes, int)
        or size_bytes <= 0
        or size_bytes > policy.sustained.max_fixture_mib << 20
    ):
        raise ValueError("sustained fixture size is outside the policy limit")
    timeout = (
        policy.sustained.operation_timeout_seconds
        * (policy.sustained.warmup_cycles + cycles)
        if child_timeout_seconds is None
        else child_timeout_seconds
    )
    if timeout <= 0:
        raise ValueError("sustained child timeout must be positive")
    names = _selected_families(family_names)
    root = (temp_root or Path(tempfile.gettempdir())).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    host = dict(host_fingerprint or _stable_host_fingerprint(root))
    host["corpus_schema"] = 2

    if candidate is not None:
        if execution_class is not ExecutionClass.CONTROLLED:
            raise ValueError("candidate confirmation requires the controlled profile")
        if output is None:
            raise ValueError("candidate confirmation requires a distinct output path")
        if output.expanduser().resolve() == candidate.expanduser().resolve():
            raise ValueError("candidate and output paths must be distinct")
    if compare is not None and candidate is not None:
        raise ValueError("compare and candidate cannot be combined")
    if output is not None and compare is not None and (
        output.expanduser().resolve() == compare.expanduser().resolve()
    ):
        raise ValueError("comparison and output paths must be distinct")

    anchor = _load_suite(compare, policy) if compare is not None else None
    if anchor is not None:
        _validate_anchor(anchor, profile=profile, host=host)
    first_candidate = _load_suite(candidate, policy) if candidate is not None else None
    if first_candidate is not None:
        _validate_anchor(first_candidate, profile=profile, host=host)
        if first_candidate.host.get("git_commit") != host.get("git_commit"):
            raise ValueError("candidate source commit is incompatible")

    repository = Path(__file__).resolve().parents[1]
    selected_fault_runner = fault_runner
    if selected_fault_runner is None and command_factory is _default_command_factory:
        selected_fault_runner = run_fault_suite
    families: list[SustainedFamilyResult] = []
    with tempfile.TemporaryDirectory(prefix="uniti-sustained-", dir=root) as raw_run:
        run_root = Path(raw_run).resolve()
        for index, family in enumerate(names):
            family_root = run_root / f"{index:02d}-{family}"
            family_root.mkdir()
            try:
                result = _run_family(
                    family,
                    execution_class=execution_class,
                    cycles=cycles,
                    family_root=family_root,
                    fixture_size_bytes=size_bytes,
                    policy=policy,
                    command_factory=command_factory,
                    fault_runner=selected_fault_runner,
                    child_timeout_seconds=timeout,
                    repository=repository,
                )
            except Exception as exc:
                result = _failed_family(
                    family,
                    cycles=cycles,
                    message=f"family setup failed: {type(exc).__name__}",
                )
            finally:
                _remove_family_root(run_root, family_root)
            families.append(result)

    raw_suite = SustainedSuiteResult(
        schema=2,
        profile="a22-v1",
        execution_class=execution_class,
        host=host,
        families=tuple(families),
        evaluations=tuple(
            SustainedEvaluation(family.family, family.state, family.messages)
            for family in families
        ),
    )
    suite = SustainedSuiteResult(
        schema=2,
        profile=raw_suite.profile,
        execution_class=raw_suite.execution_class,
        host=raw_suite.host,
        families=raw_suite.families,
        evaluations=evaluate_sustained_suite(raw_suite, policy, anchor=anchor),
    )
    suite_payload = encode_suite_result(
        suite,
        max_bytes=policy.evidence.suite_max_decoded_mib << 20,
        family_max_bytes=policy.evidence.family_max_decoded_mib << 20,
        max_checkpoints=policy.sustained.controlled_cycles,
    )
    payload = suite_payload
    if first_candidate is not None:
        if suite.state not in {ResultState.PASS, ResultState.WARN}:
            raise ValueError("candidate confirmation run is not clean")
        evidence = CandidateEvidence(
            schema=2,
            candidate_commit=str(host.get("git_commit") or "unknown"),
            suites=(first_candidate, suite),
        )
        payload = encode_candidate_evidence(
            evidence,
            max_bytes=policy.evidence.suite_max_decoded_mib << 20,
            family_max_bytes=policy.evidence.family_max_decoded_mib << 20,
            max_checkpoints=policy.sustained.controlled_cycles,
        )
    if output is not None:
        _write_new(output, payload)
    return suite


def render_sustained_human(suite: SustainedSuiteResult) -> str:
    lines = [
        f"UNITI sustained performance suite: {suite.state.value}",
        f"Profile: {suite.execution_class.value}",
    ]
    by_subject = {item.subject: item for item in suite.evaluations}
    for family in suite.families:
        evaluation = by_subject.get(family.family)
        state = family.state if evaluation is None else evaluation.state
        lines.append(f"{family.family}: {state.value}")
        if evaluation is not None:
            lines.extend(f"  {message}" for message in evaluation.messages)
    return "\n".join(lines) + "\n"
