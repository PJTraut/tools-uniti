from pathlib import Path

import pytest

from uniti.core.byte_source import ByteSource
from uniti.core.eol import EOLAnalysisCancelled, analyze_eol


def report(tmp_path: Path, payload: bytes, *, chunk_size: int = 1 << 20):
    path = tmp_path / "eol.txt"
    path.write_bytes(payload)
    with ByteSource.open(path) as source:
        return analyze_eol(source, chunk_size=chunk_size)


def test_lf_file(tmp_path: Path):
    result = report(tmp_path, b"a\nb\n")
    assert (result.lf, result.crlf, result.cr, result.kind) == (2, 0, 0, "LF")


def test_mixed_file(tmp_path: Path):
    result = report(tmp_path, b"a\r\nb\nc\r")
    assert (result.lf, result.crlf, result.cr, result.kind) == (1, 1, 1, "MIXED")


def test_no_eol(tmp_path: Path):
    result = report(tmp_path, b"single line")
    assert result.kind == "NONE"


def test_crlf_split_across_chunks_counts_once(tmp_path: Path):
    result = report(tmp_path, b"abc\r\ndef", chunk_size=4)
    assert (result.lf, result.crlf, result.cr, result.kind) == (0, 1, 0, "CRLF")


def test_utf16le_crlf_is_counted_as_crlf(tmp_path: Path):
    path = tmp_path / "utf16le.txt"
    path.write_bytes("a\r\nb\r\n".encode("utf-16-le"))
    with ByteSource.open(path) as source:
        result = analyze_eol(source, chunk_size=3, encoding="utf-16-le")
    assert (result.lf, result.crlf, result.cr, result.kind) == (0, 2, 0, "CRLF")


def test_utf16be_mixed_eol_is_decoded_before_counting(tmp_path: Path):
    path = tmp_path / "utf16be.txt"
    path.write_bytes("a\r\nb\nc\r".encode("utf-16-be"))
    with ByteSource.open(path) as source:
        result = analyze_eol(source, chunk_size=5, encoding="utf-16-be")
    assert (result.lf, result.crlf, result.cr, result.kind) == (1, 1, 1, "MIXED")


def test_utf32le_crlf_survives_arbitrary_byte_chunks(tmp_path: Path):
    path = tmp_path / "utf32le.txt"
    path.write_bytes("a\r\nb\r\n".encode("utf-32-le"))
    with ByteSource.open(path) as source:
        result = analyze_eol(source, chunk_size=5, encoding="utf-32-le")
    assert (result.lf, result.crlf, result.cr, result.kind) == (0, 2, 0, "CRLF")


def test_analysis_reports_monotonic_scanned_bytes(tmp_path: Path):
    path = tmp_path / "progress.txt"
    path.write_bytes(b"line\n" * 100)
    updates: list[tuple[int, int]] = []

    with ByteSource.open(path) as source:
        result = analyze_eol(
            source,
            chunk_size=31,
            progress=lambda completed, total: updates.append((completed, total)),
        )

    assert result.kind == "LF"
    assert updates[0] == (0, path.stat().st_size)
    assert updates[-1] == (path.stat().st_size, path.stat().st_size)
    assert [completed for completed, _ in updates] == sorted(
        completed for completed, _ in updates
    )


def test_analysis_checks_cancellation_between_chunks(tmp_path: Path):
    path = tmp_path / "cancel.txt"
    path.write_bytes(b"line\n" * 100)
    cancelled = False

    def progress(completed: int, _total: int) -> None:
        nonlocal cancelled
        if completed:
            cancelled = True

    with ByteSource.open(path) as source:
        with pytest.raises(EOLAnalysisCancelled, match="cancelled"):
            analyze_eol(
                source,
                chunk_size=31,
                cancelled=lambda: cancelled,
                progress=progress,
            )
