from pathlib import Path

from uniti.core.byte_source import ByteSource
from uniti.core.streaming import atomic_copy_source


def test_atomic_copy_is_byte_identical(tmp_path: Path):
    source_path = tmp_path / "source.bin"
    target_path = tmp_path / "target.bin"
    payload = (b"UNITI\x00\xff\r\n" * 1000) + b"end"
    source_path.write_bytes(payload)
    with ByteSource.open(source_path) as source:
        result = atomic_copy_source(source, target_path, chunk_size=257)
    assert result == target_path
    assert target_path.read_bytes() == payload


def test_atomic_copy_replaces_existing_target(tmp_path: Path):
    source_path = tmp_path / "source.bin"
    target_path = tmp_path / "target.bin"
    source_path.write_bytes(b"new")
    target_path.write_bytes(b"old")
    with ByteSource.open(source_path) as source:
        atomic_copy_source(source, target_path, chunk_size=1)
    assert target_path.read_bytes() == b"new"
