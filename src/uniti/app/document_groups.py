"""Qt-free document group (tag) profiles and their atomic storage."""
from __future__ import annotations

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

    def __post_init__(self) -> None:
        if not isinstance(self.id, str) or not _ID_RE.fullmatch(self.id):
            raise ValueError('Group id must be 1-64 letters, digits, underscores or hyphens')
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > MAX_NAME_LENGTH or not self.name.isprintable():
            raise ValueError(f'Group name must be 1-{MAX_NAME_LENGTH} printable characters')
        if not isinstance(self.color, str) or not _COLOR_RE.fullmatch(self.color):
            raise ValueError('Group color must use #RRGGBB format')
        object.__setattr__(self, 'color', self.color.lower())

    def as_dict(self) -> dict:
        return dict(id=self.id, name=self.name, color=self.color)

    @classmethod
    def from_dict(cls, payload: object) -> 'DocumentGroup':
        if not isinstance(payload, dict) or set(payload) != {'id', 'name', 'color'}:
            raise ValueError('Invalid document group keys')
        return cls(**payload)


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
