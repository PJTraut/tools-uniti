"""Human-readable rendering for stable JSON performance evidence."""

from __future__ import annotations

from .models import SuiteResult


def render_human(suite: SuiteResult) -> str:
    lines = [
        f"UNITI performance suite: {suite.state.value}",
        f"Tier: {suite.tier}",
        f"Mode: {suite.mode}",
        f"Host: {suite.host.get('cpu_model', 'unknown')}",
    ]
    evaluations = {item.scenario: item for item in suite.evaluations}
    for scenario in suite.scenarios:
        evaluation = evaluations.get(scenario.scenario)
        state = scenario.state if evaluation is None else evaluation.state
        lines.append(f"{scenario.scenario}: {state.value}")
        for name, sample in sorted(scenario.metrics.items()):
            lines.append(
                f"  {name} median={sample.median:g} p95={sample.p95:g} max={sample.maximum:g}"
            )
        if evaluation is not None:
            lines.extend(f"  {message}" for message in evaluation.messages)
    for evaluation in suite.evaluations:
        if evaluation.scenario not in {item.scenario for item in suite.scenarios}:
            lines.append(f"{evaluation.scenario}: {evaluation.state.value}")
            lines.extend(f"  {message}" for message in evaluation.messages)
    return "\n".join(lines) + "\n"
