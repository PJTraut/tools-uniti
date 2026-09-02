"""Evaluate scenario measurements against the shared product policy."""

from __future__ import annotations

from benchmarks.models import ResultState, ScenarioEvaluation, ScenarioResult
from uniti.resources.policy import PerformancePolicy


_SEVERITY = {
    ResultState.PASS: 0,
    ResultState.WARN: 1,
    ResultState.NOT_RUN: 2,
    ResultState.INVALID: 3,
    ResultState.FAIL: 4,
}


def _worse(left: ResultState, right: ResultState) -> ResultState:
    return left if _SEVERITY[left] >= _SEVERITY[right] else right


def evaluate_scenario(
    result: ScenarioResult,
    policy: PerformancePolicy,
    baseline: ScenarioResult | None = None,
) -> ScenarioEvaluation:
    """Apply absolute gates and optional lower-is-better regression limits."""

    state = result.state
    messages = list(result.messages)
    if state not in {ResultState.PASS, ResultState.WARN}:
        return ScenarioEvaluation(result.scenario, state, tuple(messages))

    if result.facts.get("integrity_ok") is False:
        state = ResultState.FAIL
        messages.append("integrity check failed")

    for name, sample in sorted(result.metrics.items()):
        gate = policy.gates.get(name)
        if gate is None:
            continue
        fail = gate.fail
        if gate.physical_ram_fraction_fail is not None:
            physical = result.facts.get("physical_memory_bytes")
            if isinstance(physical, (int, float)) and physical >= 0:
                fraction_mib = float(physical) * gate.physical_ram_fraction_fail / (1 << 20)
                fail = min(fail, fraction_mib)
        value = sample.median
        if value >= fail:
            state = _worse(state, ResultState.FAIL)
            messages.append(f"{name} {value:g} reached failure limit {fail:g}")
        elif value >= gate.warn:
            state = _worse(state, ResultState.WARN)
            messages.append(f"{name} {value:g} reached warning limit {gate.warn:g}")

    if baseline is not None and baseline.scenario == result.scenario:
        for name, sample in sorted(result.metrics.items()):
            previous = baseline.metrics.get(name)
            if previous is None or previous.median <= 0:
                continue
            change = (sample.median - previous.median) * 100.0 / previous.median
            if change >= policy.comparison.regression_failure_percent:
                state = _worse(state, ResultState.FAIL)
                messages.append(f"{name} has a {change:.1f}% regression from baseline")
            elif change >= policy.comparison.regression_warning_percent:
                state = _worse(state, ResultState.WARN)
                messages.append(f"{name} has a {change:.1f}% regression from baseline")

    return ScenarioEvaluation(result.scenario, state, tuple(messages))
