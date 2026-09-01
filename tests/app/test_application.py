import sys
from pathlib import Path

import pytest
import uniti

from uniti.app import application
from uniti.app.paths import AppPaths
from uniti.app.self_check import CheckResult, SelfCheckReport
from uniti.app.startup import ExitCode, StartupFailure


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


def test_normal_dependency_validation_rejects_installed_metadata_mismatch(monkeypatch):
    monkeypatch.setattr(uniti, "__version__", "9.9")

    with pytest.raises(StartupFailure) as caught:
        application._normal_dependencies()

    assert caught.value.exit_code is ExitCode.DEPENDENCIES
