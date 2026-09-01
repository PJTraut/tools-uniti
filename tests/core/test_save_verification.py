from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from uniti.core.byte_source import ByteSource
from uniti.core.offsets import OffsetMapper
from uniti.core.pieces import EditStore, PieceTable
from uniti.core.save import (
    SaveVerificationError,
    commit_staged_document,
    discard_staged_document,
    stage_document,
    verify_staged_document,
)
from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile


def table_for(path: Path, text: str = "Western Привет\n"):
    path.write_bytes(text.encode("utf-8"))
    source = ByteSource.open(path)
    mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=4)
    return source, PieceTable(source, "utf-8", mapper, EditStore())


def with_recomputed_fingerprint(staged, payload: bytes):
    staged.temporary.write_bytes(payload)
    return replace(
        staged,
        byte_length=len(payload),
        digest=hashlib.sha256(payload).hexdigest(),
    )


@pytest.mark.parametrize(
    "profile_key",
    [
        "utf-8",
        "utf-8-bom",
        "utf-16-le",
        "utf-16-le-bom",
        "utf-16-be",
        "utf-16-be-bom",
        "utf-32-le",
        "utf-32-le-bom",
        "utf-32-be",
        "utf-32-be-bom",
    ],
)
def test_staged_save_writes_exact_selected_profile_and_eol(tmp_path, profile_key):
    source, table = table_for(tmp_path / "source.txt")
    target = tmp_path / "target.txt"
    target.write_bytes(b"existing")
    profile = encoding_profile(profile_key)
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(profile, EOLPolicy.CRLF),
        )
        assert target.read_bytes() == b"existing"
        verify_staged_document(staged, table.iter_text())
        commit_staged_document(staged)
    finally:
        source.close()
    assert target.read_bytes() == profile.bom + "Western Привет\r\n".encode(
        profile.codec
    )


def test_windows_1252_staging_is_exact_for_representable_text(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "café\n")
    target = tmp_path / "target.txt"
    selected = OutputFormat(encoding_profile("windows-1252"), EOLPolicy.CRLF)
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=selected,
        )
        verify_staged_document(staged, table.iter_text())
        commit_staged_document(staged)
    finally:
        source.close()
    assert target.read_bytes() == b"caf\xe9\r\n"


def test_stage_records_written_size_and_digest(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "alpha\nbeta\n")
    target = tmp_path / "target.txt"
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(encoding_profile("utf-8"), EOLPolicy.LF),
        )
        payload = staged.temporary.read_bytes()
        assert staged.byte_length == len(payload)
        assert staged.digest == hashlib.sha256(payload).hexdigest()
        verify_staged_document(staged, table.iter_text())
        commit_staged_document(staged)
    finally:
        source.close()


def test_verification_rejects_changed_staged_bytes_before_commit(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "alpha\n")
    target = tmp_path / "target.txt"
    target.write_bytes(b"untouched")
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(encoding_profile("utf-8"), EOLPolicy.LF),
        )
        staged.temporary.write_bytes(b"corrupt\n")
        with pytest.raises(SaveVerificationError, match="digest|length"):
            verify_staged_document(staged, table.iter_text())
        assert target.read_bytes() == b"untouched"
    finally:
        discard_staged_document(staged)
        source.close()
    assert not staged.temporary.exists()


def test_verification_rejects_unexpected_bom_for_no_bom_profile(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "alpha\n")
    target = tmp_path / "target.txt"
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(encoding_profile("utf-8"), EOLPolicy.LF),
        )
        staged.temporary.write_bytes(b"\xef\xbb\xbfalpha\n")
        with pytest.raises(SaveVerificationError, match="BOM"):
            verify_staged_document(staged, table.iter_text())
    finally:
        discard_staged_document(staged)
        source.close()


def test_verification_rejects_missing_required_bom(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "alpha\n")
    target = tmp_path / "target.txt"
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(
                encoding_profile("utf-16-be-bom"), EOLPolicy.LF
            ),
        )
        payload = staged.temporary.read_bytes()[2:]
        changed = with_recomputed_fingerprint(staged, payload)
        with pytest.raises(SaveVerificationError, match="BOM"):
            verify_staged_document(changed, table.iter_text())
    finally:
        discard_staged_document(staged)
        source.close()


def test_transformed_preserve_output_still_requires_strict_decoding(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "alpha\n")
    target = tmp_path / "target.txt"
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(
                encoding_profile("utf-32-le"), EOLPolicy.PRESERVE
            ),
        )
        payload = staged.temporary.read_bytes()[:-1]
        changed = with_recomputed_fingerprint(staged, payload)
        with pytest.raises(SaveVerificationError, match="decode strictly"):
            verify_staged_document(changed, table.iter_text())
    finally:
        discard_staged_document(staged)
        source.close()


def test_verification_rejects_wrong_byte_order_with_valid_fingerprint(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "alpha\n")
    target = tmp_path / "target.txt"
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(
                encoding_profile("utf-16-le"), EOLPolicy.LF
            ),
        )
        changed = with_recomputed_fingerprint(
            staged,
            "alpha\n".encode("utf-16-be"),
        )
        with pytest.raises(SaveVerificationError, match="logical text"):
            verify_staged_document(changed, table.iter_text())
    finally:
        discard_staged_document(staged)
        source.close()


def test_verification_rejects_wrong_requested_line_endings(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "alpha\nbeta\n")
    target = tmp_path / "target.txt"
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(
                encoding_profile("utf-8"), EOLPolicy.CRLF
            ),
        )
        changed = with_recomputed_fingerprint(staged, b"alpha\nbeta\n")
        with pytest.raises(SaveVerificationError, match="logical text|line endings"):
            verify_staged_document(changed, table.iter_text())
    finally:
        discard_staged_document(staged)
        source.close()


def test_unverified_stage_cannot_be_committed(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "alpha\n")
    target = tmp_path / "target.txt"
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(encoding_profile("utf-8"), EOLPolicy.LF),
        )
        with pytest.raises(SaveVerificationError, match="not been verified"):
            commit_staged_document(staged)
        assert not target.exists()
    finally:
        discard_staged_document(staged)
        source.close()


def test_preserve_staging_keeps_mixed_line_endings(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "a\r\nb\nc\r")
    target = tmp_path / "target.txt"
    try:
        staged = stage_document(
            source,
            table,
            source_profile=encoding_profile("utf-8"),
            destination=target,
            output_format=OutputFormat(
                encoding_profile("utf-8"), EOLPolicy.PRESERVE
            ),
        )
        verify_staged_document(staged, table.iter_text())
        commit_staged_document(staged)
    finally:
        source.close()
    assert target.read_bytes() == b"a\r\nb\nc\r"
