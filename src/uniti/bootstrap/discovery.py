"""Validated source, host interpreter, and managed-runtime discovery."""

from __future__ import annotations

import json
import platform
import subprocess
import sys
import tomllib
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path

from uniti.app.paths import AppPaths

from .model import BootstrapError, BootstrapMode, BootstrapRequest, HostPython

_IDENTITY_CODE = (
    "import json,platform,sys;"
    "print(json.dumps({'executable':sys.executable,'version':list(sys.version_info[:3]),"
    "'implementation':platform.python_implementation(),"
    "'architecture':platform.architecture()[0],"
    "'prefix':sys.prefix,'base_prefix':sys.base_prefix}))"
)


def query_python(
    command: Sequence[str],
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> HostPython:
    invocation = [*command, "-c", _IDENTITY_CODE]
    try:
        completed = runner(
            invocation,
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise BootstrapError(f"cannot run Python candidate {command[0]!r}", 10) from error
    if completed.returncode != 0:
        raise BootstrapError(f"Python candidate {command[0]!r} failed validation", 10)
    try:
        payload = json.loads(completed.stdout)
        version_raw = payload["version"]
        if not isinstance(version_raw, list) or len(version_raw) != 3:
            raise ValueError
        version = tuple(int(value) for value in version_raw)
        if len(version) != 3:
            raise ValueError
        return HostPython(
            tuple(command),
            Path(str(payload["executable"])).resolve(),
            version,
            str(payload["implementation"]),
            str(payload["architecture"]),
            Path(str(payload["prefix"])).resolve(),
            Path(str(payload["base_prefix"])).resolve(),
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
        raise BootstrapError(f"Python candidate {command[0]!r} returned invalid identity", 10) from error


def default_candidates() -> tuple[tuple[str, ...], ...]:
    commands: list[tuple[str, ...]] = [(sys.executable,), ("python3",)]
    commands.extend((f"python3.{minor}",) for minor in range(15, 11, -1))
    if sys.platform.startswith("win"):
        commands.append(("py", "-3"))
    return tuple(dict.fromkeys(commands))


def discover_host_python(
    *,
    candidates: Iterable[Sequence[str]] | None = None,
    query: Callable[[tuple[str, ...]], HostPython] | None = None,
) -> HostPython:
    identity_query = query or (lambda command: query_python(command))
    for raw_command in candidates or default_candidates():
        command = tuple(raw_command)
        try:
            identity = identity_query(command)
        except (BootstrapError, OSError, subprocess.SubprocessError):
            continue
        if identity.supported:
            return identity
    raise BootstrapError("UNITI requires an installed Python 3.12 or newer", 10)


def validate_source_root(path: Path) -> Path:
    source_root = Path(path).expanduser().resolve()
    pyproject = source_root / "pyproject.toml"
    package = source_root / "src" / "uniti"
    try:
        payload = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project_name = payload["project"]["name"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as error:
        raise BootstrapError(f"not a valid UNITI source root: {source_root}", 13) from error
    if project_name != "uniti-editor" or not package.is_dir():
        raise BootstrapError(f"not a valid UNITI source root: {source_root}", 13)
    return source_root


def environment_path(request: BootstrapRequest) -> Path:
    source_root = validate_source_root(request.source_root)
    if request.mode is BootstrapMode.SOURCE:
        return source_root / ".venv"
    paths = request.app_paths or AppPaths.current()
    return paths.local_runtime_dir


def runtime_python(environment: Path, platform_name: str | None = None) -> Path:
    selected_platform = sys.platform if platform_name is None else platform_name
    if selected_platform.startswith("win"):
        return Path(environment) / "Scripts" / "python.exe"
    return Path(environment) / "bin" / "python"
