from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.a22_ci import (
    ARTIFACT_RETENTION_DAYS,
    MAX_FAMILY_BYTES,
    MAX_SUITE_BYTES,
    A22CIDriver,
    A22CIError,
    sanitize_results,
    validate_sustained_result,
)


FAMILIES = (
    "daily_editing",
    "format_integrity",
    "regex_replacement",
    "session_lifecycle",
)


def _suite(*, state: str = "PASS") -> dict[str, object]:
    owned = {
        "documents": 0,
        "views": 0,
        "active_workers": 0,
        "active_tasks": 0,
        "queued_tasks": 0,
        "result_stores": 0,
        "replacement_plans": 0,
        "snapshots": 0,
        "temp_paths": 0,
    }
    families = []
    evaluations = []
    for family in FAMILIES:
        family_state = state if family == FAMILIES[0] else "PASS"
        timing = {
            "daily_editing": "daily_cycle_ms",
            "format_integrity": "format_cycle_ms",
            "regex_replacement": "regex_cycle_ms",
            "session_lifecycle": "lifecycle_cycle_ms",
        }[family]
        families.append(
            {
                "schema": 2,
                "family": family,
                "profile": "a22-v1",
                "state": family_state,
                "warmup_cycles": 1,
                "measured_cycles": 5,
                "checkpoints": [
                    {
                        "cycle": cycle,
                        "metrics": {
                            "rss_mib": 100.0,
                            "cache_used_mib": 1.0,
                            timing: 3.0,
                        },
                        "owned_counts": owned,
                        "unavailable_probes": [],
                    }
                    for cycle in range(1, 6)
                ],
                "facts": {
                    "integrity_ok": family_state == "PASS",
                    "cleanup_ok": True,
                    "cycles_completed": 6,
                },
                "messages": [] if family_state == "PASS" else ["private failure"],
            }
        )
        evaluations.append(
            {
                "subject": family,
                "state": family_state,
                "messages": [] if family_state == "PASS" else ["private failure"],
            }
        )
    return {
        "schema": 2,
        "profile": "a22-v1",
        "execution_class": "hosted",
        "state": state,
        "host": {
            "architecture": "arm64",
            "platform": "darwin",
            "physical_cores": 8,
            "physical_memory": 16 << 30,
            "python_version": "3.12.4",
            "qt_version": "6.11.2",
            "corpus_schema": 2,
            "git_commit": "abcdef123456",
            "contended": False,
        },
        "families": families,
        "evaluations": evaluations,
    }


def _write_runtime(root: Path) -> Path:
    runtime = root / ".venv" / "bin" / "python"
    runtime.parent.mkdir(parents=True)
    runtime.write_bytes(b"")
    (root / ".venv" / ".uniti-runtime.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "owner": "uniti-editor",
                "healthy": True,
                "mode": "source",
                "environment_path": str(root / ".venv"),
            }
        ),
        encoding="utf-8",
    )
    return runtime


class _Runner:
    def __init__(self, payload: dict[str, object], *, returncode: int = 0) -> None:
        self.payload = payload
        self.returncode = returncode
        self.calls = []

    def __call__(self, command, **options):
        self.calls.append((list(command), dict(options)))
        output = Path(command[command.index("--output") + 1])
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(self.payload), encoding="utf-8")
        return subprocess.CompletedProcess(command, self.returncode, "", "")


def test_driver_runs_hosted_five_cycle_profile_through_owned_runtime(tmp_path: Path):
    runtime = _write_runtime(tmp_path)
    runner = _Runner(_suite())
    driver = A22CIDriver(
        tmp_path,
        "macos",
        platform_name="darwin",
        runner=runner,
        environ={"QT_QPA_PLATFORM": "inherited", "KEEP": "yes"},
    )

    result = driver.run()

    command, options = runner.calls[0]
    assert command[0] == str(runtime)
    assert command[1:6] == [
        "scripts/performance_suite.py",
        "--suite",
        "sustained",
        "--profile",
        "hosted",
    ]
    assert options["env"]["QT_QPA_PLATFORM"] == "offscreen"
    assert options["shell"] is False
    assert result["state"] == "PASS"
    evidence = tmp_path / "ci-results" / "sustained-hosted.json"
    assert evidence.is_file()
    assert evidence.stat().st_size <= MAX_SUITE_BYTES == 8 << 20
    assert [path.name for path in evidence.parent.glob("sustained-*.json")] == [
        "sustained-hosted.json"
    ]


def test_driver_accepts_the_standard_posix_venv_python_symlink(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    runtime = _write_runtime(tmp_path)
    original_is_symlink = Path.is_symlink

    def is_symlink(path: Path) -> bool:
        if path == runtime:
            return True
        return original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", is_symlink)

    driver = A22CIDriver(
        tmp_path,
        "macos",
        platform_name="darwin",
        runner=_Runner(_suite()),
    )

    assert driver.runtime_python == runtime


def test_driver_accepts_bootstrap_metadata_in_the_owned_runtime_manifest(
    tmp_path: Path,
):
    runtime = _write_runtime(tmp_path)
    marker = tmp_path / ".venv" / ".uniti-runtime.json"
    payload = json.loads(marker.read_text(encoding="utf-8"))
    payload.update(
        {
            "environment_id": "owned-runtime-id",
            "runtime": {"implementation": "CPython"},
            "updated_at": "2026-09-05T00:00:00Z",
        }
    )
    marker.write_text(json.dumps(payload), encoding="utf-8")

    driver = A22CIDriver(
        tmp_path,
        "macos",
        platform_name="darwin",
        runner=_Runner(_suite()),
    )

    assert driver.runtime_python == runtime


def test_validator_rejects_nonpass_private_unknown_duplicate_and_oversized():
    passing = json.dumps(_suite(), separators=(",", ":")).encode()
    assert validate_sustained_result(passing, require_pass=True)["state"] == "PASS"

    failing = json.dumps(_suite(state="FAIL")).encode()
    with pytest.raises(A22CIError, match="PASS"):
        validate_sustained_result(failing, require_pass=True)

    private = _suite()
    private["families"][0]["facts"]["private"] = "/Users/name/private.txt"
    with pytest.raises(A22CIError, match="private"):
        validate_sustained_result(json.dumps(private).encode(), require_pass=True)
    private["families"][0]["facts"]["private"] = "(?P<secret>needle)"
    with pytest.raises(A22CIError, match="private"):
        validate_sustained_result(json.dumps(private).encode(), require_pass=True)
    private["families"][0]["facts"]["private"] = "document body words"
    with pytest.raises(A22CIError, match="private"):
        validate_sustained_result(json.dumps(private).encode(), require_pass=True)

    unknown = json.dumps(_suite()).replace('"schema": 2', '"schema": 2, "extra": 0', 1)
    duplicate = json.dumps(_suite()).replace('"schema": 2', '"schema": 2, "schema": 2', 1)
    for raw, message in ((unknown, "fields"), (duplicate, "duplicate")):
        with pytest.raises(A22CIError, match=message):
            validate_sustained_result(raw.encode(), require_pass=True)
    with pytest.raises(A22CIError, match="size"):
        validate_sustained_result(b"x" * (MAX_SUITE_BYTES + 1), require_pass=True)


def test_failure_sanitizer_writes_only_bounded_schema_summary(tmp_path: Path):
    results = tmp_path / "ci-results"
    results.mkdir()
    payload = _suite(state="FAIL")
    payload["families"][0]["messages"] = [
        f"failure in {tmp_path}/private.txt with (?P<secret>needle) document body"
    ]
    payload["evaluations"][0]["messages"] = list(
        payload["families"][0]["messages"]
    )
    (results / "sustained-hosted.json").write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    report = sanitize_results(tmp_path, "macos")

    destination = results / "sanitized"
    metadata = json.loads(
        (destination / "artifact-metadata.json").read_text(encoding="utf-8")
    )
    summary = json.loads(
        (destination / "sustained-hosted.json").read_text(encoding="utf-8")
    )
    assert report == {"schema": 1, "family": "macos", "files": 1, "errors": 0}
    assert metadata["retention_days"] == ARTIFACT_RETENTION_DAYS == 7
    assert set(summary) == {
        "schema",
        "profile",
        "execution_class",
        "state",
        "families",
        "evaluations",
    }
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in destination.iterdir()
    )
    assert str(tmp_path) not in combined
    assert "needle" not in combined
    assert "document body" not in combined
    assert len(combined.encode()) <= MAX_FAMILY_BYTES == 2 << 20


def test_sanitizer_never_copies_successful_result(tmp_path: Path):
    results = tmp_path / "ci-results"
    results.mkdir()
    (results / "sustained-hosted.json").write_text(
        json.dumps(_suite()),
        encoding="utf-8",
    )

    report = sanitize_results(tmp_path, "macos")

    assert report["files"] == 0
    assert report["errors"] == 1
    assert not (results / "sanitized" / "sustained-hosted.json").exists()


def test_driver_cli_help_does_not_require_project_imports(tmp_path: Path):
    completed = subprocess.run(
        [sys.executable, "-S", str(Path("scripts/a22_ci.py").resolve()), "--help"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "A22 sustained" in completed.stdout
