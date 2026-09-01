import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[1]
MACOS_LAUNCHER = REPO_ROOT / "uniti.command"
WINDOWS_LAUNCHER = REPO_ROOT / "uniti.bat"
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap.py"


def _posix_python_stub(tmp_path: Path) -> tuple[Path, Path]:
    executable = tmp_path / "Python Stub"
    log = tmp_path / "launch.log"
    executable.write_text(
        """#!/bin/sh
printf '%s\\n' "$PWD" > "$UNITI_LAUNCH_TEST_LOG"
for argument in "$@"; do
    printf '%s\\n' "$argument" >> "$UNITI_LAUNCH_TEST_LOG"
done
exit "$UNITI_LAUNCH_TEST_EXIT"
""",
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable, log


def test_required_platform_launchers_are_shipped():
    assert MACOS_LAUNCHER.is_file()
    assert WINDOWS_LAUNCHER.is_file()


@pytest.mark.skipif(os.name == "nt", reason="requires a POSIX command launcher")
def test_macos_launcher_preserves_working_directory_and_arguments(tmp_path: Path):
    python_stub, log = _posix_python_stub(tmp_path)
    invocation_dir = tmp_path / "invocation directory"
    invocation_dir.mkdir()
    env = {
        **os.environ,
        "UNITI_PYTHON": str(python_stub),
        "UNITI_LAUNCH_TEST_LOG": str(log),
        "UNITI_LAUNCH_TEST_EXIT": "0",
    }

    completed = subprocess.run(
        [str(MACOS_LAUNCHER), "notes one.txt", "--self-check"],
        cwd=invocation_dir,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert log.read_text(encoding="utf-8").splitlines() == [
        str(invocation_dir),
        str(BOOTSTRAP),
        "notes one.txt",
        "--self-check",
    ]


@pytest.mark.skipif(os.name == "nt", reason="requires a POSIX command launcher")
def test_macos_launcher_propagates_bootstrap_failure(tmp_path: Path):
    python_stub, log = _posix_python_stub(tmp_path)
    env = {
        **os.environ,
        "UNITI_PYTHON": str(python_stub),
        "UNITI_LAUNCH_TEST_LOG": str(log),
        "UNITI_LAUNCH_TEST_EXIT": "23",
    }

    completed = subprocess.run(
        [str(MACOS_LAUNCHER)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 23


@pytest.mark.skipif(os.name == "nt", reason="requires a POSIX command launcher")
def test_macos_launcher_discovers_python_from_path(tmp_path: Path):
    python_stub, log = _posix_python_stub(tmp_path)
    discovered_python = tmp_path / "python3"
    discovered_python.symlink_to(python_stub)
    env = {
        **os.environ,
        "PATH": str(tmp_path),
        "UNITI_LAUNCH_TEST_LOG": str(log),
        "UNITI_LAUNCH_TEST_EXIT": "0",
    }
    env.pop("UNITI_PYTHON", None)

    completed = subprocess.run(
        [str(MACOS_LAUNCHER), "notes.txt"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert log.read_text(encoding="utf-8").splitlines()[1:] == [
        str(BOOTSTRAP),
        "notes.txt",
    ]


@pytest.mark.skipif(os.name == "nt", reason="requires a POSIX command launcher")
def test_macos_launcher_reports_missing_python(tmp_path: Path):
    env = {**os.environ, "PATH": ""}
    env.pop("UNITI_PYTHON", None)

    completed = subprocess.run(
        [str(MACOS_LAUNCHER)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 10
    assert completed.stderr == "UNITI requires an installed Python 3.12 or newer.\n"


@pytest.mark.skipif(os.name != "nt", reason="requires Windows cmd.exe")
def test_windows_launcher_preserves_context_arguments_and_exit_code(tmp_path: Path):
    checkout = tmp_path / "checkout with spaces"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    launcher = checkout / WINDOWS_LAUNCHER.name
    shutil.copy2(WINDOWS_LAUNCHER, launcher)
    bootstrap = scripts / "bootstrap.py"
    log = tmp_path / "launch.log"
    bootstrap.write_text(
        """import json
import os
import sys
from pathlib import Path

Path(os.environ["UNITI_LAUNCH_TEST_LOG"]).write_text(
    json.dumps({"cwd": os.getcwd(), "argv": sys.argv}),
    encoding="utf-8",
)
raise SystemExit(int(os.environ["UNITI_LAUNCH_TEST_EXIT"]))
""",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "UNITI_PYTHON": sys.executable,
        "UNITI_LAUNCH_TEST_LOG": str(log),
        "UNITI_LAUNCH_TEST_EXIT": "23",
    }

    completed = subprocess.run(
        [str(launcher), "notes & 100%.txt", "--self-check"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(log.read_text(encoding="utf-8"))
    assert completed.returncode == 23
    assert Path(payload["cwd"]).resolve() == tmp_path.resolve()
    assert [str(Path(payload["argv"][0]).resolve()), *payload["argv"][1:]] == [
        str(bootstrap.resolve()),
        "notes & 100%.txt",
        "--self-check",
    ]


@pytest.mark.skipif(os.name != "nt", reason="requires Windows cmd.exe")
def test_windows_launcher_discovers_python_from_path(tmp_path: Path):
    python_stub = tmp_path / "python.cmd"
    log = tmp_path / "launch.log"
    python_stub.write_text(
        """@echo off
> "%UNITI_LAUNCH_TEST_LOG%" echo %~1
exit /b %UNITI_LAUNCH_TEST_EXIT%
""",
        encoding="utf-8",
    )
    env = {
        **os.environ,
        "PATH": str(tmp_path),
        "UNITI_LAUNCH_TEST_LOG": str(log),
        "UNITI_LAUNCH_TEST_EXIT": "23",
    }
    env.pop("UNITI_PYTHON", None)

    completed = subprocess.run(
        [str(WINDOWS_LAUNCHER)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 23
    assert Path(log.read_text(encoding="utf-8").strip()).resolve() == BOOTSTRAP.resolve()


@pytest.mark.skipif(os.name != "nt", reason="requires Windows cmd.exe")
def test_windows_launcher_reports_missing_python(tmp_path: Path):
    env = {**os.environ, "PATH": ""}
    env.pop("UNITI_PYTHON", None)

    completed = subprocess.run(
        [str(WINDOWS_LAUNCHER)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 10
    assert completed.stderr.strip() == "UNITI requires an installed Python 3.12 or newer."
