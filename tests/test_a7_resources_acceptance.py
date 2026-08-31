from uniti.resources import (
    CacheManager,
    CachePriority,
    MemorySnapshot,
    PriorityWorkerPool,
    WorkPriority,
    automatic_cache_target,
)
from uniti.resources.memory import GIB


def test_resource_services_form_headless_alpha_runtime_contract():
    snapshot = MemorySnapshot(physical=16 * GIB, available=10 * GIB)
    target = automatic_cache_target(snapshot)
    assert target > 0

    cache = CacheManager(budget_bytes=128)
    cache.put("visible", "viewport", size_bytes=64, priority=CachePriority.VISIBLE)
    cache.put("stale", "old", size_bytes=96, priority=CachePriority.STALE)
    assert cache.get("visible") == "viewport"
    assert cache.used_bytes <= cache.budget_bytes

    pool = PriorityWorkerPool(max_workers=1)
    try:
        future = pool.submit(WorkPriority.SEARCH, lambda: "search-complete")
        assert future.result(timeout=1.0) == "search-complete"
    finally:
        pool.shutdown()
