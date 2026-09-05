"""Pure sustained correctness, growth, and comparison evaluation."""

from __future__ import annotations

from benchmarks.growth import (
    metric_median,
    metric_window_growth,
    owned_count_growth,
    select_growth_windows,
)
from benchmarks.host import host_fingerprints_compatible
from benchmarks.models import RESULT_STATE_SEVERITY, ResultState
from benchmarks.sustained_models import (
    ExecutionClass,
    SustainedEvaluation,
    SustainedFamilyResult,
    SustainedSuiteResult,
)
from uniti.resources.policy import PerformancePolicy


def _worse(left: ResultState, right: ResultState) -> ResultState:
    return left if RESULT_STATE_SEVERITY[left] >= RESULT_STATE_SEVERITY[right] else right


def _expected_cycles(policy: PerformancePolicy, execution_class: ExecutionClass) -> int:
    if execution_class is ExecutionClass.HOSTED:
        return policy.sustained.hosted_cycles
    if execution_class is ExecutionClass.CONTROLLED:
        return policy.sustained.controlled_cycles
    raise ValueError("unknown execution class")


def evaluate_sustained_family(
    result: SustainedFamilyResult,
    policy: PerformancePolicy,
    *,
    execution_class: ExecutionClass,
) -> SustainedEvaluation:
    """Apply immediate, absolute, and window-growth gates to one family."""

    state = result.state
    messages: list[str] = []
    if result.facts.get("integrity_ok") is False:
        state = _worse(state, ResultState.FAIL)
        messages.append("integrity check failed")
    messages.extend(result.messages)

    expected_cycles = _expected_cycles(policy, execution_class)
    if result.measured_cycles != expected_cycles:
        state = _worse(state, ResultState.INVALID)
        messages.append(
            f"measured cycle count {result.measured_cycles} does not match "
            f"{execution_class.value} policy {expected_cycles}"
        )

    try:
        early, late = select_growth_windows(
            result.checkpoints,
            measured_cycles=result.measured_cycles,
        )
    except ValueError as exc:
        state = _worse(state, ResultState.INVALID)
        messages.append(str(exc))
        return SustainedEvaluation(result.family, state, tuple(messages))

    metric_names = set().union(
        *(checkpoint.metrics.keys() for checkpoint in result.checkpoints)
    )
    for name in sorted(metric_names):
        gate = policy.gates.get(name)
        if gate is None:
            continue
        values = tuple(checkpoint.metrics.get(name) for checkpoint in result.checkpoints)
        if any(value is None for value in values):
            state = _worse(state, ResultState.INVALID)
            messages.append(f"absolute metric is incomplete: {name}")
            continue
        fail = gate.fail
        if gate.physical_ram_fraction_fail is not None:
            physical = result.facts.get("physical_memory_bytes")
            if isinstance(physical, (int, float)) and not isinstance(physical, bool):
                fraction_mib = (
                    float(physical)
                    * gate.physical_ram_fraction_fail
                    / (1 << 20)
                )
                fail = min(fail, fraction_mib)
        maximum = max(float(value) for value in values if value is not None)
        if maximum >= fail:
            state = _worse(state, ResultState.FAIL)
            messages.append(f"{name} {maximum:g} reached failure limit {fail:g}")
        elif maximum >= gate.warn:
            state = _worse(state, ResultState.WARN)
            messages.append(f"{name} {maximum:g} reached warning limit {gate.warn:g}")

    try:
        rss_growth = metric_window_growth(early, late, "rss_mib")
    except ValueError as exc:
        state = _worse(state, ResultState.INVALID)
        messages.append(str(exc))
    else:
        if rss_growth >= policy.sustained.rss_growth_fail_mib:
            state = _worse(state, ResultState.FAIL)
            messages.append(
                f"rss_mib grew {rss_growth:g} MiB and reached the "
                f"{policy.sustained.rss_growth_fail_mib:g} MiB failure limit"
            )
        elif rss_growth >= policy.sustained.rss_growth_warn_mib:
            state = _worse(state, ResultState.WARN)
            messages.append(
                f"rss_mib grew {rss_growth:g} MiB and reached the "
                f"{policy.sustained.rss_growth_warn_mib:g} MiB warning limit"
            )

    handles_unavailable = any(
        "handle_count" in checkpoint.unavailable_probes
        for checkpoint in result.checkpoints
    )
    if not handles_unavailable:
        try:
            handle_growth = metric_window_growth(early, late, "handle_count")
        except ValueError as exc:
            state = _worse(state, ResultState.INVALID)
            messages.append(str(exc))
        else:
            if handle_growth >= policy.sustained.handle_growth_fail:
                state = _worse(state, ResultState.FAIL)
                messages.append(
                    f"handle_count grew {handle_growth:g} and reached the "
                    f"{policy.sustained.handle_growth_fail} failure allowance"
                )
            elif handle_growth >= policy.sustained.handle_growth_warn:
                state = _worse(state, ResultState.WARN)
                messages.append(
                    f"handle_count grew {handle_growth:g} and reached the "
                    f"{policy.sustained.handle_growth_warn} warning allowance"
                )

    try:
        count_growth = owned_count_growth(early, late)
    except ValueError as exc:
        state = _worse(state, ResultState.INVALID)
        messages.append(str(exc))
    else:
        for name, growth in count_growth.items():
            if growth > 0:
                state = _worse(state, ResultState.FAIL)
                messages.append(f"owned {name} grew by {growth:g}")

    return SustainedEvaluation(result.family, state, tuple(messages))


def _families(suite: SustainedSuiteResult) -> dict[str, SustainedFamilyResult]:
    return {family.family: family for family in suite.families}


def _suite_identity_compatible(
    reference: SustainedSuiteResult,
    candidate: SustainedSuiteResult,
    *,
    require_same_commit: bool,
) -> bool:
    if reference.profile != candidate.profile:
        return False
    if not host_fingerprints_compatible(reference.host, candidate.host):
        return False
    if require_same_commit and reference.host.get("git_commit") != candidate.host.get(
        "git_commit"
    ):
        return False
    reference_families = _families(reference)
    candidate_families = _families(candidate)
    if set(reference_families) != set(candidate_families):
        return False
    for name, family in reference_families.items():
        other = candidate_families[name]
        if (
            family.profile,
            family.warmup_cycles,
        ) != (
            other.profile,
            other.warmup_cycles,
        ):
            return False
        if (
            reference.execution_class is candidate.execution_class
            and family.measured_cycles != other.measured_cycles
        ):
            return False
    return True


def _timing_changes(
    candidate: SustainedFamilyResult,
    anchor: SustainedFamilyResult,
) -> dict[str, float]:
    if not candidate.checkpoints or not anchor.checkpoints:
        return {}
    candidate_names = set.intersection(
        *(set(checkpoint.metrics) for checkpoint in candidate.checkpoints)
    )
    anchor_names = set.intersection(
        *(set(checkpoint.metrics) for checkpoint in anchor.checkpoints)
    )
    changes: dict[str, float] = {}
    for name in sorted(candidate_names & anchor_names):
        if not name.endswith("_ms"):
            continue
        baseline = metric_median(anchor.checkpoints, name)
        if baseline <= 0:
            continue
        current = metric_median(candidate.checkpoints, name)
        changes[name] = (current - baseline) * 100.0 / baseline
    return changes


def _confirmation_problem(
    candidate: SustainedSuiteResult,
    confirmation: SustainedSuiteResult,
    policy: PerformancePolicy,
) -> str | None:
    if confirmation.host.get("contended") is True:
        return "confirmation evidence is contended"
    if confirmation.execution_class is not ExecutionClass.CONTROLLED:
        return "confirmation evidence is incompatible"
    if not _suite_identity_compatible(
        candidate,
        confirmation,
        require_same_commit=True,
    ):
        return "confirmation evidence is incompatible"
    for family in confirmation.families:
        evaluation = evaluate_sustained_family(
            family,
            policy,
            execution_class=confirmation.execution_class,
        )
        if evaluation.state not in {ResultState.PASS, ResultState.WARN}:
            return "confirmation evidence is not clean"
    return None


def evaluate_sustained_suite(
    suite: SustainedSuiteResult,
    policy: PerformancePolicy,
    *,
    anchor: SustainedSuiteResult | None = None,
    confirmation: SustainedSuiteResult | None = None,
) -> tuple[SustainedEvaluation, ...]:
    """Evaluate one suite without mutating run, anchor, or confirmation evidence."""

    anchor_families = _families(anchor) if anchor is not None else {}
    confirmation_families = (
        _families(confirmation) if confirmation is not None else {}
    )
    comparison_compatible = anchor is None or _suite_identity_compatible(
        anchor,
        suite,
        require_same_commit=False,
    )
    confirmation_problem = (
        _confirmation_problem(suite, confirmation, policy)
        if confirmation is not None
        else None
    )
    evaluations: list[SustainedEvaluation] = []
    for family in suite.families:
        immediate = evaluate_sustained_family(
            family,
            policy,
            execution_class=suite.execution_class,
        )
        state = immediate.state
        messages = list(immediate.messages)
        if suite.execution_class is ExecutionClass.CONTROLLED and suite.host.get(
            "contended"
        ) is True:
            state = _worse(state, ResultState.INVALID)
            messages.append("controlled candidate evidence is contended")

        if anchor is not None:
            anchor_family = anchor_families.get(family.family)
            if anchor_family is None or not comparison_compatible:
                state = _worse(state, ResultState.INVALID)
                messages.append("anchor evidence is incompatible")
            else:
                changes = _timing_changes(family, anchor_family)
                for name, change in changes.items():
                    if suite.execution_class is ExecutionClass.HOSTED:
                        if change >= policy.comparison.regression_warning_percent:
                            messages.append(
                                f"{name} has a diagnostic hosted regression of "
                                f"{change:.1f}%"
                            )
                        continue
                    if change >= policy.comparison.regression_failure_percent:
                        if confirmation is None:
                            state = _worse(state, ResultState.WARN)
                            messages.append(
                                f"{name} has a provisional {change:.1f}% regression"
                            )
                            continue
                        if confirmation_problem is not None:
                            state = _worse(state, ResultState.INVALID)
                            messages.append(confirmation_problem)
                            continue
                        confirmed_family = confirmation_families[family.family]
                        confirmed_change = _timing_changes(
                            confirmed_family, anchor_family
                        ).get(name)
                        if (
                            confirmed_change is not None
                            and confirmed_change
                            >= policy.comparison.regression_failure_percent
                            and policy.comparison.required_failure_confirmations <= 2
                        ):
                            state = _worse(state, ResultState.FAIL)
                            messages.append(
                                f"{name} confirmed a {change:.1f}% regression "
                                f"in two clean runs"
                            )
                        else:
                            state = _worse(state, ResultState.WARN)
                            messages.append(
                                f"{name} has an unconfirmed {change:.1f}% regression"
                            )
                    elif change >= policy.comparison.regression_warning_percent:
                        state = _worse(state, ResultState.WARN)
                        messages.append(f"{name} has a {change:.1f}% regression")

        evaluations.append(
            SustainedEvaluation(family.family, state, tuple(messages))
        )
    return tuple(evaluations)
