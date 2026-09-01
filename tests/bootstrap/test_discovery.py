import json
import subprocess
from pathlib import Path

import pytest

from uniti.app.paths import AppPaths
from uniti.bootstrap.discovery import (
    discover_host_python,
    environment_path,
    query_python,
    runtime_python,
    validate_source_root,
)
from uniti.bootstrap.model import BootstrapError, BootstrapMode, BootstrapRequest, HostPython


def _identity(command: tuple[str, ...], version: tuple[int, int, int], executable: str):
    return HostPython(command, Path(executable), version, "CPython", "64bit")


def test_discovery_rejects_older_candidate_and_selects_supported():
    identities = {
        ("python3",): _identity(("python3",), (3, 11, 9), "/old/python"),
        ("python3.12",): _identity(("python3.12",), (3, 12, 4), "/ok/python"),
    }

    selected = discover_host_python(
        candidates=tuple(identities), query=identities.__getitem__
    )

    assert selected.executable == Path("/ok/python")


def test_discovery_reports_runtime_exit_when_no_candidate_is_supported():
    old = _identity(("python",), (3, 10, 1), "/old/python")

    with pytest.raises(BootstrapError) as caught:
        discover_host_python(candidates=(("python",),), query=lambda _: old)

    assert caught.value.exit_code == 10
    assert "Python 3.12" in str(caught.value)


def test_query_python_uses_subprocess_json_identity():
    payload = json.dumps(
        {
            "executable": "/real/python",
            "version": [3, 13, 2],
            "implementation": "CPython",
            "architecture": "64bit",
            "prefix": "/venv",
            "base_prefix": "/base",
        }
    )
    observed = {}

    def runner(command, **kwargs):
        observed["command"] = command
        observed["kwargs"] = kwargs
        return subprocess.CompletedProcess(command, 0, payload, "")

    result = query_python(("candidate",), runner=runner)

    assert result.version == (3, 13, 2)
    assert result.executable == Path("/real/python")
    assert observed["command"][0] == "candidate"
    assert observed["kwargs"]["shell"] is False


def test_source_root_requires_uniti_project(tmp_path: Path):
    (tmp_path / "src" / "uniti").mkdir(parents=True)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "not-uniti"\n', encoding="utf-8"
    )

    with pytest.raises(BootstrapError) as caught:
        validate_source_root(tmp_path)

    assert caught.value.exit_code == 13


def test_source_and_local_environment_paths_are_exact(tmp_path: Path):
    source_root = tmp_path / "source"
    (source_root / "src" / "uniti").mkdir(parents=True)
    (source_root / "pyproject.toml").write_text(
        '[project]\nname = "uniti-editor"\n', encoding="utf-8"
    )
    paths = AppPaths(
        tmp_path / "cfg",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )

    source = BootstrapRequest(BootstrapMode.SOURCE, source_root)
    local = BootstrapRequest(BootstrapMode.LOCAL, source_root, app_paths=paths)

    assert environment_path(source) == source_root.resolve() / ".venv"
    assert environment_path(local) == tmp_path / "data" / "runtime" / "venv"
    assert runtime_python(source_root / ".venv", "linux") == source_root / ".venv/bin/python"
    assert runtime_python(source_root / ".venv", "win32") == source_root / ".venv/Scripts/python.exe"
