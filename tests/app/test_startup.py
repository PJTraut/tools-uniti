import json
from pathlib import Path

import pytest

from uniti.app import application
from uniti.app.dogfood import DogfoodRecorder
from uniti.app.dogfood_store import DogfoodStore
from uniti.app.paths import AppPaths
from uniti.app.session import LoadedSession
from uniti.app.setup_state import SetupStateStore
from uniti.app.startup import (
    ExitCode,
    StartupContext,
    StartupCoordinator,
    StartupFailure,
    StartupLog,
    StartupPhase,
    StartupCompletion,
)
from uniti.resources import ResourceManager


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )


def _coordinator(paths: AppPaths) -> StartupCoordinator:
    return StartupCoordinator(
        SetupStateStore(paths.setup_state_file), StartupLog(paths.startup_log_file)
    )


def _callbacks(observed: list[StartupPhase]):
    return {
        phase: lambda context, phase=phase: observed.append(phase)
        for phase in StartupPhase
        if phase is not StartupPhase.BOOT
    }


def test_coordinator_runs_exact_order_and_persists_ready(tmp_path: Path):
    paths = _paths(tmp_path)
    observed: list[StartupPhase] = []
    context = StartupContext.create(paths, session_id="session-1")

    result = _coordinator(paths).run(context, _callbacks(observed))

    assert observed == [
        StartupPhase.RUNTIME_IDENTITY,
        StartupPhase.ENVIRONMENT_VALIDATION,
        StartupPhase.DEPENDENCY_VALIDATION,
        StartupPhase.APPLICATION_PATHS,
        StartupPhase.GUI_CAPABILITIES,
        StartupPhase.INSTANCE_ARBITRATION,
        StartupPhase.SCHEMA_MIGRATIONS,
        StartupPhase.SETTINGS_LOAD,
        StartupPhase.RESOURCE_CALIBRATION,
        StartupPhase.STALE_STATE_CLEANUP,
        StartupPhase.RECOVERY_DISCOVERY,
        StartupPhase.SESSION_RESTORE,
        StartupPhase.READY,
    ]
    assert result.phase is StartupPhase.READY
    state = SetupStateStore(paths.setup_state_file).prepare()
    assert state["startup"]["ok"] is True
    assert state["startup"]["stage"] == "READY"
    assert state["session_id"] == "session-1"
    records = [json.loads(line) for line in paths.startup_log_file.read_text().splitlines()]
    assert records[0]["phase"] == "BOOT"
    assert records[-1]["phase"] == "READY"


def test_intentional_secondary_completion_stops_without_failure_or_late_writers(
    tmp_path: Path,
):
    paths = _paths(tmp_path)
    observed: list[StartupPhase] = []
    callbacks = _callbacks(observed)

    def forwarded(_context):
        observed.append(StartupPhase.INSTANCE_ARBITRATION)
        return StartupCompletion(7)

    callbacks[StartupPhase.INSTANCE_ARBITRATION] = forwarded
    context = StartupContext.create(paths, session_id="secondary")

    result = _coordinator(paths).run(context, callbacks)

    assert observed == [
        StartupPhase.RUNTIME_IDENTITY,
        StartupPhase.ENVIRONMENT_VALIDATION,
        StartupPhase.DEPENDENCY_VALIDATION,
        StartupPhase.APPLICATION_PATHS,
        StartupPhase.GUI_CAPABILITIES,
        StartupPhase.INSTANCE_ARBITRATION,
    ]
    assert result.phase is StartupPhase.INSTANCE_ARBITRATION
    assert result.data["completion_exit_code"] == 7
    state = SetupStateStore(paths.setup_state_file).prepare()
    assert state["startup"]["ok"] is True
    records = [json.loads(line) for line in paths.startup_log_file.read_text().splitlines()]
    assert records[-1]["phase"] == "INSTANCE_ARBITRATION"
    assert records[-1]["status"] == "pass"


def test_primary_session_startup_constructs_one_process_dogfood_runtime(
    tmp_path: Path,
    monkeypatch,
):
    from uniti.app.service import UNITIService

    paths = _paths(tmp_path)
    paths.ensure()
    resources = ResourceManager(max_workers=1)
    context = StartupContext.create(paths, session_id="primary")
    context.data.update(
        resource_manager=resources,
        settings_store=object(),
        recovery_manager=object(),
        session_store=object(),
        loaded_session=LoadedSession(None, (), None, ()),
    )

    class Window:
        def set_startup_snapshot(self, _snapshot):
            return None

    window = Window()
    monkeypatch.setattr(UNITIService, "new_window", lambda self: window)
    monkeypatch.setattr(
        UNITIService,
        "run_recovery_center",
        lambda self, parent, **kwargs: 0,
    )
    callbacks = application._startup_callbacks(
        application.ApplicationRequest(),
        tmp_path / "runtime.json",
    )

    try:
        callbacks[StartupPhase.SESSION_RESTORE](context)

        service = context.data["service"]
        assert isinstance(context.data["dogfood_recorder"], DogfoodRecorder)
        assert isinstance(context.data["dogfood_store"], DogfoodStore)
        assert service.dogfood_recorder is context.data["dogfood_recorder"]
        assert service.dogfood_store is context.data["dogfood_store"]
        assert service.dogfood_store.root == paths.dogfood_dir.resolve()
    finally:
        service = context.data.get("service")
        if service is not None:
            service.shutdown_dogfood()
        resources.shutdown()


def test_forwarded_startup_never_constructs_a_dogfood_runtime(
    tmp_path: Path,
    monkeypatch,
):
    from uniti.app import instance_service
    from uniti.app.instance_protocol import InstanceReply
    from uniti.app.instance_service import InstanceRole, InstanceStart

    class ForwardedInstance:
        def __init__(self, _lock_path, _endpoint_name):
            return None

        def start(self, _request):
            return InstanceStart(
                InstanceRole.FORWARDED,
                InstanceReply(True, (), None),
            )

        def close(self):
            return None

    monkeypatch.setattr(instance_service, "InstanceService", ForwardedInstance)
    paths = _paths(tmp_path)
    paths.ensure()
    context = StartupContext.create(paths, session_id="secondary")
    callbacks = application._startup_callbacks(
        application.ApplicationRequest(),
        tmp_path / "runtime.json",
    )

    completion = callbacks[StartupPhase.INSTANCE_ARBITRATION](context)

    assert completion == StartupCompletion(ExitCode.SUCCESS)
    assert "dogfood_recorder" not in context.data
    assert "dogfood_store" not in context.data
    context.cleanup()


def test_context_rejects_illegal_phase_transition(tmp_path: Path):
    context = StartupContext.create(_paths(tmp_path), session_id="session-1")

    with pytest.raises(ValueError, match="phase transition"):
        context.advance(StartupPhase.GUI_CAPABILITIES)


def test_unexpected_failure_persists_safe_message_and_cleans_in_reverse(tmp_path: Path):
    paths = _paths(tmp_path)
    context = StartupContext.create(paths, session_id="session-1")
    stopped: list[str] = []
    context.register_cleanup(lambda: stopped.append("first"))
    context.register_cleanup(lambda: stopped.append("second"))
    callbacks = _callbacks([])
    callbacks[StartupPhase.RUNTIME_IDENTITY] = lambda _: 1 / 0

    with pytest.raises(StartupFailure) as caught:
        _coordinator(paths).run(context, callbacks)

    assert caught.value.phase is StartupPhase.RUNTIME_IDENTITY
    assert caught.value.exit_code is ExitCode.INTERNAL
    assert caught.value.safe_message == "unexpected internal startup failure"
    assert stopped == ["second", "first"]
    state = SetupStateStore(paths.setup_state_file).prepare()
    assert state["startup"]["failure_message"] == "unexpected internal startup failure"
    assert "ZeroDivisionError" not in json.dumps(state)
    assert "ZeroDivisionError" in paths.startup_log_file.read_text(encoding="utf-8")


def test_expected_failure_retains_specific_exit_code(tmp_path: Path):
    paths = _paths(tmp_path)
    context = StartupContext.create(paths, session_id="session-1")
    callbacks = _callbacks([])

    def fail(_):
        raise StartupFailure(
            StartupPhase.ENVIRONMENT_VALIDATION,
            ExitCode.ENVIRONMENT,
            "runtime marker mismatch",
        )

    callbacks[StartupPhase.ENVIRONMENT_VALIDATION] = fail

    with pytest.raises(StartupFailure) as caught:
        _coordinator(paths).run(context, callbacks)

    assert caught.value.exit_code is ExitCode.ENVIRONMENT
    assert caught.value.safe_message == "runtime marker mismatch"


def test_startup_log_rotates_before_limit_and_keeps_bounded_history(tmp_path: Path):
    path = tmp_path / "logs" / "startup.jsonl"
    log = StartupLog(path, max_bytes=90, max_rotated=2)

    for index in range(12):
        log.append({"phase": "BOOT", "index": index, "message": "x" * 30})

    assert path.stat().st_size <= 90
    assert (path.parent / "startup.jsonl.1").is_file()
    assert (path.parent / "startup.jsonl.2").is_file()
    assert not (path.parent / "startup.jsonl.3").exists()
