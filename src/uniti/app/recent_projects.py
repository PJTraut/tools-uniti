"""Qt-free Recent Projects list and its atomic storage (ADR-0018).

The one piece of project state UNITI keeps: which Paratext project folders
were opened, most recent first, and where each was left (book, chapter:verse,
document group). Nothing is ever written into a project folder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path

from .atomic_json import atomic_write_json

MAX_RECENT_PROJECTS = 20
MAX_PATH_LENGTH = 4096
MAX_TEXT_LENGTH = 256
MAX_BYTES = 64 * 1024
_FIELDS = {"folder", "name", "group_id", "book", "reference"}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key: " + key)
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class RecentProject:
    folder: str
    name: str
    group_id: str | None = None
    book: str | None = None  # book code, e.g. "GEN"
    reference: str | None = None  # "chapter:verse" or "chapter"

    def as_dict(self) -> dict:
        return dict(folder=self.folder, name=self.name, group_id=self.group_id, book=self.book, reference=self.reference)

    @classmethod
    def from_payload(cls, payload: object) -> "RecentProject":
        if not isinstance(payload, dict) or set(payload) != _FIELDS:
            raise ValueError("Invalid recent project entry")
        if not isinstance(payload["folder"], str) or not isinstance(payload["name"], str):
            raise ValueError("Invalid recent project entry")
        for key in ("group_id", "book", "reference"):
            if payload[key] is not None and not isinstance(payload[key], str):
                raise ValueError("Invalid recent project entry")
        return cls(**payload)


def _validate(entries: tuple[RecentProject, ...]) -> None:
    if len(entries) > MAX_RECENT_PROJECTS:
        raise ValueError(f"At most {MAX_RECENT_PROJECTS} recent projects are supported")
    for entry in entries:
        if not isinstance(entry, RecentProject):
            raise TypeError("entries must be RecentProject instances")
        if not entry.folder or len(entry.folder) > MAX_PATH_LENGTH:
            raise ValueError("Recent project folder must be a non-empty string")
        for value in (entry.name, entry.group_id, entry.book, entry.reference):
            if value is not None and len(value) > MAX_TEXT_LENGTH:
                raise ValueError("Recent project field is too long")


class RecentProjectsStore:
    """Published in ONE atomic JSON replacement, most recent first. Loading
    never repairs or writes a damaged file; it reads as empty."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[RecentProject, ...]:
        try:
            with self.path.open("rb") as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError("Recent projects file is too large")
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if (
                not isinstance(payload, dict)
                or set(payload) != {"schema", "projects"}
                or type(payload["schema"]) is not int
                or payload["schema"] != 1
                or not isinstance(payload["projects"], list)
            ):
                raise ValueError("Unsupported recent projects schema")
            entries = tuple(RecentProject.from_payload(item) for item in payload["projects"])
            _validate(entries)
            return entries
        except FileNotFoundError:
            return ()
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            return ()

    def save(self, entries: tuple[RecentProject, ...]):
        _validate(entries)
        return atomic_write_json(self.path, dict(schema=1, projects=[entry.as_dict() for entry in entries]))

    def find(self, folder: str | Path) -> RecentProject | None:
        key = str(folder)
        return next((entry for entry in self.load() if entry.folder == key), None)

    _KEEP = object()

    def record_opened(
        self,
        folder: str | Path,
        name: str,
        *,
        group_id: object = _KEEP,
        book: object = _KEEP,
        reference: object = _KEEP,
    ) -> RecentProject:
        """Move `folder` to the front (inserting it if new). Fields left out
        keep their remembered values; re-reads first so windows merge."""

        key = str(folder)
        entries = self.load()
        previous = next((entry for entry in entries if entry.folder == key), None)
        entry = previous or RecentProject(key, name)
        entry = _with(replace(entry, name=name), group_id=group_id, book=book, reference=reference)
        self.save((entry, *(item for item in entries if item.folder != key))[:MAX_RECENT_PROJECTS])
        return entry

    def update(
        self,
        folder: str | Path,
        *,
        group_id: object = _KEEP,
        book: object = _KEEP,
        reference: object = _KEEP,
    ) -> None:
        """Change where a listed project was left, keeping its position."""

        key = str(folder)
        entries = self.load()
        updated = tuple(
            _with(entry, group_id=group_id, book=book, reference=reference) if entry.folder == key else entry
            for entry in entries
        )
        if updated != entries:
            self.save(updated)

    def clear(self) -> None:
        self.save(())


def _with(entry: RecentProject, **fields: object) -> RecentProject:
    changes = {key: value for key, value in fields.items() if value is not RecentProjectsStore._KEEP}
    return replace(entry, **changes) if changes else entry


__all__ = ["MAX_RECENT_PROJECTS", "RecentProject", "RecentProjectsStore"]
