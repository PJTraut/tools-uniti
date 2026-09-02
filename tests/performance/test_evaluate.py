from __future__ import annotations

from benchmarks.evaluate import evaluate_scenario
from benchmarks.models import (
    MetricSample,
    ResultState,
    ScenarioEvaluation,
    ScenarioResult,
    SuiteResult,
)
from benchmarks.report import render_human
from uniti.resources.policy import load_performance_policy


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
