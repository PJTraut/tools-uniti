"""Parent/child orchestration for isolated UNITI performance scenarios."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from .corpus import CorpusKind, CorpusManifest, CorpusSpec, generate_corpus
from .evaluate import evaluate_scenario
from .host import (
    collect_host_preflight,
    evaluate_host_eligibility,
    host_fingerprints_compatible,
)
from .models import (
    MetricSample,
    ResultState,
    ScenarioEvaluation,
    ScenarioResult,
    SuiteResult,
)
from uniti.resources.policy import load_performance_policy


@dataclass(frozen=True, slots=True)
class ChildOutcome:
    scenario: str
    state: ResultState
    returncode: int | None
    timed_out: bool
    stdout_path: Path
    stderr_path: Path


def _as_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_child_commands(
    commands: Sequence[tuple[str, Sequence[str]]],
    *,
    timeout_seconds: float,
    artifact_root: Path,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> tuple[ChildOutcome, ...]:
    """Run every command in isolation and preserve bounded diagnostic output."""

    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be positive")
    artifact_root.mkdir(parents=True, exist_ok=True)
    outcomes: list[ChildOutcome] = []
    for index, (scenario, command) in enumerate(commands):
        stdout_path = artifact_root / f"{index:02d}-{scenario}.stdout.txt"
        stderr_path = artifact_root / f"{index:02d}-{scenario}.stderr.txt"
        timed_out = False
        returncode: int | None
        try:
            completed = subprocess.run(
                list(command),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
                shell=False,
                env=None if environ is None else dict(environ),
                cwd=cwd,
            )
            returncode = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as error:
            returncode = None
            timed_out = True
            stdout = _as_text(error.stdout)
            stderr = _as_text(error.stderr)
        stdout_path.write_text(stdout, encoding="utf-8")
        stderr_path.write_text(stderr, encoding="utf-8")
        outcomes.append(
            ChildOutcome(
                scenario=scenario,
                state=(
                    ResultState.PASS
                    if returncode == 0 and not timed_out
                    else ResultState.FAIL
                ),
                returncode=returncode,
                timed_out=timed_out,
                stdout_path=stdout_path,
                stderr_path=stderr_path,
            )
        )
    return tuple(outcomes)


def merge_scenario_results(results: Sequence[ScenarioResult]) -> ScenarioResult:
    if not results:
        raise ValueError("at least one scenario result is required")
    scenario = results[0].scenario
    if any(result.scenario != scenario for result in results):
        raise ValueError("scenario repetitions must share one name")
    metrics: dict[str, list[float]] = {}
    messages: list[str] = []
    severity = {
        ResultState.PASS: 0,
        ResultState.WARN: 1,
        ResultState.NOT_RUN: 2,
        ResultState.INVALID: 3,
        ResultState.FAIL: 4,
    }
    state = ResultState.PASS
    for result in results:
        state = max((state, result.state), key=severity.__getitem__)
        messages.extend(result.messages)
        for name, sample in result.metrics.items():
            metrics.setdefault(name, []).extend(sample.values)
    facts = dict(results[0].facts)
    facts["repetitions"] = len(results)
    facts["integrity_ok"] = all(
        result.facts.get("integrity_ok") is True for result in results
    )
    return ScenarioResult(
        schema=1,
        scenario=scenario,
        state=state,
        metrics={name: MetricSample(tuple(values)) for name, values in metrics.items()},
        facts=facts,
        messages=tuple(messages),
    )


def _tier_size_bytes(tier: str, policy) -> int:
    selected = policy.tiers[tier]
    if selected.size_mib is not None:
        return selected.size_mib << 20
    assert selected.sparse_size_gib is not None
    return selected.sparse_size_gib << 30


def _load_comparison(path: Path | None) -> SuiteResult | None:
    return None if path is None else SuiteResult.from_json(path.read_text(encoding="utf-8"))


def run_suite(
    tier: str,
    mode: str,
    output: Path | None = None,
    compare: Path | None = None,
    *,
    scenario_names: Sequence[str] | None = None,
    native_gui: bool = False,
    temp_root: Path | None = None,
) -> SuiteResult:
    """Preflight, generate, isolate, evaluate, report, and clean one tier."""

    from .scenarios import (
        corpus_kind_for_scenario,
        initial_scenario_names,
    )

    normalized_tier = tier.replace("-", "_")
    policy = load_performance_policy()
    if normalized_tier not in policy.tiers:
        raise ValueError(f"unknown performance tier: {tier}")
    root = (temp_root or Path(tempfile.gettempdir())).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    preflight = collect_host_preflight(root, native_gui=native_gui)
    host = preflight.as_dict()
    host["corpus_schema"] = 1
    eligibility = evaluate_host_eligibility(
        preflight,
        policy,
        tier=normalized_tier,
        mode=mode,
    )
    if eligibility.state is not ResultState.PASS:
        suite = SuiteResult(
            1,
            normalized_tier,
            mode,
            host,
            (),
            (ScenarioEvaluation("host_preflight", eligibility.state, eligibility.messages),),
        )
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(suite.to_json(), encoding="utf-8")
        return suite

    names = tuple(scenario_names or initial_scenario_names(normalized_tier))
    size_bytes = _tier_size_bytes(normalized_tier, policy)
    repetitions = policy.tiers[normalized_tier].repetitions
    comparison = _load_comparison(compare)
    compatible = comparison is not None and host_fingerprints_compatible(
        comparison.host,
        host,
    )
    repository = Path(__file__).resolve().parents[1]
    child_environment = dict(os.environ)
    if not native_gui:
        child_environment["QT_QPA_PLATFORM"] = "offscreen"
    results: list[ScenarioResult] = []
    evaluations: list[ScenarioEvaluation] = []
    with tempfile.TemporaryDirectory(prefix="uniti-performance-", dir=root) as raw_owned:
        owned = Path(raw_owned)
        for scenario_index, name in enumerate(names):
            kind = (
                CorpusKind.SPARSE_FILE
                if normalized_tier == "design_target"
                else corpus_kind_for_scenario(name)
            )
            manifest = generate_corpus(
                CorpusSpec(kind, size_bytes=size_bytes),
                owned / f"{scenario_index:02d}-{name}-corpus",
            )
            manifest_path = owned / f"{scenario_index:02d}-{name}-manifest.json"
            manifest_path.write_text(json.dumps(manifest.as_dict()), encoding="utf-8")
            result_paths = [
                owned / f"{scenario_index:02d}-{name}-{repeat:02d}-result.json"
                for repeat in range(repetitions)
            ]
            commands = tuple(
                (
                    name,
                    (
                        sys.executable,
                        "-m",
                        "benchmarks.runner",
                        "--child",
                        name,
                        str(manifest_path),
                        str(result_path),
                    ),
                )
                for result_path in result_paths
            )
            outcomes = run_child_commands(
                commands,
                timeout_seconds=(300 if normalized_tier == "design_target" else 180),
                artifact_root=owned / f"{scenario_index:02d}-{name}-artifacts",
                environ=child_environment,
                cwd=repository,
            )
            repetitions_results: list[ScenarioResult] = []
            for outcome, result_path in zip(outcomes, result_paths, strict=True):
                if result_path.exists():
                    repetitions_results.append(
                        ScenarioResult.from_json(result_path.read_text(encoding="utf-8"))
                    )
                else:
                    reason = "child timed out" if outcome.timed_out else "child produced no result"
                    repetitions_results.append(ScenarioResult.failed(name, reason))
            merged = merge_scenario_results(repetitions_results)
            results.append(merged)
            baseline = None
            if compatible and comparison is not None:
                baseline = next(
                    (item for item in comparison.scenarios if item.scenario == name),
                    None,
                )
            evaluation = evaluate_scenario(merged, policy, baseline=baseline)
            if comparison is not None and not compatible:
                evaluation = ScenarioEvaluation(
                    evaluation.scenario,
                    evaluation.state,
                    evaluation.messages + ("comparison baseline host is incompatible",),
                )
            evaluations.append(evaluation)
    suite = SuiteResult(
        1,
        normalized_tier,
        mode,
        host,
        tuple(results),
        tuple(evaluations),
    )
    if output is not None:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(suite.to_json(), encoding="utf-8")
    return suite


def _child_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.runner")
    parser.add_argument("--child", metavar="SCENARIO")
    parser.add_argument("--sustained-child", metavar="FAMILY")
    parser.add_argument("--profile", choices=("hosted", "controlled"))
    parser.add_argument("--cycles", type=int)
    parser.add_argument("--owned-root", type=Path)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("result", type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _child_parser().parse_args(argv)
    if bool(arguments.child) == bool(arguments.sustained_child):
        raise SystemExit("exactly one of --child or --sustained-child is required")
    if arguments.sustained_child:
        if (
            arguments.profile is None
            or arguments.cycles is None
            or arguments.owned_root is None
        ):
            raise SystemExit(
                "--sustained-child requires --profile, --cycles, and --owned-root"
            )
        from .sustained_models import SustainedFamilyResult, encode_family_result
        from .sustained_workloads import run_sustained_workload

        policy = load_performance_policy()
        try:
            manifest = CorpusManifest.from_dict(
                json.loads(arguments.manifest.read_text(encoding="utf-8"))
            )
            result = run_sustained_workload(
                arguments.sustained_child,
                profile=arguments.profile,
                cycles=arguments.cycles,
                manifest=manifest,
                application_root=arguments.owned_root,
            )
        except Exception as error:
            result = SustainedFamilyResult(
                schema=2,
                family=arguments.sustained_child,
                profile="a22-v1",
                state=ResultState.FAIL,
                warmup_cycles=policy.sustained.warmup_cycles,
                measured_cycles=max(1, arguments.cycles),
                checkpoints=(),
                facts={"integrity_ok": False, "cleanup_ok": False},
                messages=(f"sustained child failed: {type(error).__name__}",),
            )
        arguments.result.write_bytes(
            encode_family_result(
                result,
                max_bytes=policy.evidence.family_max_decoded_mib << 20,
                max_checkpoints=policy.sustained.controlled_cycles,
            )
        )
        if result.state in {ResultState.PASS, ResultState.WARN}:
            return 0
        if result.state is ResultState.NOT_RUN:
            return 2
        return 1
    try:
        manifest = CorpusManifest.from_dict(
            json.loads(arguments.manifest.read_text(encoding="utf-8"))
        )
        from .scenarios import run_scenario

        result = run_scenario(arguments.child, manifest)
    except Exception as error:
        result = ScenarioResult.failed(
            arguments.child,
            f"{type(error).__name__}: {error}",
        )
    arguments.result.write_text(result.to_json(), encoding="utf-8")
    return 0 if result.state is not ResultState.FAIL else 1


if __name__ == "__main__":
    raise SystemExit(main())
