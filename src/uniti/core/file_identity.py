"""Cross-platform on-disk file identity used for overwrite protection."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
