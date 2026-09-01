"""Qt-free diagnostics snapshot for alpha engineering/support."""

from __future__ import annotations

import platform
import sys
from copy import deepcopy
from collections.abc import Iterable
from typing import Mapping

import uniti
from uniti.resources import automatic_cache_target, pressure_state, probe_memory


def diagnostics_snapshot(
    documents: Iterable[object] = (),
    startup_snapshot: Mapping[str, object] | None = None,
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
        "documents": document_items,
    }
    if startup_snapshot is not None:
        snapshot["startup"] = deepcopy(dict(startup_snapshot))
    return snapshot
