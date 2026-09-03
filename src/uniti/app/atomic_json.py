"""Durable atomic JSON persistence for UNITI-owned state files."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(UTC)


def utc_timestamp(value: datetime | None = None) -> str:
    current = value or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _filename_timestamp(value: datetime | None = None) -> str:
    current = value or utc_now()
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    return current.astimezone(UTC).strftime("%Y%m%dT%H%M%S%fZ")


def sync_directory(directory: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        descriptor = os.open(directory, flags)
    except OSError:
        return
    try:
        try:
            os.fsync(descriptor)
        except OSError:
            pass
    finally:
        os.close(descriptor)


def sync_directory_strict(directory: Path) -> None:
    """Sync a directory and expose every durability failure to the caller."""

    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(directory, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def atomic_write_bytes(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
    strict_directory_sync: bool = True,
) -> None:
    """Atomically replace one binary file after flushing its exact bytes."""

    if not isinstance(payload, bytes):
        raise TypeError("atomic byte payload must be bytes")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(name)
    try:
        try:
            os.fchmod(descriptor, mode)
        except (AttributeError, OSError):
            pass
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        if strict_directory_sync:
            sync_directory_strict(target.parent)
        else:
            sync_directory(target.parent)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        newline="\n",
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            json.dump(dict(payload), handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        sync_directory(target.parent)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def preserve_invalid(path: Path, *, now: datetime | None = None) -> Path:
    source = Path(path)
    destination = source.with_name(
        f"{source.name}.{_filename_timestamp(now)}.invalid"
    )
    counter = 1
    while destination.exists():
        destination = source.with_name(
            f"{source.name}.{_filename_timestamp(now)}.{counter}.invalid"
        )
        counter += 1
    shutil.copy2(source, destination)
    sync_directory(destination.parent)
    return destination
