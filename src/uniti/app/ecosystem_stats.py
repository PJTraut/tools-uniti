"""Qt-free stats of the UNITI ecosystem for the management window (N33):
open files and projects per environment, memory, cache and recovery sizes,
and the undo caches of closed files with when they expire."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EnvironmentCount:
    key: str
    files: int
    projects: int  # Paratext projects among the files; 0 where it doesn't apply


@dataclass(frozen=True, slots=True)
class UndoCache:
    name: str
    closed_at: datetime
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class EcosystemStats:
    open_files: int
    windows: int
    environments: tuple[EnvironmentCount, ...]
    process_rss: int | None
    cache_used: int | None
    cache_budget: int | None
    recovery_bytes: int | None
    undo_caches: tuple[UndoCache, ...] = field(default=())


def directory_size(path: Path | None) -> int | None:
    """Bytes under `path`; None when it can't be read."""

    if path is None:
        return None
    total = 0
    try:
        for root, _dirs, files in os.walk(path):
            for name in files:
                try:
                    total += os.path.getsize(os.path.join(root, name))
                except OSError:
                    continue
    except OSError:
        return None
    return total


def format_bytes(value: int | None) -> str:
    if value is None:
        return "unknown"
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{value} B"


def format_remaining(expires_at: datetime, now: datetime) -> str:
    seconds = int((expires_at - now).total_seconds())
    if seconds <= 0:
        return "expires now"
    days, rest = divmod(seconds, 86400)
    hours = rest // 3600
    if days:
        return f"expires in {days} d {hours} h"
    minutes = rest % 3600 // 60
    return f"expires in {hours} h {minutes} min" if hours else f"expires in {minutes} min"


def collect_stats(service, *, recovery_bytes: int | None = None) -> EcosystemStats:
    """The numbers of `service` now. `recovery_bytes` is passed in because
    walking the recovery folder is slow enough to cache."""

    from uniti.core.environments.catalog import descriptor_for_key
    from uniti.core.environments.sfm.paratext_project import project_for_file

    registry = service.documents
    files: dict[str, int] = {}
    projects: dict[str, set[Path]] = {}
    undo: list[UndoCache] = []
    retention = registry.closed_history_retention
    for entry in registry.entries:
        if entry.view_ids:
            key = entry.environment_key
            files[key] = files.get(key, 0) + 1
            try:
                project = project_for_file(Path(entry.document.path))
            except Exception:
                project = None
            if project is not None:
                projects.setdefault(key, set()).add(Path(project.folder))
        elif entry.closed_at is not None:
            closed = entry.closed_at if entry.closed_at.tzinfo else entry.closed_at.replace(tzinfo=timezone.utc)
            name = Path(str(entry.document.path)).name or "Untitled"
            undo.append(UndoCache(name, closed, closed + retention))
    undo.sort(key=lambda cache: cache.expires_at)
    status = getattr(service.resources, "status", None)
    try:  # a live sample: the manager's own status only moves on its timer
        sample = service.resources.sample_resources()
    except Exception:
        sample = None
    return EcosystemStats(
        open_files=sum(files.values()),
        windows=service.window_count,
        environments=tuple(
            EnvironmentCount(descriptor_for_key(key).short_label, count, len(projects.get(key, ())))
            for key, count in sorted(files.items())
        ),
        process_rss=getattr(sample, "process_rss", None) or getattr(status, "process_rss", None) or None,
        cache_used=getattr(sample, "cache_used", getattr(status, "cache_used", None)),
        cache_budget=getattr(status, "cache_budget", None),
        recovery_bytes=recovery_bytes,
        undo_caches=tuple(undo),
    )
