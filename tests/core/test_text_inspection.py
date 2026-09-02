from pathlib import Path

from uniti.core.byte_source import ByteSource
from uniti.core.text_format import encoding_profile
from uniti.core.text_inspection import inspect_source, preview_source


def inspect(tmp_path: Path, payload: bytes, *, override=None):
    path = tmp_path / "sample.txt"
    path.write_bytes(payload)
    with ByteSource.open(path) as source:
        return inspect_source(source, override=override)


def test_low_confidence_legacy_detection_requires_confirmation(tmp_path):
    result = inspect(tmp_path, b"Price \x96 10")
    assert result.encoding.suggested.key == "windows-1252"
    assert result.encoding.confidence < 0.75
    assert result.encoding.requires_confirmation is True
    assert any("confidence" in reason.lower() for reason in result.encoding.reasons)


def test_mixed_eol_is_separate_from_high_confidence_encoding(tmp_path):
    result = inspect(tmp_path, b"a\r\nb\nc\r")
    assert result.encoding.suggested.key == "utf-8"
    assert result.encoding.requires_confirmation is False
    assert (result.eol.kind, result.eol.lf, result.eol.crlf, result.eol.cr) == (
        "MIXED",
        1,
        1,
        1,
    )


def test_preview_reports_malformed_bytes_for_selected_profile(tmp_path):
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"A\xffZ")
    with ByteSource.open(path) as source:
        preview = preview_source(source, encoding_profile("utf-8"))
    assert preview.text == "A\ufffdZ"
    assert preview.invalid_bytes[0].raw == b"\xff"


def test_malformed_preview_requires_confirmation_even_with_override(tmp_path):
    result = inspect(
        tmp_path,
        b"A\xffZ",
        override=encoding_profile("utf-8"),
    )
    assert result.encoding.confidence == 1.0
    assert result.encoding.malformed_preview[0].raw == b"\xff"
    assert result.encoding.requires_confirmation is True
    assert any("malformed" in reason.lower() for reason in result.encoding.reasons)


def test_bom_is_removed_only_for_matching_exact_profile(tmp_path):
    path = tmp_path / "bom.txt"
    path.write_bytes(b"\xff\xfe" + "A\r\nB".encode("utf-16-le"))
    with ByteSource.open(path) as source:
        preview = preview_source(source, encoding_profile("utf-16-le-bom"))
    assert preview.text == "A\r\nB"
    assert preview.invalid_bytes == ()


def test_selected_profile_with_conflicting_bom_requires_confirmation(tmp_path):
    result = inspect(
        tmp_path,
        b"\xef\xbb\xbfhello",
        override=encoding_profile("utf-8"),
    )
    assert result.encoding.contradictory is True
    assert result.encoding.requires_confirmation is True
    assert any("contradictory" in reason.lower() for reason in result.encoding.reasons)


def test_preview_is_bounded_without_reporting_split_character_as_invalid(tmp_path):
    path = tmp_path / "bounded.txt"
    path.write_bytes(("A" * 7 + "€" + "tail").encode("utf-8"))
    with ByteSource.open(path) as source:
        preview = preview_source(
            source,
            encoding_profile("utf-8"),
            max_bytes=8,
        )
    assert preview.text == "A" * 7
    assert preview.invalid_bytes == ()
    assert preview.truncated is True


def test_bounded_inspection_marks_eol_incomplete_and_reports_extent(tmp_path):
    path = tmp_path / "large.txt"
    path.write_bytes(b"a\n" * 100_000)

    with ByteSource.open(path) as source:
        inspection = inspect_source(source, eol_max_bytes=65_536)

    assert inspection.eol_complete is False
    assert inspection.eol_scanned_bytes == 65_536
    assert inspection.eol.kind == "LF"


def test_default_inspection_reports_complete_full_eol_evidence(tmp_path):
    path = tmp_path / "complete.txt"
    path.write_bytes(b"a\n" * 100_000)

    with ByteSource.open(path) as source:
        inspection = inspect_source(source)

    assert inspection.eol_complete is True
    assert inspection.eol_scanned_bytes == path.stat().st_size
