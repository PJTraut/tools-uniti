import os
from pathlib import Path

from uniti.app.capabilities import (
    CapabilityStatus,
    probe_filesystem,
    probe_qt,
    probe_runtime,
)
from uniti.app.paths import AppPaths
from uniti.resources import MemorySnapshot


class ReducedProbeAdapter:
    def sync_file(self, _descriptor: int) -> None:
        return None

    def replace(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)

    def sync_directory(self, _directory: Path) -> bool:
        return False


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


def test_filesystem_probe_reports_directory_sync_and_aggregate_durability(
    tmp_path: Path,
):
    paths = _paths(tmp_path)
    paths.ensure()

    results = probe_filesystem(paths, adapter=ReducedProbeAdapter())

    assert results["directory_sync"].status is CapabilityStatus.UNAVAILABLE
    assert results["durability"].status is CapabilityStatus.AVAILABLE
    assert results["durability"].details["level"] == "file_synced"
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


def test_runtime_probe_reports_unknown_when_memory_cannot_be_measured(
    tmp_path: Path, monkeypatch
):
    from uniti.app import capabilities

    paths = _paths(tmp_path)
    paths.ensure()
    monkeypatch.setattr(capabilities, "probe_memory", lambda: MemorySnapshot(0, 0))

    result = capabilities.probe_runtime(paths)["memory"]

    assert result.status is CapabilityStatus.UNKNOWN


def test_qt_probe_reports_the_same_concrete_font_as_the_editor_policy():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.font_policy import resolve_editor_font

    app = QApplication.instance() or QApplication([])
    resolution = resolve_editor_font()

    result = probe_qt(app)["font"]

    assert result.status is CapabilityStatus.AVAILABLE
    assert result.details == resolution.as_dict()


def test_qt_probe_rejects_a_fixed_font_without_required_glyph_coverage(monkeypatch):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from uniti.app import capabilities
    from uniti.ui.font_policy import FontResolution

    app = QApplication.instance() or QApplication([])
    degraded = FontResolution(
        QFont("Fallback"),
        "Fallback",
        "Fallback",
        True,
        True,
        False,
        True,
    )
    monkeypatch.setattr(capabilities, "resolve_editor_font", lambda: degraded)

    result = capabilities.probe_qt(app)["font"]

    assert result.status is CapabilityStatus.UNAVAILABLE
    assert "coverage" in result.reason
    assert result.details == degraded.as_dict()
