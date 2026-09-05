from __future__ import annotations

from dataclasses import replace

import pytest

from benchmarks.evaluate import evaluate_scenario
from benchmarks.sustained_evaluate import evaluate_sustained_suite
from benchmarks.sustained_models import (
    ExecutionClass,
    ResourceCheckpoint,
    SustainedEvaluation,
    SustainedFamilyResult,
    SustainedSuiteResult,
)
from benchmarks.models import (
    MetricSample,
    ResultState,
    ScenarioEvaluation,
    ScenarioResult,
    SuiteResult,
)
from benchmarks.report import render_human
from uniti.resources.policy import load_performance_policy


def _sustained_suite(
    *,
    execution_class: ExecutionClass,
    git_commit: str,
    cycle_ms: float,
    integrity_ok: bool = True,
    architecture: str = "x86_64",
    contended: bool = False,
    absolute_interaction_ms: float | None = None,
) -> SustainedSuiteResult:
    cycles = 5 if execution_class is ExecutionClass.HOSTED else 50
    checkpoints = []
    for cycle in range(1, cycles + 1):
        metrics = {"format_cycle_ms": cycle_ms, "rss_mib": 100.0}
        if absolute_interaction_ms is not None:
            metrics["interaction_max_ms"] = absolute_interaction_ms
        checkpoints.append(ResourceCheckpoint(cycle, metrics, {}, ("handle_count",)))
    family = SustainedFamilyResult(
        schema=2,
        family="format_integrity",
        profile="a22-v1",
        state=ResultState.PASS,
        warmup_cycles=1,
        measured_cycles=cycles,
        checkpoints=tuple(checkpoints),
        facts={"integrity_ok": integrity_ok},
        messages=(),
    )
    return SustainedSuiteResult(
        schema=2,
        profile="a22-v1",
        execution_class=execution_class,
        host={
            "architecture": architecture,
            "platform": "linux",
            "physical_cores": 8,
            "physical_memory": 16 << 30,
            "python_version": "3.12.4",
            "qt_version": "6.11.2",
            "corpus_schema": 2,
            "git_commit": git_commit,
            "contended": contended,
        },
        families=(family,),
        evaluations=(
            SustainedEvaluation("format_integrity", ResultState.PASS, ()),
        ),
    )


def test_evaluator_hard_fails_gui_freeze():
    result = ScenarioResult.success(
        scenario="search_sparse",
        metrics={"gui_heartbeat_max_ms": MetricSample((120.0,))},
    )

    evaluation = evaluate_scenario(result, load_performance_policy())

    assert evaluation.state is ResultState.FAIL
    assert "100" in evaluation.messages[0]


def test_evaluator_warns_between_warning_and_failure_limits():
    result = ScenarioResult.success(
        scenario="open_first_paint",
        metrics={"open_to_usable_ms": MetricSample((700.0,))},
    )

    evaluation = evaluate_scenario(result, load_performance_policy())

    assert evaluation.state is ResultState.WARN


def test_evaluator_applies_smaller_physical_memory_rss_limit():
    result = ScenarioResult.success(
        scenario="search_sparse",
        metrics={"peak_rss_mib": MetricSample((200.0,))},
        facts={"physical_memory_bytes": 1 << 30},
    )

    evaluation = evaluate_scenario(result, load_performance_policy())

    assert evaluation.state is ResultState.FAIL
    assert "128" in evaluation.messages[0]


def test_evaluator_hard_fails_text_integrity_loss():
    result = ScenarioResult.success(
        scenario="save_as",
        facts={"integrity_ok": False},
    )

    evaluation = evaluate_scenario(result, load_performance_policy())

    assert evaluation.state is ResultState.FAIL
    assert evaluation.messages == ("integrity check failed",)


def test_compatible_baseline_regression_uses_median_samples():
    baseline = ScenarioResult.success(
        scenario="navigation",
        metrics={"interaction_max_ms": MetricSample((20.0, 20.0, 20.0))},
    )
    current = ScenarioResult.success(
        scenario="navigation",
        metrics={"interaction_max_ms": MetricSample((25.0, 25.0, 25.0))},
    )

    evaluation = evaluate_scenario(
        current,
        load_performance_policy(),
        baseline=baseline,
    )

    assert evaluation.state is ResultState.FAIL
    assert any("25.0% regression" in message for message in evaluation.messages)


def test_scenario_json_round_trip_preserves_metrics_and_facts():
    result = ScenarioResult.success(
        scenario="typing",
        metrics={"interaction_p95_ms": MetricSample((1.0, 2.0, 3.0))},
        facts={"integrity_ok": True, "characters": 3},
    )

    restored = ScenarioResult.from_json(result.to_json())

    assert restored == result


def test_suite_json_and_human_report_preserve_gate_outcome():
    scenario = ScenarioResult.success(
        scenario="open_first_paint",
        metrics={"open_to_usable_ms": MetricSample((125.0,))},
        facts={"integrity_ok": True},
    )
    suite = SuiteResult(
        schema=1,
        tier="quick",
        mode="baseline",
        host={"cpu_model": "Test CPU", "git_commit": "abc"},
        scenarios=(scenario,),
        evaluations=(
            ScenarioEvaluation("open_first_paint", ResultState.PASS, ()),
        ),
    )

    restored = SuiteResult.from_json(suite.to_json())
    rendered = render_human(restored)

    assert restored == suite
    assert "UNITI performance suite: PASS" in rendered
    assert "open_first_paint: PASS" in rendered
    assert "open_to_usable_ms median=125" in rendered


def test_hosted_timing_regression_remains_diagnostic():
    anchor = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="anchor",
        cycle_ms=100.0,
    )
    hosted = _sustained_suite(
        execution_class=ExecutionClass.HOSTED,
        git_commit="candidate",
        cycle_ms=125.0,
    )

    evaluation = evaluate_sustained_suite(
        hosted,
        load_performance_policy(),
        anchor=anchor,
    )[0]

    assert evaluation.state is ResultState.PASS
    assert any("diagnostic" in message for message in evaluation.messages)


def test_absolute_responsiveness_failure_is_immediate_on_hosted_runs():
    hosted = _sustained_suite(
        execution_class=ExecutionClass.HOSTED,
        git_commit="candidate",
        cycle_ms=1.0,
        absolute_interaction_ms=100.0,
    )

    evaluation = evaluate_sustained_suite(
        hosted,
        load_performance_policy(),
    )[0]

    assert evaluation.state is ResultState.FAIL
    assert any("interaction_max_ms" in message for message in evaluation.messages)


def test_one_controlled_25_percent_regression_is_provisional_warning():
    anchor = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="anchor",
        cycle_ms=100.0,
    )
    candidate = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="candidate",
        cycle_ms=125.0,
    )

    evaluation = evaluate_sustained_suite(
        candidate,
        load_performance_policy(),
        anchor=anchor,
    )[0]

    assert evaluation.state is ResultState.WARN
    assert any("provisional" in message for message in evaluation.messages)


def test_two_compatible_clean_25_percent_regressions_fail():
    anchor = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="anchor",
        cycle_ms=100.0,
    )
    candidate = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="candidate",
        cycle_ms=125.0,
    )
    confirmation = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="candidate",
        cycle_ms=125.0,
    )

    evaluation = evaluate_sustained_suite(
        candidate,
        load_performance_policy(),
        anchor=anchor,
        confirmation=confirmation,
    )[0]

    assert evaluation.state is ResultState.FAIL
    assert any("confirmed" in message for message in evaluation.messages)


@pytest.mark.parametrize("problem", ["incompatible", "contended"])
def test_bad_confirmation_evidence_is_invalid(problem: str):
    anchor = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="anchor",
        cycle_ms=100.0,
    )
    candidate = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="candidate",
        cycle_ms=125.0,
    )
    confirmation = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="candidate",
        cycle_ms=125.0,
        architecture=("arm64" if problem == "incompatible" else "x86_64"),
        contended=problem == "contended",
    )

    evaluation = evaluate_sustained_suite(
        candidate,
        load_performance_policy(),
        anchor=anchor,
        confirmation=confirmation,
    )[0]

    assert evaluation.state is ResultState.INVALID
    assert any(problem in message for message in evaluation.messages)


def test_integrity_failure_wins_over_comparative_timing():
    anchor = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="anchor",
        cycle_ms=100.0,
    )
    candidate = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="candidate",
        cycle_ms=125.0,
        integrity_ok=False,
    )

    evaluation = evaluate_sustained_suite(
        candidate,
        load_performance_policy(),
        anchor=anchor,
    )[0]

    assert evaluation.state is ResultState.FAIL
    assert evaluation.messages[0] == "integrity check failed"


def test_missing_checkpoint_evidence_is_invalid_instead_of_crashing_comparison():
    anchor = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="anchor",
        cycle_ms=100.0,
    )
    candidate = _sustained_suite(
        execution_class=ExecutionClass.CONTROLLED,
        git_commit="candidate",
        cycle_ms=100.0,
    )
    empty_family = replace(candidate.families[0], checkpoints=())
    candidate = replace(candidate, families=(empty_family,))

    evaluation = evaluate_sustained_suite(
        candidate,
        load_performance_policy(),
        anchor=anchor,
    )[0]

    assert evaluation.state is ResultState.INVALID
    assert any("checkpoint" in message for message in evaluation.messages)
