"""Bounded resource checkpoints for sustained workload families."""

from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from pathlib import Path

from benchmarks.sustained_models import ResourceCheckpoint
from uniti.resources.memory import current_process_handle_count
from uniti.resources.policy import PerformancePolicy


_TRACKED_COUNT_NAMES = {
    "result_stores",
    "replacement_plans",
    "snapshots",
}


def _nonnegative_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


def _owned_path_count(root: Path, *, limit: int) -> tuple[int, bool]:
    """Count entries beneath root without following links or exceeding limit."""

    count = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        try:
            with os.scandir(directory) as entries:
                for entry in entries:
                    if count == limit:
                        return count, False
                    count += 1
                    if entry.is_dir(follow_symlinks=False):
                        pending.append(Path(entry.path))
        except OSError:
            return count, False
    return count, True


def collect_resource_checkpoint(
    cycle: int,
    *,
    service: object,
    owned_root: Path,
    policy: PerformancePolicy,
    tracked_counts: Mapping[str, int],
    handle_probe: Callable[[], int | None] = current_process_handle_count,
    directory_entry_limit: int | None = None,
) -> ResourceCheckpoint:
    """Capture fixed service facts and capped state beneath one owned root."""

    if not isinstance(owned_root, Path):
        raise TypeError("owned_root must be a Path")
    root = owned_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("owned_root must resolve to a directory")
    if not isinstance(policy, PerformancePolicy):
        raise TypeError("policy must be a PerformancePolicy")
    if not callable(handle_probe):
        raise TypeError("handle_probe must be callable")
    unknown_counts = set(tracked_counts) - _TRACKED_COUNT_NAMES
    if unknown_counts:
        raise ValueError(f"unknown tracked counts: {sorted(unknown_counts)}")
    normalized_counts = {
        name: _nonnegative_integer(tracked_counts.get(name, 0), name)
        for name in sorted(_TRACKED_COUNT_NAMES)
    }
    default_entry_limit = policy.evidence.suite_max_decoded_mib * 1024
    entry_limit = (
        default_entry_limit
        if directory_entry_limit is None
        else _nonnegative_integer(directory_entry_limit, "directory entry limit")
    )

    resources = getattr(service, "resources")
    sample = resources.sample_resources()
    task_snapshot = resources.tasks.snapshot()
    documents = getattr(service, "documents")
    windows = getattr(service, "windows")
    temp_paths, complete = _owned_path_count(root, limit=entry_limit)

    metrics = {
        "rss_mib": _nonnegative_integer(sample.process_rss, "process RSS")
        / float(1 << 20),
        "cache_used_mib": _nonnegative_integer(sample.cache_used, "cache use")
        / float(1 << 20),
    }
    unavailable: list[str] = []
    try:
        handle_count = handle_probe()
    except Exception:
        handle_count = None
    if handle_count is None:
        unavailable.append("handle_count")
    else:
        metrics["handle_count"] = float(
            _nonnegative_integer(handle_count, "handle count")
        )
    if not complete:
        unavailable.append("temp_paths")

    owned_counts = {
        "documents": _nonnegative_integer(documents.count, "document count"),
        "views": len(tuple(windows.ordered_view_ids)),
        "active_workers": _nonnegative_integer(
            sample.active_workers, "active worker count"
        ),
        "active_tasks": _nonnegative_integer(
            task_snapshot.active_count, "active task count"
        ),
        "queued_tasks": _nonnegative_integer(
            task_snapshot.queued_count, "queued task count"
        ),
        **normalized_counts,
        "temp_paths": temp_paths,
    }
    return ResourceCheckpoint(
        cycle=cycle,
        metrics=metrics,
        owned_counts=owned_counts,
        unavailable_probes=tuple(unavailable),
    )
