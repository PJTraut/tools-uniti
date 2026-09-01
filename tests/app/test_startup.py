import json
from pathlib import Path

import pytest

from uniti.app.paths import AppPaths
from uniti.app.setup_state import SetupStateStore
from uniti.app.startup import (
    ExitCode,
    StartupContext,
    StartupCoordinator,
    StartupFailure,
    StartupLog,
    StartupPhase,
)


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

    assert observed == list(StartupPhase)[1:]
    assert result.phase is StartupPhase.READY
    state = SetupStateStore(paths.setup_state_file).prepare()
    assert state["startup"]["ok"] is True
    assert state["startup"]["stage"] == "READY"
    assert state["session_id"] == "session-1"
    records = [json.loads(line) for line in paths.startup_log_file.read_text().splitlines()]
    assert records[0]["phase"] == "BOOT"
    assert records[-1]["phase"] == "READY"


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
