from pathlib import Path

from uniti.core.byte_source import ByteSource
from uniti.core.eol import analyze_eol


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
