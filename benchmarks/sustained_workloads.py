"""Deterministic sustained workload family registry."""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.corpus import CorpusKind, CorpusManifest
from benchmarks.models import ResultState
from benchmarks.sustained_models import ResourceCheckpoint, SustainedFamilyResult
from uniti.resources import PerformancePolicy

if TYPE_CHECKING:
    from benchmarks.application_harness import ApplicationWorkloadHarness


SUSTAINED_FAMILY_ORDER = (
    "daily_editing",
    "format_integrity",
    "regex_replacement",
    "session_lifecycle",
)


_CORPUS_KINDS = {
    "daily_editing": CorpusKind.ORDINARY_LINES,
    "format_integrity": CorpusKind.MIXED_UNICODE,
    "regex_replacement": CorpusKind.SEARCH_DENSE,
    "session_lifecycle": CorpusKind.ORDINARY_LINES,
}


def corpus_kind_for_sustained_family(family: str) -> CorpusKind:
    try:
        return _CORPUS_KINDS[family]
    except KeyError as exc:
        raise ValueError(f"unknown sustained workload family: {family}") from exc


def create_application_harness(
    application_root: Path,
    *,
    policy: PerformancePolicy | None = None,
    operation_timeout_seconds: float | None = None,
) -> "ApplicationWorkloadHarness":
    """Construct the shared real-application harness without importing Qt eagerly."""

    from benchmarks.application_harness import ApplicationWorkloadHarness

    return ApplicationWorkloadHarness(
        application_root,
        policy=policy,
        operation_timeout_seconds=operation_timeout_seconds,
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1 << 20):
            digest.update(chunk)
    return digest.hexdigest()


def _checkpoint_with_timing(
    checkpoint: ResourceCheckpoint,
    name: str,
    milliseconds: float,
) -> ResourceCheckpoint:
    return ResourceCheckpoint(
        cycle=checkpoint.cycle,
        metrics={**checkpoint.metrics, name: max(0.0, milliseconds)},
        owned_counts=checkpoint.owned_counts,
        unavailable_probes=checkpoint.unavailable_probes,
    )


def _tasks_idle(harness: "ApplicationWorkloadHarness") -> bool:
    snapshot = harness.resources.tasks.snapshot()
    return (
        snapshot.active_count == 0
        and snapshot.queued_count == 0
        and harness.resources.workers.active_count == 0
    )


def _run_daily_editing(
    *,
    cycles: int,
    manifest: CorpusManifest,
    application_root: Path,
) -> SustainedFamilyResult:
    if manifest.spec.kind is not CorpusKind.ORDINARY_LINES:
        raise ValueError("daily editing requires an ordinary-lines corpus")
    source = manifest.path.resolve(strict=True)
    if source.stat().st_size != manifest.spec.size_bytes:
        raise ValueError("daily corpus size does not match its manifest")
    expected_digest = _file_digest(source)
    if manifest.digest != expected_digest:
        raise ValueError("daily corpus digest does not match its manifest")

    fixture_root = application_root / "fixtures"
    fixture_root.mkdir()
    fixture = fixture_root / "daily.txt"
    shutil.copyfile(source, fixture)

    harness = create_application_harness(application_root)
    identity = harness.service_identity
    checkpoints: list[ResourceCheckpoint] = []
    original_document = None
    last_document = None
    last_next_span = None
    last_previous_span = None
    last_match_count = 0
    last_result_revision = -1
    reopened_same_document = True
    document_authorities = 0
    history_cursor = -1
    saved_cursor = None
    final_revision = -1
    try:
        total_cycles = harness.policy.sustained.warmup_cycles + cycles
        for sequence in range(total_cycles):
            measured_cycle = sequence - harness.policy.sustained.warmup_cycles + 1
            started = time.perf_counter()
            view = harness.open_owned_fixture(fixture)
            document = view.document
            if original_document is None:
                original_document = document
            else:
                reopened_same_document = (
                    reopened_same_document and document is original_document
                )

            document.insert(0, "TEMP")
            document.delete(0, 4)
            document.undo()
            document.redo()

            view.state.move_to(14)
            view.state.move_left()
            view.state.move_right(selecting=True)
            view.state.move_to(14)
            view.state.move_word_left(selecting=True)
            if view.state.selection != (9, 14):
                raise RuntimeError("daily selection movement was not exact")
            view.state.move_to(14)
            view._state_changed()

            panel = harness.service.find_replace
            panel.find_input.set_text("")
            panel.find_input.set_text("alpha")
            harness.pump_until(lambda: panel.compile_current() is not None)
            panel.next_match()
            harness.pump_until(lambda: not panel.busy and panel.result_count > 0)
            next_span = view.state.selection
            panel.previous_match()
            previous_span = view.state.selection
            panel.find_all()
            harness.pump_until(lambda: not panel.busy and panel.result_count > 0)
            result_revision = getattr(panel._results, "document_revision", -1)
            match_count = panel.result_count
            harness.pump_until(lambda: _tasks_idle(harness))

            document.save()
            harness.pump_until(lambda: _tasks_idle(harness))
            history = document.export_history()
            if document.modified or history.cursor != history.saved_cursor:
                raise RuntimeError("daily save point was not retained")
            if _file_digest(fixture) != expected_digest:
                raise RuntimeError("daily saved bytes changed unexpectedly")
            if result_revision != document.revision:
                raise RuntimeError("daily find result revision is stale")

            if not harness.close_cycle():
                raise RuntimeError("daily cycle could not close its view")
            reopened = harness.open_owned_fixture(fixture)
            reopened_same_document = (
                reopened_same_document and reopened.document is document
            )
            panel.target_changed()
            harness.pump_until(
                lambda: _tasks_idle(harness) and panel.result_count == 0
            )

            last_document = document
            last_next_span = next_span
            last_previous_span = previous_span
            last_match_count = match_count
            last_result_revision = result_revision
            history_cursor = history.cursor
            saved_cursor = history.saved_cursor
            final_revision = document.revision
            document_authorities = harness.service.documents.count
            if sequence >= harness.policy.sustained.warmup_cycles:
                checkpoint = harness.capture_checkpoint(measured_cycle)
                if (
                    checkpoint.owned_counts["documents"] != 1
                    or checkpoint.owned_counts["views"] != 1
                    or checkpoint.owned_counts["active_tasks"] != 0
                    or checkpoint.owned_counts["queued_tasks"] != 0
                    or checkpoint.owned_counts["result_stores"] != 0
                    or checkpoint.owned_counts["replacement_plans"] != 0
                    or checkpoint.owned_counts["snapshots"] != 0
                ):
                    raise RuntimeError("daily cycle left unexpected owned resources")
                checkpoints.append(
                    _checkpoint_with_timing(
                        checkpoint,
                        "daily_cycle_ms",
                        (time.perf_counter() - started) * 1000.0,
                    )
                )
    finally:
        harness.shutdown()

    if last_document is None:
        raise RuntimeError("daily workload completed no cycles")
    cleanup_ok = (
        not harness.service.is_running
        and harness.service.documents.count == 0
        and harness.service.windows.count == 0
        and _tasks_idle(harness)
        and harness.recovery_manager.diagnostics() == ()
    )
    saved_digest = _file_digest(fixture)
    integrity_ok = (
        saved_digest == expected_digest
        and last_next_span == (41, 46)
        and last_previous_span == (9, 14)
        and last_result_revision == final_revision
        and last_match_count == manifest.spec.size_bytes // 32
        and reopened_same_document
        and document_authorities == 1
        and history_cursor == saved_cursor
    )
    return SustainedFamilyResult(
        schema=2,
        family="daily_editing",
        profile="a22-v1",
        state=(
            ResultState.PASS
            if integrity_ok and cleanup_ok
            else ResultState.FAIL
        ),
        warmup_cycles=harness.policy.sustained.warmup_cycles,
        measured_cycles=cycles,
        checkpoints=tuple(checkpoints),
        facts={
            "cleanup_ok": cleanup_ok,
            "cycles_completed": total_cycles,
            "document_authorities": document_authorities,
            "expected_digest": expected_digest,
            "final_history_cursor": history_cursor,
            "final_revision": final_revision,
            "final_saved_cursor": saved_cursor,
            "integrity_ok": integrity_ok,
            "match_count": last_match_count,
            "next_span": last_next_span,
            "previous_span": last_previous_span,
            "reopened_same_document": reopened_same_document,
            "result_revision": last_result_revision,
            "saved_digest": saved_digest,
            "service_identity_reused": harness.service_identity == identity,
        },
        messages=() if integrity_ok and cleanup_ok else ("daily workflow failed",),
    )


def run_sustained_workload(
    family: str,
    *,
    profile: str,
    cycles: int,
    manifest: CorpusManifest,
    application_root: Path,
) -> SustainedFamilyResult:
    """Dispatch a registered workload; concrete cycles arrive in Tasks 7–10."""

    corpus_kind_for_sustained_family(family)
    if profile not in {"hosted", "controlled"}:
        raise ValueError(f"unknown sustained execution profile: {profile}")
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles <= 0:
        raise ValueError("sustained cycle count must be positive")
    if not isinstance(manifest, CorpusManifest):
        raise TypeError("manifest must be a CorpusManifest")
    if not isinstance(application_root, Path):
        raise TypeError("application_root must be a Path")
    if family == "daily_editing":
        return _run_daily_editing(
            cycles=cycles,
            manifest=manifest,
            application_root=application_root,
        )
    return SustainedFamilyResult(
        schema=2,
        family=family,
        profile="a22-v1",
        state=ResultState.FAIL,
        warmup_cycles=1,
        measured_cycles=cycles,
        checkpoints=(),
        facts={"integrity_ok": False, "cleanup_ok": False},
        messages=("sustained workload family is not implemented yet",),
    )
