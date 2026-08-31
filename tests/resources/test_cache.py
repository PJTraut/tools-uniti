from uniti.resources.cache import CacheManager, CachePriority


def test_worst_priority_is_evicted_before_visible_data():
    cache = CacheManager(budget_bytes=110)
    cache.put("visible", "v", size_bytes=60, priority=CachePriority.VISIBLE)
    cache.put("stale", "s", size_bytes=70, priority=CachePriority.STALE)
    assert cache.get("visible") == "v"
    assert cache.get("stale") is None
    assert cache.used_bytes == 60


def test_access_refreshes_lru_order_within_same_priority():
    cache = CacheManager(budget_bytes=120)
    cache.put("a", "A", size_bytes=40, priority=CachePriority.RECENT)
    cache.put("b", "B", size_bytes=40, priority=CachePriority.RECENT)
    cache.put("c", "C", size_bytes=40, priority=CachePriority.RECENT)
    assert cache.get("a") == "A"
    cache.evict_to(80)
    assert cache.get("b") is None
    assert cache.get("a") == "A"
    assert cache.get("c") == "C"


def test_replacing_entry_updates_byte_accounting():
    cache = CacheManager(budget_bytes=100)
    cache.put("x", "old", size_bytes=70, priority=CachePriority.INDEX)
    cache.put("x", "new", size_bytes=20, priority=CachePriority.INDEX)
    assert cache.used_bytes == 20
    assert cache.get("x") == "new"


def test_remove_and_clear_never_make_accounting_negative():
    cache = CacheManager(budget_bytes=100)
    cache.put("x", 1, size_bytes=10, priority=CachePriority.STALE)
    assert cache.remove("x") == 1
    assert cache.remove("x") is None
    cache.clear_disposable()
    assert cache.used_bytes == 0
