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
