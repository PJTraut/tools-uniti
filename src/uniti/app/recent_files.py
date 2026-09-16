"""Qt-free recent-files list and its atomic storage (BF-058)."""
from __future__ import annotations

import json
from pathlib import Path

from .atomic_json import atomic_write_json

MAX_RECENT_FILES = 10
MAX_PATH_LENGTH = 4096
MAX_BYTES = 64 * 1024


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _validate(paths: tuple[str, ...]) -> None:
    if len(paths) > MAX_RECENT_FILES:
        raise ValueError(f'At most {MAX_RECENT_FILES} recent files are supported')
    for path in paths:
        if not isinstance(path, str) or not path or len(path) > MAX_PATH_LENGTH:
            raise ValueError('Recent file path must be a non-empty string')


class RecentFilesStore:
    """Recent files are published in ONE atomic JSON replacement, most-recent
    first. Old settings remain the fallback for first use or a damaged file.
    Loading never repairs/writes a damaged file; an explicit save may
    replace it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[str, ...]:
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
            paths = tuple(payload['paths'])
            _validate(paths)
            return paths
        except FileNotFoundError:
            return ()
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            return ()

    def save(self, paths: tuple[str, ...]):
        _validate(paths)
        payload = dict(schema=1, paths=list(paths))
        encoded = (json.dumps(payload, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError(f'Recent files file exceeds {MAX_BYTES // 1024} KiB')
        return atomic_write_json(self.path, payload)

    def record_opened(self, path: str | Path) -> tuple[str, ...]:
        """Move `path` to the front of the list (inserting it if new),
        re-reading from disk first so concurrently-opened windows merge
        rather than clobber each other, then persist and return the result.
        """

        normalized = str(path)
        existing = [entry for entry in self.load() if entry != normalized]
        updated = tuple([normalized, *existing][:MAX_RECENT_FILES])
        self.save(updated)
        return updated

    def clear(self) -> tuple[str, ...]:
        self.save(())
        return ()
