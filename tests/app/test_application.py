import sys
from types import SimpleNamespace
from pathlib import Path

import pytest
import uniti

from uniti.app import application
from uniti.app.platform_policy import UnsupportedPlatformError
from uniti.app.paths import AppPaths
from uniti.app.self_check import CheckResult, SelfCheckReport
from uniti.app.startup import (
    ExitCode,
    StartupCompletion,
    StartupContext,
    StartupFailure,
    StartupPhase,
)


def test_version_does_not_require_qt(monkeypatch, capsys):
    monkeypatch.setitem(sys.modules, "PySide6", None)

    assert application.main(["uniti", "--version"]) == 0

    assert capsys.readouterr().out.strip() == uniti.__display_version__


def test_deep_and_json_require_self_check(capsys):
    assert application.main(["uniti", "--deep"]) == 2
    assert "--deep requires --self-check" in capsys.readouterr().err
    assert application.main(["uniti", "--json"]) == 2
    assert "--json requires --self-check" in capsys.readouterr().err


def test_self_check_json_path_returns_report_exit_without_qt(monkeypatch, capsys):
    report = SelfCheckReport.from_results(
        "fast",
        {},
        (CheckResult.failed("runtime", ExitCode.ENVIRONMENT, "marker missing"),),
    )
    monkeypatch.setattr(application, "run_self_check", lambda request: report)
    monkeypatch.setitem(sys.modules, "PySide6", None)

    assert application.main(["uniti", "--self-check", "--json"]) == 11

    assert '"exit_code": 11' in capsys.readouterr().out


def test_smoke_cli_dispatches_combined_smoke_and_returns_its_status(
    monkeypatch, capsys
):
    monkeypatch.setattr(
        application,
        "run_smoke",
        lambda: {"ok": True, "core_ok": True, "gui_ok": True},
        raising=False,
    )

    assert application.main(["uniti", "--smoke"]) == 0

    output = capsys.readouterr().out
    assert '"core_ok": true' in output
    assert '"gui_ok": true' in output


def test_normal_startup_without_owned_marker_returns_actionable_environment_code(
    tmp_path: Path, capsys
):
    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    request = application.ApplicationRequest(files=())

    code = application.run_desktop(
        request,
        paths=paths,
        marker_path=tmp_path / "missing-runtime-marker.json",
    )

    assert code == ExitCode.ENVIRONMENT
    assert "scripts/bootstrap.py --repair" in capsys.readouterr().err


def test_unsupported_desktop_platform_fails_at_application_paths_without_traceback(
    monkeypatch,
    capsys,
):
    def unsupported(cls):
        raise UnsupportedPlatformError("freebsd14")

    monkeypatch.setattr(AppPaths, "current", classmethod(unsupported))

    assert application.run_desktop(application.ApplicationRequest()) == ExitCode.STATE

    error = capsys.readouterr().err
    assert "APPLICATION_PATHS" in error
    assert "Unsupported UNITI platform: freebsd14" in error
    assert "Traceback" not in error


def test_unsupported_self_check_platform_returns_state_exit_without_traceback(
    monkeypatch,
    capsys,
):
    def unsupported(cls):
        raise UnsupportedPlatformError("freebsd14")

    monkeypatch.setattr(AppPaths, "current", classmethod(unsupported))

    assert application.main(["uniti", "--self-check"]) == ExitCode.STATE

    error = capsys.readouterr().err
    assert error.strip() == "UNITI cannot run: Unsupported UNITI platform: freebsd14"
    assert "Traceback" not in error


def test_normal_dependency_validation_rejects_installed_metadata_mismatch(monkeypatch):
    monkeypatch.setattr(uniti, "__version__", "9.9")

    with pytest.raises(StartupFailure) as caught:
        application._normal_dependencies()

    assert caught.value.exit_code is ExitCode.DEPENDENCIES


def test_session_startup_uses_one_recovery_center_before_requested_files(
    tmp_path: Path,
    monkeypatch,
):
    from uniti.app.service import UNITIService
    from uniti.app.session import LoadedSession

    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    paths.ensure()
    requested = tmp_path / "requested.txt"
    requested.write_text("requested", encoding="utf-8")
    candidate = object()
    context = StartupContext.create(paths, session_id="startup-session")
    context.recovery_candidates = (candidate,)
    context.data.update(
        resource_manager=object(),
        settings_store=object(),
        recovery_manager=object(),
        session_store=object(),
        loaded_session=LoadedSession(None, (), None, ()),
    )
    events: list[object] = []

    class StartupWindow:
        def set_startup_snapshot(self, snapshot):
            events.append("snapshot")

        def open_path(self, path):
            events.append(("open", Path(path)))

    window = StartupWindow()
    monkeypatch.setattr(UNITIService, "new_window", lambda self: window)

    def run_center(
        self,
        parent,
        *,
        recovery_candidates=(),
        session_problems=(),
    ):
        events.append(
            ("recovery-center", parent, recovery_candidates, session_problems)
        )
        return 0

    monkeypatch.setattr(UNITIService, "run_recovery_center", run_center)
    callbacks = application._startup_callbacks(
        application.ApplicationRequest(files=(requested,)),
        tmp_path / "runtime.json",
    )

    callbacks[StartupPhase.SESSION_RESTORE](context)

    assert events[0] == "snapshot"
    assert events[1][0] == "recovery-center"
    assert events[1][1] is window
    assert events[1][2] == (candidate,)
    assert events[2] == ("open", requested)


def test_session_surface_never_repairs_a_scanned_pointer_during_discovery(
    tmp_path: Path,
):
    from uniti.app.session import LoadedSession, SessionLoadSource

    manifest = SimpleNamespace(
        find_replace=SimpleNamespace(history_pack=None),
        notices=(),
    )
    loaded = LoadedSession(
        manifest,
        (),
        None,
        (),
        source=SessionLoadSource.GENERATION_SCAN,
        inspected_generations=1,
        pointer_repair_required=True,
    )
    repair_calls = []

    class Store:
        root = tmp_path
        packs_dir = tmp_path / "packs"

        def load_manifest(self):
            return loaded

        def discover_restore_problems(self, _manifest):
            return ()

        def repair_pointer(self, selected):
            repair_calls.append(selected)

    surfaced = application._load_session_surface(Store())

    assert surfaced.pointer_repair_required is True
    assert repair_calls == []


def test_startup_passes_scan_repair_authority_to_post_restore_controller(
    tmp_path: Path,
    monkeypatch,
):
    from uniti.app.service import UNITIService
    from uniti.app.session import LoadedSession, SessionLoadSource

    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    paths.ensure()
    manifest = object()
    loaded = LoadedSession(
        manifest,
        (),
        None,
        (),
        source=SessionLoadSource.GENERATION_SCAN,
        inspected_generations=1,
        pointer_repair_required=True,
    )
    context = StartupContext.create(paths, session_id="startup-session")
    context.data.update(
        resource_manager=object(),
        settings_store=object(),
        recovery_manager=object(),
        session_store=object(),
        loaded_session=loaded,
    )
    events: list[object] = []

    class StartupWindow:
        def set_startup_snapshot(self, _snapshot):
            events.append("snapshot")

    window = StartupWindow()

    def restore_shell(self, selected, **kwargs):
        events.append(("restore-shell", selected, kwargs))

    monkeypatch.setattr(UNITIService, "restore_shell", restore_shell)
    monkeypatch.setattr(
        UNITIService,
        "restore_active",
        lambda self: events.append("restore-active"),
    )
    monkeypatch.setattr(
        UNITIService,
        "schedule_lazy_restore",
        lambda self: events.append("lazy-restore"),
    )
    monkeypatch.setattr(
        UNITIService,
        "most_recent_window",
        property(lambda self: window),
    )
    monkeypatch.setattr(
        UNITIService,
        "run_recovery_center",
        lambda self, parent, **kwargs: events.append("recovery-center"),
    )
    callbacks = application._startup_callbacks(
        application.ApplicationRequest(),
        tmp_path / "runtime.json",
    )

    callbacks[StartupPhase.SESSION_RESTORE](context)

    shell_event = events[0]
    assert shell_event[0] == "restore-shell"
    assert shell_event[1] is manifest
    assert shell_event[2]["pointer_repair_required"] is True
    assert events[1:4] == ["restore-active", "snapshot", "recovery-center"]
    assert events[4] == "lazy-restore"


def test_startup_callbacks_cover_gui_then_instance_before_every_state_writer(
    tmp_path: Path,
):
    callbacks = application._startup_callbacks(
        application.ApplicationRequest(),
        tmp_path / "runtime.json",
    )

    assert tuple(callbacks) == tuple(StartupPhase)[1:]
    phases = tuple(callbacks)
    assert phases.index(StartupPhase.GUI_CAPABILITIES) < phases.index(
        StartupPhase.INSTANCE_ARBITRATION
    )
    assert phases.index(StartupPhase.INSTANCE_ARBITRATION) < phases.index(
        StartupPhase.SCHEMA_MIGRATIONS
    )


def test_secondary_instance_callback_returns_success_before_constructing_writers(
    tmp_path: Path,
    monkeypatch,
):
    from uniti.app import instance_service
    from uniti.app.instance_protocol import InstanceReply
    from uniti.app.instance_service import InstanceRole, InstanceStart

    events: list[object] = []

    class ForwardedInstance:
        def __init__(self, lock_path, endpoint_name):
            events.append(("construct", lock_path, endpoint_name))

        def start(self, request):
            events.append(("start", request))
            return InstanceStart(
                InstanceRole.FORWARDED,
                InstanceReply(True, (), None),
            )

        def close(self):
            events.append("close")

    monkeypatch.setattr(instance_service, "InstanceService", ForwardedInstance)
    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    paths.ensure()
    context = StartupContext.create(paths, session_id="secondary")
    callbacks = application._startup_callbacks(
        application.ApplicationRequest(),
        tmp_path / "runtime.json",
    )

    completion = callbacks[StartupPhase.INSTANCE_ARBITRATION](context)

    assert completion == StartupCompletion(ExitCode.SUCCESS)
    assert "settings_store" not in context.data
    assert "session_store" not in context.data
    assert "recovery_manager" not in context.data
    assert events[0][0] == "construct"
    assert events[1][0] == "start"
    context.cleanup()
    assert events[-1] == "close"


def test_primary_instance_request_opens_in_recent_window_and_replies_in_order(
    tmp_path: Path,
):
    from uniti.app.instance_protocol import InstanceRequest

    first = str((tmp_path / "first.txt").resolve())
    second = str((tmp_path / "second.txt").resolve())
    calls: list[object] = []

    class Window:
        def open_path(self, path):
            calls.append(("open", Path(path)))
            if Path(path).name == "second.txt":
                raise OSError("private failure")
            return object()

        def show(self):
            calls.append("show")

        def raise_(self):
            calls.append("raise")

        def activateWindow(self):
            calls.append("activate")

    window = Window()
    service = type(
        "Service",
        (),
        {"most_recent_window": window, "new_window": lambda self: window},
    )()

    class Instance:
        def reply(self, connection, reply):
            calls.append(("reply", connection, reply))

    context = StartupContext.create(
        AppPaths(
            tmp_path / "config",
            tmp_path / "data",
            tmp_path / "state",
            tmp_path / "cache",
        ),
        session_id="primary",
    )
    context.data.update(service=service, instance_service=Instance())

    application._handle_instance_request(
        context,
        "connection",
        InstanceRequest(1, True, (first, second)),
    )

    reply = calls[-1][2]
    assert reply.accepted is True
    assert tuple(outcome.path for outcome in reply.outcomes) == (first, second)
    assert reply.outcomes[0].opened is True
    assert reply.outcomes[1].opened is False
    assert reply.outcomes[1].error == "Could not open the requested file."
    assert "private failure" not in repr(reply)
    assert calls[-4:-1] == ["show", "raise", "activate"]
