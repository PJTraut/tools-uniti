"""Crash-recovery lifecycle around core delta journals."""

from __future__ import annotations

import hashlib
import uuid
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


class RecoveryManager:
    """Own recovery journals independently of the Qt shell."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self._bindings: dict[int, _Binding] = {}
        self.last_error: Exception | None = None

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
            encoding=binding.document.output_encoding,
        )
        for operation in seed_operations:
            journal.append(operation)
        binding.journal = journal
        binding.journal_path = path

    def attach(
        self,
        document: Document,
        *,
        seed_operations: tuple[EditOperation, ...] = (),
    ) -> None:
        key = id(document)
        if key in self._bindings:
            return

        binding = _Binding(document, None, None, None, None)

        def on_edit(operation: EditOperation) -> None:
            try:
                self._start_journal(binding)
                assert binding.journal is not None
                binding.journal.append(operation)
            except Exception as exc:  # recovery must never corrupt/abort the edit
                self.last_error = exc

        def on_save(_path: Path) -> None:
            try:
                self._clear_journal(binding)
            except Exception as exc:  # the save already succeeded
                self.last_error = exc

        binding.remove_edit_listener = document.add_edit_listener(on_edit)
        binding.remove_save_listener = document.add_save_listener(on_save)
        self._bindings[key] = binding
        if seed_operations:
            self._start_journal(binding, seed_operations=seed_operations)

    def _clear_journal(self, binding: _Binding) -> None:
        path = binding.journal_path
        if binding.journal is not None:
            binding.journal.close()
        binding.journal = None
        binding.journal_path = None
        if path is not None:
            try:
                path.unlink()
            except FileNotFoundError:
                pass

    def detach(self, document: Document, *, clean: bool) -> None:
        binding = self._bindings.pop(id(document), None)
        if binding is None:
            return
        remove_edit = binding.remove_edit_listener
        remove_save = binding.remove_save_listener
        if callable(remove_edit):
            remove_edit()
        if callable(remove_save):
            remove_save()
        if clean:
            self._clear_journal(binding)
        elif binding.journal is not None:
            binding.journal.close()
            binding.journal = None

    def discover(self) -> tuple[RecoveryCandidate, ...]:
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
        document = Document.open(session.source_path, encoding=session.encoding)
        try:
            replay_recovery(document, session)
            self.attach(document, seed_operations=session.operations)
        except Exception:
            document.close()
            raise
        self.discard(candidate)
        return document
