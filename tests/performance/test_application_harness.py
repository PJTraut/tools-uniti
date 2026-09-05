from __future__ import annotations

import json
import threading
import time
import weakref
from pathlib import Path

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from benchmarks.application_harness import ApplicationWorkloadHarness
from benchmarks.sustained_workloads import create_application_harness
from uniti.app.recovery_manager import RecoveryManager
from uniti.app.service import UNITIService
from uniti.app.session_store import SessionStore
from uniti.app.settings import SettingsStore
from uniti.resources import ResourceManager, TaskKind, TaskSpec


def _root(tmp_path: Path, name: str = "application") -> Path:
    root = (tmp_path / name).resolve()
    root.mkdir()
    return root


def test_harness_constructs_one_real_application_beneath_owned_root(
    tmp_path: Path,
):
    root = _root(tmp_path)

    with create_application_harness(root) as harness:
        assert isinstance(harness.application, QApplication)
        assert isinstance(harness.resources, ResourceManager)
        assert isinstance(harness.settings_store, SettingsStore)
        assert isinstance(harness.session_store, SessionStore)
        assert isinstance(harness.recovery_manager, RecoveryManager)
        assert isinstance(harness.service, UNITIService)
        assert harness.window.window_id in dict(harness.service.windows.items)
        assert all(path.is_relative_to(root) for path in harness.paths.owned_roots)
        assert harness.settings_store.path.is_relative_to(root)
        assert harness.session_store.root.is_relative_to(root)
        assert harness.recovery_manager.directory.is_relative_to(root)


def test_cycles_reuse_service_and_helpers_drive_public_application_apis(
    tmp_path: Path,
):
    root = _root(tmp_path)
    fixture = root / "fixtures" / "ordinary.txt"
    fixture.parent.mkdir()
    fixture.write_bytes(b"alpha needle omega\n")

    with ApplicationWorkloadHarness(root) as harness:
        identity = harness.service_identity
        warmup_view = harness.open_owned_fixture(fixture)
        assert warmup_view.document.read(0, warmup_view.document.total_chars()) == (
            "alpha needle omega\n"
        )
        assert harness.close_cycle()

        measured_view = harness.open_owned_fixture(fixture)
        assert harness.service_identity == identity
        assert measured_view.document is warmup_view.document

        handle = harness.resources.tasks.submit(
            TaskSpec.create(TaskKind.SEARCH, foreground=True),
            lambda _context: "finished",
        )
        assert harness.await_operation(handle) == "finished"
        harness.pump_until(lambda: handle.done)


def test_checkpoint_is_bounded_and_does_not_serialize_owned_paths(tmp_path: Path):
    root = _root(tmp_path)

    with ApplicationWorkloadHarness(root) as harness:
        checkpoint = harness.capture_checkpoint(
            1,
            result_stores=1,
            replacement_plans=2,
            snapshots=3,
        )

        payload = json.dumps(checkpoint.as_dict(), sort_keys=True)
        assert str(root) not in payload
        assert checkpoint.cycle == 1
        assert checkpoint.owned_counts["result_stores"] == 1
        assert checkpoint.owned_counts["replacement_plans"] == 2
        assert checkpoint.owned_counts["snapshots"] == 3


def test_checkpoint_requests_best_effort_heap_relief(tmp_path: Path, monkeypatch):
    root = _root(tmp_path)
    calls = []
    monkeypatch.setattr(
        "benchmarks.application_harness.release_unused_heap_pages",
        lambda: calls.append(True) or True,
    )

    with ApplicationWorkloadHarness(root) as harness:
        harness.capture_checkpoint(1)

    assert calls == [True]


def test_checkpoint_settles_deferred_view_deletion(tmp_path: Path):
    root = _root(tmp_path)
    fixture = root / "document.txt"
    fixture.write_bytes(b"owned\n")

    with ApplicationWorkloadHarness(root) as harness:
        view = harness.open_owned_fixture(fixture)
        view_reference = weakref.ref(view)
        assert harness.close_cycle()
        del view

        harness.capture_checkpoint(1)

        assert view_reference() is None


def test_checkpoint_releases_a_closed_service_window(tmp_path: Path):
    root = _root(tmp_path)

    with ApplicationWorkloadHarness(root) as harness:
        window = harness.service.new_window()
        window_reference = weakref.ref(window)
        window.close()
        harness.pump_until(lambda: harness.service.window_count == 1)
        del window

        harness.capture_checkpoint(1)

        assert window_reference() is None


def test_checkpoint_waits_for_work_scheduled_while_qt_events_settle(tmp_path: Path):
    root = _root(tmp_path)

    with ApplicationWorkloadHarness(root) as harness:
        started = threading.Event()
        release = threading.Event()

        def delayed(_context):
            started.set()
            release.wait()
            time.sleep(0.25)

        handle = harness.resources.tasks.submit(
            TaskSpec.create(TaskKind.SESSION, foreground=False),
            delayed,
        )
        assert started.wait(timeout=1)
        QTimer.singleShot(0, release.set)

        checkpoint = harness.capture_checkpoint(1)

        assert handle.done
        assert checkpoint.owned_counts["active_workers"] == 0
        assert checkpoint.owned_counts["active_tasks"] == 0


def test_pump_and_operation_waits_have_enforced_deadlines(tmp_path: Path):
    root = _root(tmp_path)

    with ApplicationWorkloadHarness(root, operation_timeout_seconds=0.01) as harness:
        with pytest.raises(TimeoutError, match="Qt condition"):
            harness.pump_until(lambda: False)

        class NeverFinished:
            done = False

        with pytest.raises(TimeoutError, match="operation"):
            harness.await_operation(NeverFinished())


def test_shutdown_releases_every_application_authority_and_can_restart(
    tmp_path: Path,
):
    first_root = _root(tmp_path, "first")
    fixture = first_root / "document.txt"
    fixture.write_bytes(b"owned\n")
    first = ApplicationWorkloadHarness(first_root)
    first.open_owned_fixture(fixture)
    first.shutdown()

    assert first.shutdown_steps == (
        "views",
        "stores",
        "recovery_bindings",
        "windows",
        "documents",
        "tasks",
        "service",
    )
    assert first.service.documents.count == 0
    assert first.service.windows.count == 0
    assert first.resources.tasks.snapshot().active_count == 0
    assert first.resources.tasks.snapshot().queued_count == 0
    assert first.recovery_manager.diagnostics() == ()
    assert not first.service.is_running

    second_root = _root(tmp_path, "second")
    second = ApplicationWorkloadHarness(second_root)
    try:
        assert second.service.is_running
        assert second.service is not first.service
        assert second.resources is not first.resources
        assert second.service.documents.count == 0
        assert second.service.windows.count == 1
        assert second.settings_store.path.is_relative_to(second_root)
        assert not second.settings_store.path.is_relative_to(first_root)
    finally:
        second.shutdown()
