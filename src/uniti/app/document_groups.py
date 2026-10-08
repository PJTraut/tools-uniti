"""Qt-free document group (tag) profiles and their atomic storage."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import json
from pathlib import Path
import re

from .atomic_json import atomic_write_json


MAX_GROUPS = 32
MAX_NAME_LENGTH = 64
MAX_BYTES = 64 * 1024

_COLOR_RE = re.compile(r'#[0-9a-fA-F]{6}')
_ID_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')

DEFAULT_GROUPS = (
    ('A', 'A', '#e06c75'),
    ('B', 'B', '#61afef'),
    ('C', 'C', '#98c379'),
)


@dataclass(frozen=True, slots=True)
class DocumentGroup:
    id: str
    name: str
    color: str
    saved_paths: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID_RE.fullmatch(self.id):
            raise ValueError('Group id must be 1-64 letters, digits, underscores or hyphens')
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > MAX_NAME_LENGTH or not self.name.isprintable():
            raise ValueError(f'Group name must be 1-{MAX_NAME_LENGTH} printable characters')
        if not isinstance(self.color, str) or not _COLOR_RE.fullmatch(self.color):
            raise ValueError('Group color must use #RRGGBB format')
        if not isinstance(self.saved_paths, tuple) or not all(
            isinstance(path, str) and path for path in self.saved_paths
        ):
            raise ValueError('Group saved paths must be a tuple of nonempty strings')
        object.__setattr__(self, 'color', self.color.lower())

    def as_dict(self) -> dict:
        return dict(
            id=self.id,
            name=self.name,
            color=self.color,
            saved_paths=list(self.saved_paths),
        )

    @classmethod
    def from_dict(cls, payload: object) -> 'DocumentGroup':
        allowed_keys = {'id', 'name', 'color', 'saved_paths'}
        required_keys = {'id', 'name', 'color'}
        if (
            not isinstance(payload, dict)
            or not required_keys <= set(payload)
            or set(payload) - allowed_keys
        ):
            raise ValueError('Invalid document group keys')
        saved_paths = payload.get('saved_paths', [])
        if not isinstance(saved_paths, list) or not all(
            isinstance(path, str) for path in saved_paths
        ):
            raise ValueError('Invalid document group keys')
        return cls(
            id=payload['id'],
            name=payload['name'],
            color=payload['color'],
            saved_paths=tuple(saved_paths),
        )


def default_groups() -> tuple[DocumentGroup, ...]:
    return tuple(DocumentGroup(*fields) for fields in DEFAULT_GROUPS)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


def _validate(groups: tuple[DocumentGroup, ...]) -> None:
    if len(groups) > MAX_GROUPS:
        raise ValueError(f'At most {MAX_GROUPS} document groups are supported')
    if len({group.id for group in groups}) != len(groups):
        raise ValueError('Document group ids must be unique')
    for group in groups:
        DocumentGroup.from_dict(group.as_dict())


class DocumentGroupStore:
    """Document groups are published in ONE atomic JSON replacement.

    Old settings remain the fallback for first use or a damaged file. Loading
    never repairs/writes a damaged file; an explicit save may replace it.
    """

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> tuple[DocumentGroup, ...]:
        try:
            with self.path.open('rb') as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError(f'Document group file exceeds {MAX_BYTES // 1024} KiB')
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if (
                not isinstance(payload, dict)
                or set(payload) != {'schema', 'groups'}
                or type(payload['schema']) is not int
                or payload['schema'] != 1
            ):
                raise ValueError('Unsupported document group schema')
            if not isinstance(payload['groups'], list) or len(payload['groups']) > MAX_GROUPS:
                raise ValueError(f'At most {MAX_GROUPS} document groups are supported')
            groups = tuple(DocumentGroup.from_dict(item) for item in payload['groups'])
            _validate(groups)
            return groups
        except FileNotFoundError:
            return default_groups()
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            return default_groups()

    def save(self, groups: tuple[DocumentGroup, ...]):
        _validate(groups)
        payload = dict(schema=1, groups=[group.as_dict() for group in groups])
        encoded = (
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n'
        ).encode('utf-8')
        if len(encoded) > MAX_BYTES:
            raise ValueError(f'Document group file exceeds {MAX_BYTES // 1024} KiB')
        return atomic_write_json(self.path, payload)


GROUPS_FILE = 'groups.json'
LEGACY_ENVIRONMENT = 'plain_text'


class EnvironmentGroups:
    """Each environment's own document groups (field test round 3, T2).

    One `DocumentGroupStore` per environment, at `groups.json` in the folder
    `folder_for(environment_key)` names (the environment's user
    configuration folder); with no folder the groups live in memory only.
    A missing file starts from the defaults (A, B, C), except Plain Text's,
    which starts from the app-wide groups used before T2 (`legacy`, decision
    D3). The legacy file is left in place and no longer written.
    """

    def __init__(
        self,
        folder_for: Callable[[str], Path | None] | None = None,
        legacy: DocumentGroupStore | None = None,
    ) -> None:
        self._folder_for = folder_for
        self._legacy = legacy
        self._cache: dict[str, tuple[DocumentGroup, ...]] = {}

    def store(self, environment_key: str) -> DocumentGroupStore | None:
        folder = None if self._folder_for is None else self._folder_for(environment_key)
        return None if folder is None else DocumentGroupStore(Path(folder) / GROUPS_FILE)

    def groups(self, environment_key: str) -> tuple[DocumentGroup, ...]:
        cached = self._cache.get(environment_key)
        if cached is None:
            cached = self._cache[environment_key] = self._load(environment_key)
        return cached

    def _load(self, environment_key: str) -> tuple[DocumentGroup, ...]:
        store = self.store(environment_key)
        if store is not None and store.path.exists():
            return store.load()
        if environment_key == LEGACY_ENVIRONMENT and self._legacy is not None:
            return self._legacy.load()
        return default_groups()

    def save(self, environment_key: str, groups: tuple[DocumentGroup, ...]) -> None:
        """Validate, persist and remember `environment_key`'s groups."""

        groups = tuple(groups)
        _validate(groups)
        store = self.store(environment_key)
        if store is not None:
            store.path.parent.mkdir(parents=True, exist_ok=True)
            store.save(groups)
        self._cache[environment_key] = groups

    def set_cached(self, environment_key: str, groups: tuple[DocumentGroup, ...]) -> None:
        """Replace the in-memory groups without writing them."""

        self._cache[environment_key] = tuple(groups)

    def group(self, environment_key: str, group_id: str | None) -> DocumentGroup | None:
        if group_id is None:
            return None
        return next((group for group in self.groups(environment_key) if group.id == group_id), None)


PROJECTS_FILE = 'projects.json'
MAX_PROJECTS = 4096


class ProjectGroups:
    """Which group each project is in (field test round 3, T5).

    In a project environment (USFM) a group belongs to a project, not to a
    book: every book of the project is in it. Stored per environment as
    `projects.json` next to its `groups.json`, keyed by project folder;
    nothing is written into a project folder. With no folder the
    assignments live in memory only.
    """

    def __init__(self, folder_for: Callable[[str], Path | None] | None = None) -> None:
        self._folder_for = folder_for
        self._cache: dict[str, dict[str, str]] = {}

    @staticmethod
    def _key(folder: Path | str) -> str:
        try:
            return str(Path(folder).resolve())
        except OSError:
            return str(Path(folder))

    def path(self, environment_key: str) -> Path | None:
        folder = None if self._folder_for is None else self._folder_for(environment_key)
        return None if folder is None else Path(folder) / PROJECTS_FILE

    def _assignments(self, environment_key: str) -> dict[str, str]:
        cached = self._cache.get(environment_key)
        if cached is None:
            cached = self._cache[environment_key] = self._load(environment_key)
        return cached

    def group(self, environment_key: str, folder: Path | str) -> str | None:
        return self._assignments(environment_key).get(self._key(folder))

    def set(self, environment_key: str, folder: Path | str, group_id: str | None) -> None:
        assignments = dict(self._assignments(environment_key))
        key = self._key(folder)
        if group_id is None:
            assignments.pop(key, None)
        else:
            if not _ID_RE.fullmatch(group_id):
                raise ValueError('Group id must be 1-64 letters, digits, underscores or hyphens')
            assignments[key] = group_id
        if len(assignments) > MAX_PROJECTS:
            raise ValueError(f'At most {MAX_PROJECTS} project groups are supported')
        self._save(environment_key, assignments)

    def forget_groups(self, environment_key: str, group_ids) -> None:
        """Groups were removed: their projects are ungrouped."""

        removed = set(group_ids)
        assignments = self._assignments(environment_key)
        kept = {folder: group for folder, group in assignments.items() if group not in removed}
        if kept != assignments:
            self._save(environment_key, kept)

    def _save(self, environment_key: str, assignments: dict[str, str]) -> None:
        path = self.path(environment_key)
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, dict(schema=1, projects=dict(sorted(assignments.items()))))
        self._cache[environment_key] = assignments

    def _load(self, environment_key: str) -> dict[str, str]:
        path = self.path(environment_key)
        if path is None:
            return {}
        try:
            with path.open('rb') as handle:
                raw = handle.read(MAX_BYTES * 4 + 1)
            if len(raw) > MAX_BYTES * 4:
                return {}
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict) or payload.get('schema') != 1 or not isinstance(payload.get('projects'), dict):
                return {}
            return {
                str(folder): group
                for folder, group in payload['projects'].items()
                if isinstance(group, str) and _ID_RE.fullmatch(group)
            }
        except FileNotFoundError:
            return {}
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError):
            # A damaged file leaves projects ungrouped; it isn't rewritten.
            return {}
