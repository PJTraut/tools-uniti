"""Command-line surface for explicit UNITI bootstrap."""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import uniti
from uniti.app.atomic_json import utc_timestamp
from uniti.app.paths import AppPaths
from uniti.app.platform_policy import UnsupportedPlatformError
from uniti.app.setup_state import SetupStateStore

from .dependencies import DependencyManager
from .discovery import environment_path, query_python, validate_source_root
from .environment import EnvironmentManager
from .model import (
    BootstrapError,
    BootstrapMode,
    BootstrapRequest,
    BootstrapResult,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create or repair a UNITI-owned runtime")
    parser.add_argument("--local", action="store_true", help="use the application-local runtime")
    parser.add_argument("--dev", action="store_true", help="install development dependencies")
    parser.add_argument("--repair", action="store_true", help="reinstall and revalidate dependencies")
    parser.add_argument("--no-launch", action="store_true", help="prepare without launching UNITI")
    parser.add_argument("--self-check", action="store_true", help="launch UNITI self-check")
    parser.add_argument("--deep", action="store_true", help="include deep functional checks")
    parser.add_argument("--json", dest="json_output", action="store_true", help="emit self-check JSON")
    return parser


def source_root() -> Path:
    return Path(__file__).resolve().parents[3]


def parse_args(argv: Sequence[str]) -> BootstrapRequest:
    parser = build_parser()
    arguments = list(argv)
    try:
        separator = arguments.index("--")
    except ValueError:
        bootstrap_arguments = arguments
        forwarded_tail: list[str] = []
    else:
        bootstrap_arguments = arguments[:separator]
        forwarded_tail = arguments[separator + 1 :]
    namespace, forwarded = parser.parse_known_args(bootstrap_arguments)
    forwarded.extend(forwarded_tail)
    self_check = bool(namespace.self_check or namespace.deep)
    if namespace.json_output and not self_check:
        parser.error("--json requires --self-check")
    root = source_root().resolve()
    try:
        app_paths = AppPaths.current()
    except UnsupportedPlatformError as error:
        raise BootstrapError(str(error), 10) from error
    return BootstrapRequest(
        mode=BootstrapMode.LOCAL if namespace.local else BootstrapMode.SOURCE,
        source_root=root,
        app_paths=app_paths,
        dev=bool(namespace.dev),
        repair=bool(namespace.repair),
        no_launch=bool(namespace.no_launch),
        self_check=self_check,
        deep=bool(namespace.deep),
        json_output=bool(namespace.json_output),
        forwarded=tuple(forwarded),
    )


def managed_command(runtime: Path, request: BootstrapRequest) -> tuple[str, ...]:
    command = [str(runtime), "-m", "uniti"]
    if request.self_check:
        command.append("--self-check")
    if request.deep:
        command.append("--deep")
    if request.json_output:
        command.append("--json")
    command.extend(request.forwarded)
    return tuple(command)


def report_progress(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def _persist_bootstrap(
    request: BootstrapRequest,
    result: BootstrapResult,
    versions: dict[str, str],
) -> None:
    paths = request.app_paths or AppPaths.current()
    store = SetupStateStore(paths.setup_state_file)
    payload = store.prepare()
    payload["uniti"] = {
        "display_version": uniti.__display_version__,
        "package_version": uniti.__version__,
        "build_identity": result.fingerprint[:12],
    }
    payload["install"] = {
        "mode": request.mode.value,
        "source_root": str(request.source_root.resolve()),
        "environment_path": str(result.environment_path),
        "environment_id": result.marker.environment_id,
    }
    payload["python"] = {
        "host": dict(result.marker.host),
        "runtime": dict(result.marker.runtime),
        "owned": True,
    }
    payload["dependencies"] = {
        "ok": True,
        "fingerprint": result.fingerprint,
        "versions": dict(versions),
    }
    payload["last_bootstrap"] = utc_timestamp()
    store.save(payload)


def run_bootstrap(
    request: BootstrapRequest,
    *,
    progress: Callable[[str], None] | None = None,
) -> BootstrapResult:
    progress_sink = report_progress if progress is None else progress
    setup_started = False

    def report_setup_stage(message: str) -> None:
        nonlocal setup_started
        if not setup_started:
            progress_sink(
                "// repairing UNITI setup"
                if request.repair
                else "// prepping UNITI for first use"
            )
            setup_started = True
        progress_sink(message)

    root = validate_source_root(request.source_root)
    host = query_python((sys.executable,))
    target = environment_path(request)
    manager = EnvironmentManager(
        source_root=root,
        environment_path=target,
        mode=request.mode,
        host=host,
        progress=report_setup_stage,
    )
    with manager.lock():
        runtime, marker = manager.ensure(repair=request.repair)
        dependencies = DependencyManager(
            runtime,
            root,
            mode=request.mode,
            dev=request.dev,
            progress=report_setup_stage,
        ).ensure(marker=marker, repair=request.repair)
        marker = manager.mark_healthy(marker, dependencies.fingerprint)
        prepared = BootstrapResult(
            target,
            runtime,
            marker,
            dependencies.fingerprint,
            dependencies.fast_path,
            None,
        )
        _persist_bootstrap(request, prepared, dict(dependencies.versions))

    if request.no_launch:
        return prepared
    if setup_started:
        progress_sink("// launching UNITI")
    command = managed_command(runtime, request)
    try:
        completed = subprocess.run(command, check=False, shell=False)
    except OSError as error:
        raise BootstrapError("managed UNITI process could not be launched", 1) from error
    return BootstrapResult(
        target,
        runtime,
        marker,
        dependencies.fingerprint,
        dependencies.fast_path,
        int(completed.returncode),
    )


def main(argv: Sequence[str] | None = None) -> int:
    try:
        request = parse_args(sys.argv[1:] if argv is None else argv)
        result = run_bootstrap(request)
    except BootstrapError as error:
        print(f"UNITI bootstrap failed: {error}", file=sys.stderr)
        return error.exit_code
    if request.no_launch:
        print(shlex.join(managed_command(result.runtime_python, request)))
        return 0
    return int(result.launched_exit_code or 0)
