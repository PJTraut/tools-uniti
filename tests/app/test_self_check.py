import json
import sys
from pathlib import Path

from uniti.app.paths import AppPaths
from uniti.app.self_check import (
    CheckResult,
    CheckStatus,
    SelfCheckReport,
    SelfCheckRunner,
    render_human,
    render_json,
)
from uniti.app.startup import ExitCode


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    paths.ensure()
    return paths


def _marker(tmp_path: Path) -> Path:
    marker = tmp_path / ".uniti-runtime.json"
    marker.write_text(
        json.dumps(
            {
                "schema": 1,
                "owner": "uniti-editor",
                "environment_id": "test-runtime",
                "mode": "source",
                "healthy": True,
            }
        ),
        encoding="utf-8",
    )
    return marker


def test_json_report_has_stable_shape(tmp_path: Path):
    runner = SelfCheckRunner(
        _paths(tmp_path), marker_path=_marker(tmp_path), runtime_python=Path(sys.executable)
    )

    payload = json.loads(render_json(runner.run()))

    assert list(payload) == ["schema", "mode", "identity", "status", "exit_code", "results"]
    assert payload["schema"] == 1
    assert payload["mode"] == "fast"
    assert {item["status"] for item in payload["results"]} <= {"pass", "fail", "skip"}


def test_human_report_names_mode_status_and_checks(tmp_path: Path):
    runner = SelfCheckRunner(
        _paths(tmp_path), marker_path=_marker(tmp_path), runtime_python=Path(sys.executable)
    )

    output = render_human(runner.run())

    assert output.startswith("UNITI self-check (fast):")
    assert "runtime:" in output
    assert "dependencies:" in output


def test_deep_check_exercises_complete_core_matrix(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    runner = SelfCheckRunner(
        _paths(tmp_path), marker_path=_marker(tmp_path), runtime_python=Path(sys.executable)
    )

    report = runner.run(deep=True)

    names = {result.name for result in report.results}
    assert {
        "encodings",
        "eol",
        "mmap",
        "byte-preservation",
        "regex-functional",
        "streaming-save",
        "recovery",
        "qt-offscreen",
    } <= names
    assert [result.name for result in report.results if result.status is CheckStatus.FAIL] == []


def test_report_uses_most_specific_failure_code():
    report = SelfCheckReport.from_results(
        "fast",
        {},
        (
            CheckResult.failed("paths", ExitCode.STATE, "not writable"),
            CheckResult.failed("qt", ExitCode.GUI, "unavailable"),
        ),
    )

    assert report.status is CheckStatus.FAIL
    assert report.exit_code is ExitCode.GUI


def test_invalid_runtime_marker_is_environment_failure(tmp_path: Path):
    marker = _marker(tmp_path)
    marker.write_text('{"schema":1,"owner":"wrong","healthy":true}', encoding="utf-8")

    report = SelfCheckRunner(
        _paths(tmp_path), marker_path=marker, runtime_python=Path(sys.executable)
    ).run()

    runtime = next(result for result in report.results if result.name == "runtime")
    assert runtime.status is CheckStatus.FAIL
    assert runtime.exit_code is ExitCode.ENVIRONMENT
