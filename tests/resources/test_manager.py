from uniti.resources import CachePriority, MemorySnapshot, PressureState, ResourceManager
from uniti.resources.memory import GIB


def test_resource_manager_sets_automatic_budget_and_reclaims_worst_priority_first():
    snapshot = MemorySnapshot(physical=16 * GIB, available=10 * GIB)
    manager = ResourceManager(max_workers=1, initial_snapshot=snapshot)
    try:
        assert manager.cache.budget_bytes > 0
        manager.put_cache("doc", "visible", "v", size_bytes=64, priority=CachePriority.VISIBLE)
        manager.put_cache("doc", "stale", "s", size_bytes=64, priority=CachePriority.STALE)
        manager.cache.evict_to(64)
        assert manager.get_cache("doc", "visible") == "v"
        assert manager.get_cache("doc", "stale") is None
    finally:
        manager.shutdown()


def test_inactive_owner_cache_is_demoted_and_evicted_before_active_owner():
    snapshot = MemorySnapshot(physical=16 * GIB, available=10 * GIB)
    manager = ResourceManager(max_workers=1, initial_snapshot=snapshot)
    try:
        manager.put_cache("active", "span", "A", size_bytes=50, priority=CachePriority.INDEX)
        manager.put_cache("inactive", "span", "I", size_bytes=50, priority=CachePriority.INDEX)
        manager.set_owner_active("inactive", False)
        manager.cache.evict_to(50)
        assert manager.get_cache("active", "span") == "A"
        assert manager.get_cache("inactive", "span") is None
    finally:
        manager.shutdown()


def test_pressure_recovery_requires_two_better_samples_but_escalates_immediately():
    green = MemorySnapshot(physical=16 * GIB, available=8 * GIB)
    manager = ResourceManager(max_workers=1, initial_snapshot=green)
    try:
        assert manager.pressure is PressureState.GREEN
        red = MemorySnapshot(physical=16 * GIB, available=512 * 1024 * 1024)
        assert manager.observe_memory(red) is PressureState.RED
        assert manager.observe_memory(green) is PressureState.RED
        assert manager.observe_memory(green) is PressureState.GREEN
    finally:
        manager.shutdown()


def test_evict_owner_removes_only_that_documents_disposable_cache():
    snapshot = MemorySnapshot(physical=16 * GIB, available=10 * GIB)
    manager = ResourceManager(max_workers=1, initial_snapshot=snapshot)
    try:
        manager.put_cache("a", "x", 1, size_bytes=10, priority=CachePriority.INDEX)
        manager.put_cache("b", "x", 2, size_bytes=10, priority=CachePriority.INDEX)
        assert manager.evict_owner("a") == 10
        assert manager.get_cache("a", "x") is None
        assert manager.get_cache("b", "x") == 2
    finally:
        manager.shutdown()
