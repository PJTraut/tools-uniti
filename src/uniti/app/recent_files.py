"""Qt-free recent-files list and its atomic storage (BF-058, BF-082)."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from .atomic_json import atomic_write_json

MAX_RECENT_FILES = 50
MAX_PATH_LENGTH = 4096
MAX_BYTES = 64 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


@dataclass(frozen=True, slots=True)
class RecentFileEntry:
    """One recently-opened path and the DocumentGroup it last carried."""

    path: str
    group_id: str | None = None

    def as_dict(self) -> dict:
        return dict(path=self.path, group_id=self.group_id)

    @classmethod
    def from_payload(cls, payload: object) -> 'RecentFileEntry':
        # Backward compatible: files written before BF-082 store a bare path.
        if isinstance(payload, str):
            return cls(path=payload)
        if (
            not isinstance(payload, dict)
            or set(payload) != {'path', 'group_id'}
            or not isinstance(payload['path'], str)
            or not (payload['group_id'] is None or isinstance(payload['group_id'], str))
        ):
            raise ValueError('Invalid recent file entry')
        return cls(path=payload['path'], group_id=payload['group_id'])


def _validate(entries: tuple[RecentFileEntry, ...]) -> None:
    if len(entries) > MAX_RECENT_FILES:
        raise ValueError(f'At most {MAX_RECENT_FILES} recent files are supported')
    for entry in entries:
        if not isinstance(entry, RecentFileEntry):
            raise TypeError('entries must be RecentFileEntry instances')
        if not entry.path or len(entry.path) > MAX_PATH_LENGTH:
            raise ValueError('Recent file path must be a non-empty string')


class RecentFilesStore:
    """Recent files are published in ONE atomic JSON replacement, most-recent
    first. Old settings remain the fallback for first use or a damaged file.
    Loading never repairs/writes a damaged file; an explicit save may
    replace it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load_entries(self) -> tuple[RecentFileEntry, ...]:
        try:
            with self.path.open('rb') as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError(f'Recent files file exceeds {MAX_BYTES // 1024} KiB')
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if (
                not isinstance(payload, dict)
                or set(payload) != {'schema', 'paths'}
                or type(payload['schema']) is not int
                or payload['schema'] != 1
            ):
                raise ValueError('Unsupported recent files schema')
            if not isinstance(payload['paths'], list) or len(payload['paths']) > MAX_RECENT_FILES:
                raise ValueError(f'At most {MAX_RECENT_FILES} recent files are supported')
            entries = tuple(RecentFileEntry.from_payload(item) for item in payload['paths'])
            _validate(entries)
            return entries
        except FileNotFoundError:
            return ()
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            return ()

    def load(self) -> tuple[str, ...]:
        return tuple(entry.path for entry in self.load_entries())

    def save_entries(self, entries: tuple[RecentFileEntry, ...]):
        _validate(entries)
        payload = dict(schema=1, paths=[entry.as_dict() for entry in entries])
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError(f'Recent files file exceeds {MAX_BYTES // 1024} KiB')
        return atomic_write_json(self.path, payload)

    def save(self, paths: tuple[str, ...]):
        self.save_entries(tuple(RecentFileEntry(path=path) for path in paths))

    def record_opened(
        self, path: str | Path, *, group_id: str | None = None
    ) -> tuple[str, ...]:
        """Move `path` to the front of the list (inserting it if new),
        re-reading from disk first so concurrently-opened windows merge
        rather than clobber each other, then persist and return the result.
        `group_id` is recorded only when given; otherwise an existing
        entry's previously-known group is preserved.
        """

        normalized = str(path)
        entries = self.load_entries()
        previous_group = next(
            (entry.group_id for entry in entries if entry.path == normalized), None
        )
        resolved_group = group_id if group_id is not None else previous_group
        existing = [entry for entry in entries if entry.path != normalized]
        updated = (RecentFileEntry(normalized, resolved_group), *existing)[:MAX_RECENT_FILES]
        self.save_entries(updated)
        return tuple(entry.path for entry in updated)

    def record_group(self, path: str | Path, group_id: str | None) -> None:
        """Update the DocumentGroup remembered for an already-recorded path
        (BF-082), so reopening it via Recent Files can restore the tag. A
        path not yet in the list is left untouched."""

        normalized = str(path)
        entries = self.load_entries()
        updated = tuple(
            RecentFileEntry(entry.path, group_id) if entry.path == normalized else entry
            for entry in entries
        )
        if updated != entries:
            self.save_entries(updated)

    def clear(self) -> tuple[str, ...]:
        self.save_entries(())
        return ()
