"""Ownership-safe UNITI virtual-environment creation, adoption, and locking."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
import venv
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable, Iterator

from uniti.app.atomic_json import atomic_write_json, utc_timestamp
from uniti.app.process_liveness import process_is_live

from .discovery import query_python, runtime_python
from .model import BootstrapError, BootstrapMode, HostPython, RuntimeMarker

RUNTIME_MARKER_SCHEMA = 1
RUNTIME_MARKER_NAME = ".uniti-runtime.json"
RUNTIME_OWNER = "uniti-editor"


@dataclass(frozen=True, slots=True)
class BootstrapLock:
    session_id: str
    pid: int
    path: Path


class EnvironmentManager:
    def __init__(
        self,
        *,
        source_root: Path,
        environment_path: Path,
        mode: BootstrapMode,
        host: HostPython,
        platform_name: str | None = None,
        query: Callable[[tuple[str, ...]], HostPython] | None = None,
        builder_factory: Callable[[], object] | None = None,
    ) -> None:
        self.source_root = Path(source_root).resolve()
        self.environment_path = Path(environment_path).resolve()
        self.mode = mode
        self.host = host
        self.platform_name = sys.platform if platform_name is None else platform_name
        self._query = query or (lambda command: query_python(command))
        self._builder_factory = builder_factory or (
            lambda: venv.EnvBuilder(with_pip=True, clear=False)
        )

    @property
    def marker_path(self) -> Path:
        return self.environment_path / RUNTIME_MARKER_NAME

    @property
    def environment_id(self) -> str:
        identity = f"{RUNTIME_OWNER}\0{self.mode.value}\0{self.environment_path}"
        return hashlib.sha256(identity.encode("utf-8")).hexdigest()[:24]

    @property
    def lock_path(self) -> Path:
        return self.environment_path.parent / f".uniti-bootstrap-{self.environment_id}.lock"

    @property
    def expected_runtime(self) -> Path:
        return runtime_python(self.environment_path, self.platform_name)

    def new_marker(self) -> RuntimeMarker:
        now = utc_timestamp()
        return RuntimeMarker(
            schema=RUNTIME_MARKER_SCHEMA,
            owner=RUNTIME_OWNER,
            environment_id=self.environment_id,
            mode=self.mode,
            environment_path=self.environment_path,
            source_root=self.source_root,
            host=self.host.as_dict(),
            runtime={},
            created_at=now,
            updated_at=now,
            dependency_fingerprint=None,
            healthy=False,
        )

    def _write_marker(self, marker: RuntimeMarker) -> None:
        atomic_write_json(self.marker_path, marker.as_dict())

    def _read_marker(self) -> RuntimeMarker | None:
        if not self.marker_path.exists():
            return None
        try:
            payload = json.loads(self.marker_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
            marker = RuntimeMarker.from_dict(payload)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
            raise BootstrapError("UNITI runtime ownership marker is invalid", 11) from error
        return marker

    def _validate_marker(self, marker: RuntimeMarker) -> None:
        matches = (
            marker.schema == RUNTIME_MARKER_SCHEMA
            and marker.owner == RUNTIME_OWNER
            and marker.environment_id == self.environment_id
            and marker.mode is self.mode
            and marker.environment_path.resolve() == self.environment_path
        )
        if self.mode is BootstrapMode.SOURCE:
            matches = matches and marker.source_root.resolve() == self.source_root
        if not matches:
            raise BootstrapError("UNITI runtime ownership marker does not match this target", 11)

    def _validate_runtime(self) -> HostPython:
        runtime = self.expected_runtime
        if not runtime.is_file():
            raise BootstrapError("UNITI runtime Python is missing; run bootstrap with --repair", 11)
        try:
            identity = self._query((str(runtime),))
        except BootstrapError as error:
            raise BootstrapError("UNITI runtime Python failed validation", 11) from error
        if not identity.supported or not identity.is_virtual_environment:
            raise BootstrapError("UNITI runtime is not a supported virtual environment", 11)
        return identity

    def _finish_environment(self, marker: RuntimeMarker) -> tuple[Path, RuntimeMarker]:
        identity = self._validate_runtime()
        updated = replace(
            marker,
            runtime=identity.as_dict(),
            updated_at=utc_timestamp(),
            healthy=False,
        )
        self._write_marker(updated)
        return self.expected_runtime, updated

    def _create_marked_environment(self) -> tuple[Path, RuntimeMarker]:
        self.environment_path.mkdir(parents=True, exist_ok=False)
        marker = self.new_marker()
        self._write_marker(marker)
        try:
            builder = self._builder_factory()
            create = getattr(builder, "create")
            create(self.environment_path)
            return self._finish_environment(marker)
        except BootstrapError:
            raise
        except Exception as error:
            raise BootstrapError(
                "UNITI runtime creation is incomplete; run bootstrap with --repair", 11
            ) from error

    def _adopt_source_environment(self) -> tuple[Path, RuntimeMarker]:
        expected = self.source_root / ".venv"
        if self.environment_path != expected.resolve():
            raise BootstrapError("source runtime must be exactly <source-root>/.venv", 11)
        if not (self.environment_path / "pyvenv.cfg").is_file():
            raise BootstrapError("source .venv is not a valid virtual environment", 11)
        identity = self._validate_runtime()
        marker = replace(self.new_marker(), runtime=identity.as_dict())
        self._write_marker(marker)
        return self.expected_runtime, marker

    def ensure(self, *, repair: bool = False) -> tuple[Path, RuntimeMarker]:
        if not self.environment_path.exists():
            return self._create_marked_environment()
        if not self.environment_path.is_dir():
            raise BootstrapError("UNITI runtime target is not a directory", 11)
        marker = self._read_marker()
        if marker is None:
            if self.mode is BootstrapMode.SOURCE:
                return self._adopt_source_environment()
            raise BootstrapError("existing local runtime is not UNITI-owned", 11)
        self._validate_marker(marker)
        try:
            identity = self._validate_runtime()
        except BootstrapError:
            if not repair:
                raise
            try:
                builder = self._builder_factory()
                getattr(builder, "create")(self.environment_path)
                identity = self._validate_runtime()
            except BootstrapError:
                raise
            except Exception as error:
                raise BootstrapError("UNITI runtime repair failed", 11) from error
        updated = replace(marker, runtime=identity.as_dict(), updated_at=utc_timestamp())
        self._write_marker(updated)
        return self.expected_runtime, updated

    def mark_healthy(self, marker: RuntimeMarker, fingerprint: str) -> RuntimeMarker:
        self._validate_marker(marker)
        updated = replace(
            marker,
            source_root=self.source_root,
            dependency_fingerprint=fingerprint,
            healthy=True,
            updated_at=utc_timestamp(),
        )
        self._write_marker(updated)
        return updated

    def _preserve_stale_lock(self) -> None:
        suffix = utc_timestamp().replace(":", "").replace("-", "").replace(".", "")
        stale_path = self.lock_path.with_name(f"{self.lock_path.name}.{suffix}.stale")
        os.replace(self.lock_path, stale_path)

    @contextmanager
    def lock(self) -> Iterator[BootstrapLock]:
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        if self.lock_path.exists():
            try:
                existing = json.loads(self.lock_path.read_text(encoding="utf-8"))
                pid = int(existing.get("pid", 0)) if isinstance(existing, dict) else 0
            except (OSError, ValueError, json.JSONDecodeError):
                pid = 0
            if process_is_live(pid):
                raise BootstrapError(f"bootstrap is already running as PID {pid}", 11)
            self._preserve_stale_lock()

        session_id = uuid.uuid4().hex
        payload = {
            "schema": 1,
            "session_id": session_id,
            "pid": os.getpid(),
            "timestamp": utc_timestamp(),
            "mode": self.mode.value,
            "target": str(self.environment_path),
        }
        try:
            descriptor = os.open(
                self.lock_path,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
        except FileExistsError as error:
            raise BootstrapError("another bootstrap acquired the runtime lock", 11) from error
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            acquired = BootstrapLock(session_id, os.getpid(), self.lock_path)
            yield acquired
        finally:
            try:
                current = json.loads(self.lock_path.read_text(encoding="utf-8"))
                if current.get("session_id") == session_id:
                    self.lock_path.unlink()
            except (OSError, AttributeError, json.JSONDecodeError):
                pass
