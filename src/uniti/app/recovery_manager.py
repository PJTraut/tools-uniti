"""Crash-recovery lifecycle around core delta journals."""

from __future__ import annotations

import hashlib
import threading
import time
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

from uniti.core.document import Document
from uniti.core.history import EditOperation
from uniti.core.recovery import (
    RecoveryJournal,
    RecoverySession,
    load_recovery,
    replay_recovery,
)


@dataclass(frozen=True, slots=True)
class RecoveryCandidate:
    journal_path: Path
    session: RecoverySession


@dataclass(slots=True)
class _Binding:
    document: Document
    journal: RecoveryJournal | None
    journal_path: Path | None
    remove_edit_listener: object
    remove_save_listener: object
    remove_metadata_listener: object
    last_future: Future | None = None
    last_fsync: float = 0.0


class RecoveryManager:
    """Own recovery journals; disk I/O never runs in the edit-listener path."""

    def __init__(self, directory: str | Path, *, fsync_interval: float = 0.25) -> None:
        if fsync_interval <= 0:
            raise ValueError("fsync_interval must be positive")
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._bindings: dict[int, _Binding] = {}
        self.last_error: Exception | None = None
        self._fsync_interval = float(fsync_interval)
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="uniti-recovery")
        self._lock = threading.RLock()
        self._shutdown = False

    def _new_journal_path(self, document: Document) -> Path:
        digest = hashlib.sha256(str(document.path.absolute()).encode("utf-8")).hexdigest()[:12]
        suffix = uuid.uuid4().hex[:10]
        return self.directory / f"{digest}-{suffix}.uniti-recovery"

    def _start_journal(
        self,
        binding: _Binding,
        *,
        seed_operations: tuple[EditOperation, ...] = (),
    ) -> None:
        if binding.journal is not None:
            return
        path = self._new_journal_path(binding.document)
        journal = RecoveryJournal.create(
            path,
            binding.document.path,
            source_encoding=binding.document.encoding_info.detected,
            output_encoding=binding.document.output_encoding,
            output_eol=binding.document.output_eol,
        )
        for operation in seed_operations:
            journal.append(operation, durable=False)
        if seed_operations:
            journal.flush(durable=True)
        binding.journal = journal
        binding.journal_path = path
        binding.last_fsync = time.monotonic()

    def _run_task(self, fn, *args, **kwargs) -> None:
        try:
            fn(*args, **kwargs)
        except Exception as exc:
            self.last_error = exc

    def _submit(self, binding: _Binding, fn, *args, **kwargs) -> Future:
        with self._lock:
            if self._shutdown:
                raise RuntimeError("recovery manager is shut down")
            future = self._executor.submit(self._run_task, fn, *args, **kwargs)
            binding.last_future = future
            return future

    def _maybe_fsync(self, binding: _Binding) -> None:
        journal = binding.journal
        if journal is None:
            return
        now = time.monotonic()
        if now - binding.last_fsync >= self._fsync_interval:
            journal.flush(durable=True)
            binding.last_fsync = now

    def _write_edit(self, binding: _Binding, operation: EditOperation) -> None:
        self._start_journal(binding)
        assert binding.journal is not None
        binding.journal.append(operation, durable=False)
        self._maybe_fsync(binding)

    def _write_metadata(
        self,
        binding: _Binding,
        output_encoding: str,
        output_eol: str | None,
    ) -> None:
        if binding.journal is None:
            return
        binding.journal.update_metadata(
            output_encoding=output_encoding,
            output_eol=output_eol,
            durable=False,
        )
        self._maybe_fsync(binding)

    def _flush_binding(self, binding: _Binding) -> None:
        if binding.journal is not None:
            binding.journal.flush(durable=True)
            binding.last_fsync = time.monotonic()

    def attach(
        self,
        document: Document,
        *,
        seed_operations: tuple[EditOperation, ...] = (),
    ) -> None:
        key = id(document)
        if key in self._bindings:
            return

        binding = _Binding(document, None, None, None, None, None)

        def on_edit(operation: EditOperation) -> None:
            try:
                self._submit(binding, self._write_edit, binding, operation)
            except Exception as exc:
                self.last_error = exc

        def on_save(_path: Path) -> None:
            try:
                self._submit(binding, self._clear_journal, binding).result()
            except Exception as exc:
                self.last_error = exc

        def on_metadata(output_encoding: str, output_eol: str | None) -> None:
            try:
                self._submit(
                    binding,
                    self._write_metadata,
                    binding,
                    output_encoding,
                    output_eol,
                )
            except Exception as exc:
                self.last_error = exc

        binding.remove_edit_listener = document.add_edit_listener(on_edit)
        binding.remove_save_listener = document.add_save_listener(on_save)
        binding.remove_metadata_listener = document.add_metadata_listener(on_metadata)
        self._bindings[key] = binding
        if seed_operations:
            self._submit(
                binding,
                self._start_journal,
                binding,
                seed_operations=seed_operations,
            )

    def _clear_journal(self, binding: _Binding) -> None:
        path = binding.journal_path
        if binding.journal is not None:
            binding.journal.flush(durable=True)
            binding.journal.close()
        binding.journal = None
        binding.journal_path = None
        if path is not None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def flush(self, document: Document | None = None) -> None:
        bindings = (
            [self._bindings.get(id(document))]
            if document is not None
            else list(self._bindings.values())
        )
        for binding in bindings:
            if binding is None:
                continue
            future = self._submit(binding, self._flush_binding, binding)
            future.result()

    def detach(self, document: Document, *, clean: bool) -> None:
        binding = self._bindings.pop(id(document), None)
        if binding is None:
            return
        remove_edit = binding.remove_edit_listener
        remove_save = binding.remove_save_listener
        remove_metadata = binding.remove_metadata_listener
        if callable(remove_edit):
            remove_edit()
        if callable(remove_save):
            remove_save()
        if callable(remove_metadata):
            remove_metadata()
        if clean:
            self._submit(binding, self._clear_journal, binding).result()
        else:
            def durable_close(target: _Binding) -> None:
                if target.journal is not None:
                    target.journal.flush(durable=True)
                    target.journal.close()
                    target.journal = None
            self._submit(binding, durable_close, binding).result()

    def discover(self) -> tuple[RecoveryCandidate, ...]:
        if self._bindings:
            self.flush()
        candidates: list[RecoveryCandidate] = []
        for path in sorted(self.directory.glob("*.uniti-recovery")):
            try:
                session = load_recovery(path)
            except (OSError, ValueError):
                continue
            if session.clean or not session.operations:
                try:
                    path.unlink()
                except OSError:
                    pass
                continue
            candidates.append(RecoveryCandidate(path, session))
        return tuple(candidates)

    def discard(self, candidate: RecoveryCandidate) -> None:
        try:
            candidate.journal_path.unlink()
        except FileNotFoundError:
            pass

    def recover(self, candidate: RecoveryCandidate) -> Document:
        session = candidate.session
        document = Document.open(session.source_path, encoding=session.source_encoding)
        try:
            replay_recovery(document, session)
            document.set_output_encoding(session.output_encoding)
            document.set_output_eol(session.output_eol)
            self.attach(document, seed_operations=session.operations)
            self.flush(document)
        except Exception:
            document.close()
            raise
        self.discard(candidate)
        return document

    def shutdown(self) -> None:
        if self._shutdown:
            return
        try:
            if self._bindings:
                self.flush()
        finally:
            self._shutdown = True
            self._executor.shutdown(wait=True, cancel_futures=False)
