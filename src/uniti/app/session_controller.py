"""Process-session capture, saved-file hashing, and restore coordination."""

from __future__ import annotations

import threading
import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from uniti.resources.tasks import TaskKind, TaskSpec

from .document_registry import DocumentEntry
from .platform_policy import native_paths_equal, normalize_native_path

if TYPE_CHECKING:
    from .session import SessionSnapshot


class SessionController:
    """Own mutable orchestration around immutable session records."""

    def __init__(
        self,
        service: object,
        *,
        session_capture: Callable[[bool], SessionSnapshot] | None = None,
        service_id: str | None = None,
        build_identity: str | None = None,
    ) -> None:
        if session_capture is not None and not callable(session_capture):
            raise TypeError("session capture must be callable")
        selected_service_id = service_id or uuid.uuid4().hex
        if not isinstance(selected_service_id, str) or not selected_service_id:
            raise ValueError("service ID must be a nonempty string")
        if build_identity is None:
            import uniti

            build_identity = uniti.__display_version__
        if not isinstance(build_identity, str) or not build_identity:
            raise ValueError("build identity must be a nonempty string")

        captured_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        self._service = service
        self._session_capture = session_capture
        self._service_id = selected_service_id
        self._build_identity = build_identity
        self._generation = selected_service_id
        self._created_at = captured_at
        self._updated_at = captured_at
        self._manifest = None
        self._packs: dict[str, object] = {}
        self._views: dict[str, object] = {}
        self._pack_loader: Callable[[str], object] | None = None
        self._restored_history_generations: dict[str, str] = {}
        self._find_pack = None
        self._problems: list[object] = []
        self._discarded_document_ids: set[str] = set()
        self._restore_handles: dict[str, object] = {}
        self._promoted_view_ids: dict[str, str] = {}
        self._restore_timer = None
        self._saved_hash_handles: dict[str, tuple[object, object]] = {}
        self._saved_hash_timer = None
        self._document_save_listeners: dict[
            str, tuple[object, Callable[[], None]]
        ] = {}
        self._pending_saved_bases: dict[str, tuple[object, object, int, object]] = {}
        self._pending_lock = threading.RLock()

    @property
    def problems(self) -> tuple[object, ...]:
        return tuple(self._problems)

    @property
    def packs(self) -> dict[str, object]:
        """Expose the live pack map for sealed restore validation tests."""

        return self._packs

    def capture(
        self,
        clean_shutdown: bool,
        *,
        excluded_document_ids: frozenset[str] = frozenset(),
    ) -> SessionSnapshot:
        if not isinstance(clean_shutdown, bool):
            raise TypeError("clean_shutdown must be bool")
        capture = self._session_capture
        if capture is not None:
            return capture(clean_shutdown)

        from .session_runtime import capture_service_session

        return capture_service_session(
            self._service,
            clean_shutdown=clean_shutdown,
            generation=self._generation,
            service_id=self._service_id,
            build_identity=self._build_identity,
            created_at=self._created_at,
            updated_at=self._updated_at,
            history_generations=dict(self._restored_history_generations),
            previous_pack_references=(
                () if self._manifest is None else self._manifest.packs
            ),
            previous_find_pack=self._find_pack,
            excluded_document_ids=excluded_document_ids,
        )

    def track_document(self, entry: DocumentEntry, *, hash_saved: bool = True) -> None:
        """Track saved-file identity for one registry authority."""

        if not isinstance(entry, DocumentEntry):
            raise TypeError("entry must be a DocumentEntry")
        previous = self._document_save_listeners.get(entry.document_id)
        if previous is None or previous[0] is not entry.document:
            if previous is not None:
                previous[1]()
            remove = entry.document.add_save_listener(
                lambda _path, document_id=entry.document_id: self._document_saved(
                    document_id
                )
            )
            self._document_save_listeners[entry.document_id] = (
                entry.document,
                remove,
            )
        if hash_saved and entry.saved_stamp is None:
            self._schedule_saved_hash(entry.document_id)

    def _document_saved(self, document_id: str) -> None:
        try:
            entry = self._service.documents.get(document_id)
        except KeyError:
            return
        document = entry.document
        pending = (
            document,
            document.export_history(),
            document.revision,
            document.disk_identity,
        )
        with self._pending_lock:
            self._pending_saved_bases[document_id] = pending
        self._schedule_saved_hash(document_id)

    def publication_durable(self, snapshot: object) -> frozenset[str]:
        """Stage saved recovery bases only after their session is durable."""

        rebase = getattr(self._service.recovery, "rebase_after_save", None)
        if not callable(rebase):
            return frozenset()
        packs = {
            pack.document_id: pack
            for pack in tuple(getattr(snapshot, "packs", ()))
        }
        scheduled: set[str] = set()
        with self._pending_lock:
            pending_items = tuple(self._pending_saved_bases.items())
        for document_id, pending in pending_items:
            document, base_history, save_revision, expected_identity = pending
            pack = packs.get(document_id)
            if (
                pack is None
                or pack.saved_stamp.identity != expected_identity
            ):
                continue
            try:
                future = rebase(
                    document,
                    saved_stamp=pack.saved_stamp,
                    base_history=base_history,
                    save_revision=save_revision,
                )
            except (RuntimeError, ValueError):
                continue
            scheduled.add(document_id)

            def finished(
                completed,
                *,
                selected_document_id=document_id,
                selected_pending=pending,
            ) -> None:
                try:
                    succeeded = completed.result() is True
                except Exception:
                    succeeded = False
                if not succeeded:
                    return
                with self._pending_lock:
                    if (
                        self._pending_saved_bases.get(selected_document_id)
                        == selected_pending
                    ):
                        self._pending_saved_bases.pop(selected_document_id, None)

            future.add_done_callback(finished)
        return frozenset(scheduled)

    def _schedule_saved_hash(self, document_id: str) -> None:
        from uniti.resources import WorkPriority

        from .session_runtime import stamp_saved_file

        service = self._service
        if not service.is_running:
            return
        try:
            entry = service.documents.get(document_id)
        except KeyError:
            return
        existing = self._saved_hash_handles.pop(document_id, None)
        if existing is not None:
            existing[0].cancel()
        entry.saved_stamp = None
        document = entry.document
        expected_identity = document.disk_identity
        spec = TaskSpec.create(
            TaskKind.HASH,
            foreground=False,
            priority=WorkPriority.PREFETCH,
            document_key=document_id,
            revision=document.revision,
        )
        handle = service.resources.tasks.submit(
            spec,
            lambda _context: stamp_saved_file(
                Path(document.path),
                expected_identity,
            ),
        )
        self._saved_hash_handles[document_id] = (handle, document)
        self._ensure_saved_hash_timer()

    def _ensure_saved_hash_timer(self) -> None:
        if self._saved_hash_timer is not None:
            return
        from PySide6.QtCore import QTimer

        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(self._poll_saved_hashes)
        timer.start()
        self._saved_hash_timer = timer

    def _poll_saved_hashes(self) -> None:
        service = self._service
        for document_id, request in tuple(self._saved_hash_handles.items()):
            handle, document = request
            if not handle.done:
                continue
            if self._saved_hash_handles.get(document_id) != request:
                continue
            self._saved_hash_handles.pop(document_id, None)
            try:
                stamp = handle.future.result()
                entry = service.documents.get(document_id)
            except Exception:
                continue
            if entry.document is document and stamp is not None:
                entry.saved_stamp = stamp
                try:
                    service.schedule_publication(clean_shutdown=False)
                except RuntimeError:
                    pass
        if not self._saved_hash_handles and self._saved_hash_timer is not None:
            self._saved_hash_timer.stop()
            self._saved_hash_timer.deleteLater()
            self._saved_hash_timer = None

    def complete_saved_hash(self, document_id: str) -> None:
        request = self._saved_hash_handles.get(document_id)
        if request is None:
            self._schedule_saved_hash(document_id)
            request = self._saved_hash_handles.get(document_id)
        if request is None:
            raise OSError("saved-file hash could not be scheduled")
        handle, document = request
        stamp = handle.future.result()
        if self._saved_hash_handles.get(document_id) == request:
            self._saved_hash_handles.pop(document_id, None)
        entry = self._service.documents.get(document_id)
        if stamp is None or entry.document is not document:
            raise OSError("saved file changed while hashing")
        entry.saved_stamp = stamp

    def restore_shell(
        self,
        manifest: object,
        *,
        packs: tuple[object, ...] = (),
        find_replace_pack: object | None = None,
        pack_loader: Callable[[str], object] | None = None,
    ) -> None:
        """Build bounded window/pane placeholders without opening source files."""

        from .session import FindReplaceHistoryPack, HistoryPack, SessionManifest
        from .session_runtime import merge_find_replace_history

        service = self._service
        service._ensure_running()
        if not isinstance(manifest, SessionManifest):
            raise TypeError("manifest must be a SessionManifest")
        if not isinstance(packs, tuple) or any(
            not isinstance(pack, HistoryPack) for pack in packs
        ):
            raise TypeError("packs must be a tuple of HistoryPack values")
        if find_replace_pack is not None and not isinstance(
            find_replace_pack, FindReplaceHistoryPack
        ):
            raise TypeError(
                "find_replace_pack must be a FindReplaceHistoryPack or None"
            )
        if pack_loader is not None and not callable(pack_loader):
            raise TypeError("pack_loader must be callable or None")
        if service.window_count or service.documents.count:
            raise RuntimeError("session shell restore requires an empty service")

        self._manifest = manifest
        self._packs = {pack.document_id: pack for pack in packs}
        self._pack_loader = pack_loader
        self._views = {view.view_id: view for view in manifest.views}
        self._find_pack = find_replace_pack
        self._problems = []
        self._discarded_document_ids = set()
        self._promoted_view_ids = {}
        self._service_id = manifest.service_id
        self._build_identity = manifest.build_identity
        self._generation = manifest.generation
        self._created_at = manifest.created_at
        self._updated_at = manifest.updated_at
        for record in manifest.windows:
            service.new_window(record)
        service.find_replace.restore_state(
            merge_find_replace_history(manifest.find_replace, find_replace_pack)
        )

    def _document_id_for_view(self, view_id: str | None) -> str | None:
        if view_id is None:
            return None
        view = self._views.get(view_id)
        return None if view is None else view.document_id

    def apply_restore_result(self, result: object) -> object | None:
        from uniti.core.file_identity import FileMatch

        from .session import SessionProblem
        from .session_runtime import RestoreDocumentResult

        if not isinstance(result, RestoreDocumentResult):
            raise TypeError("restore task returned an invalid result")
        pack = self._packs.get(result.seal.document_id)
        manifest = self._manifest
        reference = (
            None
            if manifest is None
            else next(
                (
                    item
                    for item in manifest.packs
                    if item.kind == "document"
                    and item.owner_id == result.seal.document_id
                ),
                None,
            )
        )
        if (
            manifest is None
            or reference is None
            or reference.generation != result.seal.history_generation
            or result.pack.generation != result.seal.history_generation
            or result.pack.saved_stamp.sha256 != result.seal.expected_hash
            or (
                pack is not None
                and (
                    pack.generation != result.seal.history_generation
                    or pack.saved_stamp.sha256 != result.seal.expected_hash
                    or not native_paths_equal(
                        pack.canonical_path,
                        result.pack.canonical_path,
                    )
                )
            )
        ):
            if result.document is not None:
                result.document.close()
            return None

        pack = result.pack
        self._packs[pack.document_id] = pack
        document_record = next(
            (
                record
                for record in manifest.documents
                if record.document_id == result.seal.document_id
            ),
            None,
        )
        if (
            document_record is None
            or not native_paths_equal(
                document_record.canonical_path,
                pack.canonical_path,
            )
            or document_record.view_ids != result.seal.requested_view_ids
        ):
            if result.document is not None:
                result.document.close()
            return None
        if result.match not in {FileMatch.EXACT_FAST, FileMatch.EXACT_HASH}:
            kind = (
                "missing_source"
                if result.match is FileMatch.MISSING
                else "changed_source"
            )
            message = (
                "A saved session source is missing."
                if result.match is FileMatch.MISSING
                else "A saved session source changed outside UNITI."
            )
            self._problems.append(
                SessionProblem(
                    kind,
                    Path(pack.canonical_path),
                    message,
                    pack.document_id,
                )
            )
            return None

        document = result.document
        assert document is not None
        entry = self._service.documents.adopt(
            document,
            document_id=pack.document_id,
            saved_stamp=pack.saved_stamp,
        )
        self._restored_history_generations[pack.document_id] = pack.generation
        self.track_document(entry, hash_saved=False)
        document.add_history_listener(
            lambda _event, document_id=pack.document_id: (
                self._restored_history_generations.pop(document_id, None)
            )
        )
        self._service.recovery.attach(document)
        for view_id in document_record.view_ids:
            view_record = self._views[view_id]
            window = self._service.windows.window_for_view(view_id)
            if window is None:
                document.close()
                raise RuntimeError("restored view has no window placeholder")
            window.restore_document_view(document, view_record)
        self._restore_entry_timestamps(entry, document_record)
        self._restore_post_hydration_focus(pack.document_id)
        return entry

    def _apply_fresh_result(self, result: object) -> object | None:
        from .session_runtime import FreshDocumentResult

        if not isinstance(result, FreshDocumentResult):
            raise TypeError("fresh restore task returned an invalid result")
        manifest = self._manifest
        record = (
            None
            if manifest is None
            else next(
                (
                    item
                    for item in manifest.documents
                    if item.document_id == result.document_id
                ),
                None,
            )
        )
        if (
            record is None
            or not native_paths_equal(record.canonical_path, result.canonical_path)
            or record.view_ids != result.requested_view_ids
        ):
            result.document.close()
            return None
        entry = self._service.documents.adopt(
            result.document,
            document_id=result.document_id,
            saved_stamp=result.saved_stamp,
        )
        self.track_document(entry, hash_saved=False)
        self._service.recovery.attach(result.document)
        for view_id in record.view_ids:
            view_record = self._views[view_id]
            window = self._service.windows.window_for_view(view_id)
            if window is None:
                result.document.close()
                raise RuntimeError("restored view has no window placeholder")
            window.restore_document_view(result.document, view_record)
        self._restore_entry_timestamps(entry, record)
        self._restore_post_hydration_focus(result.document_id)
        return entry

    def _restore_post_hydration_focus(self, document_id: str) -> None:
        promoted_view_id = self._promoted_view_ids.pop(document_id, None)
        if promoted_view_id is None:
            self._restore_manifest_focus()
            return
        window = self._service.windows.window_for_view(promoted_view_id)
        if window is None or window.view_for_id(promoted_view_id) is None:
            self._restore_manifest_focus()
            return
        window.panes.activate_view(promoted_view_id)
        self._service.set_active_view(window.window_id, promoted_view_id)

    def _restore_manifest_focus(self) -> None:
        manifest = self._manifest
        if manifest is None or manifest.active_view_id is None:
            return
        window = self._service.windows.window_for_view(manifest.active_view_id)
        if window is None or window.view_for_id(manifest.active_view_id) is None:
            return
        window.panes.activate_view(manifest.active_view_id)
        self._service.set_active_view(window.window_id, manifest.active_view_id)
        active_document_id = self._document_id_for_view(manifest.active_view_id)
        if active_document_id is not None:
            try:
                entry = self._service.documents.get(active_document_id)
            except KeyError:
                return
            record = next(
                item
                for item in manifest.documents
                if item.document_id == active_document_id
            )
            self._restore_entry_timestamps(entry, record)

    @staticmethod
    def _restore_entry_timestamps(entry: object, record: object) -> None:
        last_active = datetime.fromisoformat(
            record.last_active_at.replace("Z", "+00:00")
        )
        closed = (
            None
            if record.closed_at is None
            else datetime.fromisoformat(record.closed_at.replace("Z", "+00:00"))
        )
        entry.last_active_at = last_active
        entry.closed_at = closed

    def _submit_restore(self, document_id: str, *, foreground: bool):
        from uniti.resources import WorkPriority

        from .session_runtime import restore_document_pack, restore_fresh_document

        pack = self._packs.get(document_id)
        manifest = self._manifest
        loader = self._pack_loader
        if manifest is None:
            return None
        record = next(
            item for item in manifest.documents if item.document_id == document_id
        )
        reference = next(
            (
                item
                for item in manifest.packs
                if item.kind == "document" and item.owner_id == document_id
            ),
            None,
        )
        if reference is not None and pack is None and loader is None:
            return None
        spec = TaskSpec.create(
            TaskKind.HASH if foreground else TaskKind.SESSION,
            foreground=foreground,
            priority=None if foreground else WorkPriority.PREFETCH,
            document_key=document_id,
        )

        def work(_context):
            if reference is None:
                return restore_fresh_document(
                    document_id,
                    record.canonical_path,
                    record.view_ids,
                    resource_manager=self._service.resources,
                )
            selected_pack = pack if pack is not None else loader(document_id)
            return restore_document_pack(
                selected_pack,
                record.view_ids,
                resource_manager=self._service.resources,
            )

        return self._service.resources.tasks.submit(spec, work)

    def _run_restore(self, document_id: str, *, foreground: bool) -> object | None:
        handle = self._submit_restore(document_id, foreground=foreground)
        if handle is None:
            return None
        result = handle.future.result()
        from .session_runtime import FreshDocumentResult

        if isinstance(result, FreshDocumentResult):
            return self._apply_fresh_result(result)
        return self.apply_restore_result(result)

    def _record_restore_failure(self, document_id: str) -> None:
        from .session import SessionProblem

        pack = self._packs.get(document_id)
        record = (
            None
            if self._manifest is None
            else next(
                (
                    item
                    for item in self._manifest.documents
                    if item.document_id == document_id
                ),
                None,
            )
        )
        path = (
            Path(pack.canonical_path)
            if pack is not None
            else Path(record.canonical_path)
            if record is not None
            else Path("session")
        )
        if any(
            item.kind == "restore_failed" and item.document_id == document_id
            for item in self._problems
        ):
            return
        self._problems.append(
            SessionProblem(
                "restore_failed",
                path,
                "A saved session document could not be restored.",
                document_id,
            )
        )

    def restore_active(self) -> object | None:
        """Verify and restore the manifest's active document first."""

        service = self._service
        service._ensure_running()
        manifest = self._manifest
        if manifest is None:
            raise RuntimeError("no session shell is prepared")
        document_id = self._document_id_for_view(manifest.active_view_id)
        if document_id is None or document_id in self._discarded_document_ids:
            return None
        try:
            restored = self._run_restore(document_id, foreground=True)
        except Exception:
            self._record_restore_failure(document_id)
            return None
        if restored is not None:
            self._restore_manifest_focus()
        return restored

    def _ensure_restore_timer(self) -> None:
        if self._restore_timer is not None:
            return
        from PySide6.QtCore import QTimer

        timer = QTimer()
        timer.setInterval(10)
        timer.timeout.connect(self._poll_restore_tasks)
        timer.start()
        self._restore_timer = timer

    def _poll_restore_tasks(self) -> None:
        from .session_runtime import FreshDocumentResult, RestoreDocumentResult

        for document_id, handle in tuple(self._restore_handles.items()):
            if not handle.done:
                continue
            if self._restore_handles.get(document_id) is not handle:
                continue
            self._restore_handles.pop(document_id, None)
            try:
                result = handle.future.result()
            except Exception:
                self._record_restore_failure(document_id)
                continue
            if isinstance(result, FreshDocumentResult):
                self._apply_fresh_result(result)
            elif isinstance(result, RestoreDocumentResult):
                self.apply_restore_result(result)
        if not self._restore_handles and self._restore_timer is not None:
            self._restore_timer.stop()
            self._restore_timer.deleteLater()
            self._restore_timer = None

    def schedule_lazy_restore(self) -> tuple[object, ...]:
        """Queue every inactive saved document at background priority."""

        service = self._service
        service._ensure_running()
        manifest = self._manifest
        if manifest is None:
            raise RuntimeError("no session shell is prepared")
        active_document_id = self._document_id_for_view(manifest.active_view_id)
        scheduled = []
        restored_ids = {entry.document_id for entry in service.documents.entries}
        for record in manifest.documents:
            if (
                record.document_id == active_document_id
                or record.document_id in self._discarded_document_ids
                or record.document_id in self._restore_handles
                or record.document_id in restored_ids
            ):
                continue
            handle = self._submit_restore(record.document_id, foreground=False)
            if handle is not None:
                self._restore_handles[record.document_id] = handle
                scheduled.append(handle)
        if scheduled:
            self._ensure_restore_timer()
        return tuple(scheduled)

    def promote_restore(self, view_id: str) -> None:
        """Promote a queued placeholder restore when the user selects it."""

        from uniti.resources import TaskState

        document_id = self._document_id_for_view(view_id)
        if document_id is None:
            return
        handle = self._restore_handles.get(document_id)
        if handle is None or handle.state is not TaskState.QUEUED:
            return
        handle.cancel()
        promoted = self._submit_restore(document_id, foreground=True)
        if promoted is not None:
            self._promoted_view_ids[document_id] = view_id
            self._restore_handles[document_id] = promoted
            self._ensure_restore_timer()

    def discard_document(self, document_id: str) -> None:
        """Remove one explicitly discarded conflict from the prepared shell."""

        manifest = self._manifest
        if manifest is None:
            return
        record = next(
            (
                item
                for item in manifest.documents
                if item.document_id == document_id
            ),
            None,
        )
        if record is None:
            return
        handle = self._restore_handles.pop(document_id, None)
        if handle is not None:
            handle.cancel()
        for view_id in record.view_ids:
            window = self._service.windows.window_for_view(view_id)
            remove = getattr(window, "discard_session_placeholder", None)
            if callable(remove):
                remove(view_id)
            self._views.pop(view_id, None)
        self._packs.pop(document_id, None)
        self._promoted_view_ids.pop(document_id, None)
        self._discarded_document_ids.add(document_id)
        self._problems = [
            item
            for item in self._problems
            if getattr(item, "document_id", None) != document_id
        ]

    def resolve_problem(
        self,
        problem: object,
        *,
        action: object,
        located_path: Path | None,
    ) -> object:
        """Resolve one source conflict while preserving the sealed shell."""

        from uniti.core.file_identity import FileIdentity, SavedFileStamp, sha256_file
        from uniti.resources import WorkPriority
        from uniti.ui.recovery_center import RecoveryAction

        from .session_runtime import restore_document_pack, restore_fresh_document

        document_id = getattr(problem, "document_id", None)
        manifest = self._manifest
        if not isinstance(document_id, str) or manifest is None:
            raise ValueError("session problem has no restorable document")
        record = next(
            item for item in manifest.documents if item.document_id == document_id
        )
        spec = TaskSpec.create(
            TaskKind.HASH,
            foreground=True,
            priority=WorkPriority.INTERACTIVE,
            document_key=document_id,
        )
        if action is RecoveryAction.OPEN_DISK:
            handle = self._service.resources.tasks.submit(
                spec,
                lambda _context: restore_fresh_document(
                    document_id,
                    record.canonical_path,
                    record.view_ids,
                    resource_manager=self._service.resources,
                ),
            )
            restored = self._apply_fresh_result(handle.future.result())
        elif action is RecoveryAction.LOCATE_MATCH:
            if located_path is None:
                raise ValueError("a matching source path is required")
            located_path = normalize_native_path(located_path).path
            pack = self._packs.get(document_id)
            if pack is None and self._pack_loader is not None:
                pack = self._pack_loader(document_id)
            if pack is None:
                raise ValueError("session history is unavailable")

            def relocate(_context):
                digest = sha256_file(located_path)
                if digest != pack.saved_stamp.sha256:
                    raise ValueError("located file does not match session history")
                relocated = replace(
                    pack,
                    canonical_path=str(located_path),
                    saved_stamp=SavedFileStamp(
                        FileIdentity.from_path(located_path),
                        digest,
                    ),
                )
                return restore_document_pack(
                    relocated,
                    record.view_ids,
                    resource_manager=self._service.resources,
                )

            handle = self._service.resources.tasks.submit(spec, relocate)
            relocated_result = handle.future.result()
            previous_manifest = self._manifest
            previous_pack = self._packs.get(document_id)
            self._packs[document_id] = relocated_result.pack
            self._manifest = replace(
                manifest,
                documents=tuple(
                    replace(
                        item,
                        canonical_path=relocated_result.pack.canonical_path,
                    )
                    if item.document_id == document_id
                    else item
                    for item in manifest.documents
                ),
            )
            try:
                restored = self.apply_restore_result(relocated_result)
            except Exception:
                self._manifest = previous_manifest
                if previous_pack is None:
                    self._packs.pop(document_id, None)
                else:
                    self._packs[document_id] = previous_pack
                raise
            if restored is None:
                self._manifest = previous_manifest
                if previous_pack is None:
                    self._packs.pop(document_id, None)
                else:
                    self._packs[document_id] = previous_pack
        else:
            raise ValueError("session problem action is unsupported")
        if restored is None:
            raise OSError("session problem could not be resolved safely")
        self._problems = [item for item in self._problems if item != problem]
        self._service.schedule_publication(clean_shutdown=False)
        return restored

    def shutdown(self) -> None:
        """Cancel session tasks and release listeners/timers before resources close."""

        for handle, _document in self._saved_hash_handles.values():
            handle.cancel()
        self._saved_hash_handles.clear()
        for handle in self._restore_handles.values():
            handle.cancel()
            try:
                result = handle.future.result()
            except Exception:
                continue
            document = getattr(result, "document", None)
            if document is not None:
                document.close()
        self._restore_handles.clear()
        for _document_id, (_document, remove) in tuple(
            self._document_save_listeners.items()
        ):
            remove()
        self._document_save_listeners.clear()
        with self._pending_lock:
            self._pending_saved_bases.clear()
        for timer_name in ("_saved_hash_timer", "_restore_timer"):
            timer = getattr(self, timer_name)
            if timer is not None:
                timer.stop()
                timer.deleteLater()
                setattr(self, timer_name, None)


__all__ = ["SessionController"]
