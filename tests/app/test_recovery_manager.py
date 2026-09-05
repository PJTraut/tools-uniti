import os
from concurrent.futures import Future
from pathlib import Path

import pytest

from uniti.app.phase_control import (
    OperationId,
    OwnedObjectCategory,
    PhaseBoundary,
    PhaseId,
)
from uniti.app.recovery_manager import (
    FileRecoveryIO,
    RecoveryHealth,
    RecoveryManager,
)
from uniti.core.document import Document
from uniti.core.durability import (
    DurabilityError,
    DurabilityLevel,
    DurabilityResult,
)
from uniti.core.file_identity import FileIdentity, SavedFileStamp, sha256_file
from uniti.core.recovery import (
    RecoveryEventKind,
    RecoveryLoadStatus,
    RecoverySourceMismatchError,
    replay_recovery,
)
from uniti.resources import MemorySnapshot, ResourceManager
from uniti.resources.tasks import TaskKind


class InjectedRecoveryIO:
    def __init__(
        self,
        *,
        free_bytes: int = 8 << 30,
        forced_size: int | None = None,
    ) -> None:
        self._real = FileRecoveryIO()
        self.available_bytes = free_bytes
        self.forced_size = forced_size
        self.fail_append = False
        self.fail_flush = False
        self.fail_fsync = False
        self.fail_replace = False
        self.directory_level = DurabilityLevel.FULL
        self.calls: list[tuple[str, Path | None, Path | None]] = []

    @staticmethod
    def _result(operation: str, level: DurabilityLevel) -> DurabilityResult:
        if level is DurabilityLevel.FULL:
            return DurabilityResult(operation, level, True, True, True)
        return DurabilityResult(
            operation,
            level,
            True,
            True,
            False,
            "directory_sync_unavailable",
        )

    @staticmethod
    def _unsafe(operation: str) -> DurabilityError:
        cause = OSError(f"injected {operation} failure")
        return DurabilityError(
            DurabilityResult(
                operation,
                DurabilityLevel.UNSAFE,
                False,
                False,
                False,
                f"{operation}:OSError",
            ),
            cause,
        )

    def append(self, journal, record) -> None:
        self.calls.append(("append", journal.path, None))
        if self.fail_append:
            raise OSError("injected append failure")
        self._real.append(journal, record)

    def flush(self, journal) -> None:
        self.calls.append(("flush", journal.path, None))
        if self.fail_flush:
            raise OSError("injected flush failure")
        self._real.flush(journal)

    def fsync(self, journal) -> DurabilityResult:
        self.calls.append(("fsync", journal.path, None))
        if self.fail_fsync:
            raise self._unsafe("recovery_fsync")
        self._real.fsync(journal)
        return self._result("recovery_fsync", DurabilityLevel.FULL)

    def size(self, path: Path) -> int:
        if self.forced_size is not None:
            return self.forced_size
        return self._real.size(path)

    def replace(self, source: Path, destination: Path) -> DurabilityResult:
        self.calls.append(("replace", source, destination))
        if self.fail_replace:
            raise self._unsafe("recovery_replace")
        self._real.replace(source, destination)
        return self._result("recovery_replace", self.directory_level)

    def sync_directory(self, path: Path) -> DurabilityResult:
        self.calls.append(("sync_directory", path, None))
        return self._result("recovery_directory_sync", self.directory_level)

    def unlink(self, path: Path) -> None:
        self.calls.append(("unlink", path, None))
        self._real.unlink(path)

    def free_bytes(self, path: Path) -> int:
        return self.available_bytes


class RecordingPhaseObserver:
    def __init__(self) -> None:
        self.events = []

    def observe(self, event) -> None:
        self.events.append(event)


def test_recovery_emits_append_fsync_compaction_and_replace_boundaries(
    tmp_path: Path,
):
    source = tmp_path / "phase-recovery.txt"
    source.write_text("base", encoding="utf-8")
    observer = RecordingPhaseObserver()
    manager = RecoveryManager(
        tmp_path / "recovery",
        phase_observer=observer,
    )
    document = Document.open(source)
    try:
        manager.attach(document)
        document.insert(document.total_chars(), " changed")
        manager.flush(document)
        manager.compact(document).result()

        journal_events = [
            (event.operation_id, event.phase_id, event.boundary)
            for event in observer.events
            if event.owned_category is OwnedObjectCategory.RECOVERY_JOURNAL
        ]
        assert (
            OperationId.RECOVERY_WRITE,
            PhaseId.APPEND,
            PhaseBoundary.BEFORE,
        ) in journal_events
        assert (
            OperationId.RECOVERY_WRITE,
            PhaseId.APPEND,
            PhaseBoundary.AFTER,
        ) in journal_events
        assert (
            OperationId.RECOVERY_WRITE,
            PhaseId.FSYNC,
            PhaseBoundary.BEFORE,
        ) in journal_events
        assert (
            OperationId.RECOVERY_WRITE,
            PhaseId.FSYNC,
            PhaseBoundary.AFTER,
        ) in journal_events
        compaction = [
            item
            for item in journal_events
            if item[0] is OperationId.RECOVERY_COMPACTION
        ]
        operation = OperationId.RECOVERY_COMPACTION
        assert compaction == [
            (operation, PhaseId.COMPACTION, PhaseBoundary.BEFORE),
            (operation, PhaseId.APPEND, PhaseBoundary.BEFORE),
            (operation, PhaseId.APPEND, PhaseBoundary.AFTER),
            (operation, PhaseId.FSYNC, PhaseBoundary.BEFORE),
            (operation, PhaseId.FSYNC, PhaseBoundary.AFTER),
            (operation, PhaseId.REPLACE, PhaseBoundary.BEFORE),
            (operation, PhaseId.REPLACE, PhaseBoundary.AFTER),
            (operation, PhaseId.COMPACTION, PhaseBoundary.AFTER),
        ]
    finally:
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_recovery_manager_is_lazy_and_tracks_undo_redo(tmp_path: Path):
    source = tmp_path / "doc.txt"
    source.write_text("abc", encoding="utf-8")
    manager = RecoveryManager(tmp_path / "recovery")
    document = Document.open(source)
    manager.attach(document)
    assert manager.discover() == ()

    document.insert(3, "X")
    candidates = manager.discover()
    assert len(candidates) == 1
    assert candidates[0].session is not None
    assert candidates[0].session.operations == ()
    assert [event.kind for event in candidates[0].session.events] == [
        RecoveryEventKind.TRANSACTION
    ]

    document.undo()
    candidates = manager.discover()
    assert candidates[0].session is not None
    assert [event.kind for event in candidates[0].session.events] == [
        RecoveryEventKind.TRANSACTION,
        RecoveryEventKind.UNDO,
    ]
    document.redo()
    session = manager.discover()[0].session
    assert session is not None
    assert [event.kind for event in session.events] == [
        RecoveryEventKind.TRANSACTION,
        RecoveryEventKind.UNDO,
        RecoveryEventKind.REDO,
    ]

    manager.detach(document, clean=True)
    document.close()
    assert manager.discover() == ()


def test_recovery_journal_hash_uses_the_normalized_source_path(tmp_path: Path):
    source = tmp_path / "source.txt"
    alias = tmp_path / "source-alias.txt"
    source.write_text("same bytes", encoding="utf-8")
    try:
        alias.symlink_to(source)
    except OSError as error:
        pytest.skip(f"symbolic links are unavailable: {error}")
    manager = RecoveryManager(tmp_path / "recovery")
    original = Document.open(source)
    linked = Document.open(alias)
    try:
        original_prefix = manager._new_journal_path(original).name.split("-", 1)[0]
        linked_prefix = manager._new_journal_path(linked).name.split("-", 1)[0]

        assert original_prefix == linked_prefix
    finally:
        original.close()
        linked.close()
        manager.shutdown()


def test_recovery_manager_preserves_coalesced_typing_history(tmp_path: Path):
    source = tmp_path / "coalesced.txt"
    source.write_text("abc", encoding="utf-8")
    recovery_dir = tmp_path / "recovery"
    first = RecoveryManager(recovery_dir)
    document = Document.open(source)
    first.attach(document)
    document.insert(3, "X", coalesce="typing")
    document.insert(4, "Y", coalesce="typing")
    expected_history = document.export_history()
    first.detach(document, clean=False)
    document.close()
    first.shutdown()

    second = RecoveryManager(recovery_dir)
    recovered = second.recover(second.discover()[0])
    try:
        assert recovered.read(0, recovered.total_chars()) == "abcXY"
        assert recovered.export_history() == expected_history
    finally:
        second.detach(recovered, clean=True)
        recovered.close()
        second.shutdown()


def test_recovery_manager_save_retains_journal_until_session_publication(
    tmp_path: Path,
):
    source = tmp_path / "saved.txt"
    source.write_text("abc", encoding="utf-8")
    manager = RecoveryManager(tmp_path / "recovery")
    with Document.open(source) as document:
        manager.attach(document)
        document.insert(3, "X")
        assert len(manager.discover()) == 1
        document.save()
        candidate = manager.discover()[0]
        assert candidate.session is not None
        assert [event.kind for event in candidate.session.events] == [
            RecoveryEventKind.TRANSACTION,
            RecoveryEventKind.SAVE_POINT,
        ]
        document.insert(4, "Y")
        candidate = manager.discover()[0]
        assert candidate.session is not None
        assert [event.kind for event in candidate.session.events] == [
            RecoveryEventKind.TRANSACTION,
            RecoveryEventKind.SAVE_POINT,
            RecoveryEventKind.TRANSACTION,
        ]
        manager.detach(document, clean=True)


def test_recovery_manager_discovers_and_replays_simulated_crash(tmp_path: Path):
    source = tmp_path / "crash.txt"
    source.write_text("abcdef", encoding="utf-8")
    recovery_dir = tmp_path / "recovery"

    first = RecoveryManager(recovery_dir)
    document = Document.open(source)
    first.attach(document)
    document.replace(1, 3, "X")
    document.insert(document.total_chars(), "!")
    first.detach(document, clean=False)
    document.close()

    second = RecoveryManager(recovery_dir)
    candidates = second.discover()
    assert len(candidates) == 1
    recovered = second.recover(candidates[0])
    try:
        assert recovered.read(0, recovered.total_chars()) == "aXdef!"
        assert recovered.modified
        # Recovery is immediately durable again if UNITI crashes a second time.
        assert len(second.discover()) == 1
    finally:
        second.detach(recovered, clean=True)
        recovered.close()
    assert second.discover() == ()


def test_recovery_manager_rejects_changed_source(tmp_path: Path):
    source = tmp_path / "changed.txt"
    source.write_text("abc", encoding="utf-8")
    recovery_dir = tmp_path / "recovery"
    manager = RecoveryManager(recovery_dir)
    document = Document.open(source)
    manager.attach(document)
    document.insert(1, "X")
    manager.detach(document, clean=False)
    document.close()

    source.write_text("someone else", encoding="utf-8")
    candidate = RecoveryManager(recovery_dir).discover()[0]
    with pytest.raises(RecoverySourceMismatchError):
        RecoveryManager(recovery_dir).recover(candidate)


def test_recovery_uses_source_encoding_not_pending_output_encoding(tmp_path: Path):
    source = tmp_path / "legacy.txt"
    source.write_bytes(b"caf\xe9")
    recovery_dir = tmp_path / "recovery"

    first = RecoveryManager(recovery_dir)
    document = Document.open(source, encoding="windows-1252")
    first.attach(document)
    document.set_output_encoding("utf-8")
    document.insert(document.total_chars(), "!")
    first.detach(document, clean=False)
    document.close()

    second = RecoveryManager(recovery_dir)
    candidate = second.discover()[0]
    recovered = second.recover(candidate)
    try:
        assert recovered.encoding_info.detected == "windows-1252"
        assert recovered.output_encoding == "utf-8"
        assert recovered.read(0, recovered.total_chars()) == "café!"
    finally:
        second.detach(recovered, clean=True)
        recovered.close()


def test_recovery_persists_output_eol_changes_after_journal_start(tmp_path: Path):
    source = tmp_path / "eol.txt"
    source.write_bytes(b"a\nb\n")
    recovery_dir = tmp_path / "recovery"

    first = RecoveryManager(recovery_dir)
    document = Document.open(source)
    first.attach(document)
    document.insert(0, "X")  # starts the journal
    document.set_output_eol("CRLF")
    first.detach(document, clean=False)
    document.close()

    second = RecoveryManager(recovery_dir)
    recovered = second.recover(second.discover()[0])
    try:
        assert recovered.output_eol == "CRLF"
    finally:
        second.detach(recovered, clean=True)
        recovered.close()


def test_recovery_journal_io_does_not_block_edit_listener(tmp_path: Path, monkeypatch):
    import time

    source = tmp_path / "async.txt"
    source.write_text("abc", encoding="utf-8")
    original_append = FileRecoveryIO.append

    def slow_append(self, journal, record):
        time.sleep(0.15)
        return original_append(self, journal, record)

    monkeypatch.setattr(FileRecoveryIO, "append", slow_append)
    manager = RecoveryManager(tmp_path / "recovery")
    document = Document.open(source)
    try:
        manager.attach(document)
        started = time.perf_counter()
        document.insert(3, "X")
        elapsed = time.perf_counter() - started
        assert elapsed < 0.08
        manager.flush(document)
        assert len(manager.discover()) == 1
    finally:
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_failed_fsync_retains_last_durable_revision_and_warns(tmp_path: Path):
    backend = InjectedRecoveryIO()
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "source.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        document.insert(3, "X")
        manager.flush(document)
        durable = manager.diagnostic(document).durable_revision

        backend.fail_fsync = True
        document.insert(4, "Y")
        manager.flush(document)

        diagnostic = manager.diagnostic(document)
        assert diagnostic.health is RecoveryHealth.DEGRADED
        assert diagnostic.durability is DurabilityLevel.UNSAFE
        assert diagnostic.durable_revision == durable
        assert diagnostic.observed_revision == document.revision
        assert "fsync" in diagnostic.reason.lower()
    finally:
        backend.fail_fsync = False
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_successful_flush_clears_recovery_degradation(tmp_path: Path):
    backend = InjectedRecoveryIO()
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "healing.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        document.insert(3, "X")
        backend.fail_fsync = True
        manager.flush(document)
        assert manager.diagnostic(document).health is RecoveryHealth.DEGRADED

        backend.fail_fsync = False
        manager.flush(document)

        diagnostic = manager.diagnostic(document)
        assert diagnostic.health is RecoveryHealth.OK
        assert diagnostic.durability is DurabilityLevel.FULL
        assert diagnostic.durable_revision == document.revision
        assert diagnostic.reason == ""
    finally:
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_directory_sync_unavailability_is_reduced_and_later_full_sync_heals(
    tmp_path: Path,
):
    backend = InjectedRecoveryIO()
    backend.directory_level = DurabilityLevel.FILE_SYNCED
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "reduced.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        document.insert(3, "X")
        manager.flush(document)

        reduced = manager.diagnostic(document)
        assert reduced.health is RecoveryHealth.REDUCED
        assert reduced.durability is DurabilityLevel.FILE_SYNCED
        assert reduced.durable_revision == document.revision
        assert any(call[0] == "sync_directory" for call in backend.calls)

        backend.directory_level = DurabilityLevel.FULL
        manager.flush(document)

        healed = manager.diagnostic(document)
        assert healed.health is RecoveryHealth.OK
        assert healed.durability is DurabilityLevel.FULL
        assert healed.durable_revision == healed.observed_revision
    finally:
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_successful_retry_after_flush_failure_covers_appended_revision(
    tmp_path: Path,
):
    backend = InjectedRecoveryIO()
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "flush-retry.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        backend.fail_flush = True
        document.insert(3, "X")
        manager.flush(document)
        assert manager.diagnostic(document).health is RecoveryHealth.DEGRADED

        backend.fail_flush = False
        manager.flush(document)

        diagnostic = manager.diagnostic(document)
        assert diagnostic.health is RecoveryHealth.OK
        assert diagnostic.durable_revision == document.revision
    finally:
        backend.fail_flush = False
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_recovery_diagnostics_are_observable_until_listener_removal(
    tmp_path: Path,
):
    backend = InjectedRecoveryIO()
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "observable.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    observed = []
    remove_listener = manager.add_diagnostic_listener(observed.append)
    try:
        manager.attach(document)
        backend.fail_fsync = True
        document.insert(3, "X")
        manager.flush(document)
        assert any(item.health is RecoveryHealth.DEGRADED for item in observed)

        backend.fail_fsync = False
        manager.flush(document)
        assert observed[-1] == manager.diagnostic(document)
        assert observed[-1].health is RecoveryHealth.OK

        count = len(observed)
        remove_listener()
        document.insert(4, "Y")
        manager.flush(document)
        assert len(observed) == count
    finally:
        backend.fail_fsync = False
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_discovery_preserves_and_reports_invalid_evidence(tmp_path: Path):
    recovery_dir = tmp_path / "recovery"
    recovery_dir.mkdir()
    corrupt = recovery_dir / "corrupt.uniti-recovery"
    corrupt.write_bytes(b"not JSON\n")

    manager = RecoveryManager(recovery_dir)
    try:
        candidates = manager.discover()

        assert len(candidates) == 1
        assert candidates[0].evidence_path == corrupt
        assert candidates[0].load_status is RecoveryLoadStatus.CORRUPT
        assert candidates[0].session is None
        assert candidates[0].supported_actions == ("skip", "discard")
        assert corrupt.exists()
    finally:
        manager.shutdown()


def test_compaction_publishes_valid_candidate_before_retiring_old(
    tmp_path: Path,
):
    backend = InjectedRecoveryIO(forced_size=64 << 20)
    resources = ResourceManager(
        max_workers=2,
        initial_snapshot=MemorySnapshot(16 << 30, 8 << 30),
    )
    seen_kinds: list[TaskKind] = []
    resources.tasks.add_listener(
        lambda: seen_kinds.extend(
            task.spec.kind for task in resources.tasks.snapshot().tasks
        )
    )
    recovery_dir = tmp_path / "recovery"
    manager = RecoveryManager(
        recovery_dir,
        backend=backend,
        resource_manager=resources,
    )
    source = tmp_path / "compact.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        document.insert(3, "X")
        document.undo()
        document.redo()
        manager.flush(document)
        original = manager.journal_path(document)
        assert original is not None

        completed: Future[None] = Future()
        completed.set_result(None)
        binding = manager._bindings[id(document)]
        binding.compaction_pending = True
        binding.compaction_future = completed

        manager.compact(document).result(timeout=5)
        manager.flush(document)
        replacement = manager.journal_path(document)

        assert TaskKind.RECOVERY_COMPACTION in seen_kinds
        assert replacement is not None and replacement != original
        assert replacement.exists()
        assert not original.exists()
        replace_index = next(
            index for index, call in enumerate(backend.calls) if call[0] == "replace"
        )
        unlink_index = next(
            index
            for index, call in enumerate(backend.calls)
            if call[0] == "unlink" and call[1] == original
        )
        assert replace_index < unlink_index

        candidate = next(
            item for item in manager.discover() if item.evidence_path == replacement
        )
        assert candidate.session is not None
        assert [event.kind for event in candidate.session.events] == [
            RecoveryEventKind.TRANSACTION,
            RecoveryEventKind.UNDO,
            RecoveryEventKind.REDO,
        ]
        expected_history = document.export_history()
        with Document.open(source) as restored:
            replay_recovery(restored, candidate.session)
            assert restored.read(0, restored.total_chars()) == "abcX"
            assert restored.export_history() == expected_history
    finally:
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()
        resources.shutdown()


def test_saved_base_replacement_is_durable_before_old_candidate_is_retired(
    tmp_path: Path,
):
    backend = InjectedRecoveryIO()
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "saved-base.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        document.insert(3, "X")
        manager.flush(document)
        original = manager.journal_path(document)
        assert original is not None

        document.save()
        saved_history = document.export_history()
        saved_revision = document.revision
        saved_stamp = SavedFileStamp(
            FileIdentity.from_path(source),
            sha256_file(source),
        )
        document.insert(document.total_chars(), "Y")
        manager.rebase_after_save(
            document,
            saved_stamp=saved_stamp,
            base_history=saved_history,
            save_revision=saved_revision,
        ).result(timeout=5)
        manager.flush(document)

        replacement = manager.journal_path(document)
        assert replacement is not None and replacement != original
        assert replacement.exists()
        assert original.exists() is False
        replace_index = next(
            index for index, call in enumerate(backend.calls) if call[0] == "replace"
        )
        unlink_index = next(
            index
            for index, call in enumerate(backend.calls)
            if call[0] == "unlink" and call[1] == original
        )
        assert replace_index < unlink_index

        candidate = manager.discover()[0]
        assert candidate.session is not None
        with Document.open(source) as restored:
            replay_recovery(restored, candidate.session)
            assert restored.read(0, restored.total_chars()) == "abcXY"
            assert restored.can_undo is True
    finally:
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_failed_saved_base_publication_preserves_previous_recovery_candidate(
    tmp_path: Path,
):
    backend = InjectedRecoveryIO()
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "saved-base-failure.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        document.insert(3, "X")
        manager.flush(document)
        original = manager.journal_path(document)
        assert original is not None
        document.save()
        saved_history = document.export_history()
        saved_revision = document.revision
        saved_stamp = SavedFileStamp(
            FileIdentity.from_path(source),
            sha256_file(source),
        )
        document.insert(document.total_chars(), "Y")
        backend.fail_replace = True

        result = manager.rebase_after_save(
            document,
            saved_stamp=saved_stamp,
            base_history=saved_history,
            save_revision=saved_revision,
        ).result(timeout=5)

        assert result is None
        assert original.exists()
        assert manager.journal_path(document) == original
        assert manager.diagnostic(document).health is RecoveryHealth.DEGRADED
    finally:
        backend.fail_replace = False
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_failed_append_can_be_healed_by_checkpoint_compaction(tmp_path: Path):
    backend = InjectedRecoveryIO()
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "append-failure.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        manager.flush(document)
        backend.fail_append = True
        document.insert(3, "X")
        manager.flush(document)

        diagnostic = manager.diagnostic(document)
        assert diagnostic.health is RecoveryHealth.DEGRADED
        assert diagnostic.durable_revision == 0
        assert diagnostic.observed_revision == 1

        backend.fail_append = False
        manager.compact(document).result(timeout=5)
        manager.flush(document)

        diagnostic = manager.diagnostic(document)
        assert diagnostic.health is RecoveryHealth.OK
        assert diagnostic.durable_revision == 1
        candidate = manager.discover()[0]
        assert candidate.session is not None
        assert [event.kind for event in candidate.session.events] == [
            RecoveryEventKind.TRANSACTION
        ]
    finally:
        backend.fail_append = False
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_failed_compaction_publish_retains_original_candidate(tmp_path: Path):
    backend = InjectedRecoveryIO()
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "publish-failure.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        document.insert(3, "X")
        manager.flush(document)
        original = manager.journal_path(document)
        assert original is not None
        backend.fail_replace = True

        manager.compact(document).result(timeout=5)

        assert original.exists()
        assert manager.journal_path(document) == original
        diagnostic = manager.diagnostic(document)
        assert diagnostic.health is RecoveryHealth.DEGRADED
        assert "compaction" in diagnostic.reason
    finally:
        backend.fail_replace = False
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_low_space_reading_requests_compaction_without_disk_mutation(
    tmp_path: Path,
):
    backend = InjectedRecoveryIO(free_bytes=(512 << 20) - 1)
    manager = RecoveryManager(tmp_path / "recovery", backend=backend)
    source = tmp_path / "low-space.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    before = set(tmp_path.iterdir())
    try:
        manager.attach(document)
        document.insert(3, "X")
        manager.flush(document)

        assert any(call[0] == "replace" for call in backend.calls)
        assert not any(path.name.upper() == "LOWDISK" for path in tmp_path.rglob("*"))
        assert before <= set(tmp_path.iterdir())
    finally:
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()


def test_prepare_recovery_keeps_original_until_explicit_commit(tmp_path: Path):
    source = tmp_path / "two-phase.txt"
    source.write_text("abc", encoding="utf-8")
    recovery_dir = tmp_path / "recovery"
    first = RecoveryManager(recovery_dir)
    document = Document.open(source)
    first.attach(document)
    document.insert(3, "X")
    first.detach(document, clean=False)
    document.close()
    first.shutdown()

    second = RecoveryManager(recovery_dir)
    candidate = second.discover()[0]
    recovered = second.prepare_recovery(candidate)
    try:
        assert recovered.document.read(0, recovered.document.total_chars()) == "abcX"
        assert recovered.original.evidence_path.exists()
        assert recovered.fresh_journal.exists()

        second.commit_recovery(recovered)

        assert not recovered.original.evidence_path.exists()
        assert recovered.fresh_journal.exists()
    finally:
        second.detach(recovered.document, clean=True)
        recovered.document.close()
        second.shutdown()


def test_recovery_files_and_directory_are_user_only(tmp_path: Path):
    recovery_dir = tmp_path / "private-recovery"
    manager = RecoveryManager(recovery_dir)
    source = tmp_path / "private.txt"
    source.write_text("abc", encoding="utf-8")
    document = Document.open(source)
    try:
        manager.attach(document)
        document.insert(3, "X")
        manager.flush(document)
        path = manager.journal_path(document)
        assert path is not None
        if os.name != "nt":
            assert recovery_dir.stat().st_mode & 0o077 == 0
            assert path.stat().st_mode & 0o077 == 0
    finally:
        manager.detach(document, clean=True)
        document.close()
        manager.shutdown()
