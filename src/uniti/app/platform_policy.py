"""Qt-free operating-system policy shared by UNITI application services."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import ntpath
import os
from pathlib import Path
import sys
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


@dataclass(frozen=True, slots=True)
class NativePath:
    path: Path
    comparison_key: str
    exists: bool

    def __post_init__(self) -> None:
        if not isinstance(self.path, Path) or not self.path.is_absolute():
            raise ValueError("native path must be absolute")
        if "\0" in str(self.path):
            raise ValueError("native path contains a NUL")
        if not isinstance(self.comparison_key, str) or not self.comparison_key:
            raise ValueError("native path comparison key must be nonempty")
        if type(self.exists) is not bool:
            raise TypeError("native path existence flag must be bool")


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


def _path_text(value: object, label: str) -> str:
    try:
        selected = os.fspath(value)
    except TypeError as error:
        raise TypeError(f"{label} must be path-like") from error
    if not isinstance(selected, str):
        raise TypeError(f"{label} must be text")
    if not selected:
        raise ValueError(f"{label} must be nonempty")
    if "\0" in selected:
        raise ValueError(f"{label} contains a NUL")
    return selected


def normalize_native_path(
    path: str | os.PathLike[str],
    *,
    cwd: str | os.PathLike[str] | None = None,
    platform_name: str = sys.platform,
) -> NativePath:
    family = classify_platform(platform_name)
    selected = Path(_path_text(path, "native path"))
    base: Path | None = None
    if cwd is not None:
        base = Path(_path_text(cwd, "native working directory"))
        if not base.is_absolute():
            raise ValueError("native working directory must be absolute")
    if not selected.is_absolute():
        if base is None:
            try:
                base = Path.cwd()
            except OSError as error:
                raise ValueError(
                    "native working directory cannot be normalized"
                ) from error
        selected = base / selected
    try:
        resolved = selected.resolve(strict=False)
    except (OSError, RuntimeError) as error:
        raise ValueError("native path cannot be normalized") from error
    if not resolved.is_absolute():
        raise ValueError("native path cannot be normalized")
    path_text = str(resolved)
    comparison_key = (
        ntpath.normcase(path_text)
        if family is PlatformFamily.WINDOWS
        else path_text
    )
    try:
        exists = resolved.exists()
    except OSError:
        exists = False
    return NativePath(resolved, comparison_key, exists)


def native_paths_equal(
    first: str | os.PathLike[str],
    second: str | os.PathLike[str],
    *,
    platform_name: str = sys.platform,
    cwd: str | os.PathLike[str] | None = None,
) -> bool:
    left = normalize_native_path(first, cwd=cwd, platform_name=platform_name)
    right = normalize_native_path(second, cwd=cwd, platform_name=platform_name)
    if left.exists and right.exists:
        try:
            return os.path.samefile(left.path, right.path)
        except OSError:
            pass
    return left.comparison_key == right.comparison_key
