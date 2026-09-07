from __future__ import annotations

import threading
import time
from concurrent.futures import Future
from threading import Event
from types import SimpleNamespace

import pytest

from uniti.resources import MemorySnapshot, ResourceManager
from uniti.resources.tasks import (
    LatestTaskSlot,
    TaskAdmissionError,
    TaskCoordinator,
    TaskKind,
    TaskSpec,
    TaskState,
)
from uniti.resources.workers import WorkPriority


@pytest.fixture
def resource_manager():
    manager = ResourceManager(
        max_workers=2,
        initial_snapshot=MemorySnapshot(16 << 30, 8 << 30),
    )
    yield manager
    manager.shutdown()


def test_task_progress_and_completion_are_observable(resource_manager):
    release = Event()
    spec = TaskSpec.create(
        TaskKind.INDEX,
        foreground=False,
        document_key="doc",
        revision=3,
    )
    handle = resource_manager.tasks.submit(
        spec,
        lambda context: (
            context.report("indexing", 4, 10),
            release.wait(2),
            "done",
        )[-1],
    )

    assert handle.wait_for_progress(timeout=1).completed == 4
    assert resource_manager.tasks.snapshot().active_count == 1
    release.set()
    assert handle.future.result(timeout=2) == "done"
    assert handle.state is TaskState.COMPLETED


def test_task_notifications_wake_consumers_to_read_monotonic_snapshots(
    resource_manager,
):
    seen: list[int] = []
    coordinator = resource_manager.tasks

    def observe_latest() -> None:
        seen.append(coordinator.snapshot().generation)

    coordinator.add_listener(observe_latest)
    handle = coordinator.submit(
        TaskSpec.create(TaskKind.SAVE, foreground=True),
        lambda context: (context.report("Writing", 1, 2), "done")[1],
    )

    assert handle.future.result(timeout=2) == "done"
    assert seen
    assert seen == sorted(seen)
    assert coordinator.snapshot().generation == seen[-1]


def test_background_pause_holds_index_but_not_foreground_save(resource_manager):
    background_started = Event()
    save_started = Event()
    resource_manager.pause_background(True)
    background = resource_manager.tasks.submit(
        TaskSpec.create(TaskKind.INDEX, foreground=False),
        lambda _context: background_started.set(),
    )
    save = resource_manager.tasks.submit(
        TaskSpec.create(TaskKind.SAVE, foreground=True),
        lambda _context: save_started.set(),
    )

    assert save_started.wait(1.0)
    assert not background_started.wait(0.05)
    assert resource_manager.tasks.snapshot().background_paused
    assert resource_manager.tasks.kind_is_paused(TaskKind.INDEX)
    assert not resource_manager.tasks.kind_is_paused(TaskKind.SAVE)

    resource_manager.pause_background(False)
    assert background_started.wait(1.0)
    save.future.result(timeout=1.0)
    background.future.result(timeout=1.0)


def test_paused_background_does_not_occupy_the_only_worker():
    manager = ResourceManager(
        max_workers=1,
        initial_snapshot=MemorySnapshot(16 << 30, 8 << 30),
    )
    background_started = Event()
    save_started = Event()
    try:
        manager.pause_background(True)
        background = manager.tasks.submit(
            TaskSpec.create(TaskKind.INDEX, foreground=False),
            lambda _context: background_started.set(),
        )
        assert not background_started.wait(0.05)
        save = manager.tasks.submit(
            TaskSpec.create(TaskKind.SAVE, foreground=True),
            lambda _context: save_started.set(),
        )

        assert save_started.wait(0.25)
        assert not background_started.is_set()
        save.future.result(timeout=1.0)
        manager.pause_background(False)
        assert background_started.wait(1.0)
        background.future.result(timeout=1.0)
    finally:
        manager.shutdown()


def test_foreground_session_publication_runs_while_background_is_paused(
    resource_manager,
):
    resource_manager.pause_background(True)
    background = resource_manager.tasks.submit(
        TaskSpec.create(TaskKind.SESSION, foreground=False),
        lambda _context: "background session",
    )
    foreground = resource_manager.tasks.submit(
        TaskSpec.create(TaskKind.SESSION, foreground=True),
        lambda _context: "final session",
    )

    assert foreground.future.result(timeout=1) == "final session"
    assert not background.done
    assert resource_manager.tasks.snapshot().background_paused


def test_resumed_session_future_cannot_cancel_an_active_write(resource_manager):
    started = Event()
    release = Event()
    resource_manager.pause_background(True)
    handle = resource_manager.tasks.submit(
        TaskSpec.create(TaskKind.SESSION, foreground=False),
        lambda _context: (started.set(), release.wait(5), "published")[-1],
    )
    resource_manager.pause_background(False)
    try:
        assert started.wait(1)
        assert not handle.future.cancel(), "an active write must not appear cancelled"
    finally:
        release.set()
    assert handle.future.result(timeout=1) == "published"


def test_cancelling_resumed_queued_session_prevents_its_write():
    resources = ResourceManager(max_workers=1)
    started = Event()
    release = Event()
    writes = []
    try:
        resources.tasks.submit(
            TaskSpec.create(TaskKind.SAVE, foreground=True),
            lambda _context: (started.set(), release.wait(5)),
        )
        assert started.wait(1)
        resources.pause_background(True)
        handle = resources.tasks.submit(
            TaskSpec.create(TaskKind.SESSION, foreground=False),
            lambda _context: writes.append("superseded"),
        )
        resources.pause_background(False)
        assert handle.future.cancel()
        release.set()
        # The only worker must finish the older equal-priority item first.
        final = resources.tasks.submit(
            TaskSpec.create(TaskKind.SESSION, foreground=True),
            lambda _context: writes.append("final"),
        )
        final.future.result(timeout=1)
        assert writes == ["final"]
    finally:
        release.set()
        resources.shutdown()


def test_estimated_work_above_available_resources_is_refused(resource_manager):
    invoked = False

    def work(_context):
        nonlocal invoked
        invoked = True

    spec = TaskSpec.create(
        TaskKind.REPLACE,
        foreground=True,
        estimated_memory_bytes=9 << 30,
    )

    with pytest.raises(TaskAdmissionError, match="memory"):
        resource_manager.tasks.submit(spec, work)
    assert not invoked


def test_cancelled_task_observes_one_shared_token(resource_manager):
    started = Event()
    handle = resource_manager.tasks.submit(
        TaskSpec.create(TaskKind.SEARCH, foreground=True),
        lambda context: (started.set(), context.token.wait(1), context.check_cancelled()),
    )
    assert started.wait(1.0)

    handle.cancel()

    with pytest.raises(RuntimeError, match="cancelled"):
        handle.future.result(timeout=1.0)
    assert handle.state is TaskState.CANCELLED


def test_regex_task_kinds_have_visible_priorities_and_ignore_index_pause(
    resource_manager,
):
    analysis_started = Event()
    resource_manager.pause_background(True)

    analysis = resource_manager.tasks.submit(
        TaskSpec.create(TaskKind.REGEX_ANALYSIS, foreground=False),
        lambda _context: analysis_started.set(),
    )

    assert TaskSpec.create(
        TaskKind.REGEX_ANALYSIS, foreground=False
    ).priority is WorkPriority.INTERACTIVE
    assert TaskSpec.create(
        TaskKind.CAPTURE_REPORT, foreground=False
    ).priority is WorkPriority.VISIBLE
    assert not resource_manager.tasks.kind_is_paused(TaskKind.REGEX_ANALYSIS)
    assert not resource_manager.tasks.kind_is_paused(TaskKind.CAPTURE_REPORT)
    assert analysis_started.wait(1)
    analysis.future.result(timeout=1)


def test_recovery_compaction_precedes_convenience_session_work():
    compaction = TaskSpec.create(
        TaskKind.RECOVERY_COMPACTION,
        foreground=False,
    )
    session = TaskSpec.create(TaskKind.SESSION, foreground=False)
    hashing = TaskSpec.create(TaskKind.HASH, foreground=False)

    assert compaction.priority < session.priority
    assert hashing.priority < session.priority


def test_only_convenience_session_work_pauses_with_background_tasks(
    resource_manager,
):
    resource_manager.pause_background(True)

    assert resource_manager.tasks.kind_is_paused(TaskKind.SESSION)
    assert not resource_manager.tasks.kind_is_paused(TaskKind.HASH)
    assert not resource_manager.tasks.kind_is_paused(TaskKind.RECOVERY_COMPACTION)


def test_latest_task_slot_runs_one_call_and_only_the_newest_pending(
    resource_manager,
):
    entered = threading.Event()
    release = threading.Event()
    ran: list[int] = []
    discarded: list[int] = []
    completed: list[int] = []
    slot = LatestTaskSlot(
        resource_manager.tasks,
        lambda generation, _handle: completed.append(generation),
    )

    def first(_context):
        ran.append(1)
        entered.set()
        release.wait(2)
        return 1

    slot.request(
        1,
        TaskSpec.create(TaskKind.REGEX_ANALYSIS, foreground=False),
        first,
    )
    assert entered.wait(1)
    slot.request(
        2,
        TaskSpec.create(TaskKind.REGEX_ANALYSIS, foreground=False),
        lambda _context: ran.append(2),
        discard=lambda: discarded.append(2),
    )
    slot.request(
        3,
        TaskSpec.create(TaskKind.REGEX_ANALYSIS, foreground=False),
        lambda _context: ran.append(3),
        discard=lambda: discarded.append(3),
    )
    release.set()
    deadline = time.monotonic() + 2
    while completed != [1, 3] and time.monotonic() < deadline:
        time.sleep(0.005)

    assert ran == [1, 3]
    assert discarded == [2]
    slot.close()


def test_closing_latest_task_slot_cancels_active_and_discards_pending(
    resource_manager,
):
    started = threading.Event()
    release = threading.Event()
    discarded: list[str] = []
    slot = LatestTaskSlot(resource_manager.tasks, lambda *_args: None)
    slot.request(
        1,
        TaskSpec.create(TaskKind.CAPTURE_REPORT, foreground=False),
        lambda _context: (started.set(), release.wait(2))[1],
    )
    assert started.wait(1)
    slot.request(
        2,
        TaskSpec.create(TaskKind.CAPTURE_REPORT, foreground=False),
        lambda _context: None,
        discard=lambda: discarded.append("pending snapshot closed"),
    )

    slot.close()
    release.set()

    assert discarded == ["pending snapshot closed"]


def test_latest_task_slot_discards_a_request_rejected_by_admission(
    resource_manager,
):
    discarded: list[int] = []
    completed: list[int] = []
    slot = LatestTaskSlot(
        resource_manager.tasks,
        lambda generation, _handle: completed.append(generation),
    )

    slot.request(
        1,
        TaskSpec.create(
            TaskKind.REGEX_ANALYSIS,
            foreground=False,
            estimated_memory_bytes=9 << 30,
        ),
        lambda _context: 1,
        discard=lambda: discarded.append(1),
    )

    assert discarded == [1]
    assert completed == []
    slot.close()


def test_latest_task_slot_discards_active_request_cancelled_before_start(
    resource_manager,
):
    blockers_started = [threading.Event(), threading.Event()]
    release = threading.Event()
    blockers = []
    for started in blockers_started:
        blockers.append(
            resource_manager.tasks.submit(
                TaskSpec.create(TaskKind.SEARCH, foreground=True),
                lambda _context, started=started: (
                    started.set(),
                    release.wait(2),
                ),
            )
        )
    assert all(started.wait(1) for started in blockers_started)

    discarded: list[str] = []
    ran = threading.Event()
    slot = LatestTaskSlot(resource_manager.tasks, lambda *_args: None)
    spec = TaskSpec.create(TaskKind.CAPTURE_REPORT, foreground=False)
    slot.request(
        1,
        spec,
        lambda _context: ran.set(),
        discard=lambda: discarded.append("queued snapshot closed"),
    )
    slot.cancel()
    deadline = time.monotonic() + 1
    while not discarded and time.monotonic() < deadline:
        time.sleep(0.001)
    while (
        any(
            task.spec.task_id == spec.task_id
            for task in resource_manager.tasks.snapshot().tasks
        )
        and time.monotonic() < deadline
    ):
        time.sleep(0.001)
    release.set()
    for blocker in blockers:
        blocker.future.result(timeout=2)

    assert not ran.is_set()
    assert discarded == ["queued snapshot closed"]
    assert all(
        task.spec.task_id != spec.task_id
        for task in resource_manager.tasks.snapshot().tasks
    )
    slot.close()


def test_cancelling_deferred_background_task_removes_it_from_coordinator(
    resource_manager,
):
    ran = threading.Event()
    resource_manager.pause_background(True)
    spec = TaskSpec.create(TaskKind.INDEX, foreground=False)
    handle = resource_manager.tasks.submit(
        spec,
        lambda _context: ran.set(),
    )

    handle.cancel()
    resource_manager.pause_background(False)

    assert handle.future.cancelled()
    assert not ran.is_set()
    assert all(
        task.spec.task_id != spec.task_id
        for task in resource_manager.tasks.snapshot().tasks
    )


def test_cancellation_after_future_starts_still_enters_coordinator_wrapper():
    class GapPool:
        def submit(self, _priority, fn, /, *args, token=None, **kwargs):
            future = Future()
            assert future.set_running_or_notify_cancel()
            self.pending = (future, fn, args, token, kwargs)
            return future

        def finish(self) -> None:
            future, fn, args, token, kwargs = self.pending
            try:
                if token is not None:
                    token.raise_if_cancelled()
                result = fn(*args, **kwargs)
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(result)

    pool = GapPool()
    coordinator = TaskCoordinator(
        pool,
        lambda: SimpleNamespace(
            available_memory=16 << 30,
            free_disk=8 << 30,
        ),
    )
    invoked = threading.Event()
    spec = TaskSpec.create(TaskKind.CAPTURE_REPORT, foreground=False)
    handle = coordinator.submit(spec, lambda _context: invoked.set())

    handle.cancel()
    pool.finish()

    with pytest.raises(RuntimeError, match="cancelled"):
        handle.future.result()
    assert handle.state is TaskState.CANCELLED
    assert not invoked.is_set()
    assert all(
        task.spec.task_id != spec.task_id for task in coordinator.snapshot().tasks
    )
