"""Immutable, bounded byte access for UNITI documents."""

from __future__ import annotations

import mmap
import os
import threading
from pathlib import Path
from typing import BinaryIO, Iterator


class ByteSource:
    """Read-only file-backed byte source.

    The source never materializes the complete file as a Python ``bytes``
    object. mmap is preferred for non-empty files and bounded seek/read is
    retained as a fallback.
    """

    def __init__(
        self,
        path: Path,
        handle: BinaryIO,
        size: int,
        mapping: mmap.mmap | None,
        io_lock: threading.RLock | None = None,
    ) -> None:
        self._path = path
        self._handle = handle
        self._size = size
        self._mapping = mapping
        self._io_lock = io_lock or threading.RLock()
        self._closed = False

    @classmethod
    def open(
        cls,
        path: str | os.PathLike[str],
        *,
        prefer_mmap: bool = True,
    ) -> "ByteSource":
        resolved = Path(path)
        handle = resolved.open("rb")
        try:
            size = os.fstat(handle.fileno()).st_size
            mapping: mmap.mmap | None = None
            if prefer_mmap and size > 0:
                try:
                    mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
                except (OSError, ValueError, BufferError):
                    mapping = None
            return cls(resolved, handle, size, mapping)
        except Exception:
            handle.close()
            raise

    @property
    def path(self) -> Path:
        return self._path

    @property
    def size(self) -> int:
        return self._size

    @property
    def uses_mmap(self) -> bool:
        return self._mapping is not None

    def _ensure_open(self) -> None:
        if self._closed:
            raise ValueError("ByteSource is closed")

    def _validate_range(self, start: int, length: int) -> None:
        if start < 0:
            raise ValueError("start must be non-negative")
        if length < 0:
            raise ValueError("length must be non-negative")
        if start > self._size or start + length > self._size:
            raise ValueError("requested range extends beyond end of source")

    def read(self, start: int, length: int) -> bytes:
        self._ensure_open()
        self._validate_range(start, length)
        if length == 0:
            return b""
        if self._mapping is not None:
            return self._mapping[start : start + length]
        with self._io_lock:
            self._handle.seek(start)
            data = self._handle.read(length)
        if len(data) != length:
            raise OSError("short read from byte source")
        return data

    def fork(self) -> "ByteSource":
        """Duplicate the captured file identity without reopening its path."""

        self._ensure_open()
        descriptor = os.dup(self._handle.fileno())
        handle = os.fdopen(descriptor, "rb", closefd=True)
        try:
            mapping: mmap.mmap | None = None
            if self._mapping is not None and self._size > 0:
                try:
                    mapping = mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ)
                except (OSError, ValueError, BufferError):
                    mapping = None
            return ByteSource(
                self._path,
                handle,
                self._size,
                mapping,
                self._io_lock,
            )
        except Exception:
            handle.close()
            raise

    def iter_chunks(
        self,
        *,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1 << 20,
    ) -> Iterator[bytes]:
        self._ensure_open()
        if chunk_size <= 0:
            raise ValueError("chunk_size must be positive")
        stop = self._size if end is None else end
        if start < 0 or stop < start or stop > self._size:
            raise ValueError("invalid iteration range")

        offset = start
        while offset < stop:
            length = min(chunk_size, stop - offset)
            yield self.read(offset, length)
            offset += length

    def close(self) -> None:
        if self._closed:
            return
        if self._mapping is not None:
            self._mapping.close()
            self._mapping = None
        self._handle.close()
        self._closed = True

    def __enter__(self) -> "ByteSource":
        self._ensure_open()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()
