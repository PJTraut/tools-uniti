"""Deterministic sustained workload family registry."""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
from concurrent.futures import CancelledError
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.corpus import (
    CorpusKind,
    CorpusManifest,
    generate_format_fixtures,
)
from benchmarks.models import ResultState
from benchmarks.sustained_models import ResourceCheckpoint, SustainedFamilyResult
from uniti.app.service import QuitChoice
from uniti.app.session import HistoryPack, SessionLoadSource
from uniti.app.session_runtime import restore_document_pack
from uniti.core.byte_source import ByteSource
from uniti.core.document import (
    Document,
    ReplacementPlanLimitError,
    StaleDocumentRevisionError,
)
from uniti.core.file_identity import (
    ExternalFileChangedError,
    FileIdentity,
    FileMatch,
    SavedFileStamp,
)
from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile
from uniti.core.text_inspection import inspect_source
from uniti.regex.analysis import AnalysisState, analyze_pattern
from uniti.regex.captures import CaptureReportRequest, resolve_capture_report
from uniti.regex.engine import compile_pattern
from uniti.regex.match_store import MatchStore
from uniti.regex.replace import (
    collect_replacement_plan,
    collect_replacements,
    replace_all,
)
from uniti.regex.search import RegexSearchTimeout, SearchOptions, search_document
from uniti.resources import (
    PerformancePolicy,
    ResourceSnapshot,
    ResourceState,
    TaskKind,
    TaskSpec,
    WorkCancelled,
)

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

_DAILY_NEEDLE = "UNITI_DAILY_NEEDLE"
_DAILY_PRIMARY_BYTES = 256 << 10
_REGEX_DENSE_BYTES = 256 << 10
_LIFECYCLE_PANEL_VALUES = (
    ("lifecycle-find-a", "lifecycle-replace-a"),
    ("lifecycle-find-b", "lifecycle-replace-b"),
)
_LIFECYCLE_PRIMARY_BYTES = 64 << 10


def _lifecycle_panel_values(sequence: int) -> tuple[str, str]:
    """Alternate bounded values without filling the regex engine's native cache."""

    return _LIFECYCLE_PANEL_VALUES[sequence % len(_LIFECYCLE_PANEL_VALUES)]


def _copy_bounded_prefix(source: Path, target: Path, *, max_bytes: int) -> int:
    """Copy at most ``max_bytes`` without materializing the fixture in memory."""

    remaining = min(source.stat().st_size, max_bytes)
    copied = remaining
    with source.open("rb") as reader, target.open("xb") as writer:
        while remaining:
            chunk = reader.read(min(64 << 10, remaining))
            if not chunk:
                raise RuntimeError("source ended before its declared size")
            writer.write(chunk)
            remaining -= len(chunk)
    return copied


def corpus_kind_for_sustained_family(family: str) -> CorpusKind:
    try:
        return _CORPUS_KINDS[family]
    except KeyError as exc:
        raise ValueError(f"unknown sustained workload family: {family}") from exc


def attach_fault_evidence(
    family: SustainedFamilyResult,
    results: tuple[object, ...],
) -> SustainedFamilyResult:
    """Make the fixed crash suite part of lifecycle integrity evidence."""

    from benchmarks.faults import FAULT_CASE_ORDER, FaultResult

    if family.family != "session_lifecycle":
        raise ValueError("fault evidence belongs only to session_lifecycle")
    if (
        not isinstance(results, tuple)
        or not all(isinstance(result, FaultResult) for result in results)
        or tuple(result.case for result in results) != FAULT_CASE_ORDER
    ):
        raise ValueError("fault evidence is incomplete or out of order")
    passed = all(result.passed for result in results)
    cleanup_ok = all(result.cleanup_ok for result in results)
    expected_terminations = sum(
        result.expected_termination for result in results
    )
    facts = dict(family.facts)
    facts.update(
        {
            "cleanup_ok": facts.get("cleanup_ok") is True and cleanup_ok,
            "crash_recovery_verified": passed,
            "expected_terminations": expected_terminations,
            "fault_case_count": len(results),
            "integrity_ok": facts.get("integrity_ok") is True and passed,
        }
    )
    state = family.state if passed and cleanup_ok else ResultState.FAIL
    failures = tuple(result.case.value for result in results if not result.passed)
    messages = family.messages
    if failures:
        messages += (f"fault verification failed: {','.join(failures)}",)
    return replace(family, state=state, facts=facts, messages=messages)


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
    manifest_digest = _file_digest(source)
    if manifest.digest != manifest_digest:
        raise ValueError("daily corpus digest does not match its manifest")

    fixture_root = application_root / "fixtures"
    fixture_root.mkdir()
    fixture = fixture_root / "daily.txt"
    daily_fixture_bytes = _copy_bounded_prefix(
        source,
        fixture,
        max_bytes=_DAILY_PRIMARY_BYTES,
    )
    with fixture.open("r+b") as handle:
        handle.seek(32)
        handle.write(_DAILY_NEEDLE.encode("ascii"))
    expected_digest = _file_digest(fixture)

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
    retained_view_id = None
    stable_view_reused = True
    try:
        total_cycles = harness.policy.sustained.warmup_cycles + cycles
        for sequence in range(total_cycles):
            measured_cycle = sequence - harness.policy.sustained.warmup_cycles + 1
            started = time.perf_counter()
            view = harness.open_owned_fixture(fixture)
            document = view.document
            if retained_view_id is not None:
                stable_view_reused &= view.view_id == retained_view_id
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
            panel.find_input.set_text(_DAILY_NEEDLE)
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

            if sequence == 0:
                if not harness.close_cycle():
                    raise RuntimeError("daily cycle could not close its view")
                reopened = harness.open_owned_fixture(fixture)
                reopened_same_document &= reopened.document is document
                retained_view_id = reopened.view_id
            else:
                reopened_same_document &= view.document is document
                retained_view_id = view.view_id
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
        and last_next_span == (32, 32 + len(_DAILY_NEEDLE))
        and last_previous_span == (32, 32 + len(_DAILY_NEEDLE))
        and last_result_revision == final_revision
        and last_match_count == 1
        and reopened_same_document
        and stable_view_reused
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
            "daily_fixture_bytes": daily_fixture_bytes,
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
            "stable_view_reused": stable_view_reused,
        },
        messages=() if integrity_ok and cleanup_ok else ("daily workflow failed",),
    )


def _eol_value(policy: EOLPolicy) -> str | None:
    return None if policy is EOLPolicy.PRESERVE else policy.value


def _run_format_integrity(
    *,
    cycles: int,
    manifest: CorpusManifest,
    application_root: Path,
) -> SustainedFamilyResult:
    if manifest.spec.kind is not CorpusKind.MIXED_UNICODE:
        raise ValueError("format integrity requires a mixed-unicode corpus")
    sustained_source = manifest.path.resolve(strict=True)
    if sustained_source.stat().st_size != manifest.spec.size_bytes:
        raise ValueError("format corpus size does not match its manifest")
    sustained_digest = _file_digest(sustained_source)
    if manifest.digest != sustained_digest:
        raise ValueError("format corpus digest does not match its manifest")
    with ByteSource.open(sustained_source) as source:
        sustained_inspection = inspect_source(source)
    if (
        sustained_inspection.encoding.suggested.key != "utf-8"
        or sustained_inspection.encoding.malformed_preview
    ):
        raise RuntimeError("sustained Unicode corpus inspection failed")

    templates = generate_format_fixtures(application_root / "format-templates")
    fixture_bytes = sum(item.size_bytes for item in templates)
    by_name = {item.name: item for item in templates}
    work_root = application_root / "format-work"
    work_root.mkdir()
    harness = create_application_harness(application_root)
    checkpoints: list[ResourceCheckpoint] = []
    last_mixed_eol = ""
    last_invalid_hex = ""
    last_malformed_preserved = False
    last_converted_digest = ""
    last_save_as_digest = ""
    last_history_restore = False
    last_external_save_rejected = False
    last_stale_match = ""
    try:
        total_cycles = harness.policy.sustained.warmup_cycles + cycles
        for sequence in range(total_cycles):
            measured_cycle = sequence - harness.policy.sustained.warmup_cycles + 1
            started = time.perf_counter()
            work = {}
            for name, fixture in by_name.items():
                target = work_root / fixture.path.name
                shutil.copyfile(fixture.path, target)
                work[name] = target

            profiles = {
                "utf8": "utf-8",
                "utf8_bom": "utf-8-bom",
                "utf16_le_bom": "utf-16-le-bom",
                "utf16_be_bom": "utf-16-be-bom",
                "mixed_unicode": "utf-8",
            }
            for name, profile_key in profiles.items():
                with ByteSource.open(work[name]) as source:
                    inspection = inspect_source(source)
                if inspection.encoding.suggested.key != profile_key:
                    raise RuntimeError(f"{name} format inspection was not exact")
            with ByteSource.open(work["mixed_eol"]) as source:
                mixed_inspection = inspect_source(source)
            with ByteSource.open(work["malformed_utf8"]) as source:
                malformed_inspection = inspect_source(
                    source,
                    override=encoding_profile("utf-8"),
                )

            malformed_copy = work_root / "malformed-copy.txt"
            malformed_copy.unlink(missing_ok=True)
            with Document.open(
                work["malformed_utf8"],
                profile=encoding_profile("utf-8"),
                resource_manager=harness.resources,
            ) as malformed:
                annotated = malformed.read_with_annotations(
                    0, malformed.total_chars()
                )
                before_revision = malformed.revision
                malformed.export_copy(
                    malformed_copy,
                    output_format=malformed.output_format,
                    expected_destination_identity=None,
                )
                display_only = malformed.revision == before_revision
            invalid_hex = "".join(
                span.raw.hex() for span in annotated.invalid_bytes
            )
            malformed_preserved = (
                display_only
                and invalid_hex == "ff"
                and _file_digest(malformed_copy)
                == by_name["malformed_utf8"].digest
                and bool(malformed_inspection.encoding.malformed_preview)
            )

            converted_path = work["utf8"]
            with Document.open(
                converted_path,
                profile=encoding_profile("utf-8"),
                resource_manager=harness.resources,
            ) as converted:
                converted.insert(converted.total_chars(), "Edited\n")
                converted.set_output_format(
                    OutputFormat(
                        encoding_profile("utf-16-le-bom"),
                        EOLPolicy.CRLF,
                    )
                )
                converted.save()
                if converted.modified:
                    raise RuntimeError("explicit format conversion was not saved")
            converted_digest = _file_digest(converted_path)

            save_as = work_root / "mixed-eol-copy.txt"
            save_as.unlink(missing_ok=True)
            with Document.open(
                work["mixed_eol"],
                profile=encoding_profile("utf-8"),
                resource_manager=harness.resources,
            ) as mixed_document:
                mixed_document.export_copy(
                    save_as,
                    output_format=mixed_document.output_format,
                    expected_destination_identity=None,
                )
            save_as_digest = _file_digest(save_as)

            history_path = work["mixed_unicode"]
            history_document = Document.open(
                history_path,
                profile=encoding_profile("utf-8"),
                resource_manager=harness.resources,
            )
            restored = None
            try:
                history_document.insert(history_document.total_chars(), "saved\n")
                history_document.save()
                history_document.insert(history_document.total_chars(), "redo\n")
                history_document.undo()
                history = history_document.export_history()
                stamp = SavedFileStamp(
                    FileIdentity.from_path(history_path),
                    _file_digest(history_path),
                )
                selected = history_document.output_format
                saved = history_document.saved_output_format
                pack = HistoryPack(
                    document_id="format-history",
                    generation=f"format-{sequence}",
                    canonical_path=str(history_path),
                    saved_stamp=stamp,
                    source_profile_key=history_document.source_profile.key,
                    selected_output_profile_key=selected.encoding.key,
                    selected_output_eol=_eol_value(selected.eol),
                    saved_output_profile_key=saved.encoding.key,
                    saved_output_eol=_eol_value(saved.eol),
                    history=history,
                    last_active_at="2026-09-05T00:00:00Z",
                    closed_at=None,
                )
                restored_result = restore_document_pack(
                    pack,
                    (),
                    resource_manager=harness.resources,
                )
                restored = restored_result.document
                before_undo = (
                    "" if restored is None else restored.read(0, restored.total_chars())
                )
                history_restore_exact = (
                    restored is not None
                    and restored_result.match
                    in {FileMatch.EXACT_FAST, FileMatch.EXACT_HASH}
                    and restored.export_history() == history
                )
                if restored is not None:
                    restored.undo()
                    restored.redo()
                    history_restore_exact = (
                        history_restore_exact
                        and restored.read(0, restored.total_chars()) == before_undo
                    )
                    restored.close()
                    restored = None

                history_path.write_bytes(b"external bytes\n")
                history_document.insert(history_document.total_chars(), "local")
                try:
                    history_document.save()
                except ExternalFileChangedError:
                    external_save_rejected = True
                else:
                    external_save_rejected = False
                stale = restore_document_pack(
                    pack,
                    (),
                    resource_manager=harness.resources,
                )
                stale_match = stale.match.value
                if stale.document is not None:
                    stale.document.close()
            finally:
                if restored is not None:
                    restored.close()
                history_document.close()

            harness.pump_until(lambda: _tasks_idle(harness))
            last_mixed_eol = mixed_inspection.eol.kind
            last_invalid_hex = invalid_hex
            last_malformed_preserved = malformed_preserved
            last_converted_digest = converted_digest
            last_save_as_digest = save_as_digest
            last_history_restore = history_restore_exact
            last_external_save_rejected = external_save_rejected
            last_stale_match = stale_match
            if sequence >= harness.policy.sustained.warmup_cycles:
                checkpoint = harness.capture_checkpoint(measured_cycle)
                if any(
                    checkpoint.owned_counts[name] != 0
                    for name in (
                        "documents",
                        "views",
                        "active_tasks",
                        "queued_tasks",
                        "result_stores",
                        "replacement_plans",
                        "snapshots",
                    )
                ):
                    raise RuntimeError("format cycle left unexpected owned resources")
                checkpoints.append(
                    _checkpoint_with_timing(
                        checkpoint,
                        "format_cycle_ms",
                        (time.perf_counter() - started) * 1000.0,
                    )
                )
    finally:
        harness.shutdown()

    cleanup_ok = (
        not harness.service.is_running
        and _tasks_idle(harness)
        and not tuple(application_root.rglob("*.uniti-tmp"))
    )
    integrity_ok = all(
        (
            last_mixed_eol == "MIXED",
            last_invalid_hex == "ff",
            last_malformed_preserved,
            last_converted_digest
            == "8f067c5cee737099e10457ad266a409b3a24434ab9a980e0f737639e4db54d4f",
            last_save_as_digest == by_name["mixed_eol"].digest,
            last_history_restore,
            last_external_save_rejected,
            last_stale_match == FileMatch.CHANGED.value,
        )
    )
    return SustainedFamilyResult(
        schema=2,
        family="format_integrity",
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
            "converted_digest": last_converted_digest,
            "cycles_completed": total_cycles,
            "display_invalid_hex": last_invalid_hex,
            "external_save_rejected": last_external_save_rejected,
            "fixture_bytes": fixture_bytes,
            "history_restore_exact": last_history_restore,
            "integrity_ok": integrity_ok,
            "malformed_preserved": last_malformed_preserved,
            "mixed_eol_kind": last_mixed_eol,
            "save_as_digest": last_save_as_digest,
            "stale_history_match": last_stale_match,
            "sustained_digest": sustained_digest,
        },
        messages=() if integrity_ok and cleanup_ok else ("format workflow failed",),
    )


def _span_digest(records) -> str:
    digest = hashlib.sha256()
    for record in records:
        digest.update(f"{record.start}:{record.end}\n".encode("ascii"))
    return digest.hexdigest()


def _expected_dense_result(size_bytes: int) -> tuple[int, str]:
    count = 0 if size_bytes < 11 else ((size_bytes - 11) // 256) + 1
    count = min(count, 4096)
    digest = hashlib.sha256()
    for index in range(count):
        start = index * 256
        digest.update(f"{start}:{start + 11}\n".encode("ascii"))
    return count, digest.hexdigest()


def _document_utf8_digest(document: Document) -> str:
    digest = hashlib.sha256()
    for _offset, text in document.iter_text(chunk_chars=65_536):
        digest.update(text.encode("utf-8"))
    return digest.hexdigest()


def _run_regex_replacement(
    *,
    cycles: int,
    manifest: CorpusManifest,
    application_root: Path,
) -> SustainedFamilyResult:
    if manifest.spec.kind is not CorpusKind.SEARCH_DENSE:
        raise ValueError("regex replacement requires a search-dense corpus")
    source = manifest.path.resolve(strict=True)
    if source.stat().st_size != manifest.spec.size_bytes:
        raise ValueError("regex corpus size does not match its manifest")
    manifest_digest = _file_digest(source)
    if manifest.digest != manifest_digest:
        raise ValueError("regex corpus digest does not match its manifest")

    work_root = application_root / "regex-work"
    work_root.mkdir()
    dense_template = work_root / "dense-template.txt"
    dense_fixture_bytes = _copy_bounded_prefix(
        source,
        dense_template,
        max_bytes=_REGEX_DENSE_BYTES,
    )
    source_digest = _file_digest(dense_template)
    harness = create_application_harness(application_root)
    checkpoints: list[ResourceCheckpoint] = []
    last_facts: dict[str, object] = {}
    try:
        total_cycles = harness.policy.sustained.warmup_cycles + cycles
        for sequence in range(total_cycles):
            measured_cycle = sequence - harness.policy.sustained.warmup_cycles + 1
            started = time.perf_counter()
            dense_path = work_root / "dense.txt"
            sparse_path = work_root / "sparse.txt"
            zero_path = work_root / "zero.txt"
            capture_path = work_root / "captures.txt"
            lookaround_path = work_root / "lookaround.txt"
            pathological_path = work_root / "pathological.txt"
            stale_path = work_root / "stale.txt"
            cancel_path = work_root / "cancel.txt"
            stale_result_path = work_root / "stale-result.txt"
            shutil.copyfile(dense_template, dense_path)
            sparse_path.write_bytes(b"head UNITI_MATCH tail no marker")
            zero_path.write_bytes(b"aa")
            capture_path.write_bytes(b"aaaaaa")
            lookaround_path.write_bytes(b"xxa yya")
            pathological_path.write_bytes((b"a" * 32_768) + b"X")
            stale_path.write_bytes(b"x x")
            cancel_path.write_bytes(b"cancel target")
            stale_result_path.write_bytes(b"x x")

            documents: list[Document] = []
            snapshots = []
            stores: list[MatchStore] = []
            plans = []
            dense_store = None
            dense_plan = None
            try:
                dense = Document.open(
                    dense_path,
                    profile=encoding_profile("utf-8"),
                    resource_manager=harness.resources,
                )
                documents.append(dense)
                dense_pattern = compile_pattern("UNITI_MATCH")
                dense_snapshot = dense.snapshot()
                snapshots.append(dense_snapshot)
                dense_store = MatchStore(
                    memory_budget_bytes=1 << 10,
                    document_revision=dense.revision,
                )
                stores.append(dense_store)
                try:
                    for record in search_document(
                        dense_snapshot,
                        dense_pattern,
                        options=SearchOptions(
                            timeout=0.5,
                            max_matches=4096,
                            include_captures=False,
                        ),
                    ):
                        dense_store.append(record)
                finally:
                    dense_snapshot.close()
                dense_matches = len(dense_store)
                dense_result_digest = _span_digest(dense_store)
                dense_store_spilled = dense_store.spilled

                sparse = Document.open(
                    sparse_path,
                    profile=encoding_profile("utf-8"),
                    resource_manager=harness.resources,
                )
                documents.append(sparse)
                sparse_records = tuple(
                    search_document(
                        sparse,
                        dense_pattern,
                        options=SearchOptions(include_captures=False),
                    )
                )
                sparse_result_digest = _span_digest(sparse_records)
                current_replacements = collect_replacements(
                    sparse,
                    dense_pattern,
                    "HIT",
                    options=SearchOptions(max_matches=1),
                )
                for replacement in current_replacements:
                    sparse.replace(
                        replacement.start,
                        replacement.end,
                        replacement.text,
                    )
                replace_current_count = len(current_replacements)
                replace_current_exact = (
                    sparse.read(0, sparse.total_chars())
                    == "head HIT tail no marker"
                )

                zero = Document.open(
                    zero_path,
                    profile=encoding_profile("utf-8"),
                    resource_manager=harness.resources,
                )
                documents.append(zero)
                zero_pattern = compile_pattern(r"(?=a)|(?<=a)")
                zero_records = tuple(
                    search_document(
                        zero,
                        zero_pattern,
                        options=SearchOptions(include_captures=False),
                    )
                )
                zero_store = MatchStore(document_revision=zero.revision)
                stores.append(zero_store)
                for record in zero_records:
                    zero_store.append(record)
                next_index = zero_store.next_index(1)
                previous_index = zero_store.previous_index(1)
                zero_width_replacements = replace_all(
                    zero,
                    compile_pattern(r"(?=a)"),
                    "X",
                )
                zero_width_digest = _document_utf8_digest(zero)
                zero_history = zero.export_history()
                zero.undo()
                zero_undo_exact = _document_utf8_digest(zero) == _file_digest(zero_path)
                zero.redo()
                zero_redo_exact = _document_utf8_digest(zero) == zero_width_digest

                capture_document = Document.open(
                    capture_path,
                    profile=encoding_profile("utf-8"),
                    resource_manager=harness.resources,
                )
                documents.append(capture_document)
                capture_pattern = compile_pattern(r"(?P<item>a)+")
                capture_record = next(
                    search_document(
                        capture_document,
                        capture_pattern,
                        options=SearchOptions(
                            max_matches=1,
                            include_captures=False,
                        ),
                    )
                )
                capture_request = CaptureReportRequest(
                    pattern_generation=sequence + 1,
                    pattern_text=capture_pattern.pattern,
                    document_key=str(id(capture_document)),
                    revision=capture_document.revision,
                    store_id=f"capture-{sequence}",
                    requested_index=0,
                    match_count=1,
                    matches=((0, capture_record),),
                )
                capture_snapshot = capture_document.snapshot()
                snapshots.append(capture_snapshot)
                try:
                    capture_report = resolve_capture_report(
                        capture_snapshot,
                        capture_pattern,
                        capture_request,
                    )
                finally:
                    capture_snapshot.close()
                capture_occurrences = (
                    capture_report.matches[0].groups[0].occurrence_count
                )

                lookaround = Document.open(
                    lookaround_path,
                    profile=encoding_profile("utf-8"),
                    resource_manager=harness.resources,
                )
                documents.append(lookaround)
                [lookaround_record] = tuple(
                    search_document(
                        lookaround,
                        compile_pattern(r"(?<=xx)a"),
                        options=SearchOptions(
                            window_chars=4,
                            max_context_chars=64,
                            include_captures=False,
                        ),
                    )
                )

                pathological_analysis = analyze_pattern(r"(a+)+$", sequence + 1)
                pathological = Document.open(
                    pathological_path,
                    profile=encoding_profile("utf-8"),
                    resource_manager=harness.resources,
                )
                documents.append(pathological)
                pathological_timeout = False
                try:
                    tuple(
                        search_document(
                            pathological,
                            compile_pattern(r"(a+)+$"),
                            options=SearchOptions(
                                window_chars=32_769,
                                max_context_chars=65_536,
                                timeout=0.000_000_001,
                                include_captures=False,
                            ),
                        )
                    )
                except RegexSearchTimeout:
                    pathological_timeout = True

                cancel_document = Document.open(
                    cancel_path,
                    profile=encoding_profile("utf-8"),
                    resource_manager=harness.resources,
                )
                documents.append(cancel_document)
                cancel_started = threading.Event()
                published: list[MatchStore] = []

                def cancel_work(context):
                    snapshot = cancel_document.snapshot()
                    snapshots.append(snapshot)
                    try:
                        cancel_started.set()
                        if not context.token.wait(harness.operation_timeout_seconds):
                            raise TimeoutError("regex cancellation barrier expired")
                        context.check_cancelled()
                        result = MatchStore(document_revision=cancel_document.revision)
                        published.append(result)
                        return result
                    finally:
                        snapshot.close()

                cancel_handle = harness.resources.tasks.submit(
                    TaskSpec.create(TaskKind.SEARCH, foreground=True),
                    cancel_work,
                )
                if not cancel_started.wait(harness.operation_timeout_seconds):
                    cancel_handle.cancel()
                    raise TimeoutError("regex cancellation task did not start")
                cancel_handle.cancel()
                try:
                    harness.await_operation(cancel_handle)
                except (CancelledError, WorkCancelled):
                    cancelled = True
                else:
                    cancelled = False
                cancelled_before_publication = cancelled and not published

                dense_plan = collect_replacement_plan(
                    dense,
                    dense_pattern,
                    "UNITI",
                    document_revision=dense.revision,
                    memory_budget_bytes=1 << 10,
                    options=SearchOptions(
                        timeout=0.5,
                        max_matches=4096,
                        include_captures=False,
                    ),
                )
                plans.append(dense_plan)
                replacement_plan_count = len(dense_plan)
                replacement_plan_spilled = dense_plan.spilled
                before_replace_digest = _document_utf8_digest(dense)
                try:
                    dense.apply_replacement_plan(
                        dense_plan,
                        expected_revision=dense.revision,
                        memory_limit_bytes=1,
                    )
                except ReplacementPlanLimitError:
                    replacement_plan_refused = (
                        _document_utf8_digest(dense) == before_replace_digest
                    )
                else:
                    replacement_plan_refused = False
                replace_all_count = dense.apply_replacement_plan(
                    dense_plan,
                    expected_revision=dense.revision,
                    memory_limit_bytes=256 << 20,
                )
                replacement_digest = _document_utf8_digest(dense)
                dense_history = dense.export_history()
                dense.undo()
                undo_exact = _document_utf8_digest(dense) == source_digest
                dense.redo()
                redo_exact = _document_utf8_digest(dense) == replacement_digest
                atomic_undo_redo = (
                    len(dense_history.transactions) == 1
                    and undo_exact
                    and redo_exact
                    and len(zero_history.transactions) == 1
                    and zero_undo_exact
                    and zero_redo_exact
                )

                stale_document = Document.open(
                    stale_path,
                    profile=encoding_profile("utf-8"),
                    resource_manager=harness.resources,
                )
                documents.append(stale_document)
                stale_plan = collect_replacement_plan(
                    stale_document,
                    compile_pattern("x"),
                    "y",
                    document_revision=stale_document.revision,
                )
                plans.append(stale_plan)
                sealed_revision = stale_document.revision
                stale_document.insert(stale_document.total_chars(), "!")
                try:
                    stale_document.apply_replacement_plan(
                        stale_plan,
                        expected_revision=sealed_revision,
                        memory_limit_bytes=1 << 20,
                    )
                except StaleDocumentRevisionError:
                    stale_plan_rejected = (
                        stale_document.read(0, stale_document.total_chars())
                        == "x x!"
                    )
                else:
                    stale_plan_rejected = False

                stale_view = harness.open_owned_fixture(stale_result_path)
                stale_panel = harness.service.find_replace
                stale_panel.regex_checkbox.setChecked(False)
                stale_panel.find_input.set_text("")
                stale_panel.find_input.set_text("x")
                harness.pump_until(
                    lambda: stale_panel.compile_current() is not None
                )
                stale_panel.find_all()
                harness.pump_until(
                    lambda: not stale_panel.busy
                    and stale_panel.result_count == 2
                )
                result_revision = getattr(
                    stale_panel._results,
                    "document_revision",
                    -1,
                )
                result_revision_sealed = (
                    dense_store.document_revision == 0
                    and result_revision == stale_view.document.revision
                )
                stale_view.document.insert(
                    stale_view.document.total_chars(),
                    "!",
                )
                stale_result_rejected = (
                    stale_panel.result_count == 0
                    and stale_panel.status_label.text()
                    == "text changed — search again"
                )
                if not harness.close_cycle():
                    raise RuntimeError("stale-result view did not close")

                last_facts = {
                    "atomic_undo_redo": atomic_undo_redo,
                    "cancelled_before_publication": cancelled_before_publication,
                    "capture_occurrences": capture_occurrences,
                    "capture_payload_bytes": capture_report.payload_bytes,
                    "dense_matches": dense_matches,
                    "dense_result_digest": dense_result_digest,
                    "dense_store_spilled": dense_store_spilled,
                    "lookaround_span": lookaround_record.span,
                    "pathological_timeout": (
                        pathological_analysis.state is AnalysisState.VALID
                        and pathological_timeout
                    ),
                    "replace_all_count": replace_all_count,
                    "replace_current_count": replace_current_count,
                    "replace_current_exact": replace_current_exact,
                    "replacement_digest": replacement_digest,
                    "replacement_plan_count": replacement_plan_count,
                    "replacement_plan_refused": replacement_plan_refused,
                    "replacement_plan_spilled": replacement_plan_spilled,
                    "sparse_matches": len(sparse_records),
                    "sparse_result_digest": sparse_result_digest,
                    "stale_plan_rejected": stale_plan_rejected,
                    "stale_result_rejected": stale_result_rejected,
                    "result_revision_sealed": result_revision_sealed,
                    "zero_navigation_indices": (next_index, previous_index),
                    "zero_width_digest": zero_width_digest,
                    "zero_width_positions": tuple(
                        record.start for record in zero_records
                    ),
                    "zero_width_replacements": zero_width_replacements,
                }
            finally:
                for plan in plans:
                    plan.close()
                for store in stores:
                    store.close()
                for snapshot in snapshots:
                    snapshot.close()
                for document in reversed(documents):
                    document.close()

            plan_closed = True
            for plan in plans:
                try:
                    next(iter(plan))
                except ValueError:
                    continue
                plan_closed = False
            store_closed = True
            for store in stores:
                try:
                    store[0]
                except ValueError:
                    continue
                store_closed = False
            snapshots_closed = all(snapshot._closed for snapshot in snapshots)
            harness.pump_until(lambda: _tasks_idle(harness))
            last_facts.update(
                {
                    "plan_closed": plan_closed,
                    "snapshots_closed": snapshots_closed,
                    "store_closed": store_closed,
                }
            )
            if sequence >= harness.policy.sustained.warmup_cycles:
                checkpoint = harness.capture_checkpoint(measured_cycle)
                if any(
                    checkpoint.owned_counts[name] != 0
                    for name in (
                        "documents",
                        "views",
                        "active_tasks",
                        "queued_tasks",
                        "result_stores",
                        "replacement_plans",
                        "snapshots",
                    )
                ):
                    raise RuntimeError("regex cycle left unexpected owned resources")
                checkpoints.append(
                    _checkpoint_with_timing(
                        checkpoint,
                        "regex_cycle_ms",
                        (time.perf_counter() - started) * 1000.0,
                    )
                )
    finally:
        harness.shutdown()

    expected_dense_count, expected_dense_digest = _expected_dense_result(
        dense_fixture_bytes
    )
    required = (
        bool(last_facts.get("atomic_undo_redo")),
        bool(last_facts.get("cancelled_before_publication")),
        last_facts.get("capture_occurrences") == 6,
        last_facts.get("capture_payload_bytes", (1 << 20) + 1) <= 1 << 20,
        last_facts.get("dense_matches") == expected_dense_count,
        last_facts.get("dense_result_digest") == expected_dense_digest,
        bool(last_facts.get("dense_store_spilled")),
        last_facts.get("lookaround_span") == (2, 3),
        bool(last_facts.get("pathological_timeout")),
        bool(last_facts.get("replacement_plan_refused")),
        bool(last_facts.get("replacement_plan_spilled")),
        last_facts.get("replacement_plan_count") == expected_dense_count,
        last_facts.get("replace_all_count") == expected_dense_count,
        last_facts.get("replace_current_count") == 1,
        bool(last_facts.get("replace_current_exact")),
        bool(last_facts.get("result_revision_sealed")),
        bool(last_facts.get("stale_plan_rejected")),
        bool(last_facts.get("stale_result_rejected")),
        last_facts.get("sparse_matches") == 1,
        last_facts.get("sparse_result_digest")
        == "0d49377470ad4f311ebeb926f0b3c79da0c520b4529fa06f3f8fd5fc3e1cd016",
        last_facts.get("zero_navigation_indices") == (1, 0),
        last_facts.get("zero_width_digest")
        == "44920c03214ffba1dee0ac0f6ca2537ecbac72148859766df07fe914d4fffa69",
        last_facts.get("zero_width_replacements") == 2,
        last_facts.get("zero_width_positions") == (0, 1, 2),
        bool(last_facts.get("plan_closed")),
        bool(last_facts.get("snapshots_closed")),
        bool(last_facts.get("store_closed")),
    )
    cleanup_ok = (
        not harness.service.is_running
        and harness.service.documents.count == 0
        and harness.service.windows.count == 0
        and _tasks_idle(harness)
    )
    integrity_ok = all(required)
    facts = {
        **last_facts,
        "cleanup_ok": cleanup_ok,
        "cycles_completed": total_cycles,
        "dense_fixture_bytes": dense_fixture_bytes,
        "integrity_ok": integrity_ok,
    }
    return SustainedFamilyResult(
        schema=2,
        family="regex_replacement",
        profile="a22-v1",
        state=(
            ResultState.PASS
            if integrity_ok and cleanup_ok
            else ResultState.FAIL
        ),
        warmup_cycles=harness.policy.sustained.warmup_cycles,
        measured_cycles=cycles,
        checkpoints=tuple(checkpoints),
        facts=facts,
        messages=() if integrity_ok and cleanup_ok else ("regex workflow failed",),
    )


def _service_views(service) -> dict[str, object]:
    return {
        view_id: view
        for _window_id, window in service.windows.items
        for view_id in window.view_ids
        for view in (window.view_for_id(view_id),)
        if view is not None
    }


def _one_authority_per_path(service) -> bool:
    paths = tuple(entry.canonical_path for entry in service.documents.entries)
    return len(paths) == len(set(paths))


def _stage_recovery_candidate(
    harness: "ApplicationWorkloadHarness",
    path: Path,
    suffix: str,
) -> str:
    path.write_text("recovery base", encoding="utf-8")
    document = Document.open(
        path,
        profile=encoding_profile("utf-8"),
        resource_manager=harness.resources,
    )
    try:
        harness.recovery_manager.attach(document)
        document.insert(document.total_chars(), suffix)
        harness.recovery_manager.flush(document)
        harness.recovery_manager.detach(document, clean=False)
    finally:
        document.close()
    return "recovery base" + suffix


class _ReducedDurabilityAdapter:
    def sync_file(self, _descriptor: int) -> None:
        return None

    def replace(self, source: Path, destination: Path) -> None:
        source.replace(destination)

    def sync_directory(self, _directory: Path) -> bool:
        return False


def _exercise_injected_pressure(
    harness: "ApplicationWorkloadHarness",
    owned_root: Path,
    sequence: int,
) -> tuple[bool, bool, bool, bool]:
    from uniti.app.atomic_json import atomic_write_bytes
    from uniti.core.durability import DurabilityLevel

    resources = harness.resources
    status = resources.status
    physical = max(status.physical_memory, 1 << 30)
    critical = resources.observe_resources(
        ResourceSnapshot(
            physical_memory=physical,
            available_memory=0,
            process_rss=status.process_rss,
            load_per_logical_core=0.0,
            free_disk=0,
            cache_used=resources.cache.used_bytes,
            active_workers=resources.workers.active_count,
            queued_tasks=resources.workers.queued_count,
            captured_at=float(sequence + 1),
        )
    )
    resource_pressure = (
        critical is ResourceState.CRITICAL
        and resources.workers.active_limit == 1
    )
    capacity = resources.status.free_disk == 0

    resources.pause_background(True)
    worker_started = threading.Event()
    background = resources.tasks.submit(
        TaskSpec.create(TaskKind.INDEX, foreground=False),
        lambda _context: worker_started.set(),
    )
    paused = (
        resources.tasks.snapshot().background_paused
        and not worker_started.is_set()
    )
    resources.pause_background(False)
    harness.await_operation(background)
    worker_state = paused and worker_started.is_set()

    for offset in range(resources.policy.pressure.healthier_samples_before_recovery):
        resources.observe_resources(
            ResourceSnapshot(
                physical_memory=physical,
                available_memory=physical,
                process_rss=0,
                load_per_logical_core=0.0,
                free_disk=max(status.free_disk, 20 << 30),
                cache_used=resources.cache.used_bytes,
                active_workers=resources.workers.active_count,
                queued_tasks=resources.workers.queued_count,
                captured_at=float(sequence + offset + 2),
            )
        )

    durability_path = owned_root / "injected-durability.bin"
    durability = atomic_write_bytes(
        durability_path,
        b"bounded",
        adapter=_ReducedDurabilityAdapter(),
    )
    durability_injected = (
        durability.level is DurabilityLevel.FILE_SYNCED
        and durability_path.read_bytes() == b"bounded"
    )
    return resource_pressure, capacity, durability_injected, worker_state


def _run_session_lifecycle(
    *,
    cycles: int,
    manifest: CorpusManifest,
    application_root: Path,
) -> SustainedFamilyResult:
    if manifest.spec.kind is not CorpusKind.ORDINARY_LINES:
        raise ValueError("session lifecycle requires an ordinary-lines corpus")
    source = manifest.path.resolve(strict=True)
    if source.stat().st_size != manifest.spec.size_bytes:
        raise ValueError("lifecycle corpus size does not match its manifest")
    manifest_digest = _file_digest(source)
    if manifest.digest != manifest_digest:
        raise ValueError("lifecycle corpus digest does not match its manifest")

    from PySide6.QtCore import Qt
    from uniti.app.recovery_manager import RecoveryHealth
    from uniti.core.durability import DurabilityLevel
    from uniti.ui.recovery_center import RecoveryAction, RecoveryDecision

    fixture_root = application_root / "lifecycle-work"
    fixture_root.mkdir()
    primary_path = fixture_root / "primary.txt"
    secondary_path = fixture_root / "secondary.txt"
    primary_fixture_bytes = _copy_bounded_prefix(
        source,
        primary_path,
        max_bytes=_LIFECYCLE_PRIMARY_BYTES,
    )
    source_digest = _file_digest(primary_path)
    secondary_path.write_bytes(b"secondary lifecycle document\n")
    secondary_digest = _file_digest(secondary_path)

    harness = create_application_harness(application_root)
    service_identity = harness.service_identity
    panel = harness.service.find_replace
    gui_thread = threading.get_ident()
    publication_threads: list[int] = []
    load_threads: list[int] = []
    publish = harness.session_store.publish

    def observed_publish(snapshot):
        publication_threads.append(threading.get_ident())
        return publish(snapshot)

    harness.session_store.publish = observed_publish
    checks = {
        "activation_created_window": True,
        "active_first_restored": True,
        "find_replace_history_restored": True,
        "history_undo_redo_exact": True,
        "injected_capacity": True,
        "injected_durability": True,
        "injected_resource_pressure": True,
        "injected_worker_state": True,
        "independent_view_state": True,
        "lazy_documents_restored": True,
        "one_authority_per_path": True,
        "one_global_panel": True,
        "panel_attach_detach": True,
        "recovery_cleanup": True,
        "recovery_undo_redo_exact": True,
        "service_identity_reused": True,
        "service_survived_last_window": True,
        "session_generation_current": True,
        "stable_base_views_retained": True,
    }
    checkpoints: list[ResourceCheckpoint] = []
    explicit_quit = False
    generation_lease = None
    try:
        total_cycles = harness.policy.sustained.warmup_cycles + cycles
        for sequence in range(total_cycles):
            measured_cycle = sequence - harness.policy.sustained.warmup_cycles + 1
            started = time.perf_counter()
            if sequence == 0:
                first = harness.service.most_recent_window
                if first is None:
                    first = harness.service.new_window()
                view_a = harness.open_owned_fixture(primary_path)
                shared_a = first.split_current(Qt.Orientation.Horizontal)
                if shared_a is None:
                    raise RuntimeError("lifecycle split view was not created")
                view_b = first.open_path(secondary_path)
                if view_b is None:
                    raise RuntimeError("secondary lifecycle document did not open")
                second = next(
                    (
                        window
                        for _window_id, window in harness.service.windows.items
                        if window is not first
                    ),
                    None,
                )
                if second is None:
                    second = harness.service.new_window()
                shared_b = second.open_existing_document(view_b.document)
            else:
                primary_entry = harness.service.documents.find_path(primary_path)
                secondary_entry = harness.service.documents.find_path(secondary_path)
                retained_views = _service_views(harness.service)
                if (
                    primary_entry is None
                    or secondary_entry is None
                    or len(primary_entry.view_ids) != 2
                    or len(secondary_entry.view_ids) != 2
                ):
                    raise RuntimeError("lifecycle stable document views were unavailable")
                view_a, shared_a = (
                    retained_views[view_id] for view_id in primary_entry.view_ids
                )
                view_b, shared_b = (
                    retained_views[view_id] for view_id in secondary_entry.view_ids
                )
                first = harness.service.windows.window_for_view(view_a.view_id)
                second = harness.service.windows.window_for_view(shared_b.view_id)
                if first is None or second is None or first is second:
                    raise RuntimeError("lifecycle stable window layout was unavailable")

            view_a.state.move_to(2)
            shared_a.state.move_to(17)
            view_b.state.move_to(5)
            shared_b.state.move_to(11)
            view_a.set_zoom_percent(110)
            shared_a.set_zoom_percent(120)
            view_b.set_zoom_percent(130)
            shared_b.set_zoom_percent(140)
            expected_view_state = {
                view_a.view_id: (2, 110),
                shared_a.view_id: (17, 120),
                view_b.view_id: (5, 130),
                shared_b.view_id: (11, 140),
            }

            suffix_a = f" primary-{sequence}"
            suffix_b = f" secondary-{sequence}"
            view_a.document.insert(view_a.document.total_chars(), suffix_a)
            view_a.document.undo()
            view_b.document.insert(view_b.document.total_chars(), suffix_b)
            view_b.document.undo()

            find_text, replace_text = _lifecycle_panel_values(sequence)
            panel.find_input.setPlainText(find_text)
            panel.find_input.setPlainText(find_text + "-next")
            panel.find_input.undo_input()
            panel.replace_input.setPlainText(replace_text)
            panel.replace_input.setPlainText(replace_text + "-next")
            panel.replace_input.undo_input()
            panel.regex_checkbox.setChecked(True)
            panel.show()

            from uniti.ui.find_replace import FIND_REPLACE_VIEW_ID

            first.panes.activate_view(shared_a.view_id)
            harness.service.set_active_view(first.window_id, shared_a.view_id)
            harness.service.attach_find_replace()
            harness.application.processEvents()
            attached = (
                panel.placement == "attached"
                and panel._dock_host is first
                and first.panes.contains_view(FIND_REPLACE_VIEW_ID)
            )
            second.panes.activate_view(shared_b.view_id)
            harness.service.set_active_view(second.window_id, shared_b.view_id)
            harness.application.processEvents()
            followed = panel._dock_host is second and second.panes.contains_view(
                FIND_REPLACE_VIEW_ID
            )
            harness.service.detach_find_replace()
            harness.application.processEvents()
            detached = panel.placement == "detached" and panel.isFloating()
            checks["panel_attach_detach"] &= attached and followed and detached
            checks["one_global_panel"] &= (
                panel is harness.service.find_replace
                and first.find_replace is panel
                and second.find_replace is panel
            )

            first.panes.activate_view(shared_a.view_id)
            harness.service.set_active_view(first.window_id, shared_a.view_id)
            harness.pump_until(
                lambda: all(
                    entry.saved_stamp is not None
                    for entry in harness.service.documents.entries
                )
                and _tasks_idle(harness)
            )
            checks["one_authority_per_path"] &= (
                _one_authority_per_path(harness.service)
                and harness.service.documents.count == 2
                and view_a.document is shared_a.document
                and view_b.document is shared_b.document
            )

            harness.service.schedule_publication(clean_shutdown=False)
            harness.pump_until(
                lambda: harness.session_store.current_path.exists()
                and _tasks_idle(harness)
            )
            published = harness.session_store.load_manifest()
            if published.manifest is None:
                raise RuntimeError("lifecycle session publication was unavailable")
            published_manifest = published.manifest
            generation_lease = harness.session_store.retain_generation(
                published_manifest.generation
            )
            active_document_id = next(
                record.document_id
                for record in published_manifest.views
                if record.view_id == published_manifest.active_view_id
            )

            find_handle = harness.resources.tasks.submit(
                TaskSpec.create(TaskKind.SESSION, foreground=True),
                lambda _context: (
                    load_threads.append(threading.get_ident()),
                    harness.session_store.load_find_replace_pack(published_manifest),
                )[1],
            )
            find_pack = harness.await_operation(find_handle)

            if sequence == 0:
                for _window_id, window in tuple(harness.service.windows.items):
                    window.close()
                remaining = harness.service.most_recent_window
                if remaining is None or not remaining.isVisible() or remaining.views:
                    raise RuntimeError("last editor window did not remain available")
                # Exercise service-owned zero-window restore independently of
                # the user close action, which now retains an empty window.
                remaining.close_for_service()
                harness.pump_until(
                    lambda: harness.service.window_count == 0
                    and _tasks_idle(harness)
                )
                checks["service_survived_last_window"] &= (
                    harness.service.is_running
                )
                activation = harness.service.new_window()
                checks["activation_created_window"] &= (
                    harness.service.window_count == 1
                    and harness.service.is_running
                )
                activation.close_for_service()
                harness.pump_until(
                    lambda: harness.service.window_count == 0
                    and _tasks_idle(harness)
                )
            else:
                for _window_id, window in tuple(harness.service.windows.items):
                    if not window.close_all_documents(force=True):
                        raise RuntimeError("lifecycle views did not close")
                harness.pump_until(
                    lambda: not tuple(harness.service.windows.ordered_view_ids)
                    and _tasks_idle(harness)
                )
            harness.service.documents.close_all()

            loaded_ids: list[str] = []

            def load_pack(document_id: str):
                loaded_ids.append(document_id)
                load_threads.append(threading.get_ident())
                return harness.session_store.load_document_pack(
                    published_manifest,
                    document_id,
                )

            harness.service.restore_shell(
                published_manifest,
                find_replace_pack=find_pack,
                pack_loader=load_pack,
            )
            generation_lease.release()
            generation_lease = None
            restored_active = harness.service.restore_active()
            checks["active_first_restored"] &= (
                restored_active is not None
                and loaded_ids == [active_document_id]
                and harness.service.documents.count == 1
                and harness.service.active_view is not None
                and harness.service.active_view.view_id
                == published_manifest.active_view_id
            )
            harness.service.schedule_lazy_restore()
            harness.pump_until(
                lambda: harness.service.documents.count == 2
                and _tasks_idle(harness)
            )
            checks["lazy_documents_restored"] &= (
                len(loaded_ids) == 2
                and set(loaded_ids)
                == {record.document_id for record in published_manifest.documents}
            )

            restored_views = _service_views(harness.service)
            checks["independent_view_state"] &= (
                set(restored_views) == set(expected_view_state)
                and all(
                    (
                        restored_views[view_id].state.cursor,
                        restored_views[view_id].zoom_percent,
                    )
                    == expected
                    for view_id, expected in expected_view_state.items()
                )
            )
            primary_entry = harness.service.documents.find_path(primary_path)
            secondary_entry = harness.service.documents.find_path(secondary_path)
            if primary_entry is None or secondary_entry is None:
                raise RuntimeError("restored lifecycle authority was unavailable")
            primary_entry.document.redo()
            primary_redo = primary_entry.document.read(
                primary_entry.document.total_chars() - len(suffix_a),
                primary_entry.document.total_chars(),
            ) == suffix_a
            primary_entry.document.undo()
            secondary_entry.document.redo()
            secondary_redo = secondary_entry.document.read(
                secondary_entry.document.total_chars() - len(suffix_b),
                secondary_entry.document.total_chars(),
            ) == suffix_b
            secondary_entry.document.undo()
            checks["history_undo_redo_exact"] &= (
                primary_redo
                and secondary_redo
                and _document_utf8_digest(primary_entry.document) == source_digest
                and _document_utf8_digest(secondary_entry.document)
                == secondary_digest
            )
            checks["find_replace_history_restored"] &= (
                harness.service.find_replace is panel
                and panel.find_input.text() == find_text
                and panel.find_input.can_undo_input
                and panel.find_input.can_redo_input
                and panel.replace_input.text() == replace_text
                and panel.replace_input.can_undo_input
                and panel.replace_input.can_redo_input
                and panel.regex_checkbox.isChecked()
                and panel.placement == "detached"
            )
            checks["one_authority_per_path"] &= _one_authority_per_path(
                harness.service
            )

            harness.service.schedule_publication(clean_shutdown=False)
            harness.pump_until(lambda: _tasks_idle(harness))
            current = harness.session_store.load_manifest()
            checks["session_generation_current"] &= (
                current.manifest is not None
                and current.source is SessionLoadSource.POINTER
                and current.manifest.generation != published_manifest.generation
                and len(current.manifest.documents) == 2
            )

            base_recovery_evidence = frozenset(
                path.resolve()
                for path in harness.paths.recovery_dir.glob("*.uniti-recovery")
            )
            base_recovery_diagnostics = harness.recovery_manager.diagnostics()
            recover_path = fixture_root / "recover.txt"
            discard_path = fixture_root / "discard.txt"
            recovered_text = _stage_recovery_candidate(
                harness,
                recover_path,
                f" recovered-{sequence}",
            )
            _stage_recovery_candidate(
                harness,
                discard_path,
                f" discarded-{sequence}",
            )
            candidates = harness.recovery_manager.discover()
            by_path = {
                candidate.session.source_path.resolve(): candidate
                for candidate in candidates
                if candidate.session is not None
            }
            selected_paths = (recover_path.resolve(), discard_path.resolve())
            if any(path not in by_path for path in selected_paths):
                raise RuntimeError("lifecycle recovery candidates were not exact")
            selected_candidates = tuple(by_path[path] for path in selected_paths)
            entries = harness.service.recovery_entries(selected_candidates, ())
            entry_by_path = {entry.path.resolve(): entry for entry in entries}
            recovered_count = harness.service.apply_recovery_decisions(
                (
                    RecoveryDecision(
                        entry_by_path[recover_path.resolve()].entry_id,
                        RecoveryAction.RECOVER,
                    ),
                    RecoveryDecision(
                        entry_by_path[discard_path.resolve()].entry_id,
                        RecoveryAction.DISCARD,
                    ),
                ),
                recovery_candidates=selected_candidates,
                target=harness.service.most_recent_window,
            )
            recovered_entry = harness.service.documents.find_path(recover_path)
            if recovered_entry is None:
                raise RuntimeError("recovered lifecycle document was not opened")
            recovered_document = recovered_entry.document
            recovered_document.undo()
            recovered_undo = (
                recovered_document.read(0, recovered_document.total_chars())
                == "recovery base"
            )
            recovered_document.redo()
            recovered_redo = (
                recovered_document.read(0, recovered_document.total_chars())
                == recovered_text
            )
            checks["recovery_undo_redo_exact"] &= (
                recovered_count == 1 and recovered_undo and recovered_redo
            )
            checks["one_authority_per_path"] &= _one_authority_per_path(
                harness.service
            )

            recovered_document.undo()
            if recovered_document.modified or len(recovered_entry.view_ids) != 1:
                raise RuntimeError("recovered lifecycle document did not return clean")
            recovered_view_id = recovered_entry.view_ids[0]
            recovery_window = harness.service.windows.window_for_view(
                recovered_view_id
            )
            if recovery_window is None:
                raise RuntimeError("recovered lifecycle view had no window")
            recovery_window.panes.activate_view(recovered_view_id)
            harness.service.set_active_view(
                recovery_window.window_id,
                recovered_view_id,
            )
            if not recovery_window.close_current():
                raise RuntimeError("recovered lifecycle view did not close")
            harness.service.documents.retire(recovered_entry.document_id)
            harness.pump_until(
                lambda: harness.service.documents.find_path(recover_path) is None
                and _tasks_idle(harness)
            )
            primary_entry = harness.service.documents.find_path(primary_path)
            secondary_entry = harness.service.documents.find_path(secondary_path)
            checks["stable_base_views_retained"] &= (
                primary_entry is not None
                and secondary_entry is not None
                and harness.service.documents.count == 2
                and len(primary_entry.view_ids) == 2
                and len(secondary_entry.view_ids) == 2
                and len(harness.service.windows.ordered_view_ids) == 4
            )
            recovery_diagnostics = harness.recovery_manager.diagnostics()
            checks["recovery_cleanup"] &= (
                frozenset(
                    path.resolve()
                    for path in harness.paths.recovery_dir.glob("*.uniti-recovery")
                )
                == base_recovery_evidence
                and len(base_recovery_evidence) == 2
                and len(recovery_diagnostics) == len(base_recovery_diagnostics) == 2
                and all(
                    (
                        (
                            diagnostic.health is RecoveryHealth.OK
                            and diagnostic.durability is DurabilityLevel.FULL
                        )
                        or (
                            diagnostic.health is RecoveryHealth.REDUCED
                            and diagnostic.durability
                            is DurabilityLevel.FILE_SYNCED
                        )
                    )
                    and diagnostic.durable_revision
                    == diagnostic.observed_revision
                    for diagnostic in recovery_diagnostics
                )
            )
            checks["service_identity_reused"] &= (
                harness.service_identity == service_identity
            )
            pressure = _exercise_injected_pressure(
                harness,
                fixture_root,
                sequence,
            )
            for key, observed in zip(
                (
                    "injected_resource_pressure",
                    "injected_capacity",
                    "injected_durability",
                    "injected_worker_state",
                ),
                pressure,
                strict=True,
            ):
                checks[key] &= observed

            if sequence >= harness.policy.sustained.warmup_cycles:
                checkpoint = harness.capture_checkpoint(measured_cycle)
                if (
                    checkpoint.owned_counts["documents"] != 2
                    or checkpoint.owned_counts["views"] != 4
                    or any(
                        checkpoint.owned_counts[name] != 0
                        for name in (
                            "active_tasks",
                            "queued_tasks",
                            "result_stores",
                            "replacement_plans",
                            "snapshots",
                        )
                    )
                ):
                    raise RuntimeError("lifecycle cycle left owned resources")
                checkpoints.append(
                    _checkpoint_with_timing(
                        checkpoint,
                        "lifecycle_cycle_ms",
                        (time.perf_counter() - started) * 1000.0,
                    )
                )

        explicit_quit = harness.service.request_quit(
            lambda _entry: QuitChoice.DISCARD
        )
        harness.application.processEvents()
    finally:
        if generation_lease is not None:
            generation_lease.release()
        harness.shutdown()

    background_storage = (
        bool(publication_threads)
        and bool(load_threads)
        and all(thread_id != gui_thread for thread_id in publication_threads)
        and all(thread_id != gui_thread for thread_id in load_threads)
    )
    cleanup_ok = (
        explicit_quit
        and not harness.service.is_running
        and harness.service.documents.count == 0
        and harness.service.windows.count == 0
        and _tasks_idle(harness)
        and harness.recovery_manager.diagnostics() == ()
        and not tuple(harness.paths.recovery_dir.glob("*.uniti-recovery"))
    )
    integrity_ok = all(checks.values()) and background_storage
    facts = {
        **checks,
        "background_storage": background_storage,
        "cleanup_ok": cleanup_ok,
        "cycles_completed": total_cycles,
        "explicit_quit": explicit_quit,
        "integrity_ok": integrity_ok,
        "primary_fixture_bytes": primary_fixture_bytes,
        "recovery_choices": ("recover", "discard"),
    }
    return SustainedFamilyResult(
        schema=2,
        family="session_lifecycle",
        profile="a22-v1",
        state=(
            ResultState.PASS
            if integrity_ok and cleanup_ok
            else ResultState.FAIL
        ),
        warmup_cycles=harness.policy.sustained.warmup_cycles,
        measured_cycles=cycles,
        checkpoints=tuple(checkpoints),
        facts=facts,
        messages=() if integrity_ok and cleanup_ok else ("lifecycle workflow failed",),
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
    if family == "format_integrity":
        return _run_format_integrity(
            cycles=cycles,
            manifest=manifest,
            application_root=application_root,
        )
    if family == "regex_replacement":
        return _run_regex_replacement(
            cycles=cycles,
            manifest=manifest,
            application_root=application_root,
        )
    if family == "session_lifecycle":
        return _run_session_lifecycle(
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
