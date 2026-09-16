"""Small atomic JSON settings store for UNITI."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

from uniti.core.durability import DurabilityResult

from .atomic_json import atomic_write_json, preserve_invalid
from .inspection_shortcut import DEFAULT_INSPECTION_MODIFIERS, normalize_inspection_modifiers

SETTINGS_SCHEMA = 5
MIN_EDITOR_TAB_WIDTH = 1
MAX_EDITOR_TAB_WIDTH = 16
DEFAULT_EDITOR_TAB_WIDTH = 4
# Qt's nine named QFont::Weight values (Thin..Black); duplicated here rather
# than imported from `uniti.ui.text_view` so this module stays Qt-free.
FONT_WEIGHT_STEPS = (100, 200, 300, 400, 500, 600, 700, 800, 900)
DEFAULT_EDITOR_FONT_WEIGHT = 400


class UnsupportedSettingsSchema(ValueError):
    """Raised when settings belong to a newer UNITI schema."""


@dataclass(frozen=True, slots=True)
class Settings:
    last_directory: str | None = None
    performance_mode: str = "Automatic"
    editor_zoom_percent: int = 100
    editor_font_weight: int = 400
    soft_wrap: bool = False
    theme_mode: str = "System"
    theme_contrast: str = "Standard"
    whitespace_mode: str = "off"
    whitespace_inspect_modifiers: str = DEFAULT_INSPECTION_MODIFIERS
    editor_tab_width: int = DEFAULT_EDITOR_TAB_WIDTH
    find_replace_zoom_percent: int = 100
    find_replace_report_location: str = "Right"
    find_replace_geometry: tuple[int, int, int, int] | None = None
    shortcut_overrides: dict[str, str] = field(default_factory=dict)
    syntax_extension_overrides: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SettingsPreparation:
    migrated: bool
    preserved_path: Path | None
    settings: Settings


def _settings_from_payload(payload: object) -> Settings:
    if not isinstance(payload, dict):
        raise ValueError("settings must be a JSON object")
    schema = payload.get("schema", 0)
    if not isinstance(schema, int) or isinstance(schema, bool) or schema < 0:
        raise ValueError("settings schema must be a non-negative integer")
    if schema > SETTINGS_SCHEMA:
        raise UnsupportedSettingsSchema(f"unsupported settings schema {schema}")
    last_directory = payload.get("last_directory")
    if last_directory is not None and not isinstance(last_directory, str):
        last_directory = None
    performance_mode = payload.get("performance_mode", "Automatic")
    if performance_mode not in {"Conservative", "Automatic", "Maximum Performance"}:
        performance_mode = "Automatic"
    editor_zoom_percent = payload.get("editor_zoom_percent", 100)
    if (
        not isinstance(editor_zoom_percent, int)
        or isinstance(editor_zoom_percent, bool)
        or not 50 <= editor_zoom_percent <= 300
    ):
        editor_zoom_percent = 100
    editor_font_weight = payload.get("editor_font_weight", DEFAULT_EDITOR_FONT_WEIGHT)
    if (
        not isinstance(editor_font_weight, int)
        or isinstance(editor_font_weight, bool)
        or editor_font_weight not in FONT_WEIGHT_STEPS
    ):
        editor_font_weight = DEFAULT_EDITOR_FONT_WEIGHT
    soft_wrap = payload.get("soft_wrap", False)
    if not isinstance(soft_wrap, bool):
        soft_wrap = False
    theme_mode = payload.get("theme_mode", "System")
    if theme_mode not in {"System", "Light", "Dark"}:
        theme_mode = "System"
    theme_contrast = payload.get("theme_contrast", "Standard")
    if theme_contrast not in {"Standard", "High Contrast"}:
        theme_contrast = "Standard"
    whitespace_mode = payload.get("whitespace_mode", "off")
    if whitespace_mode not in {
        "off",
        "eol",
        "spaces_tabs",
        "invisible_unicode",
        "all",
    }:
        whitespace_mode = "off"
    try:
        inspection_modifiers = normalize_inspection_modifiers(
            payload.get("whitespace_inspect_modifiers", DEFAULT_INSPECTION_MODIFIERS)
        )
    except (TypeError, ValueError):
        inspection_modifiers = DEFAULT_INSPECTION_MODIFIERS
    editor_tab_width = payload.get("editor_tab_width", DEFAULT_EDITOR_TAB_WIDTH)
    if (
        not isinstance(editor_tab_width, int)
        or isinstance(editor_tab_width, bool)
        or not MIN_EDITOR_TAB_WIDTH <= editor_tab_width <= MAX_EDITOR_TAB_WIDTH
    ):
        editor_tab_width = DEFAULT_EDITOR_TAB_WIDTH
    find_replace_zoom_percent = payload.get("find_replace_zoom_percent", 100)
    if (
        not isinstance(find_replace_zoom_percent, int)
        or isinstance(find_replace_zoom_percent, bool)
        or not 50 <= find_replace_zoom_percent <= 300
    ):
        find_replace_zoom_percent = 100
    find_replace_report_location = payload.get(
        "find_replace_report_location", "Right"
    )
    if find_replace_report_location == "Bottom":
        find_replace_report_location = "Right"
    elif find_replace_report_location not in {"Hidden", "Right"}:
        find_replace_report_location = "Right"
    geometry = payload.get("find_replace_geometry")
    if (
        not isinstance(geometry, (list, tuple))
        or len(geometry) != 4
        or any(not isinstance(value, int) or isinstance(value, bool) for value in geometry)
        or geometry[2] <= 0
        or geometry[3] <= 0
    ):
        find_replace_geometry = None
    else:
        find_replace_geometry = tuple(geometry)
    raw_shortcut_overrides = payload.get("shortcut_overrides", {})
    if not isinstance(raw_shortcut_overrides, dict):
        shortcut_overrides = {}
    else:
        shortcut_overrides = {
            command_id: shortcut
            for command_id, shortcut in raw_shortcut_overrides.items()
            if isinstance(command_id, str) and isinstance(shortcut, str)
        }
    raw_syntax_extension_overrides = payload.get("syntax_extension_overrides", {})
    if not isinstance(raw_syntax_extension_overrides, dict):
        syntax_extension_overrides = {}
    else:
        syntax_extension_overrides = {
            extension: profile_key
            for extension, profile_key in raw_syntax_extension_overrides.items()
            if isinstance(extension, str) and isinstance(profile_key, str)
        }
    return Settings(
        last_directory=last_directory,
        performance_mode=performance_mode,
        editor_zoom_percent=editor_zoom_percent,
        editor_font_weight=editor_font_weight,
        soft_wrap=soft_wrap,
        theme_mode=theme_mode,
        theme_contrast=theme_contrast,
        whitespace_mode=whitespace_mode,
        whitespace_inspect_modifiers=inspection_modifiers,
        editor_tab_width=editor_tab_width,
        find_replace_zoom_percent=find_replace_zoom_percent,
        find_replace_report_location=find_replace_report_location,
        find_replace_geometry=find_replace_geometry,
        shortcut_overrides=shortcut_overrides,
        syntax_extension_overrides=syntax_extension_overrides,
    )


def _payload(settings: Settings) -> dict[str, object]:
    return {"schema": SETTINGS_SCHEMA, **asdict(settings)}


class SettingsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @property
    def theme_profiles(self):
        """The separate atomic authority for profile definitions and selection."""
        from .theme_profiles import ThemeProfileStore
        return ThemeProfileStore(self.path.with_name("theme-profiles.json"))

    @property
    def document_groups(self):
        """The separate atomic authority for document group (tag) definitions."""
        from .document_groups import DocumentGroupStore
        return DocumentGroupStore(self.path.with_name("document-groups.json"))

    @property
    def find_replace_recipes(self):
        """The separate atomic authority for saved Find/Replace recipes."""
        from .find_replace_recipes import FindReplaceRecipeStore
        return FindReplaceRecipeStore(self.path.with_name("find-replace-recipes.json"))

    def load(self) -> Settings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return _settings_from_payload(payload)
        except UnsupportedSettingsSchema:
            raise
        except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            return Settings()

    def prepare(self) -> SettingsPreparation:
        if not self.path.exists():
            settings = Settings()
            self.save(settings)
            return SettingsPreparation(True, None, settings)
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            settings = _settings_from_payload(payload)
        except UnsupportedSettingsSchema:
            raise
        except (UnicodeError, json.JSONDecodeError, TypeError, ValueError):
            preserved = preserve_invalid(self.path)
            settings = Settings()
            self.save(settings)
            return SettingsPreparation(True, preserved, settings)
        schema = payload.get("schema", 0)
        migrated = schema < SETTINGS_SCHEMA
        if migrated:
            self.save(settings)
        return SettingsPreparation(migrated, None, settings)

    def save(self, settings: Settings) -> DurabilityResult:
        return atomic_write_json(self.path, _payload(settings))
