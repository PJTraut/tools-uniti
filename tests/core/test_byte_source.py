from pathlib import Path

import pytest

from uniti.core.byte_source import ByteSource


def test_byte_source_reads_requested_range(tmp_path: Path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"0123456789")
    with ByteSource.open(path) as source:
        assert source.size == 10
        assert source.read(3, 4) == b"3456"


def test_byte_source_iterates_bounded_chunks(tmp_path: Path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"abcdefghij")
    with ByteSource.open(path) as source:
        assert list(source.iter_chunks(start=2, end=9, chunk_size=3)) == [
            b"cde",
            b"fgh",
            b"i",
        ]


def test_empty_file_is_supported(tmp_path: Path):
    path = tmp_path / "empty.txt"
    path.write_bytes(b"")
    with ByteSource.open(path) as source:
        assert source.size == 0
        assert source.read(0, 0) == b""
        assert list(source.iter_chunks()) == []


@pytest.mark.parametrize("start,length", [(-1, 1), (0, -1), (8, 3)])
def test_invalid_read_ranges_raise(tmp_path: Path, start: int, length: int):
    path = tmp_path / "data.bin"
    path.write_bytes(b"0123456789")
    with ByteSource.open(path) as source:
        with pytest.raises(ValueError):
            source.read(start, length)


def test_sparse_file_supports_offsets_above_one_gib(tmp_path: Path):
    path = tmp_path / "large.bin"
    marker_offset = (1 << 30) + 12345
    try:
        with path.open("wb") as handle:
            handle.seek(marker_offset)
            handle.write(b"UNITI")
    except OSError as exc:
        pytest.skip(f"filesystem cannot create sparse test file: {exc}")

    with ByteSource.open(path) as source:
        assert source.size == marker_offset + 5
        assert source.read(marker_offset, 5) == b"UNITI"


def test_fork_retains_open_file_after_path_replacement_and_parent_close(tmp_path: Path):
    path = tmp_path / "fork.bin"
    path.write_bytes(b"original")
    source = ByteSource.open(path, prefer_mmap=False)
    fork = source.fork()
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"replaced")
    replacement.replace(path)
    source.close()
    try:
        assert fork.read(0, 8) == b"original"
        assert not fork.uses_mmap
    finally:
        fork.close()


def test_fork_from_mapped_parent_uses_bounded_file_io(tmp_path: Path):
    path = tmp_path / "mapped-parent.bin"
    path.write_bytes(b"x" * (2 << 20))
    with ByteSource.open(path) as source:
        assert source.uses_mmap
        fork = source.fork()
        try:
            assert not fork.uses_mmap
            assert fork.read(1 << 20, 1) == b"x"
        finally:
            fork.close()
