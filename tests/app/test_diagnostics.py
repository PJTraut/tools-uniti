import json
import sys
from datetime import date
from pathlib import Path

import uniti

from uniti.app.diagnostics import diagnostics_snapshot
from uniti.app.dogfood_store import StoreFailureCode, StoreStatus
from uniti.core.document import Document
from uniti.resources import MemorySnapshot, ResourceManager


def test_diagnostics_snapshot_is_json_serializable_and_reports_runtime():
    snapshot = diagnostics_snapshot()
    assert snapshot["uniti"]["display_version"] == uniti.__display_version__
    assert snapshot["runtime"]["python"].startswith(f"{sys.version_info.major}.")
    assert snapshot["memory"]["physical_bytes"] >= 0
    assert snapshot["documents"] == []
    json.dumps(snapshot)


def test_diagnostics_snapshot_reports_open_document_state(tmp_path: Path):
    path = tmp_path / "diag.txt"
    path.write_bytes(b"abc\ndef")
    with Document.open(path) as document:
        document.insert(1, "X")
        snapshot = diagnostics_snapshot([document])
    item = snapshot["documents"][0]
    assert item["path"] == str(path)
    assert item["source_size_bytes"] == 7
    assert item["detected_encoding"] == "utf-8"
    assert item["output_encoding"] == "utf-8"
    assert item["modified"] is True
    assert isinstance(item["offset_index_complete"], bool)
    assert isinstance(item["line_index_complete"], bool)


def test_diagnostics_includes_supplied_startup_snapshot_without_mutating_it():
    startup = {
        "session_id": "abc",
        "capabilities": {"mmap": {"status": "available"}},
    }

    snapshot = diagnostics_snapshot((), startup_snapshot=startup)

    assert snapshot["startup"] == startup
    assert startup == {
        "session_id": "abc",
        "capabilities": {"mmap": {"status": "available"}},
    }


def test_diagnostics_reports_host_resources_cache_workers_and_tasks():
    manager = ResourceManager(
        max_workers=2,
        initial_snapshot=MemorySnapshot(16 << 30, 8 << 30),
    )
    try:
        snapshot = diagnostics_snapshot(resource_manager=manager)

        assert snapshot["host"]["logical_cores"] >= 1
        assert snapshot["resources"]["state"] in {
            "normal",
            "busy",
            "constrained",
            "critical",
        }
        assert snapshot["resources"]["cache_budget_bytes"] > 0
        assert snapshot["resources"]["active_worker_limit"] >= 1
        assert snapshot["tasks"]["background_paused"] is False
        assert isinstance(snapshot["tasks"]["items"], list)
        json.dumps(snapshot)
    finally:
        manager.shutdown()


def test_diagnostics_reports_bounded_dogfood_status_without_storage_paths(
    tmp_path: Path,
):
    private_root = tmp_path / "private-dogfood-root"
    status = StoreStatus(
        False,
        3,
        4096,
        date(2026, 9, 1),
        date(2026, 9, 5),
        StoreFailureCode.WRITE_FAILED,
    )

    snapshot = diagnostics_snapshot(dogfood_status=status)

    assert snapshot["dogfood"] == {
        "available": False,
        "segment_count": 3,
        "byte_count": 4096,
        "oldest_day": "2026-09-01",
        "newest_day": "2026-09-05",
        "last_failure": "write_failed",
    }
    encoded = json.dumps(snapshot)
    assert str(private_root) not in encoded
    assert "current.json.gz" not in encoded
