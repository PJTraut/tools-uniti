import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from uniti.app import application
from uniti.app.paths import AppPaths
from uniti.app.setup_state import SetupStateStore
from uniti.app.startup import StartupContext, StartupCoordinator, StartupLog, StartupPhase
from uniti.bootstrap.model import BootstrapMode


REPO_ROOT = Path(__file__).parents[1]


def test_a16_release_contract():
    assert BootstrapMode.SOURCE.value == "source"
    assert list(StartupPhase)[-1] is StartupPhase.READY
    assert application.main(["uniti", "--version"]) == 0


def test_bootstrap_help_runs_from_repository_entrypoint():
    completed = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / "bootstrap.py"), "--help"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert "--repair" in completed.stdout
    assert "--self-check" in completed.stdout


def test_complete_offscreen_startup_reaches_ready_without_pip(tmp_path: Path, monkeypatch):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    original_run = subprocess.run

    def deny_pip(command, *args, **kwargs):
        parts = tuple(str(part) for part in command)
        if len(parts) >= 3 and parts[1:3] == ("-m", "pip"):
            raise AssertionError("normal startup must not invoke pip")
        return original_run(command, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", deny_pip)
    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    marker_path = tmp_path / ".uniti-runtime.json"
    marker_path.write_text(
        json.dumps(
            {
                "schema": 1,
                "owner": "uniti-editor",
                "environment_id": "acceptance",
                "mode": "source",
                "environment_path": str(Path(sys.prefix).resolve()),
                "source_root": str(REPO_ROOT.resolve()),
                "host": {},
                "runtime": {},
                "created_at": "2026-09-01T00:00:00Z",
                "updated_at": "2026-09-01T00:00:00Z",
                "dependency_fingerprint": "acceptance",
                "healthy": True,
            }
        ),
        encoding="utf-8",
    )
    context = StartupContext.create(paths, session_id="acceptance-session")
    coordinator = StartupCoordinator(
        SetupStateStore(paths.setup_state_file), StartupLog(paths.startup_log_file)
    )

    result = coordinator.run(
        context,
        application._startup_callbacks(application.ApplicationRequest(), marker_path),
    )

    try:
        assert result.phase is StartupPhase.READY
        assert result.data["window"] is not None
        assert SetupStateStore(paths.setup_state_file).prepare()["startup"]["ok"] is True
    finally:
        window = result.data.get("window")
        if window is not None:
            window.close_all_documents(force=True)
            window.close()
        result.cleanup()
