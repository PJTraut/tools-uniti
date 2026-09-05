"""Observable crash-recovery lifecycle around semantic journals."""

from __future__ import annotations

import hashlib
import shutil
import threading
import time
import uuid
from collections.abc import Callable, Mapping
from concurrent.futures import Future
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Protocol

from uniti.core.byte_source import ByteSource
from uniti.core.document import Document
from uniti.core.durability import (
    DurabilityAdapter,
    DurabilityError,
    DurabilityLevel,
    DurabilityResult,
    NativeDurabilityAdapter,
    combine_durability,
)
from uniti.core.file_identity import (
    FileIdentity,
    FileMatch,
    SavedFileStamp,
    verify_saved_file,
)
from uniti.core.history import (
    EditOperation,
    EditTransaction,
    HistoryEvent,
    HistorySnapshot,
)
from uniti.core.recovery import (
    RecoveryCheckpoint,
    RecoveryEvent,
    RecoveryEventKind,
    RecoveryJournal,
    RecoveryLoadResult,
    RecoveryLoadStatus,
    RecoverySession,
    load_recovery_candidate,
    replay_recovery,
)
from uniti.resources import ResourceManager
from uniti.resources.tasks import TaskKind, TaskSpec

from .platform_policy import normalize_native_path


RECOVERY_COMPACT_BYTES = 64 << 20
RECOVERY_FREE_SPACE_RESERVE = 512 << 20
_HISTORY_COALESCE_KEY = "history_coalesce"


class RecoveryHealth(StrEnum):
    OK = "ok"
    REDUCED = "reduced"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class RecoveryDiagnostic:
    document_id: str
    health: RecoveryHealth
    durability: DurabilityLevel
    durable_revision: int
    observed_revision: int
    reason: str


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    journal_path: Path
    session: RecoverySession | None
    load_status: RecoveryLoadStatus = RecoveryLoadStatus.COMPLETE
    source_match: FileMatch | None = None
    supported_actions: tuple[str, ...] = ()
    safe_error: str | None = None

    @property
    def evidence_path(self) -> Path:
        return self.journal_path


@dataclass(frozen=True, slots=True)
class RecoveredDocument:
    document: Document
    original: RecoveryCandidate
    fresh_journal: Path


class RecoveryIO(Protocol):
    def append(
        self,
        journal: RecoveryJournal,
        record: RecoveryEvent | RecoveryCheckpoint,
    ) -> None: ...

    def flush(self, journal: RecoveryJournal) -> None: ...

    def fsync(self, journal: RecoveryJournal) -> DurabilityResult: ...

    def size(self, path: Path) -> int: ...

    def replace(self, source: Path, destination: Path) -> DurabilityResult: ...

    def sync_directory(self, path: Path) -> DurabilityResult: ...

    def unlink(self, path: Path) -> None: ...

    def free_bytes(self, path: Path) -> int: ...


class FileRecoveryIO:
    """Filesystem recovery backend used outside deterministic failure tests."""

    def __init__(self, *, adapter: DurabilityAdapter | None = None) -> None:
        self._adapter = adapter if adapter is not None else NativeDurabilityAdapter()

    def append(
        self,
        journal: RecoveryJournal,
        record: RecoveryEvent | RecoveryCheckpoint,
    ) -> None:
        if isinstance(record, RecoveryCheckpoint):
            journal.append_checkpoint(record, durable=False)
        elif isinstance(record, RecoveryEvent):
            journal.append_event(record, durable=False)
        else:
            raise TypeError("recovery record is invalid")

    def flush(self, journal: RecoveryJournal) -> None:
        journal.flush(durable=False)

    def fsync(self, journal: RecoveryJournal) -> DurabilityResult:
        try:
            journal.flush(durable=True)
        except OSError as error:
            result = DurabilityResult(
                "recovery_fsync",
                DurabilityLevel.UNSAFE,
                False,
                False,
                False,
                f"file_sync:{type(error).__name__}",
            )
            raise DurabilityError(result, error) from error
        return DurabilityResult(
            "recovery_fsync",
            DurabilityLevel.FULL,
            True,
            True,
            True,
        )

    def size(self, path: Path) -> int:
        return path.stat().st_size

    def replace(self, source: Path, destination: Path) -> DurabilityResult:
        try:
            self._adapter.replace(source, destination)
        except OSError as error:
            result = DurabilityResult(
                "recovery_replace",
                DurabilityLevel.UNSAFE,
                True,
                False,
                False,
                f"replace:{type(error).__name__}",
            )
            raise DurabilityError(result, error) from error
        directory = self.sync_directory(destination.parent)
        return DurabilityResult(
            "recovery_replace",
            directory.level,
            True,
            True,
            directory.directory_synced,
            directory.reason,
        )

    def sync_directory(self, path: Path) -> DurabilityResult:
        try:
            synced = self._adapter.sync_directory(path) is True
            reason = None if synced else "directory_sync_unavailable"
        except OSError as error:
            synced = False
            reason = f"directory_sync:{type(error).__name__}"
        return DurabilityResult(
            "recovery_directory_sync",
            DurabilityLevel.FULL if synced else DurabilityLevel.FILE_SYNCED,
            True,
            True,
            synced,
            reason,
        )

    def unlink(self, path: Path) -> None:
        path.unlink()

    def free_bytes(self, path: Path) -> int:
        return shutil.disk_usage(path).free


@dataclass(frozen=True, slots=True)
class _CompactionRequest:
    base_history: HistorySnapshot
    events: tuple[RecoveryEvent, ...]
    observed_revision: int


@dataclass(frozen=True, slots=True)
class _SavedBaseRequest:
    saved_stamp: SavedFileStamp
    base_history: HistorySnapshot
    save_sequence: int
    save_revision: int
    events: tuple[RecoveryEvent, ...]
    observed_sequence: int
    source_encoding: str
    output_encoding: str
    output_eol: str | None


@dataclass(slots=True)
class _Binding:
    document: Document
    document_id: str
    base_identity: FileIdentity
    base_history: HistorySnapshot
    source_encoding: str
    output_encoding: str
    output_eol: str | None
    remove_history_listener: object = None
    base_source: ByteSource | None = None
    base_hash: str | None = None
    journal: RecoveryJournal | None = None
    journal_path: Path | None = None
    last_future: Future | None = None
    last_fsync: float = 0.0
    sequence: int = 0
    written_sequence: int = 0
    durable_sequence: int = 0
    written_revision: int = 0
    durable_revision: int = 0
    observed_revision: int = 0
    events: list[RecoveryEvent] = field(default_factory=list)
    health: RecoveryHealth = RecoveryHealth.OK
    durability: DurabilityLevel = DurabilityLevel.FULL
    reason: str = ""
    directory_sync_pending: bool = False
    compaction_pending: bool = False
    compaction_future: Future | None = None


class RecoveryManager:
    """Own recovery evidence while keeping all journal I/O off edit paths."""

    def __init__(
        self,
        directory: str | Path,
        *,
        fsync_interval: float = 0.25,
        backend: RecoveryIO | None = None,
        resource_manager: ResourceManager | None = None,
    ) -> None:
        if fsync_interval <= 0:
            raise ValueError("fsync_interval must be positive")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            self.directory.chmod(0o700)
        except OSError:
            pass
        self._root = self.directory.resolve()
        self._backend = backend or FileRecoveryIO()
        self._owns_resources = resource_manager is None
        self._resources = resource_manager or ResourceManager(max_workers=1)
        self._bindings: dict[int, _Binding] = {}
        self._diagnostic_listeners: list[
            Callable[[RecoveryDiagnostic], None]
        ] = []
        self.last_error: Exception | None = None
        self._fsync_interval = float(fsync_interval)
        self._lock = threading.RLock()
        self._shutdown = False

    def _new_journal_path(self, document: Document) -> Path:
        source_path = normalize_native_path(document.path).path
        digest = hashlib.sha256(
            str(source_path).encode("utf-8")
        ).hexdigest()[:12]
        suffix = uuid.uuid4().hex[:10]
        return self.directory / f"{digest}-{suffix}.uniti-recovery"

    def _owned_path(self, path: Path, *, temporary: bool = False) -> Path:
        candidate = Path(path)
        allowed_suffix = (
            candidate.name.endswith(".uniti-recovery.tmp")
            if temporary
            else candidate.name.endswith(".uniti-recovery")
        )
        if not allowed_suffix or candidate.parent.resolve() != self._root:
            raise ValueError("recovery path is outside the owned recovery root")
        if candidate.is_symlink():
            raise ValueError("recovery path must not be a symlink")
        return candidate

    def _degrade(self, binding: _Binding, stage: str, error: Exception) -> None:
        with self._lock:
            binding.health = RecoveryHealth.DEGRADED
            binding.durability = DurabilityLevel.UNSAFE
            binding.reason = f"{stage} failed ({type(error).__name__})"
            self.last_error = error
        self._notify_diagnostic(binding)

    @staticmethod
    def _require_safe(result: DurabilityResult) -> DurabilityResult:
        if not isinstance(result, DurabilityResult):
            raise TypeError("recovery backend returned an invalid durability result")
        if result.level is DurabilityLevel.UNSAFE:
            raise DurabilityError(result, OSError(result.reason or "unsafe durability"))
        return result

    def _record_durability(
        self,
        binding: _Binding,
        result: DurabilityResult,
        *,
        advance_revision: bool,
    ) -> None:
        safe = self._require_safe(result)
        with self._lock:
            if advance_revision:
                binding.durable_sequence = binding.written_sequence
                binding.durable_revision = binding.written_revision
            binding.durability = safe.level
            if safe.level is DurabilityLevel.FILE_SYNCED:
                binding.health = RecoveryHealth.REDUCED
                binding.reason = safe.reason or "directory sync unavailable"
            elif binding.durable_sequence >= binding.sequence:
                binding.health = RecoveryHealth.OK
                binding.reason = ""
        self._notify_diagnostic(binding)

    def _mark_durable(
        self,
        binding: _Binding,
        result: DurabilityResult,
    ) -> None:
        self._record_durability(binding, result, advance_revision=True)

    def _run_guarded(self, binding: _Binding, stage: str, fn):
        try:
            return fn()
        except Exception as exc:
            self._degrade(binding, stage, exc)
            return None

    def _submit_serial(
        self,
        binding: _Binding,
        kind: TaskKind,
        stage: str,
        fn,
    ) -> Future:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("recovery manager is shut down")
            previous = binding.last_future
            spec = TaskSpec.create(
                kind,
                foreground=False,
                document_key=binding.document_id,
                revision=binding.observed_revision,
            )

            def work(_context):
                if previous is not None:
                    try:
                        previous.result()
                    except Exception:
                        pass
                return self._run_guarded(binding, stage, fn)

            try:
                handle = self._resources.tasks.submit(spec, work)
            except Exception as exc:
                self._degrade(binding, stage, exc)
                failed: Future = Future()
                failed.set_result(None)
                binding.last_future = failed
                return failed
            binding.last_future = handle.future
            return handle.future

    @staticmethod
    def _hash_source(source: ByteSource) -> str:
        digest = hashlib.sha256()
        try:
            for chunk in source.iter_chunks(chunk_size=1 << 20):
                digest.update(chunk)
            return digest.hexdigest()
        finally:
            source.close()

    def _prepare_base_hash(self, binding: _Binding) -> None:
        source = binding.base_source
        if source is None:
            if binding.base_hash is None:
                raise ValueError("recovery base source is unavailable")
            return
        binding.base_hash = self._hash_source(source)
        binding.base_source = None

    def _start_journal(self, binding: _Binding) -> None:
        if binding.journal is not None:
            return
        if binding.base_hash is None:
            raise ValueError("recovery base hash is unavailable")
        path = self._owned_path(self._new_journal_path(binding.document))
        journal = RecoveryJournal.create_v3(
            path,
            binding.document.path,
            base_identity=binding.base_identity,
            base_hash=binding.base_hash,
            source_encoding=binding.source_encoding,
            output_encoding=binding.output_encoding,
            output_eol=binding.output_eol,
            base_history=binding.base_history,
        )
        binding.journal = journal
        binding.journal_path = path
        binding.last_fsync = time.monotonic()
        binding.directory_sync_pending = True
        directory = self._require_safe(
            self._backend.sync_directory(self.directory)
        )
        binding.directory_sync_pending = (
            directory.level is not DurabilityLevel.FULL
        )
        self._record_durability(
            binding,
            directory,
            advance_revision=False,
        )

    def _sync_binding(self, binding: _Binding) -> None:
        journal = binding.journal
        if journal is None:
            return
        results = [self._require_safe(self._backend.fsync(journal))]
        if binding.directory_sync_pending:
            directory = self._require_safe(
                self._backend.sync_directory(self.directory)
            )
            results.append(directory)
            binding.directory_sync_pending = (
                directory.level is not DurabilityLevel.FULL
            )
        durability = combine_durability("recovery_publication", results)
        binding.last_fsync = time.monotonic()
        self._mark_durable(binding, durability)

    def _maybe_fsync(self, binding: _Binding) -> None:
        journal = binding.journal
        if journal is None:
            return
        now = time.monotonic()
        if now - binding.last_fsync < self._fsync_interval:
            return
        self._sync_binding(binding)

    def _write_event(
        self,
        binding: _Binding,
        event: RecoveryEvent,
        *,
        allow_compaction: bool = True,
    ) -> None:
        self._start_journal(binding)
        assert binding.journal is not None
        if event.sequence != binding.written_sequence + 1:
            raise OSError("recovery journal has an unwritten semantic gap")
        self._backend.append(binding.journal, event)
        binding.written_sequence = event.sequence
        binding.written_revision = event.revision
        self._backend.flush(binding.journal)
        self._maybe_fsync(binding)
        if allow_compaction and self._needs_compaction(binding):
            self._schedule_compaction(binding)

    def _seed_journal(self, binding: _Binding) -> None:
        self._start_journal(binding)
        assert binding.journal is not None
        if binding.events:
            self._backend.append(
                binding.journal,
                RecoveryCheckpoint(binding.base_history, tuple(binding.events)),
            )
            last = binding.events[-1]
            binding.written_sequence = last.sequence
            binding.written_revision = last.revision
        self._backend.flush(binding.journal)
        self._sync_binding(binding)

    def _flush_binding(self, binding: _Binding) -> None:
        journal = binding.journal
        if journal is None:
            return
        self._backend.flush(journal)
        self._sync_binding(binding)

    def _needs_compaction(self, binding: _Binding) -> bool:
        path = binding.journal_path
        if path is None:
            return False
        return (
            self._backend.size(path) >= RECOVERY_COMPACT_BYTES
            or self._backend.free_bytes(self.directory)
            < RECOVERY_FREE_SPACE_RESERVE
        )

    @staticmethod
    def _recovery_event(sequence: int, event: HistoryEvent) -> RecoveryEvent:
        kind = RecoveryEventKind(event.kind.value)
        metadata = dict(event.metadata)
        if kind is RecoveryEventKind.TRANSACTION and event.coalesce is not None:
            metadata[_HISTORY_COALESCE_KEY] = event.coalesce
        return RecoveryEvent(
            sequence=sequence,
            kind=kind,
            transaction=(
                event.transaction
                if kind is RecoveryEventKind.TRANSACTION
                else None
            ),
            cursor=event.cursor,
            saved_cursor=event.saved_cursor,
            revision=event.revision,
            metadata=metadata,
        )

    def _observe_history(self, binding: _Binding, event: HistoryEvent) -> None:
        with self._lock:
            binding.sequence += 1
            recovery_event = self._recovery_event(binding.sequence, event)
            binding.events.append(recovery_event)
            binding.observed_revision = event.revision
        self._notify_diagnostic(binding)
        try:
            self._submit_serial(
                binding,
                TaskKind.RECOVERY,
                "append",
                lambda: self._write_event(binding, recovery_event),
            )
        except Exception as exc:
            self._degrade(binding, "append", exc)

    def attach(
        self,
        document: Document,
        *,
        seed_operations: tuple[EditOperation, ...] = (),
        seed_events: tuple[RecoveryEvent, ...] = (),
        base_identity: FileIdentity | None = None,
        base_hash: str | None = None,
        base_history: HistorySnapshot | None = None,
        force_journal: bool = False,
    ) -> None:
        key = id(document)
        if key in self._bindings:
            return
        if seed_operations and seed_events:
            raise ValueError("recovery seed must use one event representation")
        if seed_operations:
            seed_events = tuple(
                RecoveryEvent.transaction(
                    index,
                    EditTransaction((operation,)),
                    cursor=index,
                    saved_cursor=0,
                    revision=index,
                )
                for index, operation in enumerate(seed_operations, start=1)
            )
        if seed_events:
            for previous, current in zip(seed_events, seed_events[1:]):
                if current.sequence != previous.sequence + 1:
                    raise ValueError("recovery seed event sequence is not contiguous")

        captured_history = base_history or document.export_history()
        binding = _Binding(
            document=document,
            document_id=str(key),
            base_identity=base_identity or document.disk_identity,
            base_history=captured_history,
            source_encoding=document.encoding_info.detected,
            output_encoding=document.output_encoding,
            output_eol=document.output_eol,
            base_source=None if base_hash is not None else document.source.fork(),
            base_hash=base_hash,
            sequence=seed_events[-1].sequence if seed_events else 0,
            written_revision=0,
            durable_revision=0,
            observed_revision=(
                seed_events[-1].revision if seed_events else document.revision
            ),
            events=list(seed_events),
        )
        binding.remove_history_listener = document.add_history_listener(
            lambda event, binding=binding: self._observe_history(binding, event)
        )
        self._bindings[key] = binding
        self._notify_diagnostic(binding)
        if binding.base_hash is None:
            self._submit_serial(
                binding,
                TaskKind.HASH,
                "hash",
                lambda: self._prepare_base_hash(binding),
            )
        if seed_events or force_journal:
            self._submit_serial(
                binding,
                TaskKind.RECOVERY,
                "seed",
                lambda: self._seed_journal(binding),
            )

    def _wait_for_binding(self, binding: _Binding) -> None:
        while True:
            with self._lock:
                future = binding.last_future
            if future is None:
                return
            future.result()
            with self._lock:
                if future is binding.last_future:
                    return

    def flush(self, document: Document | None = None) -> None:
        bindings = (
            [self._bindings.get(id(document))]
            if document is not None
            else list(self._bindings.values())
        )
        for binding in bindings:
            if binding is None:
                continue
            self._submit_serial(
                binding,
                TaskKind.RECOVERY,
                "fsync",
                lambda binding=binding: self._flush_binding(binding),
            )
            self._wait_for_binding(binding)

    @staticmethod
    def _diagnostic_snapshot(binding: _Binding) -> RecoveryDiagnostic:
        return RecoveryDiagnostic(
            binding.document_id,
            binding.health,
            binding.durability,
            binding.durable_revision,
            binding.observed_revision,
            binding.reason,
        )

    def _notify_diagnostic(self, binding: _Binding) -> None:
        with self._lock:
            diagnostic = self._diagnostic_snapshot(binding)
            listeners = tuple(self._diagnostic_listeners)
        for listener in listeners:
            try:
                listener(diagnostic)
            except Exception:
                # Observers must never compromise recovery durability.
                continue

    def add_diagnostic_listener(
        self,
        listener: Callable[[RecoveryDiagnostic], None],
    ) -> Callable[[], None]:
        if not callable(listener):
            raise TypeError("diagnostic listener must be callable")
        with self._lock:
            self._diagnostic_listeners.append(listener)

        def remove() -> None:
            with self._lock:
                try:
                    self._diagnostic_listeners.remove(listener)
                except ValueError:
                    pass

        return remove

    def diagnostic(self, document: Document) -> RecoveryDiagnostic:
        binding = self._bindings.get(id(document))
        if binding is None:
            raise ValueError("document is not attached to recovery")
        with self._lock:
            return self._diagnostic_snapshot(binding)

    def diagnostics(self) -> tuple[RecoveryDiagnostic, ...]:
        return tuple(
            self.diagnostic(binding.document)
            for binding in tuple(self._bindings.values())
        )

    def journal_path(self, document: Document) -> Path | None:
        binding = self._bindings.get(id(document))
        return None if binding is None else binding.journal_path

    def _compaction_request(self, binding: _Binding) -> _CompactionRequest:
        with self._lock:
            return _CompactionRequest(
                binding.base_history,
                tuple(binding.events),
                binding.observed_revision,
            )

    def _compact_binding(
        self,
        binding: _Binding,
        request: _CompactionRequest,
    ) -> None:
        old_journal = binding.journal
        old_path = binding.journal_path
        if old_journal is None or old_path is None or binding.base_hash is None:
            return
        self._flush_binding(binding)

        published = self._owned_path(self._new_journal_path(binding.document))
        temporary = self._owned_path(
            published.with_name(published.name + ".tmp"),
            temporary=True,
        )
        new_journal: RecoveryJournal | None = None
        try:
            new_journal = RecoveryJournal.create_v3(
                temporary,
                binding.document.path,
                base_identity=binding.base_identity,
                base_hash=binding.base_hash,
                source_encoding=binding.source_encoding,
                output_encoding=binding.output_encoding,
                output_eol=binding.output_eol,
                base_history=request.base_history,
            )
            self._backend.append(
                new_journal,
                RecoveryCheckpoint(request.base_history, request.events),
            )
            self._backend.flush(new_journal)
            fsync_result = self._require_safe(self._backend.fsync(new_journal))
            loaded = load_recovery_candidate(temporary)
            if (
                loaded.status is not RecoveryLoadStatus.COMPLETE
                or loaded.session is None
                or loaded.durable_events != request.events
            ):
                raise ValueError("compacted recovery candidate did not validate")
            replace_result = self._require_safe(
                self._backend.replace(temporary, published)
            )
            directory_result = self._require_safe(
                self._backend.sync_directory(self.directory)
            )
            durability = combine_durability(
                "recovery_compaction",
                (fsync_result, replace_result, directory_result),
            )
            new_journal.path = published
            binding.journal = new_journal
            binding.journal_path = published
            binding.directory_sync_pending = (
                durability.level is not DurabilityLevel.FULL
            )
            if request.events:
                last = request.events[-1]
                binding.written_sequence = last.sequence
                binding.written_revision = last.revision
            binding.last_fsync = time.monotonic()
            self._mark_durable(binding, durability)
            new_journal = None
        finally:
            if new_journal is not None:
                new_journal.close()
                try:
                    self._backend.unlink(temporary)
                except (FileNotFoundError, OSError):
                    pass

        old_journal.close()
        try:
            self._backend.unlink(self._owned_path(old_path))
        except FileNotFoundError:
            pass
        except OSError as exc:
            self.last_error = exc

    def _compaction_finished(self, binding: _Binding, future: Future) -> None:
        with self._lock:
            if binding.compaction_future is future:
                binding.compaction_pending = False

    def _schedule_compaction(self, binding: _Binding) -> Future:
        with self._lock:
            if binding.compaction_pending and binding.compaction_future is not None:
                return binding.compaction_future
            binding.compaction_pending = True
            request = self._compaction_request(binding)
            future = self._submit_serial(
                binding,
                TaskKind.RECOVERY_COMPACTION,
                "compaction",
                lambda: self._compact_binding(binding, request),
            )
            binding.compaction_future = future
            future.add_done_callback(
                lambda completed: self._compaction_finished(binding, completed)
            )
            return future

    def compact(self, document: Document) -> Future:
        binding = self._bindings.get(id(document))
        if binding is None:
            raise ValueError("document is not attached to recovery")
        return self._schedule_compaction(binding)

    def _replace_saved_base(
        self,
        binding: _Binding,
        request: _SavedBaseRequest,
    ) -> bool:
        if verify_saved_file(
            binding.document.path,
            request.saved_stamp,
        ) not in {FileMatch.EXACT_FAST, FileMatch.EXACT_HASH}:
            raise OSError("saved recovery base changed before publication")
        old_journal = binding.journal
        old_path = binding.journal_path
        if old_journal is not None:
            self._flush_binding(binding)

        published: Path | None = None
        temporary: Path | None = None
        new_journal: RecoveryJournal | None = None
        publication_durability = DurabilityResult(
            "recovery_saved_base",
            DurabilityLevel.FULL,
            True,
            True,
            True,
        )
        try:
            if request.events:
                published = self._owned_path(
                    self._new_journal_path(binding.document)
                )
                temporary = self._owned_path(
                    published.with_name(published.name + ".tmp"),
                    temporary=True,
                )
                new_journal = RecoveryJournal.create_v3(
                    temporary,
                    binding.document.path,
                    base_identity=request.saved_stamp.identity,
                    base_hash=request.saved_stamp.sha256,
                    source_encoding=request.source_encoding,
                    output_encoding=request.output_encoding,
                    output_eol=request.output_eol,
                    base_history=request.base_history,
                )
                self._backend.append(
                    new_journal,
                    RecoveryCheckpoint(request.base_history, request.events),
                )
                self._backend.flush(new_journal)
                fsync_result = self._require_safe(
                    self._backend.fsync(new_journal)
                )
                loaded = load_recovery_candidate(temporary)
                if (
                    loaded.status is not RecoveryLoadStatus.COMPLETE
                    or loaded.session is None
                    or loaded.session.base_hash != request.saved_stamp.sha256
                    or loaded.durable_events != request.events
                ):
                    raise ValueError("saved recovery base did not validate")
                replace_result = self._require_safe(
                    self._backend.replace(temporary, published)
                )
                directory_result = self._require_safe(
                    self._backend.sync_directory(self.directory)
                )
                publication_durability = combine_durability(
                    "recovery_saved_base",
                    (fsync_result, replace_result, directory_result),
                )
                new_journal.path = published

            with self._lock:
                tail = tuple(
                    event
                    for event in binding.events
                    if event.sequence > request.observed_sequence
                )
                binding.base_identity = request.saved_stamp.identity
                binding.base_hash = request.saved_stamp.sha256
                binding.base_history = request.base_history
                binding.source_encoding = request.source_encoding
                binding.output_encoding = request.output_encoding
                binding.output_eol = request.output_eol
                binding.events = list(request.events + tail)
                binding.journal = new_journal
                binding.journal_path = published
                binding.directory_sync_pending = (
                    publication_durability.level is not DurabilityLevel.FULL
                )
                durable = (
                    request.events[-1].sequence
                    if request.events
                    else request.save_sequence
                )
                durable_revision = (
                    request.events[-1].revision
                    if request.events
                    else request.save_revision
                )
                binding.written_sequence = durable
                binding.written_revision = durable_revision
                binding.last_fsync = time.monotonic()
                if binding.base_source is not None:
                    binding.base_source.close()
                    binding.base_source = None
            self._mark_durable(binding, publication_durability)
            new_journal = None
        finally:
            if new_journal is not None:
                new_journal.close()
                if temporary is not None:
                    try:
                        self._backend.unlink(temporary)
                    except (FileNotFoundError, OSError):
                        pass

        if old_journal is not None:
            old_journal.close()
        if old_path is not None and old_path != published:
            try:
                self._backend.unlink(self._owned_path(old_path))
            except FileNotFoundError:
                pass
            except OSError as exc:
                self.last_error = exc
        return True

    def rebase_after_save(
        self,
        document: Document,
        *,
        saved_stamp: SavedFileStamp,
        base_history: HistorySnapshot,
        save_revision: int,
    ) -> Future:
        """Publish a verified saved recovery base before retiring older evidence."""

        if not isinstance(saved_stamp, SavedFileStamp):
            raise TypeError("saved stamp must be a SavedFileStamp")
        if not isinstance(base_history, HistorySnapshot):
            raise TypeError("saved base history must be a HistorySnapshot")
        if type(save_revision) is not int or save_revision < 0:
            raise ValueError("save revision must be a non-negative integer")
        binding = self._bindings.get(id(document))
        if binding is None:
            raise ValueError("document is not attached to recovery")
        with self._lock:
            indexed = tuple(enumerate(binding.events))
            save_index, save_event = next(
                (
                    (index, event)
                    for index, event in reversed(indexed)
                    if event.kind is RecoveryEventKind.SAVE_POINT
                    and event.revision == save_revision
                ),
                (None, None),
            )
            if save_index is None or save_event is None:
                raise ValueError("matching recovery save point is unavailable")
            request = _SavedBaseRequest(
                saved_stamp,
                base_history,
                save_event.sequence,
                save_revision,
                tuple(binding.events[save_index + 1 :]),
                binding.sequence,
                document.encoding_info.detected,
                document.output_encoding,
                document.output_eol,
            )
        return self._submit_serial(
            binding,
            TaskKind.RECOVERY_COMPACTION,
            "saved base",
            lambda: self._replace_saved_base(binding, request),
        )

    def _terminal_event(self, binding: _Binding) -> RecoveryEvent:
        snapshot = binding.document.export_history()
        binding.sequence += 1
        return RecoveryEvent.cursor(
            binding.sequence,
            RecoveryEventKind.TERMINAL,
            cursor=snapshot.cursor,
            saved_cursor=snapshot.saved_cursor,
            revision=binding.document.revision,
        )

    def _finalize_clean(self, binding: _Binding, event: RecoveryEvent) -> None:
        self._write_event(binding, event, allow_compaction=False)
        self._flush_binding(binding)
        if binding.durable_sequence < event.sequence:
            raise OSError("terminal recovery record was not durable")
        journal = binding.journal
        path = binding.journal_path
        if journal is not None:
            journal.close()
        if path is not None:
            try:
                self._backend.unlink(self._owned_path(path))
            except FileNotFoundError:
                pass
        binding.journal = None
        binding.journal_path = None

    def _close_preserving(self, binding: _Binding) -> None:
        try:
            self._flush_binding(binding)
        finally:
            if binding.journal is not None:
                binding.journal.close()
                binding.journal = None

    def detach(self, document: Document, *, clean: bool) -> None:
        binding = self._bindings.get(id(document))
        if binding is None:
            return
        remove_history = binding.remove_history_listener
        if callable(remove_history):
            remove_history()
        self._wait_for_binding(binding)
        if clean and binding.journal is not None:
            with self._lock:
                terminal = self._terminal_event(binding)
                binding.events.append(terminal)
                binding.observed_revision = terminal.revision
            self._submit_serial(
                binding,
                TaskKind.RECOVERY,
                "terminal fsync",
                lambda: self._finalize_clean(binding, terminal),
            )
        else:
            self._submit_serial(
                binding,
                TaskKind.RECOVERY,
                "fsync",
                lambda: self._close_preserving(binding),
            )
        self._wait_for_binding(binding)
        if binding.journal is not None:
            binding.journal.close()
            binding.journal = None
        if binding.base_source is not None:
            binding.base_source.close()
            binding.base_source = None
        self._bindings.pop(id(document), None)

    @staticmethod
    def _safe_error(result: RecoveryLoadResult, match: FileMatch | None) -> str | None:
        if result.status is RecoveryLoadStatus.CORRUPT:
            return "Recovery data is invalid or corrupt."
        if result.status is RecoveryLoadStatus.UNSUPPORTED:
            return "Recovery data was created by a newer UNITI version."
        if result.status is RecoveryLoadStatus.TRUNCATED_TAIL:
            return "Recovery data has an incomplete tail; its durable prefix is available."
        if match is FileMatch.CHANGED:
            return "The source file changed outside UNITI."
        if match is FileMatch.MISSING:
            return "The source file is missing."
        return None

    @staticmethod
    def _actions(
        result: RecoveryLoadResult,
        match: FileMatch | None,
    ) -> tuple[str, ...]:
        if result.session is None:
            return ("skip", "discard")
        if match is FileMatch.MISSING:
            return ("locate", "skip", "discard")
        if match is FileMatch.CHANGED:
            return ("open_disk", "skip", "discard")
        return ("recover", "open_disk", "skip", "discard")

    @staticmethod
    def _source_match(session: RecoverySession | None) -> FileMatch | None:
        if session is None:
            return None
        if session.base_hash is not None:
            return verify_saved_file(
                session.source_path,
                SavedFileStamp(session.source_identity, session.base_hash),
            )
        try:
            identity = FileIdentity.from_path(session.source_path)
        except FileNotFoundError:
            return FileMatch.MISSING
        return (
            FileMatch.EXACT_FAST
            if identity == session.source_identity
            else FileMatch.CHANGED
        )

    def discover(self) -> tuple[RecoveryCandidate, ...]:
        if self._bindings:
            self.flush()
        candidates: list[RecoveryCandidate] = []
        for path in sorted(self.directory.glob("*.uniti-recovery")):
            try:
                owned = self._owned_path(path)
            except ValueError:
                candidates.append(
                    RecoveryCandidate(
                        path,
                        None,
                        RecoveryLoadStatus.CORRUPT,
                        supported_actions=("skip",),
                        safe_error="Recovery evidence resolves outside UNITI storage.",
                    )
                )
                continue
            result = load_recovery_candidate(owned)
            if result.session is not None and result.session.clean:
                try:
                    self._backend.unlink(owned)
                except (FileNotFoundError, OSError):
                    pass
                continue
            try:
                match = self._source_match(result.session)
            except OSError:
                match = FileMatch.CHANGED
            candidates.append(
                RecoveryCandidate(
                    journal_path=owned,
                    session=result.session,
                    load_status=result.status,
                    source_match=match,
                    supported_actions=self._actions(result, match),
                    safe_error=self._safe_error(result, match),
                )
            )
        return tuple(candidates)

    def discard(self, candidate: RecoveryCandidate) -> None:
        path = self._owned_path(candidate.evidence_path)
        try:
            self._backend.unlink(path)
        except FileNotFoundError:
            pass

    @staticmethod
    def _legacy_seed_events(
        operations: tuple[EditOperation, ...],
        *,
        metadata: Mapping[str, object],
    ) -> tuple[RecoveryEvent, ...]:
        events = [
            RecoveryEvent.transaction(
                index,
                EditTransaction((operation,)),
                cursor=index,
                saved_cursor=0,
                revision=index,
            )
            for index, operation in enumerate(operations, start=1)
        ]
        if metadata:
            sequence = len(events) + 1
            events.append(
                RecoveryEvent(
                    sequence,
                    RecoveryEventKind.METADATA,
                    None,
                    len(operations),
                    0,
                    len(operations),
                    metadata,
                )
            )
        return tuple(events)

    def prepare_recovery(self, candidate: RecoveryCandidate) -> RecoveredDocument:
        session = candidate.session
        if session is None or session.clean:
            raise ValueError("recovery candidate has no recoverable session")
        document = Document.open(
            session.source_path,
            encoding=session.source_encoding,
        )
        attached = False
        try:
            replay_recovery(document, session)
            if session.format_version in (1, 2):
                document.set_output_encoding(session.output_encoding)
                document.set_output_eol(session.output_eol)
                seed_events = self._legacy_seed_events(
                    session.operations,
                    metadata={
                        "output_encoding": session.output_encoding,
                        "output_eol": session.output_eol,
                    },
                )
                base_history = HistorySnapshot.empty()
                base_hash = None
            else:
                seed_events = session.events
                base_history = session.base_history
                base_hash = session.base_hash
            self.attach(
                document,
                seed_events=seed_events,
                base_identity=session.source_identity,
                base_hash=base_hash,
                base_history=base_history,
                force_journal=True,
            )
            attached = True
            self.flush(document)
            path = self.journal_path(document)
            diagnostic = self.diagnostic(document)
            if (
                path is None
                or diagnostic.health is RecoveryHealth.DEGRADED
                or diagnostic.durability is DurabilityLevel.UNSAFE
                or diagnostic.durable_revision < diagnostic.observed_revision
            ):
                raise OSError("fresh recovery journal is not durable")
            return RecoveredDocument(document, candidate, path)
        except Exception:
            if attached:
                self.detach(document, clean=False)
            document.close()
            raise

    def commit_recovery(self, recovered: RecoveredDocument) -> None:
        if not isinstance(recovered, RecoveredDocument):
            raise TypeError("recovered must be a RecoveredDocument")
        self.flush(recovered.document)
        diagnostic = self.diagnostic(recovered.document)
        if (
            diagnostic.health is RecoveryHealth.DEGRADED
            or diagnostic.durability is DurabilityLevel.UNSAFE
            or diagnostic.durable_revision < diagnostic.observed_revision
        ):
            raise OSError("fresh recovery state is not durable")
        current = self.journal_path(recovered.document)
        if current is None or not current.exists():
            raise OSError("fresh recovery evidence is unavailable")
        if recovered.original.evidence_path != current:
            self.discard(recovered.original)

    def recover(self, candidate: RecoveryCandidate) -> Document:
        recovered = self.prepare_recovery(candidate)
        self.commit_recovery(recovered)
        return recovered.document

    def shutdown(self) -> None:
        if self._shutdown:
            return
        try:
            for binding in tuple(self._bindings.values()):
                self.detach(binding.document, clean=False)
        finally:
            self._shutdown = True
            if self._owns_resources:
                self._resources.shutdown(wait=True)
