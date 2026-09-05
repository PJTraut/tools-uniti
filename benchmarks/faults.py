"""Parent-controlled crash verification for harness-owned UNITI state."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import queue
import shutil
import subprocess
import sys
import threading
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from itertools import islice
from pathlib import Path
from typing import BinaryIO, Sequence

from uniti.app.atomic_json import atomic_write_json
from uniti.app.phase_control import (
    OperationId,
    OwnedObjectCategory,
    PhaseBoundary,
    PhaseEvent,
    PhaseId,
)


MAX_FAULT_IPC_BYTES = 16 << 10
_MAX_MESSAGE_CHARS = 512
_MARKER_NAME = ".uniti-fault-owned.json"
_CASE_STATE_NAME = "case-state.json"
_TERMINATION_NAME = "expected-termination.json"
_SOURCE_NAME = "fixture.txt"
_BASE_BYTES = b"fault base\n"
_SESSION_BYTES = b"fault base\nsaved session\n"
_SAVE_BYTES = b"fault base\nsaved edit\n"
_EXTERNAL_BYTES = b"external authority\n"
_RECOVERY_TEXT = "fault base\nunsaved recovery\n"
_REDO_TEXT = "pending redo\n"


class FaultCase(StrEnum):
    SESSION_PREVIOUS = "session_previous"
    SESSION_CURRENT = "session_current"
    SAVE_STAGE = "save_stage"
    SAVE_REPLACE = "save_replace"
    RECOVERY_APPEND = "recovery_append"
    RECOVERY_COMPACTION = "recovery_compaction"
    EXTERNAL_EDIT = "external_edit"
    QUIT_PUBLICATION = "quit_publication"


FAULT_CASE_ORDER = tuple(FaultCase)


@dataclass(frozen=True, slots=True)
class FaultResult:
    case: FaultCase
    passed: bool
    expected_termination: bool
    barrier_valid: bool
    exact_bytes: bool
    exact_hash: bool
    history_authority: bool
    no_partial_mixture: bool
    cleanup_ok: bool
    message: str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.case, FaultCase):
            raise TypeError("fault result case must be a FaultCase")
        for name in (
            "passed",
            "expected_termination",
            "barrier_valid",
            "exact_bytes",
            "exact_hash",
            "history_authority",
            "no_partial_mixture",
            "cleanup_ok",
        ):
            if type(getattr(self, name)) is not bool:
                raise TypeError(f"fault result {name} must be bool")
        if not isinstance(self.message, str) or len(self.message) > _MAX_MESSAGE_CHARS:
            raise ValueError("fault result message is invalid")
        derived = all(
            (
                self.expected_termination,
                self.barrier_valid,
                self.exact_bytes,
                self.exact_hash,
                self.history_authority,
                self.no_partial_mixture,
                self.cleanup_ok,
            )
        )
        if self.passed is not derived or bool(self.message) is self.passed:
            raise ValueError("fault result state is inconsistent with its evidence")


_RESULT_FIELDS = frozenset(
    {
        "case",
        "passed",
        "expected_termination",
        "barrier_valid",
        "exact_bytes",
        "exact_hash",
        "history_authority",
        "no_partial_mixture",
        "cleanup_ok",
        "message",
    }
)


def encode_fault_result(result: FaultResult) -> bytes:
    if not isinstance(result, FaultResult):
        raise TypeError("fault result is invalid")
    payload = asdict(result)
    payload["case"] = result.case.value
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_FAULT_IPC_BYTES:
        raise ValueError("fault result exceeds the IPC limit")
    return encoded


def decode_fault_result(payload: bytes) -> FaultResult:
    if not isinstance(payload, bytes):
        raise TypeError("fault result payload must be bytes")
    if len(payload) > MAX_FAULT_IPC_BYTES:
        raise ValueError("fault result exceeds the IPC limit")
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("fault result is not valid JSON") from exc
    if not isinstance(value, dict) or frozenset(value) != _RESULT_FIELDS:
        raise ValueError("fault result fields are invalid")
    try:
        return FaultResult(case=FaultCase(value.pop("case")), **value)
    except (TypeError, ValueError) as exc:
        raise ValueError("fault result values are invalid") from exc


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _expected_bytes(case: FaultCase) -> bytes:
    if case in {
        FaultCase.SESSION_PREVIOUS,
        FaultCase.SESSION_CURRENT,
        FaultCase.QUIT_PUBLICATION,
    }:
        return _SESSION_BYTES
    if case is FaultCase.SAVE_REPLACE:
        return _SAVE_BYTES
    if case is FaultCase.EXTERNAL_EDIT:
        return _EXTERNAL_BYTES
    return _BASE_BYTES


def _phase_for_case(case: FaultCase) -> PhaseEvent:
    if case is FaultCase.SESSION_PREVIOUS:
        return PhaseEvent(
            OperationId.SESSION_PUBLICATION,
            PhaseId.POINTER,
            PhaseBoundary.BEFORE,
            OwnedObjectCategory.SESSION_POINTER,
        )
    if case in {
        FaultCase.SESSION_CURRENT,
        FaultCase.QUIT_PUBLICATION,
    }:
        return PhaseEvent(
            OperationId.SESSION_PUBLICATION,
            PhaseId.POINTER,
            PhaseBoundary.AFTER,
            OwnedObjectCategory.SESSION_POINTER,
        )
    if case is FaultCase.SAVE_STAGE:
        return PhaseEvent(
            OperationId.DOCUMENT_SAVE,
            PhaseId.STAGE,
            PhaseBoundary.AFTER,
            OwnedObjectCategory.DOCUMENT_OUTPUT,
        )
    if case is FaultCase.SAVE_REPLACE:
        return PhaseEvent(
            OperationId.DOCUMENT_SAVE,
            PhaseId.REPLACE,
            PhaseBoundary.AFTER,
            OwnedObjectCategory.DOCUMENT_OUTPUT,
        )
    if case is FaultCase.RECOVERY_APPEND:
        return PhaseEvent(
            OperationId.RECOVERY_WRITE,
            PhaseId.APPEND,
            PhaseBoundary.AFTER,
            OwnedObjectCategory.RECOVERY_JOURNAL,
        )
    if case is FaultCase.RECOVERY_COMPACTION:
        return PhaseEvent(
            OperationId.RECOVERY_COMPACTION,
            PhaseId.COMPACTION,
            PhaseBoundary.AFTER,
            OwnedObjectCategory.RECOVERY_JOURNAL,
        )
    return PhaseEvent(
        OperationId.DOCUMENT_SAVE,
        PhaseId.VERIFY,
        PhaseBoundary.AFTER,
        OwnedObjectCategory.DOCUMENT_OUTPUT,
    )


def _write_state(root: Path, payload: dict[str, object]) -> None:
    atomic_write_json(root / _CASE_STATE_NAME, payload)


def _read_json(path: Path, *, maximum: int = MAX_FAULT_IPC_BYTES) -> dict:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise ValueError("fault metadata is missing or oversized")
    try:
        value = json.loads(path.read_bytes())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("fault metadata is invalid") from exc
    if not isinstance(value, dict):
        raise ValueError("fault metadata must be an object")
    return value


def _send_barrier(payload: dict[str, str]) -> None:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) + 1 > MAX_FAULT_IPC_BYTES:
        raise ValueError("fault barrier exceeds the IPC limit")
    sys.stdout.buffer.write(encoded + b"\n")
    sys.stdout.buffer.flush()


class _BlockingPhaseObserver:
    def __init__(self, target: PhaseEvent) -> None:
        self.target = target
        self.triggered = False

    def observe(self, event: PhaseEvent) -> None:
        if event != self.target or self.triggered:
            return
        self.triggered = True
        _send_barrier(
            {
                "boundary": event.boundary.value,
                "kind": "phase",
                "operation": event.operation_id.value,
                "owned_category": event.owned_category.value,
                "phase": event.phase_id.value,
            }
        )
        token = sys.stdin.buffer.readline(MAX_FAULT_IPC_BYTES + 1)
        if token != b"release\n":
            raise RuntimeError("fault phase was not released")


def _empty_find_replace(target_view_id: str):
    from uniti.app.session import FindReplaceManifestRecord, InputStateRecord

    empty = InputStateRecord("", 0, 0)
    return FindReplaceManifestRecord(
        empty,
        empty,
        False,
        False,
        False,
        False,
        None,
        100,
        False,
        target_view_id,
        None,
        "attached",
    )


def _session_snapshot(source: Path, *, clean_shutdown: bool):
    from uniti.app.session import (
        SESSION_SCHEMA,
        DocumentRecord,
        HistoryPack,
        PaneRecord,
        SessionManifest,
        SessionSnapshot,
        ViewRecord,
        WindowRecord,
    )
    from uniti.core.file_identity import FileIdentity, SavedFileStamp
    from uniti.core.history import EditHistory, EditOperation, EditTransaction

    base_text = _BASE_BYTES.decode("utf-8")
    session_text = _SESSION_BYTES.decode("utf-8")
    history = EditHistory()
    history.record(
        EditTransaction(
            (EditOperation(len(base_text), "", "saved session\n"),)
        )
    )
    history.mark_saved()
    history.record(
        EditTransaction(
            (EditOperation(len(session_text), "", _REDO_TEXT),)
        )
    )
    history.undo()
    timestamp = "2026-09-05T00:00:00Z"
    document_id = "fault-document"
    view_id = "fault-view"
    pack = HistoryPack(
        document_id=document_id,
        generation="fault-history",
        canonical_path=str(source),
        saved_stamp=SavedFileStamp(FileIdentity.from_path(source), _digest(_SESSION_BYTES)),
        source_profile_key="utf-8",
        selected_output_profile_key="utf-8",
        selected_output_eol=None,
        saved_output_profile_key="utf-8",
        saved_output_eol=None,
        history=history.export_snapshot(),
        last_active_at=timestamp,
        closed_at=None,
    )
    manifest = SessionManifest(
        schema=SESSION_SCHEMA,
        generation="fault-capture",
        service_id="fault-service",
        build_identity="a22-fault",
        created_at=timestamp,
        updated_at=timestamp,
        clean_shutdown=clean_shutdown,
        active_window_id="fault-window",
        active_view_id=view_id,
        windows=(
            WindowRecord(
                "fault-window",
                (0, 0, 800, 600),
                "normal",
                PaneRecord(
                    "leaf",
                    "fault-pane",
                    view_ids=(view_id,),
                    selected_view_id=view_id,
                ),
            ),
        ),
        views=(ViewRecord(view_id, document_id, 0, 0, None, 0, 0, 0, False, 100),),
        documents=(DocumentRecord(document_id, str(source), (view_id,), timestamp, None),),
        find_replace=_empty_find_replace(view_id),
        packs=(),
    )
    return SessionSnapshot(manifest, (pack,), None)


def _run_session_child(root: Path, case: FaultCase, observer) -> None:
    from uniti.app.session_store import SessionStore

    source = root / _SOURCE_NAME
    source.write_bytes(_SESSION_BYTES)
    session_root = root / "session"
    previous_store = SessionStore(session_root)
    previous = previous_store.publish(
        _session_snapshot(source, clean_shutdown=False)
    )
    clean_shutdown = case is FaultCase.QUIT_PUBLICATION
    _write_state(
        root,
        {
            "case": case.value,
            "clean_shutdown": clean_shutdown,
            "previous_generation": previous.generation,
        },
    )
    SessionStore(session_root, phase_observer=observer).publish(
        _session_snapshot(source, clean_shutdown=clean_shutdown)
    )


def _run_quit_child(root: Path, observer) -> None:
    from uniti.app.recovery_manager import RecoveryManager
    from uniti.app.service import UNITIService
    from uniti.app.session_store import SessionStore
    from uniti.app.settings import SettingsStore
    from uniti.resources import ResourceManager

    source = root / _SOURCE_NAME
    source.write_bytes(_SESSION_BYTES)
    session_root = root / "session"
    previous = SessionStore(session_root).publish(
        _session_snapshot(source, clean_shutdown=False)
    )
    _write_state(
        root,
        {
            "case": FaultCase.QUIT_PUBLICATION.value,
            "clean_shutdown": True,
            "previous_generation": previous.generation,
        },
    )
    settings = SettingsStore(root / "config" / "settings.json")
    settings.prepare()
    resources = ResourceManager(max_workers=1)
    recovery = RecoveryManager(root / "recovery", resource_manager=resources)
    service = UNITIService(
        resource_manager=resources,
        settings_store=settings,
        session_store=SessionStore(session_root, phase_observer=observer),
        recovery_manager=recovery,
        session_capture=lambda clean: _session_snapshot(
            source,
            clean_shutdown=clean,
        ),
        service_id="fault-quit-service",
        build_identity="a22-fault",
    )
    service.request_quit(lambda _entry: None)


def _run_save_child(root: Path, observer) -> None:
    from uniti.core.document import Document
    from uniti.core.save_job import ImmediateSaveContext, prepare_document_save

    source = root / _SOURCE_NAME
    source.write_bytes(_BASE_BYTES)
    _write_state(root, {"case": "save", "new_digest": _digest(_SAVE_BYTES)})
    document = Document.open(source)
    document.insert(document.total_chars(), "saved edit\n")
    request = document.create_save_request(source, document.output_format)
    prepared = prepare_document_save(
        request,
        ImmediateSaveContext(),
        phase_observer=observer,
    )
    document.commit_prepared_save(prepared)


def _run_recovery_child(root: Path, case: FaultCase, observer) -> None:
    from uniti.app.recovery_manager import RecoveryManager
    from uniti.core.document import Document

    source = root / _SOURCE_NAME
    source.write_bytes(_BASE_BYTES)
    _write_state(root, {"case": case.value, "recovered_text": _RECOVERY_TEXT})
    manager = RecoveryManager(root / "recovery", phase_observer=observer)
    document = Document.open(source)
    manager.attach(document)
    document.insert(document.total_chars(), "unsaved recovery\n")
    manager.flush(document)
    if case is FaultCase.RECOVERY_COMPACTION:
        manager.compact(document).result()


def _run_external_child(root: Path, observer) -> None:
    from uniti.app.session_store import SessionStore
    from uniti.core.document import Document
    from uniti.core.file_identity import ExternalFileChangedError
    from uniti.core.save_job import ImmediateSaveContext, prepare_document_save

    source = root / _SOURCE_NAME
    source.write_bytes(_BASE_BYTES)
    session_root = root / "session"
    SessionStore(session_root).publish(
        _session_snapshot_for_external(source)
    )
    _write_state(
        root,
        {
            "case": FaultCase.EXTERNAL_EDIT.value,
            "original_digest": _digest(_BASE_BYTES),
        },
    )
    document = Document.open(source)
    document.insert(document.total_chars(), "saved edit\n")
    request = document.create_save_request(source, document.output_format)
    prepared = prepare_document_save(
        request,
        ImmediateSaveContext(),
        phase_observer=observer,
    )
    try:
        document.commit_prepared_save(prepared)
    except ExternalFileChangedError:
        prepared.discard()
        _send_barrier({"kind": "external_refused"})
        sys.stdin.buffer.readline(MAX_FAULT_IPC_BYTES + 1)
        return
    raise RuntimeError("external edit was overwritten")


def _session_snapshot_for_external(source: Path):
    snapshot = _session_snapshot(source, clean_shutdown=False)
    from dataclasses import replace
    from uniti.app.session import SessionSnapshot
    from uniti.core.file_identity import FileIdentity, SavedFileStamp
    from uniti.core.history import HistorySnapshot

    pack = replace(
        snapshot.packs[0],
        saved_stamp=SavedFileStamp(FileIdentity.from_path(source), _digest(_BASE_BYTES)),
        history=HistorySnapshot.empty(),
    )
    return SessionSnapshot(snapshot.manifest, (pack,), None)


def run_fault_child(case: FaultCase, root: Path, expected_digest: str) -> None:
    selected_root = _validate_owned_root(root, case)
    if expected_digest != _digest(_expected_bytes(case)):
        raise ValueError("fault fixture digest is not the expected constant")
    observer = _BlockingPhaseObserver(_phase_for_case(case))
    if case in {
        FaultCase.SESSION_PREVIOUS,
        FaultCase.SESSION_CURRENT,
    }:
        _run_session_child(selected_root, case, observer)
    elif case is FaultCase.QUIT_PUBLICATION:
        _run_quit_child(selected_root, observer)
    elif case in {FaultCase.SAVE_STAGE, FaultCase.SAVE_REPLACE}:
        _run_save_child(selected_root, observer)
    elif case in {FaultCase.RECOVERY_APPEND, FaultCase.RECOVERY_COMPACTION}:
        _run_recovery_child(selected_root, case, observer)
    else:
        _run_external_child(selected_root, observer)
    raise RuntimeError("fault child crossed its termination barrier")


def _validate_owned_root(root: Path, case: FaultCase | None = None) -> Path:
    candidate = Path(root)
    if not candidate.is_absolute() or candidate.is_symlink():
        raise ValueError("fault root must be an absolute non-symlink path")
    resolved = candidate.resolve(strict=True)
    if not resolved.is_dir():
        raise ValueError("fault root must be a directory")
    marker = _read_json(resolved / _MARKER_NAME)
    expected_fields = {"case", "schema"}
    if set(marker) != expected_fields or marker.get("schema") != 1:
        raise ValueError("fault ownership marker is invalid")
    try:
        marked_case = FaultCase(marker["case"])
    except (TypeError, ValueError) as exc:
        raise ValueError("fault ownership marker case is invalid") from exc
    if case is not None and marked_case is not case:
        raise ValueError("fault ownership marker does not match the case")
    return resolved


def _verify_session(
    root: Path,
    case: FaultCase,
    expected_digest: str,
) -> tuple[bool, bool, bool, bool, bool]:
    from uniti.app.session_runtime import restore_document_pack
    from uniti.app.session_store import SessionStore
    from uniti.resources import ResourceManager

    source = root / _SOURCE_NAME
    state = _read_json(root / _CASE_STATE_NAME)
    store = SessionStore(root / "session")
    loaded = store.load_latest()
    manifest = loaded.manifest
    exact_bytes = source.read_bytes() == _SESSION_BYTES
    exact_hash = _digest(source.read_bytes()) == expected_digest
    if manifest is None:
        return exact_bytes, exact_hash, False, False, False
    expect_previous = case is FaultCase.SESSION_PREVIOUS
    expected_clean = case is FaultCase.QUIT_PUBLICATION
    authority_ok = (
        (manifest.generation == state.get("previous_generation"))
        if expect_previous
        else (manifest.generation != state.get("previous_generation"))
    )
    authority_ok = authority_ok and manifest.clean_shutdown is expected_clean
    resources = ResourceManager(max_workers=1)
    restored = None
    try:
        pack = store.load_document_pack(manifest, "fault-document")
        restored_result = restore_document_pack(
            pack,
            ("fault-view",),
            resource_manager=resources,
        )
        restored = restored_result.document
        history_authority = (
            restored is not None
            and restored.read(0, restored.total_chars())
            == _SESSION_BYTES.decode("utf-8")
            and restored.can_undo
            and restored.can_redo
        )
        if restored is not None and history_authority:
            restored.undo()
            history_authority = (
                restored.read(0, restored.total_chars()) == _BASE_BYTES.decode("utf-8")
            )
            restored.redo()
            restored.redo()
            history_authority = history_authority and (
                restored.read(0, restored.total_chars())
                == _SESSION_BYTES.decode("utf-8") + _REDO_TEXT
            )
    finally:
        if restored is not None:
            restored.close()
        resources.shutdown()
    report = store.cleanup(now=datetime.now(UTC))
    no_partial = authority_ok and not loaded.problems and not report.errors
    temporary = tuple((root / "session").rglob("*.tmp"))
    stored = tuple(islice((root / "session").rglob("*"), 13))
    cleanup_ok = not temporary and len(stored) <= 12
    return exact_bytes, exact_hash, history_authority, no_partial, cleanup_ok


def _verify_save(
    root: Path,
    case: FaultCase,
    expected_digest: str,
) -> tuple[bool, bool, bool, bool, bool]:
    source = root / _SOURCE_NAME
    data = source.read_bytes()
    expected = _BASE_BYTES if case is FaultCase.SAVE_STAGE else _SAVE_BYTES
    temporary = tuple(root.glob(f".{_SOURCE_NAME}.*.uniti-tmp"))
    staged_ok = True
    if case is FaultCase.SAVE_STAGE:
        staged_ok = len(temporary) == 1 and temporary[0].read_bytes() == _SAVE_BYTES
    else:
        staged_ok = not temporary
    for path in temporary:
        path.unlink()
    cleanup_ok = not tuple(root.glob(f".{_SOURCE_NAME}.*.uniti-tmp"))
    exact_bytes = data == expected
    exact_hash = _digest(data) == expected_digest
    return exact_bytes, exact_hash, staged_ok, exact_bytes and staged_ok, cleanup_ok


def _verify_recovery(
    root: Path,
    expected_digest: str,
) -> tuple[bool, bool, bool, bool, bool]:
    from uniti.app.recovery_manager import RecoveryManager

    source = root / _SOURCE_NAME
    exact_bytes = source.read_bytes() == _BASE_BYTES
    exact_hash = _digest(source.read_bytes()) == expected_digest
    manager = RecoveryManager(root / "recovery")
    recovered = None
    try:
        candidates = manager.discover()
        no_partial = len(candidates) == 1 and candidates[0].session is not None
        if not no_partial:
            return exact_bytes, exact_hash, False, False, False
        recovered = manager.recover(candidates[0])
        history_authority = (
            recovered.read(0, recovered.total_chars()) == _RECOVERY_TEXT
            and recovered.can_undo
        )
        if history_authority:
            recovered.undo()
            history_authority = (
                recovered.read(0, recovered.total_chars())
                == _BASE_BYTES.decode("utf-8")
            )
            recovered.redo()
            history_authority = history_authority and (
                recovered.read(0, recovered.total_chars()) == _RECOVERY_TEXT
            )
        manager.detach(recovered, clean=True)
        recovered.close()
        recovered = None
        cleanup_ok = not tuple((root / "recovery").glob("*.uniti-recovery*"))
        return exact_bytes, exact_hash, history_authority, no_partial, cleanup_ok
    finally:
        if recovered is not None:
            manager.detach(recovered, clean=True)
            recovered.close()
        manager.shutdown()


def _verify_external(
    root: Path,
    expected_digest: str,
) -> tuple[bool, bool, bool, bool, bool]:
    from uniti.app.session_store import SessionStore
    from uniti.core.file_identity import FileMatch, verify_saved_file

    source = root / _SOURCE_NAME
    data = source.read_bytes()
    store = SessionStore(root / "session")
    loaded = store.load_latest()
    exact_bytes = data == _EXTERNAL_BYTES
    exact_hash = _digest(data) == expected_digest
    history_authority = False
    if loaded.manifest is not None:
        pack = store.load_document_pack(loaded.manifest, "fault-document")
        history_authority = (
            pack.saved_stamp.sha256 == _digest(_BASE_BYTES)
            and verify_saved_file(source, pack.saved_stamp) is FileMatch.CHANGED
        )
    temporary = tuple(root.glob(f".{_SOURCE_NAME}.*.uniti-tmp"))
    for path in temporary:
        path.unlink()
    no_partial = exact_bytes and history_authority
    cleanup_ok = not tuple(root.glob(f".{_SOURCE_NAME}.*.uniti-tmp"))
    return exact_bytes, exact_hash, history_authority, no_partial, cleanup_ok


def verify_fault_case(root: Path, expected_digest: str) -> FaultResult:
    selected_root = _validate_owned_root(root)
    marker = _read_json(selected_root / _MARKER_NAME)
    case = FaultCase(marker["case"])
    termination = _read_json(selected_root / _TERMINATION_NAME)
    expected_termination = (
        set(termination)
        == {"barrier_valid", "case", "expected", "pid", "returncode"}
        and termination.get("case") == case.value
        and termination.get("expected") is True
        and type(termination.get("pid")) is int
        and type(termination.get("returncode")) is int
        and termination["returncode"] != 0
    )
    barrier_valid = termination.get("barrier_valid") is True
    try:
        if case in {
            FaultCase.SESSION_PREVIOUS,
            FaultCase.SESSION_CURRENT,
            FaultCase.QUIT_PUBLICATION,
        }:
            checks = _verify_session(selected_root, case, expected_digest)
        elif case in {FaultCase.SAVE_STAGE, FaultCase.SAVE_REPLACE}:
            checks = _verify_save(selected_root, case, expected_digest)
        elif case in {FaultCase.RECOVERY_APPEND, FaultCase.RECOVERY_COMPACTION}:
            checks = _verify_recovery(selected_root, expected_digest)
        else:
            checks = _verify_external(selected_root, expected_digest)
        exact_bytes, exact_hash, history, no_partial, cleanup = checks
        passed = all(
            (
                expected_termination,
                barrier_valid,
                exact_bytes,
                exact_hash,
                history,
                no_partial,
                cleanup,
            )
        )
        return FaultResult(
            case,
            passed,
            expected_termination,
            barrier_valid,
            exact_bytes,
            exact_hash,
            history,
            no_partial,
            cleanup,
            "" if passed else "fault verification failed",
        )
    except Exception as exc:
        return _failed_result(case, f"verifier failed: {type(exc).__name__}")


def _failed_result(case: FaultCase, message: str) -> FaultResult:
    return FaultResult(
        case,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        False,
        message[:_MAX_MESSAGE_CHARS],
    )


def _read_bounded_line(
    stream: BinaryIO,
    *,
    timeout_seconds: float,
) -> bytes:
    received: queue.Queue[bytes | BaseException] = queue.Queue(maxsize=1)

    def read() -> None:
        try:
            received.put(stream.readline(MAX_FAULT_IPC_BYTES + 1))
        except BaseException as exc:
            received.put(exc)

    threading.Thread(target=read, daemon=True).start()
    try:
        value = received.get(timeout=timeout_seconds)
    except queue.Empty as exc:
        raise TimeoutError("fault barrier timed out") from exc
    if isinstance(value, BaseException):
        raise OSError("fault barrier could not be read") from value
    if not value.endswith(b"\n") or len(value) > MAX_FAULT_IPC_BYTES:
        raise ValueError("fault barrier is missing or oversized")
    return value[:-1]


def _decode_barrier(payload: bytes) -> dict[str, str]:
    try:
        value = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("fault barrier is invalid") from exc
    if not isinstance(value, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in value.items()
    ):
        raise ValueError("fault barrier is invalid")
    return value


def _barrier_matches(case: FaultCase, message: dict[str, str]) -> bool:
    expected = _phase_for_case(case)
    return message == {
        "boundary": expected.boundary.value,
        "kind": "phase",
        "operation": expected.operation_id.value,
        "owned_category": expected.owned_category.value,
        "phase": expected.phase_id.value,
    }


def _terminate_exact(process: subprocess.Popen, timeout_seconds: float) -> bool:
    if process.poll() is not None:
        return False
    process.terminate()
    try:
        process.wait(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=timeout_seconds)
    return process.returncode is not None and process.returncode != 0


def _run_verifier(
    command: tuple[str, ...],
    *,
    repository: Path,
    environment: dict[str, str],
    timeout_seconds: float,
) -> tuple[int, bytes]:
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        shell=False,
        cwd=repository,
        env=environment,
    )
    try:
        assert process.stdout is not None
        payload = _read_bounded_line(
            process.stdout,
            timeout_seconds=timeout_seconds,
        )
        try:
            returncode = process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError("fault verifier timed out") from exc
        return returncode, payload
    finally:
        if process.poll() is None:
            _terminate_exact(process, timeout_seconds)


def _remove_owned_case(application_root: Path, case_root: Path) -> None:
    parent = application_root.resolve(strict=True)
    selected = case_root.resolve(strict=False)
    if selected.parent != parent or selected.name not in {case.value for case in FaultCase}:
        raise RuntimeError("refusing fault cleanup outside the exact application root")
    if case_root.is_symlink():
        case_root.unlink()
    elif case_root.exists():
        shutil.rmtree(case_root)


def run_fault_case(
    case: FaultCase,
    application_root: Path,
    *,
    timeout_seconds: float,
) -> FaultResult:
    if not isinstance(case, FaultCase):
        raise TypeError("fault case must be a FaultCase")
    if timeout_seconds <= 0:
        raise ValueError("fault timeout must be positive")
    root_argument = Path(application_root)
    if root_argument.exists() and root_argument.is_symlink():
        raise ValueError("fault application root must not be a symlink")
    root_argument.mkdir(parents=True, exist_ok=True)
    root = root_argument.resolve(strict=True)
    case_root = root / case.value
    case_root.mkdir()
    atomic_write_json(case_root / _MARKER_NAME, {"case": case.value, "schema": 1})
    expected_digest = _digest(_expected_bytes(case))
    repository = Path(__file__).resolve().parents[1]
    environment = dict(os.environ)
    environment["QT_QPA_PLATFORM"] = "offscreen"
    command = (
        sys.executable,
        "-m",
        "benchmarks.faults",
        "--fault-child",
        case.value,
        "--owned-root",
        str(case_root),
        "--expected-digest",
        expected_digest,
    )
    process: subprocess.Popen | None = None
    result = _failed_result(case, "fault controller did not complete")
    try:
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            shell=False,
            cwd=repository,
            env=environment,
        )
        assert process.stdout is not None
        assert process.stdin is not None
        barrier = _decode_barrier(
            _read_bounded_line(process.stdout, timeout_seconds=timeout_seconds)
        )
        barrier_valid = _barrier_matches(case, barrier)
        if not barrier_valid:
            raise ValueError("fault child reached the wrong barrier")
        if case is FaultCase.EXTERNAL_EDIT:
            (case_root / _SOURCE_NAME).write_bytes(_EXTERNAL_BYTES)
            process.stdin.write(b"release\n")
            process.stdin.flush()
            refusal = _decode_barrier(
                _read_bounded_line(process.stdout, timeout_seconds=timeout_seconds)
            )
            if refusal != {"kind": "external_refused"}:
                raise ValueError("external edit refusal was not confirmed")
        expected_termination = _terminate_exact(process, timeout_seconds)
        if not expected_termination:
            raise RuntimeError("fault child exited before parent termination")
        atomic_write_json(
            case_root / _TERMINATION_NAME,
            {
                "case": case.value,
                "barrier_valid": barrier_valid,
                "expected": True,
                "pid": process.pid,
                "returncode": process.returncode,
            },
        )
        verifier_returncode, verifier_payload = _run_verifier(
            (
                sys.executable,
                "-m",
                "benchmarks.faults",
                "--fault-verify",
                "--owned-root",
                str(case_root),
                "--expected-digest",
                expected_digest,
            ),
            repository=repository,
            environment=environment,
            timeout_seconds=timeout_seconds,
        )
        result = decode_fault_result(verifier_payload)
        if verifier_returncode != 0 and result.passed:
            raise RuntimeError("fault verifier returned an inconsistent status")
    except Exception as exc:
        result = _failed_result(case, f"controller failed: {type(exc).__name__}")
    finally:
        if process is not None and process.poll() is None:
            _terminate_exact(process, timeout_seconds)
        _remove_owned_case(root, case_root)
    return result


def run_fault_suite(
    application_root: Path,
    *,
    timeout_seconds: float,
) -> tuple[FaultResult, ...]:
    root = Path(application_root)
    existed = root.exists()
    results = tuple(
        run_fault_case(case, root, timeout_seconds=timeout_seconds)
        for case in FAULT_CASE_ORDER
    )
    if not existed and root.is_dir() and not tuple(root.iterdir()):
        root.rmdir()
    return results


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m benchmarks.faults")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--fault-child", choices=tuple(case.value for case in FaultCase))
    mode.add_argument("--fault-verify", action="store_true")
    parser.add_argument("--owned-root", required=True, type=Path)
    parser.add_argument("--expected-digest", required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    if arguments.fault_child is not None:
        run_fault_child(
            FaultCase(arguments.fault_child),
            arguments.owned_root,
            arguments.expected_digest,
        )
        return 1
    result = verify_fault_case(arguments.owned_root, arguments.expected_digest)
    sys.stdout.buffer.write(encode_fault_result(result) + b"\n")
    sys.stdout.buffer.flush()
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "FAULT_CASE_ORDER",
    "MAX_FAULT_IPC_BYTES",
    "FaultCase",
    "FaultResult",
    "decode_fault_result",
    "encode_fault_result",
    "run_fault_case",
    "run_fault_suite",
    "verify_fault_case",
]
