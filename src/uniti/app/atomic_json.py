"""Durable atomic JSON persistence for UNITI-owned state files."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

from uniti.core.durability import (
    DurabilityAdapter,
    DurabilityError,
    DurabilityLevel,
    DurabilityResult,
    NativeDurabilityAdapter,
)


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
    NativeDurabilityAdapter().sync_directory(Path(directory))


def sync_directory_strict(directory: Path) -> None:
    """Sync a directory and expose every durability failure to the caller."""

    if not NativeDurabilityAdapter().sync_directory(Path(directory)):
        raise OSError("directory sync is unavailable")


def _unsafe_result(
    operation: str,
    stage: str,
    error: OSError,
    *,
    file_synced: bool,
) -> DurabilityError:
    result = DurabilityResult(
        operation,
        DurabilityLevel.UNSAFE,
        file_synced,
        False,
        False,
        f"{stage}:{type(error).__name__}",
    )
    return DurabilityError(result, error)


def _atomic_write_bytes(
    path: Path,
    payload: bytes,
    *,
    mode: int,
    adapter: DurabilityAdapter,
    operation: str,
) -> DurabilityResult:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    temporary = Path(name)
    open_descriptor: int | None = descriptor
    try:
        try:
            os.fchmod(descriptor, mode)
        except (AttributeError, OSError):
            pass
        handle = os.fdopen(descriptor, "wb")
        open_descriptor = None
        with handle:
            handle.write(payload)
            handle.flush()
            try:
                adapter.sync_file(handle.fileno())
            except OSError as error:
                raise _unsafe_result(
                    operation,
                    "file_sync",
                    error,
                    file_synced=False,
                ) from error
        try:
            adapter.replace(temporary, target)
        except OSError as error:
            raise _unsafe_result(
                operation,
                "replace",
                error,
                file_synced=True,
            ) from error
        try:
            directory_synced = adapter.sync_directory(target.parent) is True
            reason = None if directory_synced else "directory_sync_unavailable"
        except OSError as error:
            directory_synced = False
            reason = f"directory_sync:{type(error).__name__}"
        return DurabilityResult(
            operation,
            (
                DurabilityLevel.FULL
                if directory_synced
                else DurabilityLevel.FILE_SYNCED
            ),
            True,
            True,
            directory_synced,
            reason,
        )
    except BaseException:
        if open_descriptor is not None:
            try:
                os.close(open_descriptor)
            except OSError:
                pass
        try:
            temporary.unlink()
        except OSError:
            pass
        raise


def atomic_write_bytes(
    path: Path,
    payload: bytes,
    *,
    mode: int = 0o600,
    strict_directory_sync: bool = True,
    adapter: DurabilityAdapter | None = None,
) -> DurabilityResult:
    """Atomically replace one binary file after flushing its exact bytes."""

    if not isinstance(payload, bytes):
        raise TypeError("atomic byte payload must be bytes")
    if type(strict_directory_sync) is not bool:
        raise TypeError("strict_directory_sync must be bool")
    return _atomic_write_bytes(
        Path(path),
        payload,
        mode=mode,
        adapter=adapter if adapter is not None else NativeDurabilityAdapter(),
        operation="atomic_write_bytes",
    )


def atomic_write_json(
    path: Path,
    payload: Mapping[str, object],
    *,
    adapter: DurabilityAdapter | None = None,
) -> DurabilityResult:
    encoded = (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")
    return _atomic_write_bytes(
        Path(path),
        encoded,
        mode=0o600,
        adapter=adapter if adapter is not None else NativeDurabilityAdapter(),
        operation="atomic_write_json",
    )


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
