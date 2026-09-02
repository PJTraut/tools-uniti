from pathlib import Path

from uniti.core.byte_source import ByteSource
from uniti.core.lines import LineIndex


def test_line_index_records_mixed_line_starts(tmp_path: Path):
    path = tmp_path / "lines.txt"
    path.write_bytes(b"a\r\nb\nc\rd")
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8", chunk_size=2)
        assert index.line_start(0) == 0
        assert index.line_start(1) == 3
        assert index.line_start(2) == 5
        assert index.line_start(3) == 7


def test_line_offsets_use_bounded_chunk_details(tmp_path: Path):
    path = tmp_path / "lines.txt"
    path.write_bytes(b"\n" * 2_000_000)
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8", detail_budget_bytes=2 << 20)
        assert index.total_lines() == 2_000_001
        assert index.line_start(1_900_000) == 1_900_000
        assert index.summary_bytes < 1 << 20
        assert index.resident_detail_bytes <= 2 << 20


def test_crlf_crossing_decode_windows_is_one_line_ending(tmp_path: Path):
    path = tmp_path / "crlf.txt"
    path.write_bytes(b"ab\r\ncd")
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8", chunk_size=3)
        assert index.total_lines() == 2
        assert index.line_start(1) == 4


def test_utf16_and_utf32_line_offsets_are_byte_accurate(tmp_path: Path):
    cases = [
        ("utf-16-le", "a\r\nb\nc"),
        ("utf-32-be", "a\r\nb\nc"),
    ]
    for encoding, text in cases:
        path = tmp_path / f"{encoding}.txt"
        path.write_bytes(text.encode(encoding))
        newline_1 = len("a\r\n".encode(encoding))
        newline_2 = len("a\r\nb\n".encode(encoding))
        with ByteSource.open(path) as source:
            index = LineIndex(source, encoding, chunk_size=5)
            assert index.total_lines() == 3
            assert index.line_start(1) == newline_1
            assert index.line_start(2) == newline_2


def test_bom_file_line_zero_starts_after_bom(tmp_path: Path):
    path = tmp_path / "bom-lines.txt"
    path.write_bytes(b"\xef\xbb\xbf" + b"a\nb")
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8-sig", chunk_size=2)
        assert index.line_start(0) == 3
        assert index.line_start(1) == 5


def test_line_for_byte_uses_latest_line_start(tmp_path: Path):
    path = tmp_path / "lookup.txt"
    path.write_bytes(b"aa\nbbb\ncccc")
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8", chunk_size=3)
        assert index.line_for_byte(0) == 0
        assert index.line_for_byte(4) == 1
        assert index.line_for_byte(8) == 2


def test_empty_file_has_one_empty_line(tmp_path: Path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8")
        assert index.complete
        assert index.total_lines() == 1
        assert index.line_start(0) == 0


def test_early_line_lookup_does_not_index_entire_source(tmp_path: Path):
    path = tmp_path / "lazy-lines.txt"
    path.write_bytes(b"a\n" * 50_000)
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8", chunk_size=128)
        assert index.line_start(3) == 6
        assert index.indexed_byte_end < source.size
        assert not index.complete


def test_line_for_byte_resolves_pending_cr_at_window_end(tmp_path: Path):
    path = tmp_path / "pending-cr.txt"
    path.write_bytes(b"a\rb")
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8", chunk_size=2)
        assert index.line_for_byte(2) == 1


def test_line_for_byte_keeps_boundary_before_lf_on_previous_line(tmp_path: Path):
    path = tmp_path / "pending-crlf.txt"
    path.write_bytes(b"a\r\nb")
    with ByteSource.open(path) as source:
        index = LineIndex(source, "utf-8", chunk_size=2)
        assert index.line_for_byte(2) == 0
        assert index.line_for_byte(3) == 1
