from __future__ import annotations

from threading import Event

import pytest

from uniti.resources import MemorySnapshot, ResourceManager
from uniti.resources.tasks import (
    TaskAdmissionError,
    TaskKind,
    TaskSpec,
    TaskState,
)


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
