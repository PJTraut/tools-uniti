"""UNITI CLI and desktop startup with all Qt imports kept lazy."""

from __future__ import annotations

import argparse
import importlib.metadata
import json
import os
import platform
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

import uniti

from .paths import AppPaths
from .startup import (
    ExitCode,
    StartupContext,
    StartupCoordinator,
    StartupFailure,
    StartupLog,
    StartupPhase,
)


@dataclass(frozen=True, slots=True)
class ApplicationRequest:
    files: tuple[Path, ...] = ()
    self_check: bool = False
    smoke: bool = False
    deep: bool = False
    json_output: bool = False
    version: bool = False


class ApplicationUsageError(ValueError):
    pass


def _argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="uniti", description="UNITI text editor")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--self-check", action="store_true", help="validate this UNITI runtime")
    group.add_argument(
        "--smoke",
        action="store_true",
        help="run core and self-closing GUI smoke checks",
    )
    group.add_argument("--version", action="store_true", help="print the UNITI version")
    parser.add_argument("--deep", action="store_true", help="run deep functional checks")
    parser.add_argument("--json", dest="json_output", action="store_true", help="emit JSON")
    parser.add_argument("files", nargs="*", type=Path)
    return parser


def parse_args(argv: list[str]) -> ApplicationRequest:
    arguments = list(argv)
    if arguments and (arguments[0] == "uniti" or arguments[0].endswith("/uniti")):
        arguments = arguments[1:]
    namespace = _argument_parser().parse_args(arguments)
    if namespace.deep and not namespace.self_check:
        raise ApplicationUsageError("--deep requires --self-check")
    if namespace.json_output and not namespace.self_check:
        raise ApplicationUsageError("--json requires --self-check")
    return ApplicationRequest(
        files=tuple(namespace.files),
        self_check=bool(namespace.self_check),
        smoke=bool(namespace.smoke),
        deep=bool(namespace.deep),
        json_output=bool(namespace.json_output),
        version=bool(namespace.version),
    )


def run_self_check(request: ApplicationRequest):
    from .self_check import SelfCheckRunner

    return SelfCheckRunner().run(deep=request.deep)


def run_smoke() -> dict[str, object]:
    from .smoke import run_combined_smoke

    return run_combined_smoke()


def _capability_payload(results: Mapping[str, object]) -> dict[str, object]:
    return {
        name: result.as_dict() if hasattr(result, "as_dict") else result
        for name, result in results.items()
    }


def _runtime_marker(marker_path: Path) -> dict[str, object]:
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise StartupFailure(
            StartupPhase.ENVIRONMENT_VALIDATION,
            ExitCode.ENVIRONMENT,
            "UNITI runtime ownership marker is missing or unreadable",
            error,
        ) from error
    if not isinstance(payload, dict):
        raise StartupFailure(
            StartupPhase.ENVIRONMENT_VALIDATION,
            ExitCode.ENVIRONMENT,
            "UNITI runtime ownership marker is invalid",
        )
    valid = (
        payload.get("schema") == 1
        and payload.get("owner") == "uniti-editor"
        and payload.get("healthy") is True
        and Path(str(payload.get("environment_path", ""))).resolve()
        == Path(sys.prefix).resolve()
    )
    if not valid:
        raise StartupFailure(
            StartupPhase.ENVIRONMENT_VALIDATION,
            ExitCode.ENVIRONMENT,
            "UNITI runtime ownership marker does not match this interpreter",
        )
    return payload


def _normal_dependencies() -> dict[str, str]:
    try:
        import PySide6
        import regex

        versions = {
            "uniti-editor": importlib.metadata.version("uniti-editor"),
            "regex": importlib.metadata.version("regex"),
            "PySide6": importlib.metadata.version("PySide6"),
        }
    except (ImportError, ModuleNotFoundError, importlib.metadata.PackageNotFoundError) as error:
        raise StartupFailure(
            StartupPhase.DEPENDENCY_VALIDATION,
            ExitCode.DEPENDENCIES,
            "UNITI runtime dependencies are missing; explicit repair is required",
            error,
        ) from error
    if versions["regex"] != "2026.5.9":
        raise StartupFailure(
            StartupPhase.DEPENDENCY_VALIDATION,
            ExitCode.DEPENDENCIES,
            "UNITI regex dependency version does not match the release",
        )
    if versions["uniti-editor"] != uniti.__version__:
        raise StartupFailure(
            StartupPhase.DEPENDENCY_VALIDATION,
            ExitCode.DEPENDENCIES,
            "installed UNITI metadata does not match the running release",
        )
    try:
        pyside_parts = tuple(int(part) for part in versions["PySide6"].split(".")[:2])
    except ValueError as error:
        raise StartupFailure(
            StartupPhase.DEPENDENCY_VALIDATION,
            ExitCode.DEPENDENCIES,
            "UNITI PySide6 version is invalid",
            error,
        ) from error
    if pyside_parts < (6, 8):
        raise StartupFailure(
            StartupPhase.DEPENDENCY_VALIDATION,
            ExitCode.DEPENDENCIES,
            "UNITI requires PySide6 6.8 or newer",
        )
    return versions


def _startup_callbacks(
    request: ApplicationRequest,
    marker_path: Path,
) -> dict[StartupPhase, object]:
    from uniti.resources import ResourceManager, probe_memory

    from .capabilities import CapabilityStatus, probe_filesystem, probe_qt, probe_runtime
    from .cleanup import cleanup_stale, create_session_record
    from .recovery_manager import RecoveryManager
    from .settings import SettingsStore, UnsupportedSettingsSchema

    def runtime(context: StartupContext) -> None:
        if sys.version_info < (3, 12):
            raise StartupFailure(
                StartupPhase.RUNTIME_IDENTITY,
                ExitCode.RUNTIME,
                "UNITI requires Python 3.12 or newer",
            )
        results = probe_runtime(context.paths, marker_path=marker_path)
        context.identity = {
            "python": platform.python_version(),
            "executable": str(Path(sys.executable).resolve()),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
        }
        context.capabilities["runtime"] = _capability_payload(results)

    def environment(context: StartupContext) -> None:
        marker = _runtime_marker(marker_path)
        context.data["runtime_marker"] = marker
        context.state["install"] = {
            "mode": marker.get("mode"),
            "source_root": marker.get("source_root"),
            "environment_path": marker.get("environment_path"),
            "environment_id": marker.get("environment_id"),
        }

    def dependencies(context: StartupContext) -> None:
        versions = _normal_dependencies()
        marker = context.data["runtime_marker"]
        context.state["dependencies"] = {
            "ok": True,
            "fingerprint": marker.get("dependency_fingerprint"),
            "versions": versions,
        }

    def application_paths(context: StartupContext) -> None:
        try:
            context.paths.ensure()
            results = probe_filesystem(context.paths)
        except OSError as error:
            raise StartupFailure(
                StartupPhase.APPLICATION_PATHS,
                ExitCode.STATE,
                "UNITI application paths are unavailable",
                error,
            ) from error
        required = ("write", "fsync", "atomic_replace")
        if any(results[name].status is not CapabilityStatus.AVAILABLE for name in required):
            raise StartupFailure(
                StartupPhase.APPLICATION_PATHS,
                ExitCode.STATE,
                "UNITI application paths do not support required writes",
            )
        context.capabilities["filesystem"] = _capability_payload(results)

    def schemas(context: StartupContext) -> None:
        store = SettingsStore(context.paths.settings_file)
        try:
            preparation = store.prepare()
        except (OSError, UnsupportedSettingsSchema) as error:
            raise StartupFailure(
                StartupPhase.SCHEMA_MIGRATIONS,
                ExitCode.STATE,
                "UNITI settings schema cannot be prepared safely",
                error,
            ) from error
        context.data["settings_store"] = store
        context.data["settings_preparation"] = preparation

    def settings(context: StartupContext) -> None:
        store = context.data["settings_store"]
        context.settings = store.load()

    def resources(context: StartupContext) -> None:
        snapshot = probe_memory()
        manager = ResourceManager(initial_snapshot=snapshot)
        context.data["resource_manager"] = manager
        context.register_cleanup(lambda: manager.shutdown(wait=True))
        context.resources = {
            "physical": snapshot.physical,
            "available": snapshot.available,
            "cache_budget": manager.cache_budget_bytes,
            "worker_count": manager.worker_count,
            "pressure": manager.pressure.value,
        }

    def stale_cleanup(context: StartupContext) -> None:
        report = cleanup_stale(context.paths, active_session_ids=(context.session_id,))
        record = create_session_record(
            context.paths,
            session_id=context.session_id,
            pid=os.getpid(),
            build_identity=uniti.__display_version__,
        )
        context.data["cleanup_report"] = report
        context.data["session_record"] = record

    def recovery(context: StartupContext) -> None:
        manager = RecoveryManager(context.paths.recovery_dir)
        context.data["recovery_manager"] = manager
        context.register_cleanup(manager.shutdown)
        context.recovery_candidates = manager.discover()

    def gui(context: StartupContext) -> None:
        try:
            from PySide6.QtWidgets import QApplication
        except (ImportError, ModuleNotFoundError) as error:
            raise StartupFailure(
                StartupPhase.GUI_CAPABILITIES,
                ExitCode.GUI,
                "UNITI desktop UI requires PySide6",
                error,
            ) from error
        app = QApplication.instance() or QApplication(["uniti"])
        results = probe_qt(app)
        if results["qt"].status is not CapabilityStatus.AVAILABLE:
            raise StartupFailure(
                StartupPhase.GUI_CAPABILITIES,
                ExitCode.GUI,
                "UNITI could not initialize the Qt platform",
            )
        context.data["qapplication"] = app
        context.capabilities["qt"] = _capability_payload(results)

    def session(context: StartupContext) -> None:
        from PySide6.QtWidgets import QMessageBox
        from uniti.app.service import UNITIService
        from uniti.app.session_store import SessionStore

        session_store = SessionStore(context.paths.durable_session_dir)
        loaded_session = session_store.load_latest()
        service = UNITIService(
            resource_manager=context.data["resource_manager"],
            settings_store=context.data["settings_store"],
            session_store=session_store,
            recovery_manager=context.data["recovery_manager"],
        )
        window = service.new_window()
        window.set_startup_snapshot(context.snapshot())
        service.run_recovery_center(
            window,
            recovery_candidates=context.recovery_candidates,
            session_problems=loaded_session.problems,
        )
        for path in request.files:
            try:
                window.open_path(path)
            except Exception as error:
                QMessageBox.critical(window, "Open Failed", f"{path}\n\n{error}")
        context.data["service"] = service
        context.data["window"] = window

    def ready(context: StartupContext) -> None:
        context.state["uniti"] = {
            "display_version": uniti.__display_version__,
            "package_version": uniti.__version__,
            "build_identity": uniti.__display_version__,
        }

    return {
        StartupPhase.RUNTIME_IDENTITY: runtime,
        StartupPhase.ENVIRONMENT_VALIDATION: environment,
        StartupPhase.DEPENDENCY_VALIDATION: dependencies,
        StartupPhase.APPLICATION_PATHS: application_paths,
        StartupPhase.SCHEMA_MIGRATIONS: schemas,
        StartupPhase.SETTINGS_LOAD: settings,
        StartupPhase.RESOURCE_CALIBRATION: resources,
        StartupPhase.STALE_STATE_CLEANUP: stale_cleanup,
        StartupPhase.RECOVERY_DISCOVERY: recovery,
        StartupPhase.GUI_CAPABILITIES: gui,
        StartupPhase.SESSION_RESTORE: session,
        StartupPhase.READY: ready,
    }


def run_desktop(
    request: ApplicationRequest,
    *,
    paths: AppPaths | None = None,
    marker_path: Path | None = None,
) -> int:
    from .setup_state import SetupStateStore, UnsupportedSetupSchema

    selected_paths = paths or AppPaths.current()
    selected_marker = marker_path or (Path(sys.prefix) / ".uniti-runtime.json")
    context = StartupContext.create(selected_paths, session_id=uuid.uuid4().hex)
    coordinator = StartupCoordinator(
        SetupStateStore(selected_paths.setup_state_file),
        StartupLog(selected_paths.startup_log_file),
    )
    try:
        coordinator.run(context, _startup_callbacks(request, selected_marker))
    except StartupFailure as failure:
        print(
            f"UNITI startup failed in {failure.phase.name}: {failure.safe_message}\n"
            "Repair with: python scripts/bootstrap.py --repair",
            file=sys.stderr,
        )
        return int(failure.exit_code)
    except (OSError, UnsupportedSetupSchema) as error:
        print(
            f"UNITI startup state failed: {error}\n"
            "Repair with: python scripts/bootstrap.py --repair",
            file=sys.stderr,
        )
        return int(ExitCode.STATE)

    app = context.data["qapplication"]
    window = context.data["window"]
    window.set_startup_snapshot(context.diagnostics)
    window.show()
    try:
        return int(app.exec())
    finally:
        context.cleanup()


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv if argv is None else argv)
    try:
        request = parse_args(arguments)
    except ApplicationUsageError as error:
        print(f"uniti: error: {error}", file=sys.stderr)
        return int(ExitCode.USAGE)
    except SystemExit as exit_request:
        return int(exit_request.code or 0)

    if request.version:
        print(uniti.__display_version__)
        return int(ExitCode.SUCCESS)
    if request.self_check:
        from .self_check import render_human, render_json

        report = run_self_check(request)
        output = render_json(report) if request.json_output else render_human(report)
        print(output, end="")
        return int(report.exit_code)
    if request.smoke:
        result = run_smoke()
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        if result.get("ok") is True:
            return int(ExitCode.SUCCESS)
        if result.get("gui_ok") is not True:
            return int(ExitCode.GUI)
        return int(ExitCode.FUNCTIONAL)
    return run_desktop(request)
