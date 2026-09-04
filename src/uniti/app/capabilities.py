"""Bounded runtime, filesystem, and lazy Qt capability probes."""

from __future__ import annotations

import json
import mmap
import os
import platform
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Mapping

from uniti.core.durability import (
    DurabilityAdapter,
    DurabilityLevel,
    DurabilityResult,
    NativeDurabilityAdapter,
)
from uniti.resources import probe_memory

from .paths import AppPaths


class CapabilityStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class CapabilityResult:
    status: CapabilityStatus
    reason: str
    details: Mapping[str, object] = field(default_factory=dict)

    def as_dict(self) -> dict[str, object]:
        return {
            "status": self.status.value,
            "reason": self.reason,
            "details": dict(self.details),
        }


def _available(reason: str, **details: object) -> CapabilityResult:
    return CapabilityResult(CapabilityStatus.AVAILABLE, reason, details)


def _unavailable(reason: str, **details: object) -> CapabilityResult:
    return CapabilityResult(CapabilityStatus.UNAVAILABLE, reason, details)


def _durability_details(result: DurabilityResult) -> dict[str, object]:
    details = result.as_dict()
    details["durability_reason"] = details.pop("reason")
    return details


def _file_handle_result() -> CapabilityResult:
    try:
        import resource

        soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
        return _available("file-handle limit available", soft=int(soft), hard=int(hard))
    except (ImportError, AttributeError, OSError, ValueError):
        return CapabilityResult(
            CapabilityStatus.UNKNOWN,
            "file-handle limit is not exposed by this platform",
        )


def _marker_result(marker_path: Path) -> CapabilityResult:
    if not marker_path.is_file():
        return _unavailable("UNITI runtime ownership marker is missing")
    try:
        payload = json.loads(marker_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return _unavailable("UNITI runtime ownership marker is unreadable")
    if not isinstance(payload, dict) or payload.get("schema") != 1:
        return _unavailable("UNITI runtime ownership marker schema is invalid")
    if payload.get("owner") != "uniti-editor":
        return _unavailable("UNITI runtime ownership does not match")
    if payload.get("healthy") is not True:
        return _unavailable("UNITI runtime is marked unhealthy")
    return _available(
        "UNITI runtime ownership is valid",
        environment_id=payload.get("environment_id"),
        mode=payload.get("mode"),
    )


def probe_runtime(
    paths: AppPaths,
    *,
    marker_path: Path | None = None,
) -> dict[str, CapabilityResult]:
    memory = probe_memory()
    logical_cpu = max(1, os.cpu_count() or 1)
    try:
        disk = shutil.disk_usage(paths.data_dir)
        disk_result = _available("application-data disk is available", free_bytes=disk.free)
    except OSError:
        disk_result = _unavailable("application-data disk usage is unavailable")
    selected_marker = marker_path or (Path(sys.prefix) / ".uniti-runtime.json")
    memory_result = (
        _available(
            "memory calibration available",
            physical_bytes=memory.physical,
            available_bytes=memory.available,
            effective_available_bytes=memory.effective_available,
        )
        if memory.physical > 0
        else CapabilityResult(
            CapabilityStatus.UNKNOWN,
            "physical memory is not exposed by this platform/runtime",
            {
                "physical_bytes": memory.physical,
                "available_bytes": memory.available,
                "effective_available_bytes": memory.effective_available,
            },
        )
    )
    return {
        "python": _available(
            "runtime identity available",
            executable=str(Path(sys.executable).resolve()),
            version=platform.python_version(),
            implementation=platform.python_implementation(),
            architecture=platform.architecture()[0],
            platform=sys.platform,
            system=platform.system(),
            release=platform.release(),
            machine=platform.machine(),
        ),
        "memory": memory_result,
        "cpu": _available("logical CPU count available", logical_count=logical_cpu),
        "disk": disk_result,
        "file_handles": _file_handle_result(),
        "environment_marker": _marker_result(selected_marker),
    }


def probe_filesystem(
    paths: AppPaths,
    *,
    adapter: DurabilityAdapter | None = None,
) -> dict[str, CapabilityResult]:
    paths.temp_dir.mkdir(parents=True, exist_ok=True)
    selected_adapter = adapter if adapter is not None else NativeDurabilityAdapter()
    probe_payload = b"UNITI capability probe"
    stem = f"uniti-capability-{uuid.uuid4().hex}"
    first = paths.temp_dir / f"{stem}.first"
    second = paths.temp_dir / f"{stem}.second"
    results: dict[str, CapabilityResult] = {}
    file_synced = False
    replaced = False
    directory_synced = False
    failure_reason: str | None = None
    try:
        try:
            with first.open("wb") as handle:
                handle.write(probe_payload)
                handle.flush()
            results["write"] = _available("temporary write succeeded")
        except OSError as error:
            results["write"] = _unavailable("temporary write failed")
            failure_reason = f"write:{type(error).__name__}"
            try:
                directory_available = (
                    selected_adapter.sync_directory(paths.temp_dir) is True
                )
            except OSError:
                directory_available = False
            results["directory_sync"] = (
                _available("directory sync succeeded")
                if directory_available
                else _unavailable("directory sync is unavailable")
            )
            results["durability"] = _unavailable(
                "safe atomic publication is unavailable",
                **_durability_details(
                    DurabilityResult(
                        "filesystem_probe",
                        DurabilityLevel.UNSAFE,
                        False,
                        False,
                        False,
                        failure_reason,
                    )
                ),
            )
            return results

        try:
            with first.open("r+b") as handle:
                handle.flush()
                selected_adapter.sync_file(handle.fileno())
            file_synced = True
            results["fsync"] = _available("file fsync succeeded")
        except OSError as error:
            results["fsync"] = _unavailable("file fsync is unavailable")
            failure_reason = f"file_sync:{type(error).__name__}"

        try:
            with second.open("wb") as handle:
                handle.write(probe_payload)
                handle.flush()
                selected_adapter.sync_file(handle.fileno())
            selected_adapter.replace(second, first)
            replaced = True
            results["atomic_replace"] = _available("atomic replace succeeded")
        except OSError as error:
            results["atomic_replace"] = _unavailable("atomic replace failed")
            if failure_reason is None:
                failure_reason = f"replace:{type(error).__name__}"

        try:
            directory_synced = selected_adapter.sync_directory(paths.temp_dir) is True
        except OSError as error:
            directory_synced = False
            if failure_reason is None:
                failure_reason = f"directory_sync:{type(error).__name__}"
        results["directory_sync"] = (
            _available("directory sync succeeded")
            if directory_synced
            else _unavailable("directory sync is unavailable")
        )

        if file_synced and replaced:
            level = (
                DurabilityLevel.FULL
                if directory_synced
                else DurabilityLevel.FILE_SYNCED
            )
            reason = (
                None
                if directory_synced
                else failure_reason or "directory_sync_unavailable"
            )
        else:
            level = DurabilityLevel.UNSAFE
            directory_synced = False
            reason = failure_reason or "atomic_publication_unavailable"
        durability = DurabilityResult(
            "filesystem_probe",
            level,
            file_synced,
            replaced,
            directory_synced,
            reason,
        )
        results["durability"] = (
            _available(
                "safe atomic publication is available",
                **_durability_details(durability),
            )
            if level is not DurabilityLevel.UNSAFE
            else _unavailable(
                "safe atomic publication is unavailable",
                **_durability_details(durability),
            )
        )

        try:
            with first.open("r+b") as handle:
                with mmap.mmap(handle.fileno(), 0, access=mmap.ACCESS_READ) as mapped:
                    _ = mapped[:1]
            results["mmap"] = _available("memory mapping succeeded")
        except (OSError, ValueError):
            results["mmap"] = _unavailable("memory mapping is unavailable")

        if hasattr(os, "setxattr") and hasattr(os, "removexattr"):
            try:
                os.setxattr(first, b"user.uniti.probe", b"1")
                os.removexattr(first, b"user.uniti.probe")
                results["xattrs"] = _available("extended attributes succeeded")
            except OSError:
                results["xattrs"] = _unavailable("extended attributes are unavailable")
        else:
            results["xattrs"] = CapabilityResult(
                CapabilityStatus.UNKNOWN,
                "extended attributes are not exposed by this runtime",
            )
        return results
    finally:
        for path in (first, second):
            try:
                path.unlink()
            except FileNotFoundError:
                pass


def probe_qt(app: object | None = None) -> dict[str, CapabilityResult]:
    try:
        import PySide6
        from PySide6.QtCore import QLibraryInfo, qVersion
        from PySide6.QtGui import QFontDatabase, QGuiApplication
        from PySide6.QtWidgets import QApplication
    except (ImportError, ModuleNotFoundError):
        return {"qt": _unavailable("PySide6 is not installed")}

    application = app or QApplication.instance()
    if application is None:
        return {"qt": _unavailable("QApplication has not been created")}
    gui = QGuiApplication.instance()
    try:
        font = QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)
        font_result = _available("fixed-width font resolved", family=font.family())
    except Exception:
        font_result = _unavailable("fixed-width font resolution failed")
    clipboard = gui.clipboard() if gui is not None else None
    input_method = gui.inputMethod() if gui is not None else None
    screens = gui.screens() if gui is not None else []
    return {
        "qt": _available(
            "Qt application is available",
            pyside_version=PySide6.__version__,
            qt_version=qVersion(),
            platform_plugin=QGuiApplication.platformName(),
            plugins_path=QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath),
        ),
        "font": font_result,
        "clipboard": (
            _available(
                "clipboard is available",
                selection_supported=bool(clipboard.supportsSelection()),
            )
            if clipboard is not None
            else _unavailable("clipboard is unavailable")
        ),
        "input_method": (
            _available("input method is available", visible=bool(input_method.isVisible()))
            if input_method is not None
            else _unavailable("input method is unavailable")
        ),
        "screens": _available(
            "display information is available",
            count=len(screens),
            displays=[
                {
                    "name": screen.name(),
                    "logical_dpi": screen.logicalDotsPerInch(),
                    "device_pixel_ratio": screen.devicePixelRatio(),
                }
                for screen in screens
            ],
        ),
    }
