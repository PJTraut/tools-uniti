"""Immutable, Qt-free color profiles and their atomic selection authority."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from importlib.resources import files
import json
from pathlib import Path
import re
from types import MappingProxyType

from .atomic_json import atomic_write_json

BUILTIN_IDS = (
    'System', 'Light', 'Dark', 'Paper', 'Slate',
    'SolarizedDark', 'SolarizedLight', 'Monokai', 'Dracula', 'GruvboxDark', 'Nord',
)
# Packaged theme JSON filenames (in assets/themes/), in the order they're
# offered — the ids above match each file's own "id" field.
PACKAGED_THEME_FILES = (
    'paper', 'slate',
    'solarized_dark', 'solarized_light', 'monokai', 'dracula', 'gruvbox_dark', 'nord',
)
PALETTE_ROLES = ('Window', 'WindowText', 'Base', 'AlternateBase', 'ToolTipBase',
                 'ToolTipText', 'Text', 'Button', 'ButtonText', 'BrightText',
                 'Highlight', 'HighlightedText', 'Link', 'PlaceholderText')
EDITOR_ROLES = ('base', 'text', 'gutter_base', 'gutter_text', 'selection',
                'selected_text', 'match', 'current_match', 'invalid_byte',
                'space_marker', 'tab_marker', 'eol_marker', 'invisible_marker',
                'invisible_background', 'invisible_border')
# BF-063: matches `uniti.ui.syntax_theme`'s tokenizer categories exactly.
SYNTAX_ROLES = ('keyword', 'string', 'number', 'tag', 'attribute', 'heading',
                 'comment', 'punctuation')
COLOR_ROLES = tuple('palette.' + r for r in PALETTE_ROLES) + (
    'disabled.Text', 'disabled.WindowText', 'disabled.ButtonText',
) + tuple('editor.' + r for r in EDITOR_ROLES) + tuple('syntax.' + r for r in SYNTAX_ROLES)
MAX_PROFILES = 32
MAX_BYTES = 128 * 1024
# Schema 2 added the `syntax.*` roles above (BF-063); a schema-1 file on disk
# predates them entirely, not merely omits optional fields.
THEME_SCHEMA = 2


@dataclass(frozen=True, slots=True)
class ThemeProfile:
    id: str
    name: str
    base_mode: str
    colors: Mapping[str, str]

    def __post_init__(self):
        if not isinstance(self.id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', self.id):
            raise ValueError('Profile id must be 1–64 letters, digits, underscores or hyphens')
        if not isinstance(self.name, str) or not self.name.strip() or len(self.name) > 64 or not self.name.isprintable():
            raise ValueError('Profile name must be 1–64 printable characters')
        if self.base_mode not in ('Light', 'Dark'):
            raise ValueError('Profile base mode must be Light or Dark')
        if not isinstance(self.colors, Mapping) or set(self.colors) != set(COLOR_ROLES):
            raise ValueError('Profile must contain every supported color role and no other roles')
        if any(not isinstance(c, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', c) for c in self.colors.values()):
            raise ValueError('Colors must use #RRGGBB format')
        object.__setattr__(self, 'colors', MappingProxyType({k: v.lower() for k, v in self.colors.items()}))

    def as_dict(self):
        return dict(id=self.id, name=self.name, base_mode=self.base_mode, colors=dict(self.colors))

    @classmethod
    def from_dict(cls, payload, *, packaged=False):
        if not isinstance(payload, dict) or set(payload) != {'id', 'name', 'base_mode', 'colors'}:
            raise ValueError('Invalid profile keys')
        profile = cls(**payload)
        if not packaged and profile.id in BUILTIN_IDS:
            raise ValueError('Built-in profiles are read-only')
        return profile


def packaged_profiles() -> tuple[ThemeProfile, ...]:
    root = files('uniti.ui').joinpath('assets', 'themes')
    return tuple(ThemeProfile.from_dict(json.loads(root.joinpath(name + '.json').read_text(encoding='utf-8')), packaged=True)
                 for name in PACKAGED_THEME_FILES)


@dataclass(frozen=True, slots=True)
class ThemeProfileState:
    profiles: tuple[ThemeProfile, ...] = ()
    active_id: str = 'System'
    error: str | None = None

    def resolve(self) -> ThemeProfile | None:
        return next((p for p in (*packaged_profiles(), *self.profiles) if p.id == self.active_id), None)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key: ' + key)
        result[key] = value
    return result


class ThemeProfileStore:
    """profiles and active_id are published in ONE atomic JSON replacement.

    Old settings remain the fallback for first use or damaged files. Loading
    never repairs/writes damaged files; an explicit Apply may replace them.
    """
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self, fallback='System') -> ThemeProfileState:
        fallback = fallback if fallback in ('System', 'Light', 'Dark') else 'System'
        try:
            with self.path.open('rb') as handle:
                raw = handle.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise ValueError('Theme file exceeds 128 KiB')
            payload = json.loads(raw, object_pairs_hook=_unique_object)
            if not isinstance(payload, dict) or set(payload) != {'schema', 'profiles', 'active_id'} or type(payload['schema']) is not int or payload['schema'] not in (1, THEME_SCHEMA):
                raise ValueError('Unsupported theme profile schema')
            if not isinstance(payload['profiles'], list) or len(payload['profiles']) > MAX_PROFILES:
                raise ValueError('At most 32 custom profiles are supported')
            raw_profiles = payload['profiles']
            if payload['schema'] == 1:
                raw_profiles = [self._migrate_schema_1_profile(p) for p in raw_profiles]
            profiles = tuple(ThemeProfile.from_dict(p) for p in raw_profiles)
            self._validate(profiles)
            selected = payload['active_id']
            if not isinstance(selected, str):
                raise ValueError('Invalid selected profile')
            if selected not in (*BUILTIN_IDS, *(p.id for p in profiles)):
                return ThemeProfileState(profiles, fallback, 'Unknown selected theme; using ' + fallback)
            return ThemeProfileState(profiles, selected)
        except FileNotFoundError:
            return ThemeProfileState(active_id=fallback)
        except (OSError, UnicodeError, ValueError, TypeError, RecursionError) as exc:
            return ThemeProfileState(active_id=fallback, error=str(exc))

    @staticmethod
    def _validate(profiles):
        if len(profiles) > MAX_PROFILES or len({p.id for p in profiles}) != len(profiles):
            raise ValueError('At most 32 uniquely identified custom profiles are supported')
        for p in profiles:
            ThemeProfile.from_dict(p.as_dict())

    @staticmethod
    def _migrate_schema_1_profile(payload):
        """Freeze in schema 1's live-derived syntax colors (BF-063).

        A schema-1 file predates the `syntax.*` roles entirely, so this
        computes what `syntax_category_palette` would already have shown for
        that profile's own background and saves it as this profile's
        explicit starting colors — identical to today's look, editable from
        here on. `syntax_category_palette` needs a `QColor`, so Qt is
        imported here, deferred, rather than at module level: every other
        path through this otherwise Qt-free module (loading or saving a
        current-schema file) never needs it. If PySide6 isn't installed at
        all (this module's own Qt-free design allows that), the profile is
        left as-is and fails `ThemeProfile` validation normally, which
        `ThemeProfileStore.load()` already handles like any other damaged
        file — a graceful degradation, not a crash.
        """
        if not isinstance(payload, dict) or not isinstance(payload.get('colors'), dict):
            return payload
        colors = payload['colors']
        base = colors.get('editor.base')
        if not isinstance(base, str) or any(role in colors for role in COLOR_ROLES if role.startswith('syntax.')):
            return payload
        try:
            from PySide6.QtGui import QColor
            from uniti.ui.syntax_theme import syntax_category_palette
        except ImportError:
            return payload
        derived = syntax_category_palette(QColor(base))
        migrated = dict(colors)
        migrated.update({'syntax.' + role: derived[role].name() for role in SYNTAX_ROLES})
        return {**payload, 'colors': migrated}

    def save(self, profiles: tuple[ThemeProfile, ...], active_id: str):
        self._validate(profiles)
        if active_id not in (*BUILTIN_IDS, *(p.id for p in profiles)):
            raise ValueError('Unknown selected profile')
        payload = dict(schema=THEME_SCHEMA, profiles=[p.as_dict() for p in profiles], active_id=active_id)
        if len((json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode('utf-8')) > MAX_BYTES:
            raise ValueError('Theme file exceeds 128 KiB')
        return atomic_write_json(self.path, payload)
