from uniti.resources.memory import (
    GIB,
    MIB,
    MemorySnapshot,
    PressureState,
    automatic_cache_target,
    pressure_state,
    probe_memory,
)


def test_automatic_policy_matches_64gib_architecture_example():
    snapshot = MemorySnapshot(physical=64 * GIB, available=50 * GIB)
    reserve = max(2 * GIB, min(8 * GIB, snapshot.physical // 10))
    claimable = snapshot.available - reserve
    expected = min(snapshot.physical // 2, claimable * 7 // 10)
    assert automatic_cache_target(snapshot) == expected


def test_effective_available_includes_reclaimable_uniti_cache():
    snapshot = MemorySnapshot(
        physical=64 * GIB,
        available=4 * GIB,
        reclaimable_cache=20 * GIB,
    )
    assert snapshot.effective_available == 24 * GIB
    assert pressure_state(snapshot) is PressureState.GREEN


def test_pressure_states_use_effective_available_ratio():
    assert pressure_state(MemorySnapshot(64 * GIB, 20 * GIB)) is PressureState.GREEN
    assert pressure_state(MemorySnapshot(64 * GIB, 12 * GIB)) is PressureState.YELLOW
    assert pressure_state(MemorySnapshot(64 * GIB, 6 * GIB)) is PressureState.ORANGE
    assert pressure_state(MemorySnapshot(64 * GIB, 3 * GIB)) is PressureState.RED


def test_unknown_memory_uses_conservative_cache_target():
    assert automatic_cache_target(MemorySnapshot(0, 0)) == 128 * MIB


def test_probe_memory_never_returns_negative_values():
    snapshot = probe_memory()
    assert snapshot.physical >= 0
    assert snapshot.available >= 0
