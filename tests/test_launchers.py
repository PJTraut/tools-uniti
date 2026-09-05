import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[1]
POSIX_LAUNCHER = REPO_ROOT / "uniti.command"
WINDOWS_LAUNCHER = REPO_ROOT / "uniti.bat"
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap.py"


def _posix_python_stub(tmp_path: Path) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    executable = tmp_path / "Python Stub Ω (100%)"
    capture = tmp_path / "capture Привет.py"
    log = tmp_path / "launch Ω.json"
    capture.write_text(
        """import json
import os
import sys
from pathlib import Path

Path(os.environ["UNITI_LAUNCH_TEST_LOG"]).write_text(
    json.dumps(
        {"cwd": os.getcwd(), "arguments": sys.argv[1:]},
        ensure_ascii=False,
    ),
    encoding="utf-8",
)
raise SystemExit(int(os.environ["UNITI_LAUNCH_TEST_EXIT"]))
""",
        encoding="utf-8",
    )
    executable.write_text(
        (
            "#!/bin/sh\n"
            f"exec {shlex.quote(sys.executable)} {shlex.quote(str(capture))} \"$@\"\n"
        ),
        encoding="utf-8",
    )
    executable.chmod(0o755)
    return executable, log


def _launcher_checkout(tmp_path: Path, launcher: Path) -> tuple[Path, Path]:
    checkout = tmp_path / "checkout Ω Привет (100%)"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    copied = checkout / launcher.name
    shutil.copy2(launcher, copied)
    copied.chmod(0o755)
    bootstrap = scripts / "bootstrap.py"
    bootstrap.write_text("# launcher target\n", encoding="utf-8", newline="")
    return copied, bootstrap


def _windows_python_stub(tmp_path: Path) -> Path:
    directory = tmp_path / "Python Stub Ω Привет (100%)"
    directory.mkdir(parents=True)
    wrapper = directory / "python.cmd"
    wrapper.write_text(
        """@echo off
"%UNITI_REAL_PYTHON%" %*
exit /b %ERRORLEVEL%
""",
        encoding="utf-8",
    )
    return wrapper


def test_required_platform_launchers_are_shipped():
    assert POSIX_LAUNCHER.is_file()
    assert WINDOWS_LAUNCHER.is_file()


@pytest.mark.skipif(os.name == "nt", reason="requires a POSIX command launcher")
def test_posix_launcher_preserves_working_directory_and_arguments(tmp_path: Path):
    python_stub, log = _posix_python_stub(tmp_path)
    launcher, bootstrap = _launcher_checkout(tmp_path, POSIX_LAUNCHER)
    invocation_dir = tmp_path / "invocation directory Ω"
    invocation_dir.mkdir()
    path_dir = tmp_path / "ignored PATH candidate"
    path_dir.mkdir()
    ignored = path_dir / "python3"
    ignored.write_text("#!/bin/sh\nexit 99\n", encoding="utf-8", newline="")
    ignored.chmod(0o755)
    arguments = (
        "notes one.txt",
        "Ω",
        "Привет",
        "100%",
        "a&b",
        "(group)",
        "-leading",
        "",
    )
    env = {
        **os.environ,
        "PATH": str(path_dir),
        "UNITI_PYTHON": str(python_stub),
        "UNITI_LAUNCH_TEST_LOG": str(log),
        "UNITI_LAUNCH_TEST_EXIT": "0",
    }

    completed = subprocess.run(
        [shutil.which("sh") or "/bin/sh", str(launcher), *arguments],
        cwd=invocation_dir,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(log.read_text(encoding="utf-8"))
    assert Path(payload["cwd"]).resolve() == invocation_dir.resolve()
    assert payload["arguments"] == [str(bootstrap), *arguments]


@pytest.mark.skipif(os.name == "nt", reason="requires a POSIX command launcher")
def test_posix_launcher_propagates_bootstrap_failure(tmp_path: Path):
    python_stub, _log = _posix_python_stub(tmp_path)
    env = {
        **os.environ,
        "UNITI_PYTHON": str(python_stub),
        "UNITI_LAUNCH_TEST_LOG": str(tmp_path / "launch.json"),
        "UNITI_LAUNCH_TEST_EXIT": "23",
    }

    completed = subprocess.run(
        [str(POSIX_LAUNCHER)],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 23


@pytest.mark.skipif(os.name == "nt", reason="requires a POSIX command launcher")
def test_posix_launcher_discovers_python_from_path(tmp_path: Path):
    python_stub, log = _posix_python_stub(tmp_path)
    discovered_python = tmp_path / "python3"
    discovered_python.symlink_to(python_stub)
    later_candidate = tmp_path / "python3.15"
    later_candidate.write_text(
        "#!/bin/sh\nexit 99\n",
        encoding="utf-8",
        newline="",
    )
    later_candidate.chmod(0o755)
    env = {
        **os.environ,
        "PATH": str(tmp_path),
        "UNITI_LAUNCH_TEST_LOG": str(log),
        "UNITI_LAUNCH_TEST_EXIT": "0",
    }
    env.pop("UNITI_PYTHON", None)

    completed = subprocess.run(
        [str(POSIX_LAUNCHER), "notes.txt"],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    payload = json.loads(log.read_text(encoding="utf-8"))
    assert payload["arguments"] == [str(BOOTSTRAP), "notes.txt"]


@pytest.mark.skipif(os.name == "nt", reason="requires a POSIX command launcher")
def test_posix_launcher_reports_missing_python(tmp_path: Path):
    env = {**os.environ, "PATH": ""}
    env.pop("UNITI_PYTHON", None)

    completed = subprocess.run(
        [str(POSIX_LAUNCHER)],
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
    checkout = tmp_path / "checkout Ω Привет (100%)"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    launcher = checkout / WINDOWS_LAUNCHER.name
    shutil.copy2(WINDOWS_LAUNCHER, launcher)
    bootstrap = scripts / "bootstrap.py"
    log = tmp_path / "launch.json"
    bootstrap.write_text(
        """import json
import os
import sys
from pathlib import Path

Path(os.environ["UNITI_LAUNCH_TEST_LOG"]).write_text(
    json.dumps({"cwd": os.getcwd(), "argv": sys.argv}, ensure_ascii=False),
    encoding="utf-8",
)
raise SystemExit(int(os.environ["UNITI_LAUNCH_TEST_EXIT"]))
""",
        encoding="utf-8",
    )
    python_stub = _windows_python_stub(tmp_path)
    env = {
        **os.environ,
        "UNITI_PYTHON": str(python_stub),
        "UNITI_REAL_PYTHON": sys.executable,
        "UNITI_LAUNCH_TEST_LOG": str(log),
        "UNITI_LAUNCH_TEST_EXIT": "23",
    }
    arguments = (
        "notes one.txt",
        "Ω",
        "Привет",
        "100%",
        "a&b",
        "(group)",
        "-leading",
        "",
    )

    completed = subprocess.run(
        [str(launcher), *arguments],
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
        *arguments,
    ]


@pytest.mark.skipif(os.name != "nt", reason="requires Windows cmd.exe")
def test_windows_launcher_discovers_python_from_path(tmp_path: Path):
    path_dir = tmp_path / "PATH Ω Привет (100%)"
    path_dir.mkdir()
    python_stub = path_dir / "python.cmd"
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
        "PATH": str(path_dir),
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


@pytest.mark.skipif(os.name != "nt", reason="requires Windows PowerShell")
def test_windows_launcher_invokes_from_powershell(tmp_path: Path):
    powershell = shutil.which("powershell.exe") or shutil.which("pwsh.exe")
    if powershell is None:
        pytest.fail("required Windows PowerShell executable is unavailable")
    checkout = tmp_path / "PowerShell checkout Ω (100%)"
    scripts = checkout / "scripts"
    scripts.mkdir(parents=True)
    launcher = checkout / WINDOWS_LAUNCHER.name
    shutil.copy2(WINDOWS_LAUNCHER, launcher)
    bootstrap = scripts / "bootstrap.py"
    log = tmp_path / "PowerShell launch.json"
    bootstrap.write_text(
        """import json
import os
import sys
from pathlib import Path

Path(os.environ["UNITI_LAUNCH_TEST_LOG"]).write_text(
    json.dumps({"cwd": os.getcwd(), "argv": sys.argv}, ensure_ascii=False),
    encoding="utf-8",
)
raise SystemExit(23)
""",
        encoding="utf-8",
    )
    python_stub = _windows_python_stub(tmp_path)
    env = {
        **os.environ,
        "UNITI_PYTHON": str(python_stub),
        "UNITI_REAL_PYTHON": sys.executable,
        "UNITI_LAUNCH_TEST_LOG": str(log),
    }
    command = (
        "& .\\uniti.bat 'notes one.txt' 'Ω' 'Привет' '100%' "
        "'a&b' '(group)' '-leading' ''; exit $LASTEXITCODE"
    )

    completed = subprocess.run(
        [powershell, "-NoProfile", "-Command", command],
        cwd=checkout,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    payload = json.loads(log.read_text(encoding="utf-8"))
    assert completed.returncode == 23
    assert Path(payload["cwd"]).resolve() == checkout.resolve()
    assert [str(Path(payload["argv"][0]).resolve()), *payload["argv"][1:]] == [
        str(bootstrap.resolve()),
        "notes one.txt",
        "Ω",
        "Привет",
        "100%",
        "a&b",
        "(group)",
        "-leading",
        "",
    ]
