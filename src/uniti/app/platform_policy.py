"""Qt-free operating-system policy shared by UNITI application services."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Mapping


class PlatformFamily(StrEnum):
    MACOS = "macos"
    WINDOWS = "windows"
    LINUX = "linux"


class UnsupportedPlatformError(RuntimeError):
    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name
        selected = "".join(
            character if character.isprintable() else "?"
            for character in platform_name
        )[:64]
        selected = selected or "<empty>"
        super().__init__(f"Unsupported UNITI platform: {selected}")


def classify_platform(platform_name: str) -> PlatformFamily:
    if not isinstance(platform_name, str):
        raise TypeError("platform name must be a string")
    if platform_name == "darwin":
        return PlatformFamily.MACOS
    if platform_name.startswith("win"):
        return PlatformFamily.WINDOWS
    if platform_name.startswith("linux"):
        return PlatformFamily.LINUX
    raise UnsupportedPlatformError(platform_name)


def absolute_environment_root(
    environ: Mapping[str, str],
    name: str,
    fallback: Path,
) -> Path:
    selected_fallback = Path(fallback)
    if not selected_fallback.is_absolute() or "\0" in str(selected_fallback):
        raise ValueError("fallback root must be absolute")
    value = environ.get(name, "")
    if not isinstance(value, str) or not value or "\0" in value:
        return selected_fallback
    candidate = Path(value)
    return candidate if candidate.is_absolute() else selected_fallback
