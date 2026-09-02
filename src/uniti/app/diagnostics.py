"""Qt-free diagnostics snapshot for alpha engineering/support."""

from __future__ import annotations

import platform
import sys
import tempfile
from copy import deepcopy
from collections.abc import Iterable
from pathlib import Path
from typing import Mapping

import uniti
from uniti.resources import (
    ResourceManager,
    ResourceSampler,
    automatic_cache_target,
    classify_resource_state,
    load_performance_policy,
    pressure_state,
    probe_host_profile,
    probe_memory,
)


def diagnostics_snapshot(
    documents: Iterable[object] = (),
    startup_snapshot: Mapping[str, object] | None = None,
    *,
    resource_manager: ResourceManager | None = None,
) -> dict[str, object]:
    memory = probe_memory()
    document_items: list[dict[str, object]] = []
    for document in documents:
        document_items.append(
            {
                "path": str(document.path),
                "source_size_bytes": int(document.source.size),
                "detected_encoding": str(document.encoding_info.detected),
                "output_encoding": str(document.output_encoding),
                "output_eol": document.output_eol,
                "modified": bool(document.modified),
                "offset_index_complete": bool(document.offset_mapper.complete),
                "source_line_index_complete": bool(document.source_line_index.complete),
                "line_index_complete": bool(document.document_line_index.complete),
            }
        )

    if resource_manager is None:
        profile = probe_host_profile(Path(tempfile.gettempdir()))
        live = ResourceSampler(profile).sample(
            cache_used_bytes=0,
            active_workers=0,
            queued_tasks=0,
        )
        resource_state = classify_resource_state(
            live,
            load_performance_policy(),
        )
        resource_items = {
            "state": resource_state.value,
            "available_memory_bytes": live.available_memory,
            "process_rss_bytes": live.process_rss,
            "load_per_logical_core": live.load_per_logical_core,
            "free_disk_bytes": live.free_disk,
            "cache_used_bytes": 0,
            "cache_budget_bytes": automatic_cache_target(memory),
            "active_workers": 0,
            "active_worker_limit": 0,
            "queued_tasks": 0,
        }
        task_snapshot = None
    else:
        profile = resource_manager.host_profile
        status = resource_manager.status
        resource_items = {
            "state": status.state.value,
            "available_memory_bytes": status.available_memory,
            "process_rss_bytes": status.process_rss,
            "load_per_logical_core": status.load_per_logical_core,
            "free_disk_bytes": status.free_disk,
            "cache_used_bytes": status.cache_used,
            "cache_budget_bytes": status.cache_budget,
            "active_workers": status.active_workers,
            "active_worker_limit": status.active_worker_limit,
            "queued_tasks": status.queued_tasks,
        }
        task_snapshot = resource_manager.tasks.snapshot()

    task_items: list[dict[str, object]] = []
    if task_snapshot is not None:
        for task in task_snapshot.tasks:
            progress = task.progress
            task_items.append(
                {
                    "task_id": task.spec.task_id,
                    "kind": task.spec.kind.value,
                    "state": task.state.value,
                    "foreground": task.spec.foreground,
                    "document_key": task.spec.document_key,
                    "revision": task.spec.revision,
                    "progress": (
                        None
                        if progress is None
                        else {
                            "phase": progress.phase,
                            "completed": progress.completed,
                            "total": progress.total,
                            "cancellable": progress.cancellable,
                        }
                    ),
                }
            )

    snapshot = {
        "uniti": {
            "display_version": uniti.__display_version__,
            "package_version": uniti.__version__,
        },
        "runtime": {
            "python": platform.python_version(),
            "implementation": platform.python_implementation(),
            "platform": sys.platform,
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
        },
        "memory": {
            "physical_bytes": memory.physical,
            "available_bytes": memory.available,
            "effective_available_bytes": memory.effective_available,
            "automatic_cache_target_bytes": automatic_cache_target(memory),
            "pressure": pressure_state(memory).value,
        },
        "host": {
            "cpu_model": profile.cpu_model,
            "architecture": profile.architecture,
            "physical_cores": profile.physical_cores,
            "logical_cores": profile.logical_cores,
            "physical_memory_bytes": profile.physical_memory,
            "platform": profile.platform,
            "platform_release": profile.platform_release,
            "temp_root": str(profile.temp_root),
        },
        "resources": resource_items,
        "tasks": {
            "background_paused": (
                False
                if task_snapshot is None
                else task_snapshot.background_paused
            ),
            "items": task_items,
        },
        "documents": document_items,
    }
    if startup_snapshot is not None:
        snapshot["startup"] = deepcopy(dict(startup_snapshot))
    return snapshot
