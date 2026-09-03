from pathlib import Path

import pytest

from uniti.core.file_identity import (
    FileHashCancelled,
    FileIdentity,
    FileMatch,
    SavedFileStamp,
    sha256_file,
    verify_saved_file,
)


def test_file_identity_captures_stable_stat_fields(tmp_path: Path):
    path = tmp_path / "identity.txt"
    path.write_text("abc", encoding="utf-8")
    identity = FileIdentity.from_path(path)
    stat = path.stat()
    assert identity.size == 3
    assert identity.mtime_ns == stat.st_mtime_ns
    assert identity.inode == getattr(stat, "st_ino", None)
    assert identity.device == getattr(stat, "st_dev", None)


def test_saved_file_verification_uses_metadata_fast_path(tmp_path, monkeypatch):
    path = tmp_path / "saved.txt"
    path.write_bytes(b"exact bytes")
    stamp = SavedFileStamp(FileIdentity.from_path(path), sha256_file(path))
    called = False

    def forbidden_hash(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("fast match must not hash")

    monkeypatch.setattr("uniti.core.file_identity.sha256_file", forbidden_hash)

    assert verify_saved_file(path, stamp) is FileMatch.EXACT_FAST
    assert called is False


def test_saved_file_verification_hashes_when_metadata_changes(tmp_path: Path):
    path = tmp_path / "saved.txt"
    path.write_bytes(b"exact bytes")
    stamp = SavedFileStamp(FileIdentity.from_path(path), sha256_file(path))

    replacement = tmp_path / "replacement.txt"
    replacement.write_bytes(b"exact bytes")
    replacement.replace(path)
    assert verify_saved_file(path, stamp) is FileMatch.EXACT_HASH

    changed = tmp_path / "changed.txt"
    changed.write_bytes(b"other bytes")
    changed.replace(path)
    assert verify_saved_file(path, stamp) is FileMatch.CHANGED

    path.unlink()
    assert verify_saved_file(path, stamp) is FileMatch.MISSING


def test_sha256_file_reports_streaming_progress_and_cancellation(tmp_path: Path):
    path = tmp_path / "large-enough.bin"
    path.write_bytes(b"a" * 10)
    progress: list[tuple[int, int]] = []

    digest = sha256_file(path, chunk_bytes=4, progress=lambda done, total: progress.append((done, total)))

    assert len(digest) == 64
    assert progress == [(0, 10), (4, 10), (8, 10), (10, 10)]

    checks = 0

    def cancelled() -> bool:
        nonlocal checks
        checks += 1
        return checks >= 4

    with pytest.raises(FileHashCancelled, match="cancelled"):
        sha256_file(path, chunk_bytes=4, cancelled=cancelled)


def test_saved_file_stamp_rejects_malformed_sha256(tmp_path: Path):
    path = tmp_path / "saved.txt"
    path.write_bytes(b"x")

    with pytest.raises(ValueError, match="SHA-256"):
        SavedFileStamp(FileIdentity.from_path(path), "not-a-hash")
