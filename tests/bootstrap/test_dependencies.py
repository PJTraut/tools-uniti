import json
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from uniti.bootstrap.dependencies import DependencyManager, DependencyManifest
from uniti.bootstrap.model import BootstrapError, BootstrapMode, RuntimeMarker


@pytest.fixture
def source_root(tmp_path: Path) -> Path:
    (tmp_path / "pyproject.toml").write_text(
        """
[build-system]
requires = ["setuptools>=75"]
build-backend = "setuptools.build_meta"
[project]
name = "uniti-editor"
version = "0.1a15"
requires-python = ">=3.12"
dependencies = ["regex==2026.5.9"]
[project.optional-dependencies]
ui = ["PySide6>=6.8"]
dev = ["pytest>=9"]
""".strip(),
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def marker(source_root: Path) -> RuntimeMarker:
    environment = source_root / ".venv"
    return RuntimeMarker(
        schema=1,
        owner="uniti-editor",
        environment_id="runtime-1",
        mode=BootstrapMode.SOURCE,
        environment_path=environment,
        source_root=source_root,
        host={"version": [3, 12, 4], "executable": "/host/python"},
        runtime={"version": [3, 12, 4], "executable": str(environment / "bin/python")},
        created_at="2026-09-01T00:00:00Z",
        updated_at="2026-09-01T00:00:00Z",
        dependency_fingerprint=None,
        healthy=False,
    )


def successful_runner(observed: list[tuple[str, ...]]):
    def run(command, **kwargs):
        invocation = tuple(str(part) for part in command)
        observed.append(invocation)
        if "-c" in invocation:
            stdout = json.dumps(
                {"uniti-editor": "0.1a15", "regex": "2026.5.9", "PySide6": "6.9.2"}
            )
        else:
            stdout = "No broken requirements found.\n"
        return subprocess.CompletedProcess(command, 0, stdout, "")

    return run


def test_manifest_reads_canonical_base_ui_and_dev_groups(source_root: Path):
    manifest = DependencyManifest.load(source_root)

    assert manifest.project_name == "uniti-editor"
    assert manifest.version == "0.1a15"
    assert manifest.base == ("regex==2026.5.9",)
    assert manifest.ui == ("PySide6>=6.8",)
    assert manifest.dev == ("pytest>=9",)


@pytest.mark.parametrize(
    ("mode", "dev", "editable", "extra"),
    [
        (BootstrapMode.SOURCE, False, True, "[ui]"),
        (BootstrapMode.SOURCE, True, True, "[ui,dev]"),
        (BootstrapMode.LOCAL, False, False, "[ui]"),
        (BootstrapMode.LOCAL, True, False, "[ui,dev]"),
    ],
)
def test_install_command_uses_only_runtime_python(
    source_root: Path, mode: BootstrapMode, dev: bool, editable: bool, extra: str
):
    runtime = source_root / "managed" / "bin" / "python"
    manager = DependencyManager(runtime, source_root, mode=mode, dev=dev)

    command = manager.install_command()

    assert command[:4] == (str(runtime), "-m", "pip", "install")
    assert ("-e" in command) is editable
    assert command[-1] == f"{source_root.resolve()}{extra}"


def test_healthy_matching_marker_uses_validation_only_fast_path(source_root, marker):
    observed: list[tuple[str, ...]] = []
    manager = DependencyManager(
        source_root / ".venv/bin/python",
        source_root,
        mode=BootstrapMode.SOURCE,
        runner=successful_runner(observed),
    )
    versions = {"uniti-editor": "0.1a15", "regex": "2026.5.9", "PySide6": "6.9.2"}
    matching = replace(
        marker,
        healthy=True,
        dependency_fingerprint=manager.fingerprint(marker, versions),
    )

    result = manager.ensure(marker=matching, repair=False)

    assert result.fast_path is True
    assert manager.install_command() not in observed
    assert any(command[1:4] == ("-m", "pip", "check") for command in observed)


def test_repair_installs_even_when_marker_matches(source_root, marker):
    observed: list[tuple[str, ...]] = []
    manager = DependencyManager(
        source_root / ".venv/bin/python",
        source_root,
        mode=BootstrapMode.SOURCE,
        runner=successful_runner(observed),
    )
    versions = {"uniti-editor": "0.1a15", "regex": "2026.5.9", "PySide6": "6.9.2"}
    matching = replace(
        marker,
        healthy=True,
        dependency_fingerprint=manager.fingerprint(marker, versions),
    )

    result = manager.ensure(marker=matching, repair=True)

    assert result.fast_path is False
    assert manager.install_command() in observed


def test_broken_pip_check_is_dependency_failure(source_root, marker):
    def broken_runner(command, **kwargs):
        invocation = tuple(str(part) for part in command)
        if "-c" in invocation:
            return subprocess.CompletedProcess(
                command,
                0,
                json.dumps(
                    {"uniti-editor": "0.1a15", "regex": "2026.5.9", "PySide6": "6.9.2"}
                ),
                "",
            )
        if invocation[-1] == "check":
            return subprocess.CompletedProcess(command, 1, "broken requirement", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = DependencyManager(
        source_root / ".venv/bin/python",
        source_root,
        mode=BootstrapMode.SOURCE,
        runner=broken_runner,
    )

    with pytest.raises(BootstrapError) as caught:
        manager.ensure(marker=marker, repair=True)

    assert caught.value.exit_code == 12
