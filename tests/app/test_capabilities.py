from pathlib import Path

from uniti.app.capabilities import (
    CapabilityStatus,
    probe_filesystem,
    probe_runtime,
)
from uniti.app.paths import AppPaths


def _paths(tmp_path: Path) -> AppPaths:
    return AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )


def test_filesystem_probe_is_bounded_to_temp_and_cleans_fixtures(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.ensure()

    results = probe_filesystem(paths)

    assert results["write"].status is CapabilityStatus.AVAILABLE
    assert results["fsync"].status in {
        CapabilityStatus.AVAILABLE,
        CapabilityStatus.UNAVAILABLE,
    }
    assert results["atomic_replace"].status is CapabilityStatus.AVAILABLE
    assert results["mmap"].status in {
        CapabilityStatus.AVAILABLE,
        CapabilityStatus.UNAVAILABLE,
    }
    assert list(paths.temp_dir.iterdir()) == []


def test_runtime_probe_reports_identity_memory_cpu_disk_and_marker(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.ensure()
    marker = tmp_path / ".uniti-runtime.json"
    marker.write_text('{"schema":1,"owner":"uniti-editor","healthy":true}', encoding="utf-8")

    results = probe_runtime(paths, marker_path=marker)

    assert results["python"].status is CapabilityStatus.AVAILABLE
    assert results["memory"].details["physical_bytes"] >= 0
    assert results["cpu"].details["logical_count"] >= 1
    assert results["disk"].details["free_bytes"] >= 0
    assert results["environment_marker"].status is CapabilityStatus.AVAILABLE


def test_runtime_probe_marks_invalid_ownership_marker_unavailable(tmp_path: Path):
    paths = _paths(tmp_path)
    paths.ensure()
    marker = tmp_path / ".uniti-runtime.json"
    marker.write_text('{"schema":1,"owner":"someone-else"}', encoding="utf-8")

    result = probe_runtime(paths, marker_path=marker)["environment_marker"]

    assert result.status is CapabilityStatus.UNAVAILABLE
    assert "ownership" in result.reason
