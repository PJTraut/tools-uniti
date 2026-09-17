import threading

import pytest

from uniti.resources.cancel import CancellationToken, WorkCancelled
from uniti.resources.workers import PriorityWorkerPool, WorkPriority


def test_higher_priority_queued_work_runs_before_lower_priority_work():
    pool = PriorityWorkerPool(max_workers=1, thread_name_prefix="uniti-test")
    blocker_started = threading.Event()
    release_blocker = threading.Event()
    order: list[str] = []

    def blocker():
        blocker_started.set()
        release_blocker.wait(1.0)

    try:
        running = pool.submit(WorkPriority.INTERACTIVE, blocker)
        assert blocker_started.wait(1.0)
        low = pool.submit(WorkPriority.PREFETCH, lambda: order.append("low"))
        high = pool.submit(WorkPriority.SEARCH, lambda: order.append("high"))
        release_blocker.set()
        running.result(timeout=1.0)
        high.result(timeout=1.0)
        low.result(timeout=1.0)
        assert order == ["high", "low"]
    finally:
        pool.shutdown()


def test_worker_future_propagates_exceptions():
    pool = PriorityWorkerPool(max_workers=1)
    try:
        def fail():
            raise ValueError("boom")

        future = pool.submit(WorkPriority.SEARCH, fail)
        with pytest.raises(ValueError, match="boom"):
            future.result(timeout=1.0)
    finally:
        pool.shutdown()


def test_precancelled_job_never_invokes_callable():
    pool = PriorityWorkerPool(max_workers=1)
    token = CancellationToken()
    token.cancel()
    invoked = False

    def work():
        nonlocal invoked
        invoked = True

    try:
        future = pool.submit(WorkPriority.SEARCH, work, token=token)
        with pytest.raises(WorkCancelled):
            future.result(timeout=1.0)
        assert not invoked
    finally:
        pool.shutdown()


def test_submit_after_shutdown_is_rejected():
    pool = PriorityWorkerPool(max_workers=1)
    pool.shutdown()
    with pytest.raises(RuntimeError, match="shut down"):
        pool.submit(WorkPriority.SEARCH, lambda: None)


def test_active_limit_holds_queued_work_until_capacity_increases():
    pool = PriorityWorkerPool(max_workers=2, thread_name_prefix="uniti-limit")
    release = threading.Event()
    both_started = threading.Event()
    lock = threading.Lock()
    started: list[int] = []

    def work(index: int):
        with lock:
            started.append(index)
            if len(started) == 2:
                both_started.set()
        release.wait(1.0)

    try:
        pool.set_active_limit(1)
        first = pool.submit(WorkPriority.SEARCH, work, 1)
        second = pool.submit(WorkPriority.SEARCH, work, 2)
        for _ in range(100):
            with lock:
                count = len(started)
            if count:
                break
            threading.Event().wait(0.005)
        assert count == 1
        assert pool.active_count == 1
        assert pool.queued_count == 1

        pool.set_active_limit(2)
        assert both_started.wait(1.0)
        assert pool.active_count == 2
        release.set()
        first.result(timeout=1.0)
        second.result(timeout=1.0)
    finally:
        release.set()
        pool.shutdown()


def test_round_robin_prevents_one_document_from_starving_another_at_same_priority():
    """BF-040: same-tier dispatch is round-robin by document, not pure FIFO.

    Before this fix, a burst of same-priority tasks from one document
    (e.g. a large Find-in-Selection) would dispatch strictly ahead of a
    single task from another document submitted right after it.
    """
    pool = PriorityWorkerPool(max_workers=1, thread_name_prefix="uniti-fair")
    blocker_started = threading.Event()
    release_blocker = threading.Event()
    order: list[str] = []

    def blocker():
        blocker_started.set()
        release_blocker.wait(1.0)

    try:
        running = pool.submit(WorkPriority.SEARCH, blocker, document_key="blocker")
        assert blocker_started.wait(1.0)

        a_futures = [
            pool.submit(
                WorkPriority.SEARCH,
                lambda index=index: order.append(f"a{index}"),
                document_key="doc-a",
            )
            for index in range(5)
        ]
        b_future = pool.submit(
            WorkPriority.SEARCH,
            lambda: order.append("b0"),
            document_key="doc-b",
        )

        release_blocker.set()
        running.result(timeout=1.0)
        for future in a_futures:
            future.result(timeout=1.0)
        b_future.result(timeout=1.0)

        assert order == ["a0", "b0", "a1", "a2", "a3", "a4"]
    finally:
        pool.shutdown()


def test_active_limit_is_clamped_to_pool_capacity():
    pool = PriorityWorkerPool(max_workers=3)
    try:
        pool.set_active_limit(0)
        assert pool.active_limit == 1
        pool.set_active_limit(99)
        assert pool.active_limit == 3
    finally:
        pool.shutdown()
