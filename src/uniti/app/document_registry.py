"""Process-lifetime ownership of authoritative UNITI documents."""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from uniti.core.document import Document
from uniti.core.file_identity import SavedFileStamp


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


def _same_file(first: Path, second: Path) -> bool:
    if first == second:
        return True
    try:
        return os.path.samefile(first, second)
    except (FileNotFoundError, OSError):
        return False


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

    @property
    def count(self) -> int:
        return len(self._entries)

    @property
    def entries(self) -> tuple[DocumentEntry, ...]:
        """Return entries in stable adoption order."""

        return tuple(self._entries.values())

    def find_path(self, path: Path) -> DocumentEntry | None:
        candidate = Path(path).resolve(strict=False)
        for entry in self._entries.values():
            if _same_file(entry.canonical_path, candidate):
                return entry
        return None

    def adopt(
        self,
        document: Document,
        *,
        document_id: str | None = None,
        saved_stamp: SavedFileStamp | None = None,
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

        canonical_path = Path(document.path).resolve(strict=False)
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
        )
        self._entries[selected_id] = entry
        self._documents[id(document)] = selected_id
        return entry

    def get(self, document_id: str) -> DocumentEntry:
        return self._entries[_identifier(document_id, "document ID")]

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
        entry.document.close()
        return entry

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
