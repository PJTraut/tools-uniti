"""Qt-free immutable types shared by UNITI bootstrap components."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from uniti.app.paths import AppPaths


class BootstrapMode(StrEnum):
    SOURCE = "source"
    LOCAL = "local"


@dataclass(frozen=True, slots=True)
class HostPython:
    command: tuple[str, ...]
    executable: Path
    version: tuple[int, int, int]
    implementation: str
    architecture: str
    prefix: Path | None = None
    base_prefix: Path | None = None

    @property
    def supported(self) -> bool:
        return self.version >= (3, 12, 0)

    @property
    def is_virtual_environment(self) -> bool:
        return (
            self.prefix is not None
            and self.base_prefix is not None
            and self.prefix != self.base_prefix
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "command": list(self.command),
            "executable": str(self.executable),
            "version": list(self.version),
            "implementation": self.implementation,
            "architecture": self.architecture,
            "prefix": str(self.prefix) if self.prefix is not None else None,
            "base_prefix": str(self.base_prefix) if self.base_prefix is not None else None,
        }


@dataclass(frozen=True, slots=True)
class BootstrapRequest:
    mode: BootstrapMode
    source_root: Path
    app_paths: AppPaths | None = None
    dev: bool = False
    repair: bool = False
    no_launch: bool = False
    self_check: bool = False
    deep: bool = False
    json_output: bool = False
    forwarded: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class RuntimeMarker:
    schema: int
    owner: str
    environment_id: str
    mode: BootstrapMode
    environment_path: Path
    source_root: Path
    host: Mapping[str, object]
    runtime: Mapping[str, object]
    created_at: str
    updated_at: str
    dependency_fingerprint: str | None
    healthy: bool

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "owner": self.owner,
            "environment_id": self.environment_id,
            "mode": self.mode.value,
            "environment_path": str(self.environment_path),
            "source_root": str(self.source_root),
            "host": dict(self.host),
            "runtime": dict(self.runtime),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "dependency_fingerprint": self.dependency_fingerprint,
            "healthy": self.healthy,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "RuntimeMarker":
        try:
            return cls(
                schema=int(payload["schema"]),
                owner=str(payload["owner"]),
                environment_id=str(payload["environment_id"]),
                mode=BootstrapMode(str(payload["mode"])),
                environment_path=Path(str(payload["environment_path"])),
                source_root=Path(str(payload["source_root"])),
                host=dict(payload["host"]),  # type: ignore[arg-type]
                runtime=dict(payload["runtime"]),  # type: ignore[arg-type]
                created_at=str(payload["created_at"]),
                updated_at=str(payload["updated_at"]),
                dependency_fingerprint=(
                    None
                    if payload.get("dependency_fingerprint") is None
                    else str(payload["dependency_fingerprint"])
                ),
                healthy=bool(payload["healthy"]),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid UNITI runtime marker") from error


@dataclass(frozen=True, slots=True)
class BootstrapResult:
    environment_path: Path
    runtime_python: Path
    marker: RuntimeMarker
    fingerprint: str
    fast_path: bool
    launched_exit_code: int | None = None


class BootstrapError(RuntimeError):
    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = int(exit_code)
