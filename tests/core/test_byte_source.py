import sys
from pathlib import Path

import pytest

import uniti.core.byte_source as byte_source_module
from uniti.app.sparse import enable_sparse_file
from uniti.core.byte_source import ByteSource
from uniti.core.durability import NativeDurabilityAdapter


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


def test_windows_source_uses_replace_shareable_handle_without_mmap(
    tmp_path: Path,
    monkeypatch,
):
    path = tmp_path / "replaceable.txt"
    path.write_bytes(b"replaceable")
    opened: list[Path] = []

    def open_shared_delete(candidate: Path):
        opened.append(candidate)
        return candidate.open("rb")

    monkeypatch.setattr(byte_source_module.sys, "platform", "win32")
    monkeypatch.setattr(
        byte_source_module,
        "_open_windows_read_shared_delete",
        open_shared_delete,
    )
    monkeypatch.setattr(
        byte_source_module.mmap,
        "mmap",
        lambda *_args, **_kwargs: pytest.fail("Windows sources must not be mapped"),
    )

    with ByteSource.open(path, prefer_mmap=True) as source:
        assert source.read(0, source.size) == b"replaceable"
        assert source.uses_mmap is False

    assert opened == [path]


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
            assert enable_sparse_file(handle.fileno())
            handle.seek(marker_offset)
            handle.write(b"UNITI")
    except OSError as exc:
        pytest.fail(f"required sparse test fixture is unavailable: {exc}")

    with ByteSource.open(path) as source:
        assert source.size == marker_offset + 5
        assert source.read(marker_offset, 5) == b"UNITI"


def test_windows_simulated_reads_support_large_sparse_files_without_mmap(
    tmp_path: Path,
    monkeypatch,
):
    """Coverage gap closed: mmap is unconditionally disabled on Windows
    (ByteSource.open's own `not windows` gate), so on a real Windows machine
    every large file is always read through the buffered seek/read
    fallback -- but until this test, nothing combined a simulated-Windows
    dispatch with a genuinely large (>1 GiB) file, so a regression in that
    specific combination could only ever have been caught by a real Windows
    CI run happening to notice, not by a dedicated assertion."""

    path = tmp_path / "large-windows.bin"
    marker_offset = (1 << 30) + 54321
    marker = b"UNITI_WINDOWS_TAIL"
    try:
        with path.open("wb") as handle:
            assert enable_sparse_file(handle.fileno())
            handle.write(b"head\n")
            handle.seek(marker_offset)
            handle.write(marker)
    except OSError as exc:
        pytest.fail(f"required sparse test fixture is unavailable: {exc}")

    opened: list[Path] = []

    def open_shared_delete(candidate: Path):
        opened.append(candidate)
        return candidate.open("rb")

    monkeypatch.setattr(byte_source_module.sys, "platform", "win32")
    monkeypatch.setattr(
        byte_source_module,
        "_open_windows_read_shared_delete",
        open_shared_delete,
    )
    monkeypatch.setattr(
        byte_source_module.mmap,
        "mmap",
        lambda *_args, **_kwargs: pytest.fail(
            "a simulated-Windows large file must not be mapped"
        ),
    )

    with ByteSource.open(path, prefer_mmap=True) as source:
        assert source.uses_mmap is False
        assert source.size == marker_offset + len(marker)
        assert source.read(0, 5) == b"head\n"
        assert source.read(marker_offset, len(marker)) == marker
        # A bounded read spanning out of the sparse hole and into the tail
        # marker, exercising the fallback at a boundary a small fixture
        # could never reach.
        spanning = list(
            source.iter_chunks(
                start=marker_offset - 32,
                end=marker_offset + len(marker),
                chunk_size=8,
            )
        )
        assert b"".join(spanning) == (b"\x00" * 32) + marker

    assert opened == [path]


def test_fork_retains_open_file_after_path_replacement_and_parent_close(tmp_path: Path):
    path = tmp_path / "fork.bin"
    path.write_bytes(b"original")
    source = ByteSource.open(path, prefer_mmap=False)
    fork = source.fork()
    replacement = tmp_path / "replacement.bin"
    replacement.write_bytes(b"replaced")
    NativeDurabilityAdapter().replace(replacement, path)
    source.close()
    try:
        assert fork.read(0, 8) == b"original"
        assert not fork.uses_mmap
    finally:
        fork.close()


def test_fork_uses_bounded_file_io_for_each_parent_access_mode(tmp_path: Path):
    path = tmp_path / "mapped-parent.bin"
    path.write_bytes(b"x" * (2 << 20))
    with ByteSource.open(path) as source:
        assert source.uses_mmap is (not sys.platform.startswith("win"))
        fork = source.fork()
        try:
            assert not fork.uses_mmap
            assert fork.read(1 << 20, 1) == b"x"
        finally:
            fork.close()
