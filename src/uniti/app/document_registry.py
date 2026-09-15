"""Process-lifetime ownership of authoritative UNITI documents."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from uniti.core.document import Document
from uniti.core.file_identity import SavedFileStamp

from .platform_policy import native_paths_equal, normalize_native_path


CLOSED_HISTORY_RETENTION = timedelta(days=7)


class DuplicateDocumentError(RuntimeError):
    """Raised when a second document authority targets an owned file."""


@dataclass(slots=True, eq=False)
class DocumentEntry:
    """One authoritative document and its process/session ownership metadata."""

    document_id: str
    canonical_path: Path
    document: Document
    view_ids: tuple[str, ...]
    saved_stamp: SavedFileStamp | None
    last_active_at: datetime
    closed_at: datetime | None
    group_id: str | None = None
    is_untitled: bool = False


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} must be a nonempty string")
    return value


def _datetime(value: datetime, label: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{label} must be timezone-aware")
    return value


class DocumentRegistry:
    """Keep one live ``Document`` authority for each source identity."""

    def __init__(
        self,
        *,
        clock: Callable[[], datetime] = _utc_now,
        closed_history_retention: timedelta = CLOSED_HISTORY_RETENTION,
    ) -> None:
        if not callable(clock):
            raise TypeError("clock must be callable")
        if (
            not isinstance(closed_history_retention, timedelta)
            or closed_history_retention <= timedelta(0)
        ):
            raise ValueError("closed history retention must be positive")
        self._clock = clock
        self._closed_history_retention = closed_history_retention
        self._entries: dict[str, DocumentEntry] = {}
        self._documents: dict[int, str] = {}
        self._views: dict[str, str] = {}
        self._remove_listeners: list[Callable[[DocumentEntry], None]] = []

    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[DocumentEntry, ...]:
        """Return entries in stable adoption order."""

        return tuple(self._entries.values())

    def add_remove_listener(
        self,
        listener: Callable[[DocumentEntry], None],
    ) -> Callable[[], None]:
        """Observe authority removal so process services can release bindings."""

        if not callable(listener):
            raise TypeError("document removal listener must be callable")
        self._remove_listeners.append(listener)

        def remove() -> None:
            try:
                self._remove_listeners.remove(listener)
            except ValueError:
                pass

        return remove

    def find_path(self, path: Path) -> DocumentEntry | None:
        candidate = normalize_native_path(path).path
        for entry in self._entries.values():
            if native_paths_equal(entry.canonical_path, candidate):
                return entry
        return None

    def adopt(
        self,
        document: Document,
        *,
        document_id: str | None = None,
        saved_stamp: SavedFileStamp | None = None,
        is_untitled: bool = False,
    ) -> DocumentEntry:
        if not isinstance(document, Document):
            raise TypeError("document must be a Document")
        if saved_stamp is not None and not isinstance(saved_stamp, SavedFileStamp):
            raise TypeError("saved_stamp must be a SavedFileStamp or None")
        existing_id = self._documents.get(id(document))
        if existing_id is not None:
            entry = self._entries[existing_id]
            if document_id is not None and document_id != entry.document_id:
                raise DuplicateDocumentError("document already has a different ID")
            if saved_stamp is not None and saved_stamp != entry.saved_stamp:
                raise DuplicateDocumentError("document already has a different saved stamp")
            return entry

        canonical_path = normalize_native_path(document.path).path
        existing = self.find_path(canonical_path)
        if existing is not None:
            raise DuplicateDocumentError(
                f"document path is already owned by {existing.document_id}"
            )
        selected_id = uuid.uuid4().hex if document_id is None else _identifier(
            document_id, "document ID"
        )
        if selected_id in self._entries:
            raise DuplicateDocumentError(f"document ID is already owned: {selected_id}")
        now = _datetime(self._clock(), "clock result")
        entry = DocumentEntry(
            selected_id,
            canonical_path,
            document,
            (),
            saved_stamp,
            now,
            None,
            None,
            is_untitled,
        )
        self._entries[selected_id] = entry
        self._documents[id(document)] = selected_id
        return entry

    def get(self, document_id: str) -> DocumentEntry:
        return self._entries[_identifier(document_id, "document ID")]

    def set_group(self, document_id: str, group_id: str | None) -> None:
        """Assign (or clear) the one group a document belongs to."""

        entry = self.get(document_id)
        if group_id is not None:
            _identifier(group_id, "document group ID")
        entry.group_id = group_id

    def entry_for_view(self, view_id: str) -> DocumentEntry | None:
        document_id = self._views.get(_identifier(view_id, "view ID"))
        return None if document_id is None else self._entries[document_id]

    def bind_view(self, document_id: str, view_id: str) -> None:
        entry = self.get(document_id)
        selected_view_id = _identifier(view_id, "view ID")
        existing_id = self._views.get(selected_view_id)
        if existing_id is not None and existing_id != entry.document_id:
            raise ValueError(
                f"view {selected_view_id!r} is already bound to document {existing_id}"
            )
        if existing_id is None:
            self._views[selected_view_id] = entry.document_id
            entry.view_ids = entry.view_ids + (selected_view_id,)
        entry.last_active_at = _datetime(self._clock(), "clock result")
        entry.closed_at = None

    def activate_view(self, view_id: str) -> DocumentEntry:
        entry = self.entry_for_view(view_id)
        if entry is None:
            raise KeyError(view_id)
        entry.last_active_at = _datetime(self._clock(), "clock result")
        return entry

    def release_view(self, view_id: str) -> DocumentEntry:
        selected_view_id = _identifier(view_id, "view ID")
        try:
            document_id = self._views.pop(selected_view_id)
        except KeyError as exc:
            raise KeyError(selected_view_id) from exc
        entry = self._entries[document_id]
        entry.view_ids = tuple(
            candidate for candidate in entry.view_ids if candidate != selected_view_id
        )
        now = _datetime(self._clock(), "clock result")
        entry.last_active_at = now
        if not entry.view_ids and not entry.document.modified:
            entry.closed_at = now
        return entry

    def close_expired(self, now: datetime) -> tuple[str, ...]:
        selected_now = _datetime(now, "expiry time")
        expired = tuple(
            entry.document_id
            for entry in self._entries.values()
            if not entry.view_ids
            and entry.closed_at is not None
            and selected_now - entry.closed_at >= self._closed_history_retention
        )
        for document_id in expired:
            self._remove(document_id)
        return expired

    def _remove(self, document_id: str) -> DocumentEntry:
        entry = self._entries.pop(document_id)
        for view_id in entry.view_ids:
            self._views.pop(view_id, None)
        self._documents.pop(id(entry.document), None)
        try:
            for listener in tuple(self._remove_listeners):
                listener(entry)
        finally:
            entry.document.close()
        return entry

    def retire(self, document_id: str) -> DocumentEntry:
        """Remove and close an entry that must not remain in history retention."""

        selected_id = _identifier(document_id, "document ID")
        entry = self.get(selected_id)
        if entry.view_ids:
            raise ValueError("cannot retire a document with live views")
        return self._remove(selected_id)

    def replace_document(
        self,
        document_id: str,
        replacement: Document,
        *,
        allow_path_change: bool = False,
    ) -> Document:
        """Atomically replace one authority while retaining its view bindings.

        ``allow_path_change`` permits the replacement to target a different
        path than the current authority — used when an untitled document is
        saved for the first time to a real destination — and clears
        ``is_untitled`` once that happens.
        """

        if not isinstance(replacement, Document):
            raise TypeError("replacement must be a Document")
        entry = self.get(document_id)
        if id(replacement) in self._documents:
            raise DuplicateDocumentError("replacement document is already owned")
        canonical_path = normalize_native_path(replacement.path).path
        path_changed = not native_paths_equal(canonical_path, entry.canonical_path)
        if path_changed and not allow_path_change:
            raise DuplicateDocumentError("replacement path does not match the authority")
        if path_changed:
            existing = self.find_path(canonical_path)
            if existing is not None and existing is not entry:
                raise DuplicateDocumentError(
                    f"document path is already owned by {existing.document_id}"
                )
        original = entry.document
        self._documents.pop(id(original), None)
        self._documents[id(replacement)] = entry.document_id
        entry.document = replacement
        entry.canonical_path = canonical_path
        entry.saved_stamp = None
        entry.last_active_at = _datetime(self._clock(), "clock result")
        if path_changed:
            entry.is_untitled = False
        original.close()
        return original

    def close_all(self) -> None:
        """Close every owned document during final service teardown."""

        for document_id in tuple(self._entries):
            self._remove(document_id)


__all__ = [
    "CLOSED_HISTORY_RETENTION",
    "DocumentEntry",
    "DocumentRegistry",
    "DuplicateDocumentError",
]
