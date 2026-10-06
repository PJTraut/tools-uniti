from __future__ import annotations

from uniti.core.environment_findings import FindingSeverity
from uniti.core.environments.sfm.usfmtc_adapter import validate_with_usfmtc


def test_empty_text_yields_no_findings():
    assert validate_with_usfmtc("") == ()


def test_well_formed_usfm_yields_no_findings():
    text = "\\id GEN\n\\usfm 3.1\n\\c 1\n\\v 1 In the beginning God created the heavens and the earth.\n"

    assert validate_with_usfmtc(text) == ()


def test_unknown_marker_is_reported():
    text = "\\id GEN\n\\usfm 3.1\n\\c 1\n\\v 1 Text \\zzzcustom stuff\\zzzcustom* here.\n"

    findings = validate_with_usfmtc(text)

    assert len(findings) == 1
    assert findings[0].severity == FindingSeverity.WARNING
    assert findings[0].code == "usfm.usfmtc-reference"
    assert "zzzcustom" in findings[0].message


def test_findings_span_the_whole_document_by_design(tmp_path):
    text = "\\id GEN\n\\usfm 3.1\n\\c 1\n\\v 1 Text \\zzzcustom stuff\\zzzcustom* here.\n"

    findings = validate_with_usfmtc(text)

    assert findings[0].start == 0
    assert findings[0].end == len(text)
