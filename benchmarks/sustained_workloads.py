"""Deterministic sustained workload family registry."""

from __future__ import annotations

import hashlib
import shutil
import time
from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.corpus import (
    CorpusKind,
    CorpusManifest,
    generate_format_fixtures,
)
from benchmarks.models import ResultState
from benchmarks.sustained_models import ResourceCheckpoint, SustainedFamilyResult
from uniti.app.session import HistoryPack
from uniti.app.session_runtime import restore_document_pack
from uniti.core.byte_source import ByteSource
from uniti.core.document import Document
from uniti.core.file_identity import (
    ExternalFileChangedError,
    FileIdentity,
    FileMatch,
    SavedFileStamp,
)
from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile
from uniti.core.text_inspection import inspect_source
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
    if family == "format_integrity":
        return _run_format_integrity(
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
