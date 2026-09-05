from __future__ import annotations

import pytest

from benchmarks.models import ResultState
from benchmarks.growth import select_growth_windows
from benchmarks.sustained_evaluate import evaluate_sustained_family
from benchmarks.sustained_models import (
    ExecutionClass,
    ResourceCheckpoint,
    SustainedFamilyResult,
)
from uniti.resources.policy import load_performance_policy


def _checkpoint(
    cycle: int,
    *,
    rss_mib: float = 100.0,
    retained_rss_mib: float = 0.0,
    handle_count: float = 20.0,
    owned_counts: dict[str, int] | None = None,
    unavailable_probes: tuple[str, ...] = (),
) -> ResourceCheckpoint:
    return ResourceCheckpoint(
        cycle=cycle,
        metrics={
            "rss_mib": rss_mib,
            "retained_rss_mib": retained_rss_mib,
            "handle_count": handle_count,
        },
        owned_counts=owned_counts
        or {
            "documents": 0,
            "tasks": 0,
            "result_stores": 0,
            "replacement_plans": 0,
            "snapshots": 0,
            "temp_paths": 0,
        },
        unavailable_probes=unavailable_probes,
    )


def _family(checkpoints: tuple[ResourceCheckpoint, ...]) -> SustainedFamilyResult:
    return SustainedFamilyResult(
        schema=2,
        family="daily_editing",
        profile="a22-v1",
        state=ResultState.PASS,
        warmup_cycles=1,
        measured_cycles=len(checkpoints),
        checkpoints=checkpoints,
        facts={"integrity_ok": True},
        messages=(),
    )


def _growth_family(
    *,
    cycles: int,
    rss_growth: float = 0.0,
    retained_rss_mib: float = 0.0,
    handle_growth: float = 0.0,
    owned_name: str | None = None,
    handles_available: bool = True,
) -> SustainedFamilyResult:
    early_count = 2 if cycles == 5 else 10
    late_start = cycles - early_count + 1
    checkpoints = []
    for cycle in range(1, cycles + 1):
        late = cycle >= late_start
        counts = {
            "documents": 0,
            "tasks": 0,
            "result_stores": 0,
            "replacement_plans": 0,
            "snapshots": 0,
            "temp_paths": 0,
        }
        if owned_name is not None and late:
            counts[owned_name] = 1
        checkpoints.append(
            _checkpoint(
                cycle,
                rss_mib=100.0 + (rss_growth if late else 0.0),
                retained_rss_mib=retained_rss_mib if late else 0.0,
                handle_count=20.0 + (handle_growth if late else 0.0),
                owned_counts=counts,
                unavailable_probes=(() if handles_available else ("handle_count",)),
            )
        )
    return _family(tuple(checkpoints))


def test_five_cycle_growth_windows_use_cycles_one_two_and_four_five():
    checkpoints = tuple(_checkpoint(cycle) for cycle in range(1, 6))

    early, late = select_growth_windows(checkpoints, measured_cycles=5)

    assert tuple(item.cycle for item in early) == (1, 2)
    assert tuple(item.cycle for item in late) == (4, 5)


def test_fifty_cycle_growth_windows_use_first_and_last_ten():
    checkpoints = tuple(_checkpoint(cycle) for cycle in range(1, 51))

    early, late = select_growth_windows(checkpoints, measured_cycles=50)

    assert tuple(item.cycle for item in early) == tuple(range(1, 11))
    assert tuple(item.cycle for item in late) == tuple(range(41, 51))


@pytest.mark.parametrize(
    ("growth", "expected"),
    [
        (15.9, ResultState.PASS),
        (16.0, ResultState.WARN),
        (32.0, ResultState.FAIL),
    ],
)
def test_late_rss_growth_uses_16_and_32_mib_gates(
    growth: float,
    expected: ResultState,
):
    result = evaluate_sustained_family(
        _growth_family(cycles=5, rss_growth=growth),
        load_performance_policy(),
        execution_class=ExecutionClass.HOSTED,
    )

    assert result.state is expected


def test_inherited_64_mib_retained_growth_gate_fails_immediately():
    result = evaluate_sustained_family(
        _growth_family(cycles=5, retained_rss_mib=64.0),
        load_performance_policy(),
        execution_class=ExecutionClass.HOSTED,
    )

    assert result.state is ResultState.FAIL
    assert any("retained_rss_mib" in message for message in result.messages)


@pytest.mark.parametrize(
    "owned_name",
    [
        "documents",
        "tasks",
        "result_stores",
        "replacement_plans",
        "snapshots",
        "temp_paths",
    ],
)
def test_any_late_owned_resource_growth_fails_exactly(owned_name: str):
    result = evaluate_sustained_family(
        _growth_family(cycles=5, owned_name=owned_name),
        load_performance_policy(),
        execution_class=ExecutionClass.HOSTED,
    )

    assert result.state is ResultState.FAIL
    assert any(owned_name in message for message in result.messages)


@pytest.mark.parametrize(
    ("growth", "available", "expected"),
    [
        (4.0, True, ResultState.WARN),
        (16.0, True, ResultState.FAIL),
        (100.0, False, ResultState.PASS),
    ],
)
def test_handle_growth_allowance_applies_only_to_available_probe(
    growth: float,
    available: bool,
    expected: ResultState,
):
    result = evaluate_sustained_family(
        _growth_family(
            cycles=5,
            handle_growth=growth,
            handles_available=available,
        ),
        load_performance_policy(),
        execution_class=ExecutionClass.HOSTED,
    )

    assert result.state is expected
