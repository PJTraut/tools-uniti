"""Exercise Quit and relaunch with real Qt, workers, and isolated durable state."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]
DESKTOP_RUN = r"""
import json
import os
import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from uniti.app import application
from uniti.app.paths import AppPaths
from uniti.app.service import UNITIService

root = Path(sys.argv[1])
mode = sys.argv[2]
paths = AppPaths(*(root / name for name in ('config', 'data', 'state', 'cache')))
app = QApplication([])
original_new_window = UNITIService.new_window

def new_window(service, record=None):
    window = original_new_window(service, record)

    def act():
        if mode in ('close_then_quit', 'close_then_terminate'):
            window.close()
            assert window.isVisible()
            assert service.window_count == 1
            assert service.is_running
        if mode == 'legacy_zero_window':
            window.close_for_service()
        if mode in ('close_then_terminate', 'legacy_zero_window'):
            wait_for_empty_session()
            return
        if mode == 'paused_quit':
            window.set_pause_background(True)
            service.schedule_publication()
        window._command_actions['file.quit'].trigger()
        assert not service.is_running, service.last_quit_error

    def wait_for_empty_session():
        loaded = service.sessions.load_manifest()
        expected_windows = 0 if mode == 'legacy_zero_window' else 1
        if (
            loaded.manifest is None
            or len(loaded.manifest.windows) != expected_windows
            or loaded.manifest.views
        ):
            QTimer.singleShot(10, wait_for_empty_session)
            return
        assert service.window_count == expected_windows
        # Model terminal termination: no orderly service cleanup runs.
        os._exit(0)

    QTimer.singleShot(100, act)
    return window

UNITIService.new_window = new_window
code = application.run_desktop(
    application.ApplicationRequest(),
    paths=paths,
    marker_path=root / 'runtime.json',
)
print(json.dumps({'exit_code': code}), flush=True)
raise SystemExit(code)
"""


@pytest.mark.parametrize(
    "first_exit",
    ["quit", "paused_quit", "close_then_quit", "close_then_terminate", "legacy_zero_window"],
)
def test_desktop_exit_releases_process_and_relaunches_saved_session(
    tmp_path: Path,
    first_exit: str,
):
    (tmp_path / "runtime.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "owner": "uniti-editor",
                "healthy": True,
                "environment_path": str(Path(sys.prefix).resolve()),
            }
        ),
        encoding="utf-8",
    )
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    for mode in (first_exit, "quit"):
        result = subprocess.run(
            [sys.executable, "-c", DESKTOP_RUN, str(tmp_path), mode],
            cwd=REPO_ROOT,
            env=env,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "SESSION_RESTORE" not in result.stderr
        assert "Traceback" not in result.stderr
        if mode not in ("close_then_terminate", "legacy_zero_window"):
            assert json.loads(result.stdout)["exit_code"] == 0

    from uniti.app.session_store import SessionStore

    loaded = SessionStore(tmp_path / "state" / "session").load_manifest()
    assert loaded.manifest is not None
    assert loaded.manifest.clean_shutdown
    assert len(loaded.manifest.windows) == 1
