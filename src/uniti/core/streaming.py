"""Streaming write primitives for UNITI."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .byte_source import ByteSource


def atomic_copy_source(
    source: ByteSource,
    destination: str | os.PathLike[str],
    *,
    chunk_size: int = 1 << 20,
) -> Path:
    """Copy a byte source through a temporary file and atomically replace target."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")

    target = Path(destination)
    fd: int | None = None
    temp_path: Path | None = None
    try:
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{target.name}.",
            suffix=".uniti-tmp",
            dir=target.parent,
        )
        temp_path = Path(temp_name)
        with os.fdopen(fd, "wb") as handle:
            fd = None
            for chunk in source.iter_chunks(chunk_size=chunk_size):
                handle.write(chunk)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, target)
        temp_path = None
        return target
    except Exception:
        if fd is not None:
            os.close(fd)
        if temp_path is not None:
            try:
                temp_path.unlink()
            except FileNotFoundError:
                pass
        raise
