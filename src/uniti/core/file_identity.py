"""Cross-platform on-disk file identity used for overwrite protection."""

from __future__ import annotations

import hashlib
import os
import re
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


_SHA256_RE = re.compile(r"[0-9a-f]{64}\Z")


class FileHashCancelled(RuntimeError):
    """Raised when a streaming saved-file hash is cancelled."""


class FileMatch(StrEnum):
    EXACT_FAST = "exact_fast"
    EXACT_HASH = "exact_hash"
    CHANGED = "changed"
    MISSING = "missing"


@dataclass(frozen=True, slots=True)
class FileIdentity:
    size: int
    mtime_ns: int
    inode: int | None = None
    device: int | None = None

    @classmethod
    def from_path(cls, path: str | os.PathLike[str]) -> "FileIdentity":
        stat = Path(path).stat()
        return cls(
            size=stat.st_size,
            mtime_ns=stat.st_mtime_ns,
            inode=getattr(stat, "st_ino", None),
            device=getattr(stat, "st_dev", None),
        )


@dataclass(frozen=True, slots=True)
class SavedFileStamp:
    identity: FileIdentity
    sha256: str

    def __post_init__(self) -> None:
        if not isinstance(self.identity, FileIdentity):
            raise TypeError("identity must be a FileIdentity")
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("saved file SHA-256 must be 64 lowercase hex characters")


def sha256_file(
    path: Path,
    *,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[int, int], None] | None = None,
    chunk_bytes: int = 1 << 20,
) -> str:
    """Hash a file progressively without retaining its contents."""

    if type(chunk_bytes) is not int or chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be a positive integer")
    target = Path(path)
    total = target.stat().st_size
    completed = 0
    digest = hashlib.sha256()
    if progress is not None:
        progress(0, total)
    with target.open("rb") as handle:
        while True:
            if cancelled():
                raise FileHashCancelled("saved-file hashing cancelled")
            chunk = handle.read(chunk_bytes)
            if cancelled():
                raise FileHashCancelled("saved-file hashing cancelled")
            if not chunk:
                break
            digest.update(chunk)
            completed += len(chunk)
            if progress is not None:
                progress(completed, total)
    return digest.hexdigest()


def verify_saved_file(
    path: Path,
    expected: SavedFileStamp,
    *,
    cancelled: Callable[[], bool] = lambda: False,
    progress: Callable[[int, int], None] | None = None,
) -> FileMatch:
    """Verify a saved path by identity first and stream its hash only if needed."""

    target = Path(path)
    try:
        actual = FileIdentity.from_path(target)
    except FileNotFoundError:
        return FileMatch.MISSING
    if actual == expected.identity:
        return FileMatch.EXACT_FAST
    digest = sha256_file(target, cancelled=cancelled, progress=progress)
    return FileMatch.EXACT_HASH if digest == expected.sha256 else FileMatch.CHANGED


class ExternalFileChangedError(RuntimeError):
    """Raised before UNITI would overwrite a path changed outside UNITI."""

    def __init__(
        self,
        path: Path,
        expected: FileIdentity | None,
        actual: FileIdentity | None,
    ) -> None:
        self.path = path
        self.expected = expected
        self.actual = actual
        if expected is None and actual is not None:
            detail = "appeared on disk"
        elif actual is None:
            detail = "is no longer present"
        else:
            detail = "has changed on disk"
        super().__init__(f"{path} {detail}; refusing to overwrite it")
