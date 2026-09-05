from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scripts.a21_ci import (
    ARTIFACT_RETENTION_DAYS,
    MAX_INPUT_BYTES,
    A21CIDriver,
    A21CIError,
    load_skip_policy,
    sanitize_results,
    verify_skips,
)


class RecordingRunner:
    def __init__(self, *responses: subprocess.CompletedProcess[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, command, **kwargs):
        self.calls.append((list(command), dict(kwargs)))
        if self.responses:
            return self.responses.pop(0)
        return subprocess.CompletedProcess(command, 0, "", "")


def _completed(payload: object, *, returncode: int = 0):
    stdout = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.CompletedProcess([], returncode, stdout, "")


def _driver(
    tmp_path: Path,
    *,
    family: str = "macos",
    platform_name: str = "darwin",
    runner=None,
    which=lambda name: f"/usr/bin/{name}",
) -> A21CIDriver:
    runtime = (
        tmp_path / ".venv" / "Scripts" / "python.exe"
        if family == "windows"
        else tmp_path / ".venv" / "bin" / "python"
    )
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"")
    (tmp_path / ".venv" / ".uniti-runtime.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "owner": "uniti-editor",
                "healthy": True,
                "mode": "source",
                "environment_path": str(tmp_path / ".venv"),
            }
        ),
        encoding="utf-8",
    )
    return A21CIDriver(
        tmp_path,
        family,
        platform_name=platform_name,
        runner=runner or RecordingRunner(),
        which=which,
        environ={"QT_QPA_PLATFORM": "inherited", "KEEP": "yes"},
    )


def _policy(path: Path, families: dict[str, list[list[str]]]) -> Path:
    path.write_text(
        json.dumps({"schema": 1, "families": families}),
        encoding="utf-8",
    )
    return path


def _junit(path: Path, cases: list[tuple[str, str, str | None]]) -> Path:
    items = []
    for file_name, test_name, reason in cases:
        skipped = "" if reason is None else f'<skipped message="{reason}" />'
        items.append(
            f'<testcase file="{file_name}" name="{test_name}" time="0.1">'
            f"{skipped}</testcase>"
        )
    path.write_text(
        f'<testsuites tests="{len(cases)}"><testsuite>{"".join(items)}'
        "</testsuite></testsuites>",
        encoding="utf-8",
    )
    return path


def test_skip_verifier_requires_exact_node_id_and_reason(tmp_path: Path):
    policy = _policy(
        tmp_path / "policy.json",
        {
            "macos": [["tests/test_one.py::test_windows", "requires Windows"]],
            "linux": [],
            "windows": [],
        },
    )
    junit = _junit(
        tmp_path / "pytest.xml",
        [
            ("tests/test_one.py", "test_windows", "requires Windows"),
            ("tests/test_one.py", "test_runs", None),
        ],
    )

    result = verify_skips(junit, "macos", policy)

    assert result == {"schema": 1, "family": "macos", "tests": 2, "skips": 1}


@pytest.mark.parametrize(
    ("cases", "match"),
    (
        (
            [("tests/test_one.py", "test_windows", "wrong reason")],
            "reason",
        ),
        (
            [("tests/test_one.py", "test_linux_only", "linux reason")],
            "should run",
        ),
        (
            [("tests/test_one.py", "test_unknown", "unknown reason")],
            "unknown skip",
        ),
        ([("tests/test_one.py", "test_runs", None)], "missing expected skip"),
    ),
)
def test_skip_verifier_rejects_inexact_skip_sets(
    tmp_path: Path,
    cases,
    match: str,
):
    policy = _policy(
        tmp_path / "policy.json",
        {
            "macos": [["tests/test_one.py::test_windows", "requires Windows"]],
            "linux": [["tests/test_one.py::test_linux_only", "linux reason"]],
            "windows": [],
        },
    )
    junit = _junit(tmp_path / "pytest.xml", cases)

    with pytest.raises(A21CIError, match=match):
        verify_skips(junit, "macos", policy)


def test_skip_policy_rejects_duplicate_entries_and_unknown_family(tmp_path: Path):
    duplicate = _policy(
        tmp_path / "duplicate.json",
        {
            "macos": [["a::b", "reason"], ["a::b", "reason"]],
            "linux": [],
            "windows": [],
        },
    )
    with pytest.raises(A21CIError, match="duplicate"):
        load_skip_policy(duplicate)
    with pytest.raises(A21CIError, match="family"):
        verify_skips(tmp_path / "missing.xml", "freebsd", duplicate)


def test_skip_verifier_rejects_duplicate_malformed_oversized_and_zero_junit(
    tmp_path: Path,
):
    policy = _policy(
        tmp_path / "policy.json",
        {"macos": [], "linux": [], "windows": []},
    )
    duplicate = _junit(
        tmp_path / "duplicate.xml",
        [
            ("tests/test_one.py", "test_same", None),
            ("tests/test_one.py", "test_same", None),
        ],
    )
    with pytest.raises(A21CIError, match="duplicate"):
        verify_skips(duplicate, "macos", policy)

    malformed = tmp_path / "malformed.xml"
    malformed.write_text("<testsuites>", encoding="utf-8")
    with pytest.raises(A21CIError, match="malformed"):
        verify_skips(malformed, "macos", policy)

    oversized = tmp_path / "oversized.xml"
    oversized.write_bytes(b"x" * (MAX_INPUT_BYTES + 1))
    with pytest.raises(A21CIError, match="size"):
        verify_skips(oversized, "macos", policy)

    zero = _junit(tmp_path / "zero.xml", [])
    with pytest.raises(A21CIError, match="zero tests"):
        verify_skips(zero, "macos", policy)


def test_driver_uses_owned_posix_and_windows_runtime_paths(tmp_path: Path):
    posix_runner = RecordingRunner()
    posix = _driver(tmp_path / "posix", runner=posix_runner)
    posix.run_compile()
    assert posix_runner.calls[0][0][0] == str(
        tmp_path / "posix" / ".venv" / "bin" / "python"
    )
    assert posix_runner.calls[0][1]["shell"] is False

    windows_runner = RecordingRunner()
    windows = _driver(
        tmp_path / "windows",
        family="windows",
        platform_name="win32",
        runner=windows_runner,
    )
    windows.run_compile()
    assert windows_runner.calls[0][0][0] == str(
        tmp_path / "windows" / ".venv" / "Scripts" / "python.exe"
    )


def test_driver_rejects_a_family_that_does_not_match_the_host(tmp_path: Path):
    with pytest.raises(A21CIError, match="does not match the host"):
        _driver(tmp_path, family="linux", platform_name="darwin")


def test_driver_sets_exact_offscreen_and_native_smoke_environments(tmp_path: Path):
    offscreen_payload = {
        "ok": True,
        "platform_family": "macos",
        "qt_platform": "offscreen",
    }
    native_payload = {
        "ok": True,
        "platform_family": "macos",
        "qt_platform": "cocoa",
    }
    runner = RecordingRunner(_completed(offscreen_payload), _completed(native_payload))
    driver = _driver(tmp_path / "mac", runner=runner)

    driver.run_smoke("offscreen")
    driver.run_smoke("native")

    assert runner.calls[0][1]["env"]["QT_QPA_PLATFORM"] == "offscreen"
    assert "QT_QPA_PLATFORM" not in runner.calls[1][1]["env"]
    assert runner.calls[0][1]["shell"] is False
    assert runner.calls[1][1]["shell"] is False


def test_linux_native_smoke_requires_xvfb_and_xcb(tmp_path: Path):
    payload = {
        "ok": True,
        "platform_family": "linux",
        "qt_platform": "xcb",
    }
    runner = RecordingRunner(_completed(payload))
    driver = _driver(
        tmp_path,
        family="linux",
        platform_name="linux",
        runner=runner,
        which=lambda name: "/usr/bin/xvfb-run" if name == "xvfb-run" else None,
    )

    driver.run_smoke("native")

    command, options = runner.calls[0]
    assert command[:2] == ["/usr/bin/xvfb-run", "-a"]
    assert command[2] == str(tmp_path / ".venv" / "bin" / "python")
    assert options["env"]["QT_QPA_PLATFORM"] == "xcb"


def test_windows_native_smoke_uses_windows_plugin_without_qt_override(
    tmp_path: Path,
):
    payload = {
        "ok": True,
        "platform_family": "windows",
        "qt_platform": "windows",
    }
    runner = RecordingRunner(_completed(payload))
    driver = _driver(
        tmp_path,
        family="windows",
        platform_name="win32",
        runner=runner,
    )

    driver.run_smoke("native")

    command, options = runner.calls[0]
    assert command[0] == str(
        tmp_path / ".venv" / "Scripts" / "python.exe"
    )
    assert "QT_QPA_PLATFORM" not in options["env"]


def test_driver_propagates_subprocess_failure(tmp_path: Path):
    runner = RecordingRunner(_completed("failed", returncode=23))
    driver = _driver(tmp_path, runner=runner)

    with pytest.raises(A21CIError, match="failed") as raised:
        driver.run_compile()

    assert raised.value.exit_code == 23


def test_sanitizer_redacts_roots_strips_streams_and_uses_fixed_allowlist(
    tmp_path: Path,
):
    results = tmp_path / "ci-results"
    results.mkdir()
    workspace = tmp_path.resolve()
    home = tmp_path / "home secret-user"
    temp = tmp_path / "temp Unicode Ω"
    runner_work = tmp_path / "runner-work"
    (results / "runtime.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "family": "macos",
                "python_version": "3.12.4",
                "owned": True,
                "secret": str(home / "token"),
            }
        ),
        encoding="utf-8",
    )
    (results / "smoke-native.json").write_text(
        json.dumps(
            {
                "ok": False,
                "platform_family": "macos",
                "qt_platform": "cocoa",
                "durability": "full",
                "font": {
                    "resolved_family": str(home / "private-font"),
                    "fixed_pitch": True,
                    "unapproved": str(temp / "secret"),
                },
                "error": str(workspace / "private.txt"),
            }
        ),
        encoding="utf-8",
    )
    (results / "pytest.xml").write_text(
        "<testsuites tests=\"1\"><testsuite name=\"suite\">"
        "<properties><property name=\"secret\" value=\"value\" /></properties>"
        "<testcase file=\"tests/test_one.py\" name=\"test_failure\" time=\"0.2\">"
        f"<failure>{workspace}/source.py {home}/token {temp}/data "
        f"{runner_work}/job</failure><system-out>SECRET OUTPUT</system-out>"
        "<system-err>SECRET ERROR</system-err></testcase></testsuite></testsuites>",
        encoding="utf-8",
    )
    (results / "arbitrary-secret.txt").write_text("must not copy", encoding="utf-8")
    sanitized = results / "sanitized"
    sanitized.mkdir()
    (sanitized / "old-arbitrary-secret.txt").write_text(
        "must not retain",
        encoding="utf-8",
    )

    report = sanitize_results(
        tmp_path,
        "macos",
        home=home,
        temp=temp,
        runner_work=runner_work,
    )

    metadata = json.loads(
        (sanitized / "artifact-metadata.json").read_text(encoding="utf-8")
    )
    assert report["errors"] == 0
    assert metadata["retention_days"] == ARTIFACT_RETENTION_DAYS == 7
    assert not (sanitized / "arbitrary-secret.txt").exists()
    assert not (sanitized / "old-arbitrary-secret.txt").exists()
    combined = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(sanitized.iterdir())
    )
    assert str(workspace) not in combined
    assert str(home) not in combined
    assert str(temp) not in combined
    assert str(runner_work) not in combined
    assert "SECRET OUTPUT" not in combined
    assert "SECRET ERROR" not in combined
    assert "<properties" not in combined
    failure = ET.parse(sanitized / "pytest.xml").find(".//failure")
    assert failure is not None
    assert "<workspace>" in (failure.text or "")
    smoke = json.loads(
        (sanitized / "smoke-native.json").read_text(encoding="utf-8")
    )
    assert smoke["font"] == {
        "fixed_pitch": True,
        "resolved_family": "<home>/private-font",
    }


def test_sanitizer_records_invalid_oversized_and_total_budget_errors(tmp_path: Path):
    results = tmp_path / "ci-results"
    results.mkdir()
    (results / "runtime.json").write_text("not-json", encoding="utf-8")
    (results / "self-check.json").write_bytes(b"x" * (MAX_INPUT_BYTES + 1))

    report = sanitize_results(tmp_path, "macos")

    assert report["errors"] == 2
    errors = json.loads(
        (results / "sanitized" / "artifact-errors.json").read_text(
            encoding="utf-8"
        )
    )
    assert {item["reason"] for item in errors["errors"]} == {
        "invalid",
        "oversized",
    }
    assert all(set(item) == {"file", "reason"} for item in errors["errors"])


def test_sanitizer_rejects_inputs_over_the_aggregate_budget(tmp_path: Path):
    results = tmp_path / "ci-results"
    results.mkdir()
    per_file = (MAX_INPUT_BYTES * 7) // 8
    for name in (
        "runtime.json",
        "self-check.json",
        "smoke-offscreen.json",
        "smoke-native.json",
        "pytest.xml",
    ):
        (results / name).write_bytes(b"x" * per_file)

    report = sanitize_results(tmp_path, "macos")

    assert report["files"] == 0
    assert report["errors"] == 1
    errors = json.loads(
        (results / "sanitized" / "artifact-errors.json").read_text(
            encoding="utf-8"
        )
    )
    assert errors["errors"] == [
        {"file": "<aggregate>", "reason": "total_budget"}
    ]


def test_checked_skip_policy_has_unique_entries_for_supported_families():
    policy = load_skip_policy(Path("ci/a21-skip-policy.json"))

    assert set(policy) == {"macos", "linux", "windows"}
    assert all(policy.values())
    for entries in policy.values():
        assert len(entries) == len({node_id for node_id, _reason in entries})
