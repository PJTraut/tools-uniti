import json
import sys
from pathlib import Path

from uniti.app.diagnostics import diagnostics_snapshot
from uniti.core.document import Document


def test_diagnostics_snapshot_is_json_serializable_and_reports_runtime():
    snapshot = diagnostics_snapshot()
    assert snapshot["uniti"]["display_version"].startswith("v0.001a")
    assert snapshot["runtime"]["python"].startswith(f"{sys.version_info.major}.")
    assert snapshot["memory"]["physical_bytes"] >= 0
    assert snapshot["documents"] == []
    json.dumps(snapshot)


def test_diagnostics_snapshot_reports_open_document_state(tmp_path: Path):
    path = tmp_path / "diag.txt"
    path.write_text("abc\ndef", encoding="utf-8")
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
