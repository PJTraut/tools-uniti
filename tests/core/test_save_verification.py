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
    SaveOptions,
    UnrepresentableCharacterError,
    UnresolvedMalformedBytesError,
    commit_staged_document,
    discard_staged_document,
    save_document,
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


def test_verified_is_exposed_read_only(tmp_path):
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
        assert staged.verified is False
        verify_staged_document(staged, table.iter_text())
        assert staged.verified is True
        with pytest.raises((AttributeError, TypeError)):
            staged.verified = False
    finally:
        discard_staged_document(staged)
        source.close()


def test_commit_uses_verified_identity_seal_without_rehashing(
    tmp_path,
    monkeypatch,
):
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
        verify_staged_document(staged, table.iter_text())
        monkeypatch.setattr(
            "uniti.core.save._file_length_and_digest",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                AssertionError("commit rehashed verified output")
            ),
        )

        assert commit_staged_document(staged) == target
    finally:
        discard_staged_document(staged)
        source.close()


def test_commit_rejects_same_size_temp_mutation_after_verification(tmp_path):
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
        verify_staged_document(staged, table.iter_text())
        staged.temporary.write_bytes(b"omega\n")

        with pytest.raises(SaveVerificationError, match="changed after verification"):
            commit_staged_document(staged)
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


@pytest.mark.parametrize(
    "selected",
    [
        OutputFormat(encoding_profile("utf-16-le"), EOLPolicy.PRESERVE),
        OutputFormat(encoding_profile("utf-8"), EOLPolicy.CRLF),
    ],
)
def test_unresolved_malformed_bytes_block_any_transformation(tmp_path, selected):
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"A\xffB\n")
    source = ByteSource.open(path)
    mapper = OffsetMapper(source, "utf-8", checkpoint_bytes=2)
    table = PieceTable(source, "utf-8", mapper, EditStore())
    target = tmp_path / "target.txt"
    target.write_bytes(b"untouched")
    try:
        with pytest.raises(UnresolvedMalformedBytesError) as exc_info:
            stage_document(
                source,
                table,
                source_profile=encoding_profile("utf-8"),
                destination=target,
                output_format=selected,
                chunk_chars=2,
            )
        assert exc_info.value.position == 1
        assert exc_info.value.raw == b"\xff"
    finally:
        source.close()
    assert target.read_bytes() == b"untouched"
    assert list(tmp_path.glob(".target.txt.*.uniti-tmp")) == []


def test_unrepresentable_error_reports_document_position_before_staging(tmp_path):
    source, table = table_for(tmp_path / "source.txt", "AПривет\n")
    target = tmp_path / "target.txt"
    try:
        with pytest.raises(UnrepresentableCharacterError) as exc_info:
            stage_document(
                source,
                table,
                source_profile=encoding_profile("utf-8"),
                destination=target,
                output_format=OutputFormat(
                    encoding_profile("windows-1252"), EOLPolicy.PRESERVE
                ),
            )
        assert exc_info.value.character == "П"
        assert exc_info.value.position == 1
    finally:
        source.close()
    assert not target.exists()
    assert list(tmp_path.glob(".target.txt.*.uniti-tmp")) == []


def test_save_document_discards_stage_when_verifier_refuses(
    tmp_path,
    monkeypatch,
):
    source, table = table_for(tmp_path / "source.txt", "alpha\n")
    target = tmp_path / "target.txt"
    target.write_bytes(b"untouched")

    def refuse(*_args, **_kwargs):
        raise SaveVerificationError("injected verification refusal")

    monkeypatch.setattr("uniti.core.save.verify_staged_document", refuse)
    try:
        with pytest.raises(SaveVerificationError, match="injected"):
            save_document(
                source,
                table,
                source_encoding="utf-8",
                source_bom=None,
                destination=target,
                options=SaveOptions(
                    output_format=OutputFormat(
                        encoding_profile("utf-8"), EOLPolicy.LF
                    )
                ),
            )
    finally:
        source.close()
    assert target.read_bytes() == b"untouched"
    assert list(tmp_path.glob(".target.txt.*.uniti-tmp")) == []
