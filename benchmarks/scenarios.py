"""Initial a18 user-experience scenarios executed in isolated children."""

from __future__ import annotations

import gc
import hashlib
import os
import tempfile
import threading
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


def _p95(values: list[float]) -> float:
    ordered = sorted(values or [0.0])
    return ordered[min(len(ordered) - 1, max(0, int(len(ordered) * 0.95) - 1))]


def _wait_for_task(app, handle, started: float, *, timeout: float = 180.0):
    """Pump Qt while one coordinated task runs and capture UX timings."""

    heartbeats: list[float] = []
    progress_times: list[float] = []
    seen_progress_at: float | None = None
    deadline = time.perf_counter() + timeout
    while not handle.done and time.perf_counter() < deadline:
        heartbeat_started = time.perf_counter()
        app.processEvents()
        heartbeats.append((time.perf_counter() - heartbeat_started) * 1000.0)
        progress = handle.progress
        if progress is not None and progress.updated_at != seen_progress_at:
            seen_progress_at = progress.updated_at
            progress_times.append(progress.updated_at)
        time.sleep(0.001)
    if not handle.done:
        handle.cancel()
        raise TimeoutError("performance task did not complete before its deadline")
    app.processEvents()
    completed = time.perf_counter()
    progress = handle.progress
    if progress is not None and progress.updated_at != seen_progress_at:
        progress_times.append(progress.updated_at)
    first_progress_ms = (
        (progress_times[0] - started) * 1000.0
        if progress_times
        else (completed - started) * 1000.0
    )
    gaps = [
        (right - left) * 1000.0
        for left, right in zip(progress_times, progress_times[1:])
    ]
    if progress_times:
        gaps.append((completed - progress_times[-1]) * 1000.0)
    return handle.future.result(), {
        "gui_heartbeat_p95_ms": _p95(heartbeats),
        "gui_heartbeat_max_ms": max(heartbeats or [0.0]),
        "first_progress_ms": first_progress_ms,
        "progress_gap_ms": max(gaps or [0.0]),
        "completion_ms": (completed - started) * 1000.0,
    }


def _measure_cancellation(app, handle, *, timeout: float = 5.0) -> tuple[float, bool]:
    """Cancel after observable progress and measure time until worker exit."""

    deadline = time.perf_counter() + timeout
    while handle.progress is None and not handle.done and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.001)
    if handle.done or handle.progress is None:
        return 0.0, False
    started = time.perf_counter()
    handle.cancel()
    while not handle.done and time.perf_counter() < deadline:
        app.processEvents()
        time.sleep(0.001)
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    if not handle.done:
        return elapsed_ms, False
    try:
        payload = handle.future.result()
    except Exception:
        return elapsed_ms, handle.token.cancelled
    close = getattr(payload, "close", None)
    if close is not None:
        close()
    return elapsed_ms, False


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
            observed = document.source.read(offset, len("UNITI_MARKER"))
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            mapped_bytes = document.offset_mapper.indexed_byte_end
            lazy_source_navigation = (
                not document.offset_mapper.complete
                and not document.document_line_index.complete
                and mapped_bytes < 1 << 20
            )
            integrity = observed == b"UNITI_MARKER" and lazy_source_navigation
        interaction_ms = elapsed_ms
        heartbeat_ms = 0.0
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
        mapped_bytes = view.document.offset_mapper.indexed_byte_end
        lazy_source_navigation = False
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
            "mapped_bytes": mapped_bytes,
            "lazy_source_navigation": lazy_source_navigation,
            "integrity_ok": integrity,
        },
    )


def _open_interaction_window(manifest: CorpusManifest):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    resources = ResourceManager()
    window = UNITIMainWindow(resource_manager=resources)
    window.resize(900, 600)
    view = window.open_path(manifest.path)
    window.show()
    view.setFocus()
    app.processEvents()
    view.viewport().repaint()
    app.processEvents()
    return app, resources, window, view


def _close_interaction_window(app, resources, window) -> None:
    window.close_all_documents(force=True)
    window.close()
    resources.shutdown()
    app.processEvents()


def _interaction_metrics(
    timings: list[float],
    start_current: int,
    start_peak: int,
) -> dict[str, MetricSample]:
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    return {
        "interaction_p95_ms": MetricSample((_p95(timings),)),
        "interaction_max_ms": MetricSample((max(timings or [0.0]),)),
        "peak_rss_mib": MetricSample((peak_mib,)),
        "retained_rss_mib": MetricSample((retained_mib,)),
    }


def _measure_gui_action(app, view, action) -> float:
    started = time.perf_counter()
    action()
    view.viewport().repaint()
    app.processEvents()
    return (time.perf_counter() - started) * 1000.0


def _typing(manifest: CorpusManifest) -> ScenarioResult:
    app, resources, window, view = _open_interaction_window(manifest)
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    original = view.document.read(0, 128)
    inserted = "UNITI typing sample "
    timings: list[float] = []
    try:
        for character in inserted:
            timings.append(
                _measure_gui_action(
                    app,
                    view,
                    lambda character=character: (
                        view.state.insert_text(character),
                        view._state_changed(),
                    ),
                )
            )
        edit_ok = view.document.read(0, len(inserted) + len(original)) == inserted + original
        view.document.undo()
        undo_ok = view.document.read(0, len(original)) == original
        one_atomic_typing_undo = not view.document.can_undo
    finally:
        _close_interaction_window(app, resources, window)
    return ScenarioResult.success(
        scenario="typing",
        metrics=_interaction_metrics(timings, start_current, start_peak),
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "keystrokes": len(inserted),
            "one_atomic_typing_undo": one_atomic_typing_undo,
            "integrity_ok": edit_ok and undo_ok and one_atomic_typing_undo,
        },
    )


def _scroll(manifest: CorpusManifest) -> ScenarioResult:
    app, resources, window, view = _open_interaction_window(manifest)
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    revision = view.document.revision
    first = view.document.read(0, 128)
    last_start = max(0, manifest.spec.size_bytes - 128)
    last = view.document.source.read(
        last_start,
        manifest.spec.size_bytes - last_start,
    )
    timings: list[float] = []
    unwrapped_moved = False
    wrapped_moved = False
    try:
        for _ in range(8):
            scrollbar = view.verticalScrollBar()
            before = scrollbar.value()
            timings.append(
                _measure_gui_action(
                    app,
                    view,
                    lambda scrollbar=scrollbar: scrollbar.setValue(
                        min(
                            scrollbar.maximum(),
                            scrollbar.value() + max(1, scrollbar.pageStep() // 2),
                        )
                    ),
                )
            )
            unwrapped_moved = unwrapped_moved or scrollbar.value() != before
        timings.append(
            _measure_gui_action(app, view, lambda: view.set_soft_wrap(True))
        )
        for _ in range(8):
            scrollbar = view.verticalScrollBar()
            before = scrollbar.value()
            timings.append(
                _measure_gui_action(
                    app,
                    view,
                    lambda scrollbar=scrollbar: scrollbar.setValue(
                        min(
                            scrollbar.maximum(),
                            scrollbar.value() + max(1, scrollbar.pageStep() // 2),
                        )
                    ),
                )
            )
            wrapped_moved = wrapped_moved or scrollbar.value() != before
        wrap_index = view._wrapped_row_index()
        resident_rows = wrap_index.resident_row_count
        mapped_bytes = view.document.offset_mapper.indexed_byte_end
        integrity = (
            view.document.revision == revision
            and view.document.read(0, 128) == first
            and view.document.source.read(
                last_start,
                manifest.spec.size_bytes - last_start,
            )
            == last
            and unwrapped_moved
            and wrapped_moved
            and resident_rows <= 2048
        )
    finally:
        _close_interaction_window(app, resources, window)
    return ScenarioResult.success(
        scenario="scroll",
        metrics=_interaction_metrics(timings, start_current, start_peak),
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "unwrapped_scrolled": unwrapped_moved,
            "wrapped_scrolled": wrapped_moved,
            "resident_wrapped_rows": resident_rows,
            "mapped_bytes": mapped_bytes,
            "integrity_read_bytes": len(first) + len(last),
            "integrity_ok": integrity,
        },
    )


def _giant_line(manifest: CorpusManifest) -> ScenarioResult:
    app, resources, window, view = _open_interaction_window(manifest)
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    revision = view.document.revision
    first = view.document.read(0, 128)
    last_start = max(0, manifest.spec.size_bytes - 128)
    last = view.document.source.read(
        last_start,
        manifest.spec.size_bytes - last_start,
    )
    timings: list[float] = []
    horizontal_moved = False
    wrapped_moved = False
    try:
        for _ in range(4):
            scrollbar = view.horizontalScrollBar()
            before = scrollbar.value()
            timings.append(
                _measure_gui_action(
                    app,
                    view,
                    lambda scrollbar=scrollbar: scrollbar.setValue(
                        min(
                            scrollbar.maximum(),
                            scrollbar.value() + max(1, scrollbar.pageStep()),
                        )
                    ),
                )
            )
            horizontal_moved = horizontal_moved or scrollbar.value() != before
        timings.append(
            _measure_gui_action(app, view, lambda: view.set_soft_wrap(True))
        )
        for _ in range(8):
            scrollbar = view.verticalScrollBar()
            before = scrollbar.value()
            timings.append(
                _measure_gui_action(
                    app,
                    view,
                    lambda scrollbar=scrollbar: scrollbar.setValue(
                        min(
                            scrollbar.maximum(),
                            scrollbar.value() + max(1, scrollbar.pageStep() // 2),
                        )
                    ),
                )
            )
            wrapped_moved = wrapped_moved or scrollbar.value() != before
        wrap_index = view._wrapped_row_index()
        resident_rows = wrap_index.resident_row_count
        mapped_bytes = view.document.offset_mapper.indexed_byte_end
        integrity = (
            view.document.revision == revision
            and view.document.read(0, 128) == first
            and view.document.source.read(
                last_start,
                manifest.spec.size_bytes - last_start,
            )
            == last
            and horizontal_moved
            and wrapped_moved
            and resident_rows <= 2048
        )
    finally:
        _close_interaction_window(app, resources, window)
    return ScenarioResult.success(
        scenario="giant_line",
        metrics=_interaction_metrics(timings, start_current, start_peak),
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "horizontal_scrolled": horizontal_moved,
            "wrapped_scrolled": wrapped_moved,
            "resident_wrapped_rows": resident_rows,
            "mapped_bytes": mapped_bytes,
            "integrity_read_bytes": len(first) + len(last),
            "integrity_ok": integrity,
        },
    )


def _resource_recovery(manifest: CorpusManifest) -> ScenarioResult:
    from uniti.resources import CachePriority, ResourceSnapshot, ResourceState

    resources = ResourceManager()
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    normal_worker_limit = resources.workers.max_workers
    normal_cache_budget = resources.cache_budget_bytes
    physical = max(1, resources.status.physical_memory)
    base = {
        "physical_memory": physical,
        "process_rss": current_process_rss_bytes(),
        "load_per_logical_core": 0.0,
        "free_disk": resources.status.free_disk,
        "cache_used": 0,
        "active_workers": 0,
        "queued_tasks": 0,
    }
    timings: list[float] = []
    try:
        resources.put_cache(
            "benchmark",
            "disposable",
            object(),
            size_bytes=min(1 << 20, max(1, normal_cache_budget)),
            priority=CachePriority.STALE,
        )
        started = time.perf_counter()
        critical_state = resources.observe_resources(
            ResourceSnapshot(
                **base,
                available_memory=0,
                captured_at=time.monotonic(),
            )
        )
        timings.append((time.perf_counter() - started) * 1000.0)
        critical_worker_limit = resources.workers.active_limit
        critical_cache_budget = resources.cache_budget_bytes
        cache_released = resources.cache.used_bytes == 0

        resources.pause_background(True)
        pause_visible = resources.status.background_paused
        resources.pause_background(False)
        pause_cleared = not resources.status.background_paused

        recovery_state = critical_state
        for _ in range(resources.policy.pressure.healthier_samples_before_recovery):
            started = time.perf_counter()
            recovery_state = resources.observe_resources(
                ResourceSnapshot(
                    **base,
                    available_memory=physical,
                    captured_at=time.monotonic(),
                )
            )
            timings.append((time.perf_counter() - started) * 1000.0)
        recovered_worker_limit = resources.workers.active_limit
        recovered_cache_budget = resources.cache_budget_bytes
        integrity = (
            critical_state is ResourceState.CRITICAL
            and critical_worker_limit == 1
            and critical_cache_budget <= normal_cache_budget
            and cache_released
            and pause_visible
            and pause_cleared
            and recovery_state is ResourceState.NORMAL
            and recovered_worker_limit == normal_worker_limit
            and recovered_cache_budget == normal_cache_budget
        )
    finally:
        resources.shutdown()
    return ScenarioResult.success(
        scenario="resource_recovery",
        metrics=_interaction_metrics(timings, start_current, start_peak),
        facts={
            "physical_memory_bytes": physical,
            "source_bytes": manifest.spec.size_bytes,
            "normal_worker_limit": normal_worker_limit,
            "critical_worker_limit": critical_worker_limit,
            "recovered_worker_limit": recovered_worker_limit,
            "critical_cache_budget": critical_cache_budget,
            "recovered_cache_budget": recovered_cache_budget,
            "integrity_ok": integrity,
        },
    )


def _search(manifest: CorpusManifest, *, scenario_name: str) -> ScenarioResult:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.core.document import Document
    from uniti.regex.engine import compile_pattern
    from uniti.regex.match_store import MatchStore
    from uniti.regex.search import SearchOptions, search_document
    from uniti.resources import TaskKind, TaskSpec

    app = QApplication.instance() or QApplication([])
    resources = ResourceManager()
    document = Document.open(
        manifest.path,
        encoding="utf-8",
        resource_manager=resources,
    )
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    pattern = "UNITI_MARKER" if manifest.spec.kind is CorpusKind.SPARSE_FILE else "UNITI_MATCH"
    expected_matches = 2 if manifest.spec.kind is CorpusKind.SPARSE_FILE else 3
    dense = manifest.spec.kind is CorpusKind.SEARCH_DENSE
    snapshot = document.snapshot()

    def perform(context):
        store = MatchStore(memory_budget_bytes=64 << 10)
        try:
            with snapshot:
                for record in search_document(
                    snapshot,
                    compile_pattern(pattern),
                    options=SearchOptions(timeout=None, include_captures=False),
                    cancelled=lambda: context.token.cancelled,
                    progress=lambda completed, total: context.report(
                        "Searching", completed, total
                    ),
                ):
                    store.append(record)
        except Exception:
            store.close()
            raise
        return store

    spec = TaskSpec.create(
        TaskKind.SEARCH,
        foreground=True,
        document_key=str(manifest.path),
        revision=document.revision,
        estimated_memory_bytes=2 << 20,
    )
    interaction_started = time.perf_counter()
    handle = resources.tasks.submit(spec, perform)
    interaction_ms = (time.perf_counter() - interaction_started) * 1000.0
    started = interaction_started
    store, timings = _wait_for_task(app, handle, started)
    matches = len(store)
    first = store[0] if matches else None
    last = store[-1] if matches else None
    first_text = b""
    last_text = b""
    if first is not None and last is not None:
        with manifest.path.open("rb") as source:
            source.seek(first.start)
            first_text = source.read(first.end - first.start)
            source.seek(last.start)
            last_text = source.read(last.end - last.start)
    records_valid = (
        first is not None
        and last is not None
        and first_text == pattern.encode("ascii")
        and last_text == pattern.encode("ascii")
    )

    cancel_ms = 0.0
    cancelled = True
    if dense:
        cancel_snapshot = document.snapshot()

        def cancel_work(context):
            with cancel_snapshot:
                matches = 0
                while not context.token.cancelled:
                    matches += sum(
                        1
                        for _ in search_document(
                            cancel_snapshot,
                            compile_pattern(pattern),
                            options=SearchOptions(
                                timeout=None,
                                include_captures=False,
                                progress_chars=64 << 10,
                            ),
                            cancelled=lambda: context.token.cancelled,
                            progress=lambda completed, total: context.report(
                                "Searching", completed, total
                            ),
                        )
                    )
                return matches

        cancel_handle = resources.tasks.submit(
            TaskSpec.create(
                TaskKind.SEARCH,
                foreground=True,
                document_key=str(manifest.path),
                revision=document.revision,
                estimated_memory_bytes=2 << 20,
            ),
            cancel_work,
        )
        cancel_ms, cancelled = _measure_cancellation(app, cancel_handle)

    spilled = store.spilled
    store.close()
    document.close()
    resources.shutdown()
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    metrics = {
        "interaction_max_ms": MetricSample((interaction_ms,)),
        "gui_heartbeat_p95_ms": MetricSample((timings["gui_heartbeat_p95_ms"],)),
        "gui_heartbeat_max_ms": MetricSample((timings["gui_heartbeat_max_ms"],)),
        "first_progress_ms": MetricSample((timings["first_progress_ms"],)),
        "progress_gap_ms": MetricSample((timings["progress_gap_ms"],)),
        "search_completion_ms": MetricSample((timings["completion_ms"],)),
        "peak_rss_mib": MetricSample((peak_mib,)),
        "retained_rss_mib": MetricSample((retained_mib,)),
    }
    if dense:
        metrics["cancel_normal_ms"] = MetricSample((cancel_ms,))
    return ScenarioResult.success(
        scenario=scenario_name,
        metrics=metrics,
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "matches": matches,
            "spilled": spilled,
            "cancelled": cancelled,
            "integrity_ok": (
                records_valid
                and cancelled
                and (matches > 1_000 and spilled if dense else matches == expected_matches)
            ),
        },
    )


def _search_sparse(manifest: CorpusManifest) -> ScenarioResult:
    return _search(manifest, scenario_name="search_sparse")


def _search_dense(manifest: CorpusManifest) -> ScenarioResult:
    return _search(manifest, scenario_name="search_dense")


def _replace(manifest: CorpusManifest) -> ScenarioResult:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.core.document import Document, ReplacementPlanLimitError
    from uniti.regex.engine import compile_pattern
    from uniti.regex.replace import collect_replacement_plan
    from uniti.regex.search import SearchOptions
    from uniti.resources import TaskKind, TaskSpec

    app = QApplication.instance() or QApplication([])
    resources = ResourceManager()
    document = Document.open(
        manifest.path,
        encoding="utf-8",
        resource_manager=resources,
    )
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    compiled = compile_pattern("UNITI_MATCH")
    revision = document.revision
    snapshot = document.snapshot()

    def perform(context):
        with snapshot:
            return collect_replacement_plan(
                snapshot,
                compiled,
                "UNITI_SWAP",
                document_revision=revision,
                memory_budget_bytes=64 << 10,
                options=SearchOptions(timeout=None, include_captures=False),
                cancelled=lambda: context.token.cancelled,
                progress=lambda completed, total: context.report(
                    "Planning replacements", completed, total
                ),
            )

    spec = TaskSpec.create(
        TaskKind.REPLACE,
        foreground=True,
        document_key=str(manifest.path),
        revision=revision,
        estimated_memory_bytes=2 << 20,
    )
    interaction_started = time.perf_counter()
    handle = resources.tasks.submit(spec, perform)
    interaction_ms = (time.perf_counter() - interaction_started) * 1000.0
    plan, timings = _wait_for_task(app, handle, interaction_started)
    planned = len(plan)
    spilled = plan.spilled
    prefix_before = document.read(0, 512)
    safe_refusal = False
    try:
        document.apply_replacement_plan(
            plan,
            expected_revision=revision,
            memory_limit_bytes=16 << 10,
        )
    except ReplacementPlanLimitError:
        safe_refusal = True
    unchanged_after_refusal = document.read(0, 512) == prefix_before
    plan.close()

    small_snapshot = document.snapshot()
    with small_snapshot:
        small_plan = collect_replacement_plan(
            small_snapshot,
            compiled,
            "UNITI_SWAP",
            document_revision=document.revision,
            memory_budget_bytes=1 << 20,
            options=SearchOptions(
                timeout=None,
                max_matches=2,
                include_captures=False,
            ),
        )
    try:
        applied = document.apply_replacement_plan(
            small_plan,
            expected_revision=document.revision,
            memory_limit_bytes=1 << 20,
        )
    finally:
        small_plan.close()
    changed = document.read(0, 512).count("UNITI_SWAP") == 2
    document.undo()
    atomic_undo = document.read(0, 512) == prefix_before

    document.close()
    resources.shutdown()
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    return ScenarioResult.success(
        scenario="replace",
        metrics={
            "interaction_max_ms": MetricSample((interaction_ms,)),
            "gui_heartbeat_p95_ms": MetricSample((timings["gui_heartbeat_p95_ms"],)),
            "gui_heartbeat_max_ms": MetricSample((timings["gui_heartbeat_max_ms"],)),
            "first_progress_ms": MetricSample((timings["first_progress_ms"],)),
            "progress_gap_ms": MetricSample((timings["progress_gap_ms"],)),
            "replace_completion_ms": MetricSample((timings["completion_ms"],)),
            "peak_rss_mib": MetricSample((peak_mib,)),
            "retained_rss_mib": MetricSample((retained_mib,)),
        },
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "planned_replacements": planned,
            "plan_spilled": spilled,
            "safe_refusal": safe_refusal,
            "atomic_undo": atomic_undo,
            "integrity_ok": (
                planned > 1_000
                and spilled
                and safe_refusal
                and unchanged_after_refusal
                and applied == 2
                and changed
                and atomic_undo
            ),
        },
    )


def _regex_intelligence(manifest: CorpusManifest) -> ScenarioResult:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.core.document import Document
    from uniti.regex.analysis import AnalysisState, analyze_pattern
    from uniti.regex.captures import CaptureReportRequest, resolve_capture_report
    from uniti.regex.engine import compile_pattern
    from uniti.regex.match_store import MatchStore
    from uniti.regex.replace import collect_replacement_plan
    from uniti.regex.search import SearchOptions, search_document
    from uniti.resources import TaskKind, TaskSpec

    app = QApplication.instance() or QApplication([])
    resources = ResourceManager()
    document = Document.open(
        manifest.path,
        encoding="utf-8",
        resource_manager=resources,
    )
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    interaction_timings: list[float] = []
    stage_timings: list[dict[str, float]] = []
    store = None
    plan = None
    search_snapshot = None
    report_snapshot = None
    plan_snapshot = None
    cancel_snapshot = None
    cleanup_ok = False
    try:
        analysis_started = time.perf_counter()
        analysis_handle = resources.tasks.submit(
            TaskSpec.create(
                TaskKind.REGEX_ANALYSIS,
                foreground=False,
                estimated_memory_bytes=2 << 20,
            ),
            lambda _context: analyze_pattern(
                r"(?V1)(?P<item>\p{L}+)(?P<item>\p{L}+)"
                r"(?|(\d+)|(\p{L}+))(?P=item)",
                generation=1,
            ),
        )
        interaction_timings.append(
            (time.perf_counter() - analysis_started) * 1000.0
        )
        analysis, analysis_timing = _wait_for_task(
            app,
            analysis_handle,
            analysis_started,
        )
        stage_timings.append(analysis_timing)
        advanced_analysis_ok = (
            analysis.state is AnalysisState.VALID
            and analysis.identities_reconciled
            and analysis.compiled.__class__.__module__ == "_regex"
        )

        zero_width_pattern = compile_pattern(r"(?P<boundary>\b)")
        search_snapshot = document.snapshot()

        def search_work(context):
            result = MatchStore(
                memory_budget_bytes=64 << 10,
                document_revision=document.revision,
            )
            try:
                with search_snapshot:
                    for record in search_document(
                        search_snapshot,
                        zero_width_pattern,
                        options=SearchOptions(
                            timeout=None,
                            max_matches=4096,
                            include_captures=False,
                        ),
                        cancelled=lambda: context.token.cancelled,
                        progress=lambda completed, total: context.report(
                            "Searching zero-width matches",
                            completed,
                            total,
                        ),
                    ):
                        result.append(record)
            except Exception:
                result.close()
                raise
            return result

        search_started = time.perf_counter()
        search_handle = resources.tasks.submit(
            TaskSpec.create(
                TaskKind.SEARCH,
                foreground=True,
                document_key=str(manifest.path),
                revision=document.revision,
                estimated_memory_bytes=2 << 20,
            ),
            search_work,
        )
        interaction_timings.append(
            (time.perf_counter() - search_started) * 1000.0
        )
        store, search_timing = _wait_for_task(app, search_handle, search_started)
        stage_timings.append(search_timing)
        zero_width_matches = len(store)
        search_capture_free = all(
            not store[index].captures for index in range(len(store))
        )

        requested_matches = tuple(
            (index, store[index]) for index in range(min(2, len(store)))
        )
        request = CaptureReportRequest(
            pattern_generation=analysis.generation,
            pattern_text=zero_width_pattern.pattern,
            document_key=str(id(document)),
            revision=document.revision,
            store_id=store.store_id,
            requested_index=0,
            match_count=len(store),
            matches=requested_matches,
        )
        report_snapshot = document.snapshot()

        def report_work(context):
            with report_snapshot:
                return resolve_capture_report(
                    report_snapshot,
                    zero_width_pattern,
                    request,
                    cancelled=lambda: context.token.cancelled,
                )

        report_started = time.perf_counter()
        report_handle = resources.tasks.submit(
            TaskSpec.create(
                TaskKind.CAPTURE_REPORT,
                foreground=False,
                document_key=str(manifest.path),
                revision=document.revision,
                estimated_memory_bytes=2 << 20,
            ),
            report_work,
        )
        interaction_timings.append(
            (time.perf_counter() - report_started) * 1000.0
        )
        report, report_timing = _wait_for_task(app, report_handle, report_started)
        stage_timings.append(report_timing)
        capture_report_bounded = (
            len(report.matches) == 2
            and report.payload_bytes <= 1 << 20
            and all(
                match.unavailable_reason is None
                and len(match.groups) == 1
                and len(match.groups[0].previews) <= 5
                for match in report.matches
            )
        )
        capture_report_matches = len(report.matches)
        capture_report_payload_bytes = report.payload_bytes

        plan_snapshot = document.snapshot()

        def plan_work(context):
            with plan_snapshot:
                return collect_replacement_plan(
                    plan_snapshot,
                    zero_width_pattern,
                    "·",
                    document_revision=document.revision,
                    memory_budget_bytes=64 << 10,
                    options=SearchOptions(
                        timeout=None,
                        max_matches=4096,
                        include_captures=False,
                    ),
                    cancelled=lambda: context.token.cancelled,
                    progress=lambda completed, total: context.report(
                        "Planning zero-width replacements",
                        completed,
                        total,
                    ),
                )

        plan_started = time.perf_counter()
        plan_handle = resources.tasks.submit(
            TaskSpec.create(
                TaskKind.REPLACE,
                foreground=True,
                document_key=str(manifest.path),
                revision=document.revision,
                estimated_memory_bytes=2 << 20,
            ),
            plan_work,
        )
        interaction_timings.append(
            (time.perf_counter() - plan_started) * 1000.0
        )
        plan, plan_timing = _wait_for_task(app, plan_handle, plan_started)
        stage_timings.append(plan_timing)
        zero_width_plan_count = len(plan)
        zero_width_plan_exact = (
            zero_width_plan_count == zero_width_matches
            and all(item.start == item.end for item in plan)
        )

        cancel_snapshot = document.snapshot()

        def cancel_work(context):
            with cancel_snapshot:
                return sum(
                    1
                    for _record in search_document(
                        cancel_snapshot,
                        zero_width_pattern,
                        options=SearchOptions(
                            timeout=None,
                            include_captures=False,
                            progress_chars=64 << 10,
                        ),
                        cancelled=lambda: context.token.cancelled,
                        progress=lambda completed, total: context.report(
                            "Searching for cancellation",
                            completed,
                            total,
                        ),
                    )
                )

        cancel_started = time.perf_counter()
        cancel_handle = resources.tasks.submit(
            TaskSpec.create(
                TaskKind.SEARCH,
                foreground=True,
                document_key=str(manifest.path),
                revision=document.revision,
                estimated_memory_bytes=2 << 20,
            ),
            cancel_work,
        )
        interaction_timings.append(
            (time.perf_counter() - cancel_started) * 1000.0
        )
        cancel_ms, cancelled = _measure_cancellation(app, cancel_handle)
    finally:
        snapshots_closed = True
        for snapshot in (
            search_snapshot,
            report_snapshot,
            plan_snapshot,
            cancel_snapshot,
        ):
            if snapshot is not None:
                snapshot.close()
                snapshots_closed = snapshots_closed and snapshot._closed
        store_closed = store is None
        if store is not None:
            store.close()
            try:
                store[0]
            except ValueError:
                store_closed = True
        plan_closed = plan is None
        if plan is not None:
            plan.close()
            try:
                next(iter(plan))
            except ValueError:
                plan_closed = True
        document.close()
        document_closed = document._closed
        resources.shutdown()
        cleanup_ok = (
            snapshots_closed
            and document_closed
            and store_closed
            and plan_closed
            and not resources.tasks.snapshot().tasks
        )

    digest_ok = (
        manifest.digest is not None
        and _digest(manifest.path) == manifest.digest
    )
    del analysis, analysis_handle, search_handle, report, report_handle
    del plan_handle, cancel_handle, request, store, plan, zero_width_pattern
    del search_work, report_work, plan_work, cancel_work
    del search_snapshot, report_snapshot, plan_snapshot, cancel_snapshot
    del document, resources
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    return ScenarioResult.success(
        scenario="regex_intelligence",
        metrics={
            "interaction_max_ms": MetricSample((max(interaction_timings),)),
            "gui_heartbeat_p95_ms": MetricSample(
                (max(item["gui_heartbeat_p95_ms"] for item in stage_timings),)
            ),
            "gui_heartbeat_max_ms": MetricSample(
                (max(item["gui_heartbeat_max_ms"] for item in stage_timings),)
            ),
            "first_progress_ms": MetricSample(
                (
                    max(
                        search_timing["first_progress_ms"],
                        plan_timing["first_progress_ms"],
                    ),
                )
            ),
            "progress_gap_ms": MetricSample(
                (
                    max(
                        search_timing["progress_gap_ms"],
                        plan_timing["progress_gap_ms"],
                    ),
                )
            ),
            "cancel_normal_ms": MetricSample((cancel_ms,)),
            "analysis_completion_ms": MetricSample(
                (analysis_timing["completion_ms"],)
            ),
            "capture_report_ms": MetricSample((report_timing["completion_ms"],)),
            "zero_width_plan_ms": MetricSample((plan_timing["completion_ms"],)),
            "peak_rss_mib": MetricSample((peak_mib,)),
            "retained_rss_mib": MetricSample((retained_mib,)),
        },
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "advanced_analysis_ok": advanced_analysis_ok,
            "zero_width_matches": zero_width_matches,
            "search_capture_free": search_capture_free,
            "capture_report_matches": capture_report_matches,
            "capture_report_payload_bytes": capture_report_payload_bytes,
            "capture_report_bounded": capture_report_bounded,
            "zero_width_plan_replacements": zero_width_plan_count,
            "zero_width_plan_exact": zero_width_plan_exact,
            "cancelled": cancelled,
            "source_digest": manifest.digest,
            "snapshots_closed": snapshots_closed,
            "document_closed": document_closed,
            "store_closed": store_closed,
            "plan_closed": plan_closed,
            "cleanup_ok": cleanup_ok,
            "integrity_ok": (
                advanced_analysis_ok
                and zero_width_matches == 4096
                and search_capture_free
                and capture_report_bounded
                and zero_width_plan_exact
                and cancelled
                and digest_ok
                and cleanup_ok
            ),
        },
    )


def _wait_for_file_operation(app, window, operation, started: float):
    heartbeats: list[float] = []
    progress_times: list[float] = []
    seen_progress_at: float | None = None
    deadline = time.perf_counter() + 180.0
    while operation.task_id in window._save_jobs and time.perf_counter() < deadline:
        heartbeat_started = time.perf_counter()
        app.processEvents()
        heartbeats.append((time.perf_counter() - heartbeat_started) * 1000.0)
        progress = operation.task.progress
        if progress is not None and progress.updated_at != seen_progress_at:
            seen_progress_at = progress.updated_at
            progress_times.append(progress.updated_at)
        time.sleep(0.001)
    if operation.task_id in window._save_jobs:
        operation.cancel()
        raise TimeoutError("progressive file operation did not complete")
    completed = time.perf_counter()
    if operation.task.future.exception() is not None:
        operation.task.future.result()
    first_progress_ms = (
        (progress_times[0] - started) * 1000.0
        if progress_times
        else (completed - started) * 1000.0
    )
    gaps = [
        (right - left) * 1000.0
        for left, right in zip(progress_times, progress_times[1:])
    ]
    if progress_times:
        gaps.append((completed - progress_times[-1]) * 1000.0)
    return {
        "gui_heartbeat_p95_ms": _p95(heartbeats),
        "gui_heartbeat_max_ms": max(heartbeats or [0.0]),
        "first_progress_ms": first_progress_ms,
        "progress_gap_ms": max(gaps or [0.0]),
        "completion_ms": (completed - started) * 1000.0,
    }


def _save_output(manifest: CorpusManifest, *, in_place: bool) -> ScenarioResult:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    scenario_name = "save" if in_place else "save_as"
    app = QApplication.instance() or QApplication([])
    resources = ResourceManager()
    window = UNITIMainWindow(resource_manager=resources)
    view = window.open_path(manifest.path)
    app.processEvents()
    target = (
        manifest.path
        if in_place
        else manifest.path.parent / "uniti-benchmark-save-as.txt"
    )
    target.unlink(missing_ok=True) if not in_place else None
    cancel_target = manifest.path.parent / "uniti-benchmark-cancelled-save.txt"
    cancel_target.unlink(missing_ok=True)
    start_current = current_process_rss_bytes()
    start_peak = peak_process_rss_bytes()
    try:
        started = time.perf_counter()
        operation = (
            window.start_save_current()
            if in_place
            else window.start_save_current_as(target, view.document.output_format)
        )
        interaction_ms = (time.perf_counter() - started) * 1000.0
        if operation is None:
            raise RuntimeError("progressive save was not admitted")
        timings = _wait_for_file_operation(app, window, operation, started)
        output_digest = _digest(target)
        output_ok = manifest.digest is None or output_digest == manifest.digest
        source_identity_ok = view.document.path == manifest.path

        window._tabs.setCurrentWidget(view)
        cancel_operation = window.start_save_current_as(
            cancel_target,
            view.document.output_format,
        )
        if cancel_operation is None:
            raise RuntimeError("cancellation save was not admitted")
        cancel_deadline = time.perf_counter() + 5.0
        while (
            cancel_operation.task.progress is None
            and not cancel_operation.done
            and time.perf_counter() < cancel_deadline
        ):
            app.processEvents()
            time.sleep(0.001)
        cancel_started = time.perf_counter()
        cancel_operation.cancel()
        while (
            cancel_operation.task_id in window._save_jobs
            and time.perf_counter() < cancel_deadline
        ):
            app.processEvents()
            time.sleep(0.001)
        cancel_ms = (time.perf_counter() - cancel_started) * 1000.0
        cancelled_ok = (
            cancel_operation.task_id not in window._save_jobs
            and not cancel_target.exists()
            and view.isEnabled()
        )
    finally:
        window.close_all_documents(force=True)
        window.close()
        resources.shutdown()
        app.processEvents()
        if not in_place:
            target.unlink(missing_ok=True)
        cancel_target.unlink(missing_ok=True)
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    return ScenarioResult.success(
        scenario=scenario_name,
        metrics={
            "interaction_max_ms": MetricSample((interaction_ms,)),
            "gui_heartbeat_p95_ms": MetricSample((timings["gui_heartbeat_p95_ms"],)),
            "gui_heartbeat_max_ms": MetricSample((timings["gui_heartbeat_max_ms"],)),
            "first_progress_ms": MetricSample((timings["first_progress_ms"],)),
            "progress_gap_ms": MetricSample((timings["progress_gap_ms"],)),
            "cancel_normal_ms": MetricSample((cancel_ms,)),
            "save_completion_ms": MetricSample((timings["completion_ms"],)),
            "peak_rss_mib": MetricSample((peak_mib,)),
            "retained_rss_mib": MetricSample((retained_mib,)),
        },
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "output_digest": output_digest,
            "cancelled_target_preserved": cancelled_ok,
            "source_identity_preserved": source_identity_ok,
            "integrity_ok": output_ok and source_identity_ok and cancelled_ok,
        },
    )


def _save(manifest: CorpusManifest) -> ScenarioResult:
    return _save_output(manifest, in_place=True)


def _save_as(manifest: CorpusManifest) -> ScenarioResult:
    return _save_output(manifest, in_place=False)


def _session_restore(manifest: CorpusManifest) -> ScenarioResult:
    """Measure bounded shell, active-first, lazy, and cancellation behavior."""

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.service import QuitChoice, UNITIService
    from uniti.app.session_store import LocalStorageBackend, SessionStore
    from uniti.app.settings import SettingsStore
    from uniti.resources import TaskKind, TaskSpec

    class ScenarioRecovery:
        def attach(self, _document, **_kwargs) -> None:
            return None

        def detach(self, _document, *, clean: bool) -> None:
            return None

        def shutdown(self) -> None:
            return None

    class ThreadRecordingBackend(LocalStorageBackend):
        def __init__(self, root: Path) -> None:
            super().__init__(root)
            self.storage_threads: set[int] = set()

        def write_synced(self, path: Path, data: bytes):
            self.storage_threads.add(threading.get_ident())
            return super().write_synced(path, data)

        def read_bytes(self, path: Path) -> bytes:
            self.storage_threads.add(threading.get_ident())
            return super().read_bytes(path)

    app = QApplication.instance() or QApplication([])
    app.setQuitOnLastWindowClosed(False)
    gui_thread = threading.get_ident()
    heartbeats: list[float] = []
    creator = None
    restored = None
    creator_resources = None
    restored_resources = None
    cleanup_ok = False
    with tempfile.TemporaryDirectory(
        prefix="uniti-session-restore-",
        dir=manifest.path.parent,
    ) as raw_work:
        work = Path(raw_work)
        lazy_path = work / "lazy-document.txt"
        lazy_path.write_text("lazy session history", encoding="utf-8")
        session_root = work / "sessions"
        backend = ThreadRecordingBackend(session_root)
        store = SessionStore(session_root, backend=backend)
        worker_threads: set[int] = set()
        restored_histories: dict[str, object] = {}

        def wait_until(predicate, *, timeout: float = 30.0) -> None:
            deadline = time.perf_counter() + timeout
            while time.perf_counter() < deadline:
                started = time.perf_counter()
                app.processEvents()
                heartbeats.append((time.perf_counter() - started) * 1000.0)
                if predicate():
                    return
                time.sleep(0.001)
            app.processEvents()
            if not predicate():
                raise TimeoutError("session restore benchmark did not settle")

        try:
            creator_resources = ResourceManager()
            creator = UNITIService(
                resource_manager=creator_resources,
                settings_store=SettingsStore(work / "creator-settings.json"),
                session_store=store,
                recovery_manager=ScenarioRecovery(),
                service_id="performance-creator",
                build_identity="performance-session-restore",
            )
            creator_window = creator.new_window()
            active_view = creator_window.open_path(manifest.path)
            lazy_view = creator_window.open_path(lazy_path)
            if active_view is None or lazy_view is None:
                raise RuntimeError("session performance sources did not open")
            lazy_view.document.insert(lazy_view.document.total_chars(), " saved")
            lazy_view.document.save()
            creator.set_active_view(creator_window.window_id, active_view.view_id)
            wait_until(
                lambda: all(
                    entry.saved_stamp is not None
                    for entry in creator.documents.entries
                )
            )
            creator._publish_snapshot_durably(
                creator.capture_session(clean_shutdown=True)
            )
            creator.request_quit(lambda _entry: QuitChoice.DISCARD)
            app.processEvents()
            creator = None
            creator_resources = None
            gc.collect()
            start_current = current_process_rss_bytes()
            start_peak = peak_process_rss_bytes()
            heartbeats.clear()

            restored_resources = ResourceManager()
            load_started = time.perf_counter()

            def load_manifest(_context):
                worker_threads.add(threading.get_ident())
                return store.load_manifest()

            load_handle = restored_resources.tasks.submit(
                TaskSpec.create(TaskKind.SESSION, foreground=False),
                load_manifest,
            )
            loaded, load_timing = _wait_for_task(
                app,
                load_handle,
                load_started,
            )
            if loaded.manifest is None:
                raise RuntimeError("session performance manifest was not published")
            shell_started = time.perf_counter()
            restored = UNITIService(
                resource_manager=restored_resources,
                settings_store=SettingsStore(work / "restored-settings.json"),
                session_store=store,
                recovery_manager=ScenarioRecovery(),
                service_id="performance-restored",
                build_identity="performance-session-restore",
            )

            def load_pack(document_id: str):
                worker_threads.add(threading.get_ident())
                pack = store.load_document_pack(loaded.manifest, document_id)
                restored_histories[document_id] = pack.history
                return pack

            restored.restore_shell(
                loaded.manifest,
                find_replace_pack=loaded.find_replace_pack,
                pack_loader=load_pack,
            )
            app.processEvents()
            shell_ms = (time.perf_counter() - shell_started) * 1000.0
            shell_usable = (
                restored.window_count == 1
                and restored.documents.count == 0
                and restored.active_view is None
            )
            active_started = time.perf_counter()
            restored.restore_active()
            active_completion_ms = (
                time.perf_counter() - active_started
            ) * 1000.0
            active_entry = restored.documents.find_path(manifest.path)
            active_history_restored = (
                active_entry is not None
                and active_entry.saved_stamp is not None
                and restored.active_view is not None
                and active_entry.document.export_history()
                == restored_histories.get(active_entry.document_id)
            )

            lazy_handles = restored.schedule_lazy_restore()
            wait_until(lambda: restored.documents.count == 2)
            lazy_entry = restored.documents.find_path(lazy_path)
            lazy_history_restored = (
                len(lazy_handles) == 1
                and lazy_entry is not None
                and lazy_entry.document.can_undo
                and lazy_entry.document.export_history()
                == restored_histories.get(lazy_entry.document_id)
            )

            def cancellable_session(context):
                worker_threads.add(threading.get_ident())
                context.report("Preparing session cancellation", 1, 2)
                while not context.token.wait(0.002):
                    pass
                context.check_cancelled()

            cancel_handle = restored_resources.tasks.submit(
                TaskSpec.create(TaskKind.SESSION, foreground=False),
                cancellable_session,
            )
            cancel_ms, cancelled = _measure_cancellation(app, cancel_handle)
            storage_threads = backend.storage_threads | worker_threads
            all_storage_work_off_gui = bool(storage_threads) and all(
                thread_id != gui_thread for thread_id in storage_threads
            )
            restored.request_quit(lambda _entry: QuitChoice.DISCARD)
            app.processEvents()
            restored = None
            restored_resources = None
            creator_window = None
            active_view = None
            lazy_view = None
            active_entry = None
            lazy_entry = None
            loaded = None
            cleanup_ok = True
        finally:
            for service in (restored, creator):
                if service is not None and service.is_running:
                    service.request_quit(lambda _entry: QuitChoice.DISCARD)
            for resources in (restored_resources, creator_resources):
                if resources is not None:
                    resources.shutdown(wait=True)
            app.processEvents()

    cleanup_ok = cleanup_ok and not work.exists()
    peak_mib, retained_mib = _rss_facts(start_current, start_peak)
    completion_ms = load_timing["completion_ms"] + shell_ms + active_completion_ms
    integrity_ok = (
        shell_usable
        and active_history_restored
        and lazy_history_restored
        and cancelled
        and all_storage_work_off_gui
        and cleanup_ok
    )
    return ScenarioResult.success(
        scenario="session_restore",
        metrics={
            "open_to_usable_ms": MetricSample(
                (load_timing["completion_ms"] + shell_ms,)
            ),
            "interaction_max_ms": MetricSample((shell_ms,)),
            "gui_heartbeat_p95_ms": MetricSample((_p95(heartbeats),)),
            "gui_heartbeat_max_ms": MetricSample((max(heartbeats or [0.0]),)),
            "cancel_normal_ms": MetricSample((cancel_ms,)),
            "session_restore_completion_ms": MetricSample((completion_ms,)),
            "peak_rss_mib": MetricSample((peak_mib,)),
            "retained_rss_mib": MetricSample((retained_mib,)),
        },
        facts={
            "physical_memory_bytes": probe_memory().physical,
            "source_bytes": manifest.spec.size_bytes,
            "shell_usable": shell_usable,
            "active_history_restored": active_history_restored,
            "lazy_history_restored": lazy_history_restored,
            "cancelled": cancelled,
            "storage_worker_threads": len(storage_threads),
            "all_storage_work_off_gui": all_storage_work_off_gui,
            "cleanup_ok": cleanup_ok,
            "integrity_ok": integrity_ok,
        },
    )


_SCENARIOS = {
    "open_first_paint": _open_first_paint,
    "navigation": _navigation,
    "typing": _typing,
    "scroll": _scroll,
    "giant_line": _giant_line,
    "search_sparse": _search_sparse,
    "search_dense": _search_dense,
    "replace": _replace,
    "regex_intelligence": _regex_intelligence,
    "save": _save,
    "save_as": _save_as,
    "resource_recovery": _resource_recovery,
    "session_restore": _session_restore,
}


def run_scenario(name: str, manifest: CorpusManifest) -> ScenarioResult:
    try:
        scenario = _SCENARIOS[name]
    except KeyError as error:
        raise ValueError(f"unknown performance scenario: {name}") from error
    return scenario(manifest)


def corpus_kind_for_scenario(name: str) -> CorpusKind:
    if name == "regex_intelligence":
        return CorpusKind.MIXED_UNICODE
    if name == "giant_line":
        return CorpusKind.GIANT_LINE
    if name == "search_sparse":
        return CorpusKind.SEARCH_SPARSE
    if name in {"search_dense", "replace"}:
        return CorpusKind.SEARCH_DENSE
    if name in _SCENARIOS:
        return CorpusKind.ORDINARY_LINES
    raise ValueError(f"unknown performance scenario: {name}")


def initial_scenario_names(tier: str) -> tuple[str, ...]:
    if tier == "design_target":
        return ("open_first_paint", "navigation", "search_sparse")
    return (
        "open_first_paint",
        "navigation",
        "typing",
        "scroll",
        "giant_line",
        "search_sparse",
        "search_dense",
        "replace",
        "regex_intelligence",
        "save",
        "save_as",
        "resource_recovery",
        "session_restore",
    )
