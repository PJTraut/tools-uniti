import json
import os
import sys
from pathlib import Path

import uniti
import pytest

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


def test_schema_check_reports_the_current_settings_schema(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.settings_file.write_text('{"schema":3}', encoding="utf-8")
    runner = SelfCheckRunner(
        paths, marker_path=_marker(tmp_path), runtime_python=Path(sys.executable)
    )

    summary, details = runner._schemas()

    assert summary == "setup and settings schemas are readable"
    assert details == {
        "setup": 1,
        "settings": 3,
        "settings_migrated": False,
    }


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
        "text-integrity",
        "large-file",
        "regex-intelligence",
        "recovery",
        "recovery-session",
        "qt-offscreen",
    } <= names
    assert [result.name for result in report.results if result.status is CheckStatus.FAIL] == []


def test_regex_intelligence_probe_reports_only_safe_bounded_facts(
    tmp_path: Path,
):
    summary, details = SelfCheckRunner._deep_regex_intelligence(tmp_path)

    assert summary == "regex intelligence, captures, zero-width, and undo passed"
    assert set(details) == {
        "regex_version",
        "advanced_patterns",
        "zero_width_matches",
        "report_payload_bytes",
        "replacement_count",
        "undo_exact",
    }
    assert details["regex_version"] == "2026.5.9"
    assert details["advanced_patterns"] == 5
    assert details["zero_width_matches"] == 6
    assert details["report_payload_bytes"] <= 1 << 20
    assert details["replacement_count"] == 4
    assert details["undo_exact"] is True


def test_recovery_session_probe_reports_only_safe_bounded_facts(tmp_path: Path):
    summary, details = SelfCheckRunner._deep_recovery_session(tmp_path)

    assert summary == "saved session and crash recovery histories passed"
    assert set(details) == {
        "session_documents",
        "session_transactions",
        "session_hash_exact",
        "recovery_candidates",
        "recovery_transactions",
        "recovery_undo_available",
        "recovery_redo_exact",
        "external_change_detected",
        "external_source_preserved",
    }
    assert details == {
        "session_documents": 1,
        "session_transactions": 1,
        "session_hash_exact": True,
        "recovery_candidates": 1,
        "recovery_transactions": 1,
        "recovery_undo_available": True,
        "recovery_redo_exact": True,
        "external_change_detected": True,
        "external_source_preserved": True,
    }


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


def test_installed_metadata_mismatch_is_dependency_failure(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(uniti, "__version__", "9.9")
    runner = SelfCheckRunner(
        _paths(tmp_path), marker_path=_marker(tmp_path), runtime_python=Path(sys.executable)
    )

    report = runner.run()

    dependency = next(result for result in report.results if result.name == "dependencies")
    assert dependency.status is CheckStatus.FAIL
    assert dependency.exit_code is ExitCode.DEPENDENCIES


def test_deep_qt_check_requires_fixed_font_coverage(tmp_path: Path, monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from uniti.app import capabilities
    from uniti.app.capabilities import CapabilityResult, CapabilityStatus

    monkeypatch.setattr(
        capabilities,
        "probe_qt",
        lambda _app: {
            "qt": CapabilityResult(CapabilityStatus.AVAILABLE, "Qt available"),
            "font": CapabilityResult(
                CapabilityStatus.UNAVAILABLE,
                "fixed font coverage is unavailable",
            ),
        },
    )

    with pytest.raises(RuntimeError, match="font coverage"):
        SelfCheckRunner._deep_qt(tmp_path)
