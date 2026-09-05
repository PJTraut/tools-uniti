"""Pure checkpoint-window calculations for sustained performance evidence."""

from __future__ import annotations

import statistics
from typing import Mapping

from benchmarks.sustained_models import ResourceCheckpoint


def select_growth_windows(
    checkpoints: tuple[ResourceCheckpoint, ...],
    *,
    measured_cycles: int,
) -> tuple[tuple[ResourceCheckpoint, ...], tuple[ResourceCheckpoint, ...]]:
    """Select the policy-defined early and late checkpoint windows."""

    if isinstance(measured_cycles, bool) or measured_cycles not in {5, 50}:
        raise ValueError("growth windows require exactly 5 or 50 measured cycles")
    if len(checkpoints) != measured_cycles:
        raise ValueError("one checkpoint is required for every measured cycle")
    if not all(isinstance(item, ResourceCheckpoint) for item in checkpoints):
        raise ValueError("growth windows require resource checkpoints")
    expected_cycles = tuple(range(1, measured_cycles + 1))
    if tuple(item.cycle for item in checkpoints) != expected_cycles:
        raise ValueError("checkpoint cycles must cover the measured sequence")
    width = 2 if measured_cycles == 5 else 10
    return checkpoints[:width], checkpoints[-width:]


def metric_window_growth(
    early: tuple[ResourceCheckpoint, ...],
    late: tuple[ResourceCheckpoint, ...],
    metric: str,
) -> float:
    """Return late-window median minus early-window median for one metric."""

    try:
        early_values = tuple(item.metrics[metric] for item in early)
        late_values = tuple(item.metrics[metric] for item in late)
    except KeyError as exc:
        raise ValueError(f"checkpoint metric is incomplete: {metric}") from exc
    if not early_values or not late_values:
        raise ValueError("growth windows must not be empty")
    return float(statistics.median(late_values) - statistics.median(early_values))


def owned_count_growth(
    early: tuple[ResourceCheckpoint, ...],
    late: tuple[ResourceCheckpoint, ...],
) -> Mapping[str, float]:
    """Return median growth for every consistently reported owned count."""

    if not early or not late:
        raise ValueError("growth windows must not be empty")
    names = set(early[0].owned_counts)
    if any(set(item.owned_counts) != names for item in (*early, *late)):
        raise ValueError("owned count checkpoints must use consistent keys")
    return {
        name: float(
            statistics.median(item.owned_counts[name] for item in late)
            - statistics.median(item.owned_counts[name] for item in early)
        )
        for name in sorted(names)
    }


def metric_median(
    checkpoints: tuple[ResourceCheckpoint, ...], metric: str
) -> float:
    """Return the median value of a complete checkpoint metric."""

    if not checkpoints:
        raise ValueError("metric median requires checkpoints")
    try:
        values = tuple(item.metrics[metric] for item in checkpoints)
    except KeyError as exc:
        raise ValueError(f"checkpoint metric is incomplete: {metric}") from exc
    return float(statistics.median(values))
