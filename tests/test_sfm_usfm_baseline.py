from __future__ import annotations

from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline


def test_loads_the_vendored_baseline_with_known_markers():
    sheet = load_usfm_baseline()

    markers = {record.marker for record in sheet.records}
    assert "id" in markers
    assert "v" in markers
    assert "c" in markers
    assert len(sheet.records) > 100


def test_baseline_load_is_cached_across_calls():
    first = load_usfm_baseline()
    second = load_usfm_baseline()

    assert first is second


def test_id_record_has_expected_structural_fields():
    sheet = load_usfm_baseline()

    id_record = next(record for record in sheet.records if record.marker == "id")
    keys = {entry.key for entry in id_record.entries}
    assert "StyleType" in keys
