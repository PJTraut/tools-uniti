"""Capability-driven durability results for atomic UNITI publication."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import sys
import time
from typing import Protocol


_MAX_DETAIL_CHARS = 128

# ERROR_UNABLE_TO_REMOVE_REPLACED (a prior version of the destination could
# not be deleted) and ERROR_SHARING_VIOLATION (something else has it open) --
# both are routinely transient on Windows (antivirus or an indexer briefly
# holding the destination open), not a persistent failure, so a replace is
# worth retrying through them rather than failing on the first contended
# attempt.
_TRANSIENT_REPLACE_WINERRORS = frozenset({1175, 32})


def _retry_transient_replace(
    attempt: Callable[[], None],
    *,
    max_attempts: int = 5,
    initial_delay_seconds: float = 0.02,
    sleep: Callable[[float], None] = time.sleep,
) -> None:
    """Run `attempt` (a single ReplaceFileW call), retrying with backoff
    through `_TRANSIENT_REPLACE_WINERRORS`. Any other OSError, or the last
    attempt's, is raised immediately -- this is for riding out a momentary
    lock, not for masking a persistent failure (wrong permissions, a
    read-only/hidden target, a policy block)."""

    delay = initial_delay_seconds
    for remaining in range(max_attempts - 1, -1, -1):
        try:
            attempt()
            return
        except OSError as error:
            if remaining == 0 or getattr(error, "winerror", None) not in (
                _TRANSIENT_REPLACE_WINERRORS
            ):
                raise
            sleep(delay)
            delay *= 2


def _windows_replace_existing(source: Path, destination: Path) -> None:
    """Atomically replace an existing Windows path that permits delete sharing."""

    import ctypes
    from ctypes import wintypes

    replace_file = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
    replace_file.argtypes = (
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.LPVOID,
    )
    replace_file.restype = wintypes.BOOL

    def attempt() -> None:
        if not replace_file(
            str(destination),
            str(source),
            None,
            0,
            None,
            None,
        ):
            raise ctypes.WinError(ctypes.get_last_error())

    _retry_transient_replace(attempt)


class DurabilityLevel(StrEnum):
    FULL = "full"
    FILE_SYNCED = "file_synced"
    UNSAFE = "unsafe"


@dataclass(frozen=True, slots=True)
class DurabilityResult:
    operation: str
    level: DurabilityLevel
    file_synced: bool
    replaced: bool
    directory_synced: bool
    reason: str | None = None

    def __post_init__(self) -> None:
        if (
            not isinstance(self.operation, str)
            or not self.operation
            or len(self.operation) > _MAX_DETAIL_CHARS
            or not self.operation.isprintable()
        ):
            raise ValueError("durability operation must be bounded printable text")
        if not isinstance(self.level, DurabilityLevel):
            raise TypeError("durability level must be a DurabilityLevel")
        if any(
            type(value) is not bool
            for value in (
                self.file_synced,
                self.replaced,
                self.directory_synced,
            )
        ):
            raise TypeError("durability facts must be bool")
        if self.reason is not None and (
            not isinstance(self.reason, str)
            or not self.reason
            or len(self.reason) > _MAX_DETAIL_CHARS
            or not self.reason.isprintable()
        ):
            raise ValueError("durability reason must be bounded printable text")

        if self.level is DurabilityLevel.FULL:
            valid = (
                self.file_synced
                and self.replaced
                and self.directory_synced
                and self.reason is None
            )
        elif self.level is DurabilityLevel.FILE_SYNCED:
            valid = (
                self.file_synced
                and self.replaced
                and not self.directory_synced
                and self.reason is not None
            )
        else:
            valid = (
                not self.directory_synced
                and (not self.file_synced or not self.replaced)
                and self.reason is not None
            )
        if not valid:
            raise ValueError("durability level does not match its observed facts")

    def as_dict(self) -> dict[str, object]:
        return {
            "operation": self.operation,
            "level": self.level.value,
            "file_synced": self.file_synced,
            "replaced": self.replaced,
            "directory_synced": self.directory_synced,
            "reason": self.reason,
        }


class DurabilityError(OSError):
    def __init__(self, result: DurabilityResult, cause: OSError) -> None:
        if not isinstance(result, DurabilityResult):
            raise TypeError("durability error result is invalid")
        if result.level is not DurabilityLevel.UNSAFE:
            raise ValueError("durability error requires an unsafe result")
        if not isinstance(cause, OSError):
            raise TypeError("durability error cause must be an OSError")
        self.result = result
        self.cause = cause
        super().__init__(
            f"{result.operation} durability failed ({result.reason})"
        )


class DurabilityAdapter(Protocol):
    def sync_file(self, descriptor: int) -> None: ...

    def replace(self, source: Path, destination: Path) -> None: ...

    def sync_directory(self, directory: Path) -> bool: ...


class NativeDurabilityAdapter:
    def sync_file(self, descriptor: int) -> None:
        os.fsync(descriptor)

    def replace(self, source: Path, destination: Path) -> None:
        if sys.platform.startswith("win") and Path(destination).exists():
            _windows_replace_existing(Path(source), Path(destination))
            return
        os.replace(source, destination)

    def sync_directory(self, directory: Path) -> bool:
        flags = os.O_RDONLY
        if hasattr(os, "O_DIRECTORY"):
            flags |= os.O_DIRECTORY
        try:
            descriptor = os.open(Path(directory), flags)
        except (AttributeError, OSError):
            return False
        synced = False
        try:
            try:
                os.fsync(descriptor)
            except OSError:
                return False
            synced = True
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
        return synced


def combine_durability(
    operation: str,
    results: Iterable[DurabilityResult],
) -> DurabilityResult:
    selected = tuple(results)
    if not selected:
        raise ValueError("durability combination requires at least one result")
    if any(not isinstance(result, DurabilityResult) for result in selected):
        raise TypeError("durability combination contains an invalid result")
    file_synced = all(result.file_synced for result in selected)
    replaced = all(result.replaced for result in selected)
    directory_synced = all(result.directory_synced for result in selected)
    if any(result.level is DurabilityLevel.UNSAFE for result in selected):
        level = DurabilityLevel.UNSAFE
    elif any(result.level is DurabilityLevel.FILE_SYNCED for result in selected):
        level = DurabilityLevel.FILE_SYNCED
    else:
        level = DurabilityLevel.FULL
    reasons = tuple(
        dict.fromkeys(
            result.reason
            for result in selected
            if result.reason is not None
        )
    )
    reason = None if not reasons else ";".join(reasons)[:_MAX_DETAIL_CHARS]
    return DurabilityResult(
        operation,
        level,
        file_synced,
        replaced,
        directory_synced,
        reason,
    )


__all__ = [
    "DurabilityAdapter",
    "DurabilityError",
    "DurabilityLevel",
    "DurabilityResult",
    "NativeDurabilityAdapter",
    "combine_durability",
]
