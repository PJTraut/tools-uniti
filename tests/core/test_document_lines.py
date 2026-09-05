from pathlib import Path

import pytest

from uniti.core.byte_source import ByteSource
from uniti.core.document_lines import DocumentLineIndex
from uniti.core.offsets import OffsetMapper
from uniti.core.pieces import EditStore, PieceTable
from uniti.resources import MemorySnapshot, ResourceManager


def make_table(path: Path, text: str, *, checkpoint_bytes: int = 8):
    path.write_text(text, encoding="utf-8", newline="")
    source = ByteSource.open(path)
    mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=checkpoint_bytes)
    table = PieceTable(source, "utf-8", mapper, EditStore())
    return source, mapper, table


@pytest.mark.parametrize(
    ("text", "starts"),
    [
        ("a\nb\n", [0, 2, 4]),
        ("a\r\nb\r\n", [0, 3, 6]),
        ("a\rb\r", [0, 2, 4]),
        ("a\r\nb\nc\rd", [0, 3, 5, 7]),
    ],
)
def test_document_line_index_tracks_all_eol_forms(tmp_path: Path, text: str, starts: list[int]):
    source, _, table = make_table(tmp_path / "eol.txt", text)
    try:
        index = DocumentLineIndex(table, chunk_chars=2)
        assert index.total_lines() == len(starts)
        assert [index.line_start(i) for i in range(len(starts))] == starts
    finally:
        source.close()


def test_crlf_split_across_iteration_window_is_one_eol(tmp_path: Path):
    source, _, table = make_table(tmp_path / "split.txt", "x\r\ny")
    try:
        index = DocumentLineIndex(table, chunk_chars=2)
        assert index.total_lines() == 2
        assert index.line_start(1) == 3
        assert index.line_for_char(2) == 0
        assert index.line_for_char(3) == 1
    finally:
        source.close()


def test_crlf_split_across_source_and_edit_pieces_is_one_eol(tmp_path: Path):
    source, _, table = make_table(tmp_path / "pieces.txt", "a\rb")
    try:
        table.insert(2, "\n")
        index = DocumentLineIndex(table, chunk_chars=1)
        assert table.read(0, table.total_chars()) == "a\r\nb"
        assert index.total_lines() == 2
        assert index.line_start(1) == 3
    finally:
        source.close()


def test_line_index_is_progressive_for_early_lookup(tmp_path: Path):
    source, mapper, table = make_table(tmp_path / "large.txt", "abc\n" * 50_000, checkpoint_bytes=32)
    try:
        index = DocumentLineIndex(table, chunk_chars=32)
        assert index.line_start(3) == 12
        assert not index.complete
        assert index.indexed_char_end <= 64
        assert not mapper.complete
    finally:
        source.close()


def test_newline_dense_index_keeps_only_bounded_detail(tmp_path: Path):
    source, _, table = make_table(tmp_path / "dense.txt", "\n" * 2_000_000)
    try:
        index = DocumentLineIndex(
            table,
            chunk_chars=65_536,
            detail_budget_bytes=2 << 20,
        )

        assert index.total_lines() == 2_000_001
        assert index.line_start(1_900_000) == 1_900_000
        assert index.summary_bytes < 1 << 20
        assert index.resident_detail_bytes <= 2 << 20
    finally:
        source.close()


def test_document_line_details_use_shared_disposable_cache(tmp_path: Path):
    source, _, table = make_table(tmp_path / "cached-lines.txt", "line\n" * 1000)
    manager = ResourceManager(
        max_workers=1,
        initial_snapshot=MemorySnapshot(16 << 30, 8 << 30),
    )
    try:
        index = DocumentLineIndex(
            table,
            chunk_chars=128,
            resource_manager=manager,
            cache_owner="document",
        )
        index.total_lines()

        assert manager.get_cache("document", ("line-detail", 0)) is not None
        manager.evict_owner("document")
        assert index.resident_detail_bytes == 0
    finally:
        manager.shutdown()
        source.close()


def test_invalidate_rebuilds_only_from_containing_chunk(tmp_path: Path):
    source, _, table = make_table(tmp_path / "invalidate.txt", "aa\nbb\ncc\ndd")
    try:
        index = DocumentLineIndex(table, chunk_chars=4)
        assert index.total_lines() == 4
        table.insert(5, "\nX")
        index.invalidate_from_char(5)
        assert index.indexed_char_end == 4
        assert index.line_start(0) == 0
        assert index.line_start(1) == 3
        assert index.total_lines() == 5
        assert [index.line_start(i) for i in range(5)] == [0, 3, 6, 8, 11]
    finally:
        source.close()


def test_document_line_end_returns_content_end_without_eol(tmp_path: Path):
    from uniti.core.document import Document

    path = tmp_path / "line-end.txt"
    path.write_bytes(b"aa\r\nbb\ncc\rdd")
    with Document.open(path) as document:
        assert [document.line_end(i) for i in range(4)] == [2, 6, 9, 12]


def test_document_line_terminator_never_reads_more_than_two_characters(
    tmp_path: Path,
    monkeypatch,
):
    from uniti.core.document import Document

    path = tmp_path / "giant-line.txt"
    path.write_text(
        ("x" * (3 << 20)) + "\r\ntail",
        encoding="utf-8",
        newline="",
    )
    with Document.open(path) as document:
        assert document.line_start(1) == (3 << 20) + 2
        observed_widths: list[int] = []
        original_read = document._piece_table.read

        def bounded_read(start, end, *args, **kwargs):
            observed_widths.append(end - start)
            return original_read(start, end, *args, **kwargs)

        monkeypatch.setattr(document._piece_table, "read", bounded_read)

        assert document.line_terminator(0) == "\r\n"
        assert observed_widths
        assert max(observed_widths) <= 2
