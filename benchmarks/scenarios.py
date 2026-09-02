"""Initial a18 user-experience scenarios executed in isolated children."""

from __future__ import annotations

import gc
import hashlib
import os
import tempfile
import time
from pathlib import Path

from benchmarks.corpus import CorpusKind, CorpusManifest
from benchmarks.models import MetricSample, ScenarioResult
from uniti.resources import (
    ResourceManager,
    current_process_rss_bytes,
    peak_process_rss_bytes,
    probe_memory,
)


def _rss_facts(start_current: int, start_peak: int) -> tuple[float, float]:
    gc.collect()
    current = current_process_rss_bytes()
    peak = peak_process_rss_bytes()
    peak_delta = max(0, peak - start_peak, current - start_current) / (1 << 20)
    retained_delta = max(0, current - start_current) / (1 << 20)
    return peak_delta, retained_delta


def _digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _open_first_paint(manifest: CorpusManifest) -> ScenarioResult:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    resources = ResourceManager()
    window = UNITIMainWindow(resource_manager=resources)
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    started = time.perf_counter()
    view = window.open_path(manifest.path)
    app.processEvents()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    integrity = view is not None and view.document.path == manifest.path
    window.close_all_documents(force=True)
    window.close()
    resources.shutdown()
    app.processEvents()
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    return ScenarioResult.success(
        scenario="open_first_paint",
        metrics={
            "open_to_usable_ms": MetricSample((elapsed_ms,)),
            "peak_rss_mib": MetricSample((peak_mib,)),
            "retained_rss_mib": MetricSample((retained_mib,)),
        },
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "source_bytes": manifest.spec.size_bytes,
            "integrity_ok": integrity,
        },
    )


def _navigation(manifest: CorpusManifest) -> ScenarioResult:
    if manifest.spec.kind is CorpusKind.SPARSE_FILE:
        from uniti.core.document import Document

        start_current = current_process_rss_bytes()
        start_peak = peak_process_rss_bytes()
        with Document.open(manifest.path, encoding="utf-8") as document:
            started = time.perf_counter()
            target_line = None
            offset = manifest.marker_offsets[-1]
            observed = document.read(offset, offset + len("UNITI_MARKER"))
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            integrity = observed == "UNITI_MARKER"
        interaction_ms = elapsed_ms
        heartbeat_ms = elapsed_ms
        completion_ms = elapsed_ms
    else:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from uniti.ui.main_window import UNITIMainWindow

        app = QApplication.instance() or QApplication([])
        resources = ResourceManager()
        window = UNITIMainWindow(resource_manager=resources)
        start_current = current_process_rss_bytes()
        start_peak = peak_process_rss_bytes()
        view = window.open_path(manifest.path)
        app.processEvents()
        target_line = max(0, (manifest.spec.size_bytes // 32) * 9 // 10)
        started = time.perf_counter()
        accepted = window.go_to_line(target_line + 1)
        interaction_ms = (time.perf_counter() - started) * 1000.0
        heartbeat_ms = 0.0
        deadline = time.perf_counter() + 30.0
        while window._navigation_jobs and time.perf_counter() < deadline:
            heartbeat_started = time.perf_counter()
            app.processEvents()
            heartbeat_ms = max(
                heartbeat_ms,
                (time.perf_counter() - heartbeat_started) * 1000.0,
            )
            time.sleep(0.001)
        heartbeat_started = time.perf_counter()
        app.processEvents()
        heartbeat_ms = max(
            heartbeat_ms,
            (time.perf_counter() - heartbeat_started) * 1000.0,
        )
        completion_ms = (time.perf_counter() - started) * 1000.0
        offset = view.state.cursor if view is not None else -1
        integrity = (
            accepted
            and view is not None
            and not window._navigation_jobs
            and offset == target_line * 32
        )
        window.close_all_documents(force=True)
        window.close()
        resources.shutdown()
        app.processEvents()
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    return ScenarioResult.success(
        scenario="navigation",
        metrics={
            "interaction_max_ms": MetricSample((interaction_ms,)),
            "gui_heartbeat_max_ms": MetricSample((heartbeat_ms,)),
            "navigation_completion_ms": MetricSample((completion_ms,)),
            "peak_rss_mib": MetricSample((peak_mib,)),
            "retained_rss_mib": MetricSample((retained_mib,)),
        },
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "target_line": target_line,
            "target_offset": offset,
            "integrity_ok": integrity,
        },
    )


def _search_sparse(manifest: CorpusManifest) -> ScenarioResult:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.core.document import Document
    from uniti.regex.engine import compile_pattern
    from uniti.regex.search import SearchOptions, search_document
    from uniti.resources import WorkPriority

    app = QApplication.instance() or QApplication([])
    resources = ResourceManager()
    document = Document.open(
        manifest.path,
        encoding="utf-8",
        resource_manager=resources,
    )
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    beats: list[float] = []
    previous = time.perf_counter()

    pattern = "UNITI_MARKER" if manifest.spec.kind is CorpusKind.SPARSE_FILE else "UNITI_MATCH"
    expected_matches = 2 if manifest.spec.kind is CorpusKind.SPARSE_FILE else 3

    def perform() -> int:
        return sum(
            1
            for _ in search_document(
                document,
                compile_pattern(pattern),
                options=SearchOptions(timeout=None, include_captures=False),
            )
        )

    future = resources.workers.submit(WorkPriority.SEARCH, perform)
    while not future.done():
        app.processEvents()
        now = time.perf_counter()
        beats.append((now - previous) * 1000.0)
        previous = now
        time.sleep(0.001)
    matches = future.result()
    beats.append((time.perf_counter() - previous) * 1000.0)
    document.close()
    resources.shutdown()
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    ordered = sorted(beats or [0.0])
    p95 = ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]
    return ScenarioResult.success(
        scenario="search_sparse",
        metrics={
            "gui_heartbeat_p95_ms": MetricSample((p95,)),
            "gui_heartbeat_max_ms": MetricSample((max(ordered),)),
            "peak_rss_mib": MetricSample((peak_mib,)),
            "retained_rss_mib": MetricSample((retained_mib,)),
        },
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "matches": matches,
            "integrity_ok": matches == expected_matches,
        },
    )


def _save_as(manifest: CorpusManifest) -> ScenarioResult:
    from uniti.core.document import Document

    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    descriptor, raw_target = tempfile.mkstemp(prefix="uniti-benchmark-save-", suffix=".txt")
    os.close(descriptor)
    target = Path(raw_target)
    target.unlink()
    try:
        with Document.open(manifest.path, encoding="utf-8") as document:
            started = time.perf_counter()
            document.export_copy(target, output_format=document.output_format)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
        integrity = manifest.digest is None or _digest(target) == manifest.digest
    finally:
        target.unlink(missing_ok=True)
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    return ScenarioResult.success(
        scenario="save_as",
        metrics={
            "interaction_max_ms": MetricSample((elapsed_ms,)),
            "peak_rss_mib": MetricSample((peak_mib,)),
            "retained_rss_mib": MetricSample((retained_mib,)),
        },
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "integrity_ok": integrity,
        },
    )


_SCENARIOS = {
    "open_first_paint": _open_first_paint,
    "navigation": _navigation,
    "search_sparse": _search_sparse,
    "save_as": _save_as,
}


def run_scenario(name: str, manifest: CorpusManifest) -> ScenarioResult:
    try:
        scenario = _SCENARIOS[name]
    except KeyError as error:
        raise ValueError(f"unknown performance scenario: {name}") from error
    return scenario(manifest)


def corpus_kind_for_scenario(name: str) -> CorpusKind:
    if name == "search_sparse":
        return CorpusKind.SEARCH_SPARSE
    if name in _SCENARIOS:
        return CorpusKind.ORDINARY_LINES
    raise ValueError(f"unknown performance scenario: {name}")


def initial_scenario_names(tier: str) -> tuple[str, ...]:
    if tier == "design_target":
        return ("open_first_paint", "navigation", "search_sparse")
    return ("open_first_paint", "navigation", "search_sparse", "save_as")
