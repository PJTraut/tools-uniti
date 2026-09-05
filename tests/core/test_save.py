import os
import stat
from pathlib import Path

import pytest

from uniti.core.byte_source import ByteSource
from uniti.core.durability import DurabilityLevel
from uniti.core.offsets import OffsetMapper
from uniti.core.pieces import EditStore, PieceTable
from uniti.core.save import (
    SaveOptions,
    UnrepresentableCharacterError,
    commit_staged_document,
    discard_staged_document,
    save_document,
    stage_document,
    verify_staged_document,
)
from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile


class ReducedSaveAdapter:
    def sync_file(self, _descriptor: int) -> None:
        return None

    def replace(self, source: Path, destination: Path) -> None:
        os.replace(source, destination)

    def sync_directory(self, _directory: Path) -> bool:
        return False


def table_for(path: Path, data: bytes, encoding: str):
    path.write_bytes(data)
    source = ByteSource.open(path)
    mapper = OffsetMapper(source, encoding, checkpoint_bytes=4)
    table = PieceTable(source, encoding, mapper, EditStore())
    return source, table


def test_preserve_save_direct_copies_invalid_source_bytes(tmp_path: Path):
    source, table = table_for(tmp_path / "source.txt", b"A\xffB\r\nC", "utf-8")
    target = tmp_path / "saved.txt"
    try:
        table.insert(1, "X")
        save_document(
            source,
            table,
            source_encoding="utf-8",
            source_bom=None,
            destination=target,
        )
    finally:
        source.close()
    assert target.read_bytes() == b"AX\xffB\r\nC"


def test_preserve_save_keeps_utf8_bom_once(tmp_path: Path):
    source, table = table_for(tmp_path / "bom.txt", b"\xef\xbb\xbfabc", "utf-8-sig")
    target = tmp_path / "bom-out.txt"
    try:
        table.insert(1, "X")
        save_document(
            source,
            table,
            source_encoding="utf-8-sig",
            source_bom=b"\xef\xbb\xbf",
            destination=target,
        )
    finally:
        source.close()
    assert target.read_bytes() == b"\xef\xbb\xbfaXbc"


def test_eol_conversion_is_stateful_across_small_chunks(tmp_path: Path):
    source, table = table_for(tmp_path / "mixed.txt", b"a\r\nb\rc\nd", "utf-8")
    target = tmp_path / "lf.txt"
    try:
        save_document(
            source,
            table,
            source_encoding="utf-8",
            source_bom=None,
            destination=target,
            options=SaveOptions(eol="LF", chunk_chars=2),
        )
    finally:
        source.close()
    assert target.read_bytes() == b"a\nb\nc\nd"


def test_encoding_conversion_is_strict_and_cleans_temp_file(tmp_path: Path):
    source, table = table_for(tmp_path / "unicode.txt", "café ₹".encode(), "utf-8")
    target = tmp_path / "legacy.txt"
    try:
        with pytest.raises(UnrepresentableCharacterError) as exc_info:
            save_document(
                source,
                table,
                source_encoding="utf-8",
                source_bom=None,
                destination=target,
                options=SaveOptions(encoding="windows-1252", chunk_chars=3),
            )
    finally:
        source.close()
    assert exc_info.value.encoding == "windows-1252"
    assert exc_info.value.character == "₹"
    assert not target.exists()
    assert list(tmp_path.glob(".legacy.txt.*.uniti-tmp")) == []


def test_encoding_conversion_writes_representable_text(tmp_path: Path):
    source, table = table_for(tmp_path / "unicode-ok.txt", "café".encode(), "utf-8")
    target = tmp_path / "legacy-ok.txt"
    try:
        save_document(
            source,
            table,
            source_encoding="utf-8",
            source_bom=None,
            destination=target,
            options=SaveOptions(encoding="windows-1252", chunk_chars=2),
        )
    finally:
        source.close()
    assert target.read_bytes() == b"caf\xe9"


def test_atomic_write_text_chunks_normalizes_eol_across_chunk_boundaries(tmp_path: Path):
    from uniti.core.save import atomic_write_text_chunks

    target = tmp_path / "chunks.txt"
    atomic_write_text_chunks(
        iter(["a\r", "\nb\r", "c\n"]),
        target,
        encoding="utf-8",
        eol="LF",
    )
    assert target.read_bytes() == b"a\nb\nc\n"


def test_atomic_save_preserves_existing_platform_mode(tmp_path: Path):
    source_path = tmp_path / "mode.txt"
    source, table = table_for(source_path, b"abc", "utf-8")
    source_path.chmod(0o644)
    try:
        table.insert(3, "X")
        save_document(
            source,
            table,
            source_encoding="utf-8",
            source_bom=None,
            destination=source_path,
        )
    finally:
        source.close()
    mode = source_path.stat().st_mode
    if os.name == "nt":
        assert mode & stat.S_IWRITE
    else:
        assert mode & 0o777 == 0o644


def test_atomic_save_preserves_supported_xattrs(tmp_path: Path):
    api_available = all(
        hasattr(__import__("os"), name)
        for name in ("setxattr", "getxattr")
    )
    if not api_available:
        assert api_available is False
        return
    import os

    source_path = tmp_path / "xattr.txt"
    source, table = table_for(source_path, b"abc", "utf-8")
    name = "user.uniti-test"
    try:
        try:
            os.setxattr(source_path, name, b"kept")
        except OSError:
            filesystem_available = False
        else:
            filesystem_available = True
        if not filesystem_available:
            assert filesystem_available is False
            return
        assert filesystem_available is True
        table.insert(3, "X")
        save_document(
            source,
            table,
            source_encoding="utf-8",
            source_bom=None,
            destination=source_path,
        )
    finally:
        source.close()
    assert os.getxattr(source_path, name) == b"kept"


def test_verified_staged_save_exposes_file_synced_commit_durability(tmp_path: Path):
    source, table = table_for(tmp_path / "source.txt", b"abc", "utf-8")
    target = tmp_path / "target.txt"
    adapter = ReducedSaveAdapter()
    staged = None
    try:
        table.insert(3, "X")
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(
                encoding_profile("utf-8"),
                EOLPolicy.PRESERVE,
            ),
            adapter=adapter,
        )
        assert staged.commit_durability is None
        verify_staged_document(staged, table.iter_text())

        assert commit_staged_document(staged) == target

        assert staged.commit_durability is not None
        assert staged.commit_durability.level is DurabilityLevel.FILE_SYNCED
        assert target.read_bytes() == b"abcX"
    finally:
        if staged is not None:
            discard_staged_document(staged)
        source.close()
