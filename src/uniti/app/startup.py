"""Qt-free ordered startup coordination and bounded lifecycle logging."""

from __future__ import annotations

import json
import os
import time
import traceback
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

from .atomic_json import utc_timestamp
from .paths import AppPaths
from .setup_state import SetupStateStore


class ExitCode(IntEnum):
    SUCCESS = 0
    INTERNAL = 1
    USAGE = 2
    RUNTIME = 10
    ENVIRONMENT = 11
    DEPENDENCIES = 12
    STATE = 13
    FUNCTIONAL = 14
    GUI = 15


class StartupPhase(IntEnum):
    BOOT = 0
    RUNTIME_IDENTITY = 1
    ENVIRONMENT_VALIDATION = 2
    DEPENDENCY_VALIDATION = 3
    APPLICATION_PATHS = 4
    SCHEMA_MIGRATIONS = 5
    SETTINGS_LOAD = 6
    RESOURCE_CALIBRATION = 7
    STALE_STATE_CLEANUP = 8
    RECOVERY_DISCOVERY = 9
    GUI_CAPABILITIES = 10
    SESSION_RESTORE = 11
    READY = 12


class StartupFailure(RuntimeError):
    def __init__(
        self,
        phase: StartupPhase,
        exit_code: ExitCode,
        safe_message: str,
        cause: BaseException | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.phase = phase
        self.exit_code = exit_code
        self.safe_message = safe_message
        self.cause = cause


def _serialize(value: object) -> object:
    if hasattr(value, "as_dict") and callable(value.as_dict):
        return _serialize(value.as_dict())
    if isinstance(value, Mapping):
        return {str(key): _serialize(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_serialize(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if hasattr(value, "value"):
        return _serialize(value.value)
    return str(value)


@dataclass(slots=True)
class StartupContext:
    paths: AppPaths
    session_id: str
    phase: StartupPhase = StartupPhase.BOOT
    state: dict[str, object] = field(default_factory=dict)
    identity: dict[str, object] = field(default_factory=dict)
    resources: object | None = None
    settings: object | None = None
    recovery_candidates: tuple[object, ...] = ()
    capabilities: dict[str, object] = field(default_factory=dict)
    diagnostics: dict[str, object] = field(default_factory=dict)
    data: dict[str, object] = field(default_factory=dict)
    _cleanups: list[Callable[[], object]] = field(default_factory=list)

    @classmethod
    def create(cls, paths: AppPaths, *, session_id: str) -> "StartupContext":
        return cls(paths=paths, session_id=session_id)

    def advance(self, phase: StartupPhase) -> None:
        expected = StartupPhase(int(self.phase) + 1)
        if phase is not expected:
            raise ValueError(
                f"illegal startup phase transition {self.phase.name} -> {phase.name}"
            )
        self.phase = phase

    def register_cleanup(self, callback: Callable[[], object]) -> None:
        self._cleanups.append(callback)

    def cleanup(self) -> tuple[str, ...]:
        errors: list[str] = []
        while self._cleanups:
            callback = self._cleanups.pop()
            try:
                callback()
            except Exception as error:
                errors.append(type(error).__name__)
        return tuple(errors)

    def snapshot(self) -> dict[str, object]:
        return {
            "session_id": self.session_id,
            "phase": self.phase.name,
            "identity": _serialize(self.identity),
            "install": _serialize(self.state.get("install", {})),
            "dependencies": _serialize(self.state.get("dependencies", {})),
            "schemas": _serialize(self.state.get("schemas", {})),
            "resources": _serialize(self.resources),
            "capabilities": _serialize(self.capabilities),
            "timestamps": {
                "last_bootstrap": self.state.get("last_bootstrap"),
                "last_startup_attempt": self.state.get("last_startup_attempt"),
                "last_successful_startup": self.state.get("last_successful_startup"),
            },
        }


class StartupLog:
    def __init__(
        self,
        path: Path,
        *,
        max_bytes: int = 5 * 1024 * 1024,
        max_rotated: int = 10,
    ) -> None:
        if max_bytes <= 0 or max_rotated < 0:
            raise ValueError("startup log bounds must be positive")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.max_rotated = max_rotated

    def _rotate(self) -> None:
        if self.max_rotated == 0:
            try:
                self.path.unlink()
            except FileNotFoundError:
                pass
            return
        oldest = self.path.with_name(f"{self.path.name}.{self.max_rotated}")
        try:
            oldest.unlink()
        except FileNotFoundError:
            pass
        for index in range(self.max_rotated - 1, 0, -1):
            source = self.path.with_name(f"{self.path.name}.{index}")
            destination = self.path.with_name(f"{self.path.name}.{index + 1}")
            if source.exists():
                os.replace(source, destination)
        if self.path.exists():
            os.replace(self.path, self.path.with_name(f"{self.path.name}.1"))

    def append(self, record: Mapping[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(
            _serialize(record), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ) + "\n"
        encoded_size = len(line.encode("utf-8"))
        try:
            current_size = self.path.stat().st_size
        except FileNotFoundError:
            current_size = 0
        if current_size and current_size + encoded_size > self.max_bytes:
            self._rotate()
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(line)
            handle.flush()


class StartupCoordinator:
    def __init__(self, state_store: SetupStateStore, startup_log: StartupLog) -> None:
        self.state_store = state_store
        self.startup_log = startup_log

    def _save_phase(
        self,
        context: StartupContext,
        *,
        ok: bool,
        duration_ms: float,
        failure: StartupFailure | None = None,
    ) -> None:
        startup = {
            "ok": bool(ok and context.phase is StartupPhase.READY),
            "stage": context.phase.name,
            "failure_code": int(failure.exit_code) if failure is not None else None,
            "failure_message": failure.safe_message if failure is not None else None,
            "fast_path": bool(context.data.get("fast_path", False)),
            "duration_ms": round(duration_ms, 3),
        }
        context.state["startup"] = startup
        context.state["session_id"] = context.session_id
        context.state["capabilities"] = _serialize(context.capabilities)
        if context.resources is not None:
            context.state["resources"] = _serialize(context.resources)
        if context.phase is StartupPhase.READY and ok:
            context.state["last_successful_startup"] = utc_timestamp()
        self.state_store.save(context.state)

    def run(
        self,
        context: StartupContext,
        callbacks: Mapping[StartupPhase, Callable[[StartupContext], object | None]],
    ) -> StartupContext:
        context.paths.state_dir.mkdir(parents=True, exist_ok=True)
        context.paths.log_dir.mkdir(parents=True, exist_ok=True)
        context.state = self.state_store.prepare()
        context.state["last_startup_attempt"] = utc_timestamp()
        self._save_phase(context, ok=False, duration_ms=0.0)
        self.startup_log.append(
            {"timestamp": utc_timestamp(), "phase": "BOOT", "status": "pass", "duration_ms": 0.0}
        )

        for phase in list(StartupPhase)[1:]:
            started = time.perf_counter()
            context.advance(phase)
            callback = callbacks.get(phase)
            if callback is None:
                failure = StartupFailure(
                    phase, ExitCode.INTERNAL, f"startup callback missing for {phase.name}"
                )
                self._record_failure(context, failure, started, traceback_text=None)
                context.cleanup()
                raise failure
            try:
                callback(context)
            except StartupFailure as failure:
                self._record_failure(context, failure, started, traceback_text=None)
                context.cleanup()
                raise
            except BaseException as cause:
                failure = StartupFailure(
                    phase,
                    ExitCode.INTERNAL,
                    "unexpected internal startup failure",
                    cause,
                )
                self._record_failure(
                    context,
                    failure,
                    started,
                    traceback_text=traceback.format_exc(),
                )
                context.cleanup()
                raise failure from cause
            duration = (time.perf_counter() - started) * 1000.0
            self._save_phase(context, ok=True, duration_ms=duration)
            self.startup_log.append(
                {
                    "timestamp": utc_timestamp(),
                    "phase": phase.name,
                    "status": "pass",
                    "duration_ms": round(duration, 3),
                }
            )
        context.diagnostics = context.snapshot()
        return context

    def _record_failure(
        self,
        context: StartupContext,
        failure: StartupFailure,
        started: float,
        *,
        traceback_text: str | None,
    ) -> None:
        duration = (time.perf_counter() - started) * 1000.0
        self._save_phase(context, ok=False, duration_ms=duration, failure=failure)
        record: dict[str, object] = {
            "timestamp": utc_timestamp(),
            "phase": context.phase.name,
            "status": "fail",
            "exit_code": int(failure.exit_code),
            "message": failure.safe_message,
            "duration_ms": round(duration, 3),
        }
        if traceback_text is not None:
            record["traceback"] = traceback_text
        self.startup_log.append(record)
