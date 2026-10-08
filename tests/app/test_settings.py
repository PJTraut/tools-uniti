import json
from pathlib import Path

import pytest

from uniti.app.document_groups import default_groups
from uniti.app.settings import (
    SETTINGS_SCHEMA,
    Settings,
    SettingsStore,
    UnsupportedSettingsSchema,
)
from uniti.core.durability import DurabilityLevel, DurabilityResult

FUTURE_SCHEMA = SETTINGS_SCHEMA + 1


def _file_synced(operation: str) -> DurabilityResult:
    return DurabilityResult(
        operation,
        DurabilityLevel.FILE_SYNCED,
        True,
        True,
        False,
        "directory_sync_unavailable",
    )


@pytest.fixture
def path(tmp_path: Path) -> Path:
    return tmp_path / "settings.json"


@pytest.fixture
def store(path: Path) -> SettingsStore:
    return SettingsStore(path)


def _write(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


# --- load / save basics -----------------------------------------------------


def test_settings_store_defaults_when_missing(store: SettingsStore):
    assert store.load() == Settings()


def test_settings_store_round_trips_and_replaces_atomically(tmp_path: Path):
    path = tmp_path / "config" / "settings.json"
    store = SettingsStore(path)
    settings = Settings(
        last_directory=str(tmp_path / "docs"),
        performance_mode="Maximum Performance",
        editor_zoom_percent=130,
        soft_wrap=True,
    )
    store.save(settings)
    assert store.load() == settings
    payload = _read(path)
    assert payload["schema"] == SETTINGS_SCHEMA
    assert payload["last_directory"] == str(tmp_path / "docs")
    assert payload["performance_mode"] == "Maximum Performance"
    assert payload["editor_zoom_percent"] == 130
    assert payload["soft_wrap"] is True
    assert not list(path.parent.glob("*.tmp"))


def test_settings_save_exposes_file_synced_durability(store: SettingsStore, monkeypatch):
    expected = _file_synced("atomic_write_json")
    monkeypatch.setattr(
        "uniti.app.settings.atomic_write_json",
        lambda _path, _payload: expected,
    )

    assert store.save(Settings()) is expected


def test_settings_store_ignores_unknown_keys_for_forward_compatibility(
    path: Path, store: SettingsStore
):
    _write(path, {"last_directory": "/tmp", "future": 42})
    assert store.load().last_directory == "/tmp"


@pytest.mark.parametrize(
    "raw",
    [
        "not-json",
        "[]",
        '{"schema":-1}',
        '{"schema":"5"}',
        '{"schema":true}',
    ],
    ids=["not-json", "not-object", "negative-schema", "string-schema", "bool-schema"],
)
def test_settings_store_unreadable_payload_falls_back_to_defaults(
    path: Path, store: SettingsStore, raw: str
):
    path.write_text(raw, encoding="utf-8")
    assert store.load() == Settings()


def test_load_refuses_future_schema(path: Path, store: SettingsStore):
    _write(path, {"schema": FUTURE_SCHEMA})
    with pytest.raises(UnsupportedSettingsSchema, match=f"schema {FUTURE_SCHEMA}"):
        store.load()


# --- per-field validation ---------------------------------------------------


def test_settings_reject_invalid_editor_view_state(path: Path, store: SettingsStore):
    _write(path, {"schema": 1, "editor_zoom_percent": 999, "soft_wrap": "yes"})

    settings = store.load()

    assert settings.editor_zoom_percent == 100
    assert settings.soft_wrap is False


def test_invalid_scalar_fields_fall_back_to_defaults(path: Path, store: SettingsStore):
    _write(
        path,
        {
            "schema": SETTINGS_SCHEMA,
            "last_directory": 42,
            "performance_mode": "Turbo",
            "find_replace_geometry": [0, 0, 0, 100],
        },
    )

    settings = store.load()

    assert settings.last_directory is None
    assert settings.performance_mode == "Automatic"
    assert settings.find_replace_geometry is None


def test_editor_font_and_tab_width_round_trip(path: Path, store: SettingsStore):
    store.save(Settings(editor_font_weight=700, editor_tab_width=8))

    loaded = store.load()
    assert loaded.editor_font_weight == 700
    assert loaded.editor_tab_width == 8
    payload = _read(path)
    assert payload["editor_font_weight"] == 700
    assert payload["editor_tab_width"] == 8


@pytest.mark.parametrize("value", [0, -1, 350, "700", True, 700.0, 1000])
def test_editor_font_weight_rejects_values_outside_qts_nine_named_steps(
    path: Path, store: SettingsStore, value
):
    _write(path, {"schema": SETTINGS_SCHEMA, "editor_font_weight": value})
    assert store.load().editor_font_weight == 400


@pytest.mark.parametrize("value", [0, -1, 17, "4", True, 4.0])
def test_editor_tab_width_rejects_out_of_range_or_wrong_type_values(
    path: Path, store: SettingsStore, value
):
    _write(path, {"schema": SETTINGS_SCHEMA, "editor_tab_width": value})
    assert store.load().editor_tab_width == 4


def test_find_replace_view_state_round_trips(store: SettingsStore):
    expected = Settings(
        find_replace_zoom_percent=140,
        find_replace_report_location="Right",
        find_replace_geometry=(20, 30, 700, 360),
        find_replace_attached_height=220,
    )

    store.save(expected)

    assert store.load() == expected


@pytest.mark.parametrize("value", [0, -5, "220", True, 220.0])
def test_find_replace_attached_height_rejects_non_positive_or_wrong_type(
    path: Path, store: SettingsStore, value
):
    _write(path, {"schema": SETTINGS_SCHEMA, "find_replace_attached_height": value})
    assert store.load().find_replace_attached_height is None


def test_find_replace_report_zoom_percent_round_trip_and_rejects_malformed(
    path: Path, store: SettingsStore
):
    """BF-092: the Match Report's own font size, tracked independently of
    find_replace_zoom_percent (the input fields' own)."""

    expected = Settings(find_replace_report_zoom_percent=160)
    store.save(expected)
    assert store.load() == expected

    _write(path, {"schema": SETTINGS_SCHEMA, "find_replace_report_zoom_percent": 9999})
    assert store.load().find_replace_report_zoom_percent == 100


def test_legacy_bottom_report_setting_migrates_to_right(path: Path, store: SettingsStore):
    _write(path, {"schema": 1, "find_replace_report_location": "Bottom"})
    assert store.load().find_replace_report_location == "Right"


def test_toggle_window_geometry_and_zoom_round_trip(store: SettingsStore):
    """2026-09-20 request: remember each toggle window's (Character
    Inspector, Compare, ...) previous size and zoom level across reopens
    -- one generic, keyed mechanism rather than a dedicated pair of
    fields per window. BF-087 extends the same mechanism to a toggle
    window's own internal splitter position (only Character Inspector's
    list/detail split has one so far)."""

    expected = Settings(
        toggle_window_zoom_percent={"character_inspector": 150, "compare": 80},
        toggle_window_geometry={
            "character_inspector": (40, 60, 720, 480),
            "compare": (0, 0, 900, 600),
        },
        toggle_window_splitter_sizes={"character_inspector": (280, 420)},
    )

    store.save(expected)

    assert store.load() == expected


def test_toggle_window_geometry_and_zoom_reject_malformed_entries(
    path: Path, store: SettingsStore
):
    _write(
        path,
        {
            "schema": 1,
            "toggle_window_zoom_percent": {
                "character_inspector": 9999,
                "compare": 150,
                "bad": "nope",
            },
            "toggle_window_geometry": {
                "character_inspector": [1, 2, 3],
                "compare": [0, 0, 900, 600],
                "bad": "nope",
            },
            "toggle_window_splitter_sizes": {
                "character_inspector": [280, 0],
                "compare": [300, 400],
                "bad": "nope",
            },
        },
    )
    settings = store.load()
    assert settings.toggle_window_zoom_percent == {"compare": 150}
    assert settings.toggle_window_geometry == {"compare": (0, 0, 900, 600)}
    assert settings.toggle_window_splitter_sizes == {"compare": (300, 400)}


def test_theme_mode_round_trips_and_invalid_values_fall_back_to_system(
    path: Path, store: SettingsStore
):
    store.save(Settings(theme_mode="Dark"))
    assert store.load().theme_mode == "Dark"

    _write(path, {"schema": 1, "theme_mode": "Neon"})
    assert store.load().theme_mode == "System"


def test_invalid_new_fields_do_not_erase_valid_theme_mode(
    path: Path, store: SettingsStore
):
    _write(
        path,
        {
            "schema": 3,
            "theme_mode": "Light",
            "theme_contrast": "Extreme",
            "whitespace_mode": "everything",
        },
    )

    loaded = store.load()

    assert loaded.theme_mode == "Light"
    assert loaded.theme_contrast == "Standard"
    assert loaded.whitespace_mode == "off"


def test_shortcut_overrides_round_trip_and_invalid_entries_are_dropped(
    path: Path, store: SettingsStore
):
    store.save(Settings(shortcut_overrides={"editor.zoom_in": "Ctrl+K"}))
    assert store.load().shortcut_overrides == {"editor.zoom_in": "Ctrl+K"}

    # Only non-string values are dropped; shortcut text is validated later.
    _write(
        path,
        {
            "schema": 1,
            "shortcut_overrides": {
                "ok": " ctrl + k ",
                "invalid": "not a shortcut",
                "bad": 42,
            },
        },
    )
    assert store.load().shortcut_overrides == {
        "ok": " ctrl + k ",
        "invalid": "not a shortcut",
    }


def test_syntax_extension_overrides_round_trip_and_invalid_entries_are_dropped(
    path: Path, store: SettingsStore
):
    store.save(Settings(syntax_extension_overrides={"usj": "json"}))
    assert store.load().syntax_extension_overrides == {"usj": "json"}

    _write(
        path,
        {
            "schema": 1,
            "syntax_extension_overrides": {"ok": "xml", "bad": 42, "alsobad": None},
        },
    )
    assert store.load().syntax_extension_overrides == {"ok": "xml"}


# --- prepare / migration ----------------------------------------------------


def test_prepare_writes_defaults_when_missing(path: Path, store: SettingsStore):
    result = store.prepare()

    assert result.migrated is True
    assert result.preserved_path is None
    assert result.settings == Settings()
    assert _read(path)["schema"] == SETTINGS_SCHEMA


def test_prepare_leaves_current_schema_untouched(
    path: Path, store: SettingsStore, monkeypatch
):
    store.save(Settings(theme_mode="Dark"))
    writes: list[object] = []
    monkeypatch.setattr(
        "uniti.app.settings.atomic_write_json",
        lambda *_args, **_kwargs: writes.append(object()) or _file_synced("write"),
    )

    result = store.prepare()

    assert result.migrated is False
    assert result.settings.theme_mode == "Dark"
    assert writes == []


def test_prepare_migrates_legacy_settings_to_current_schema(
    path: Path, store: SettingsStore
):
    _write(path, {"last_directory": "/tmp", "performance_mode": "Automatic"})

    result = store.prepare()

    assert result.migrated is True
    assert result.preserved_path is None
    assert result.settings.last_directory == "/tmp"
    assert _read(path)["schema"] == SETTINGS_SCHEMA


def test_prepare_migrates_schema_one_panel_values_with_current_defaults(
    path: Path, store: SettingsStore
):
    _write(
        path,
        {
            "schema": 1,
            "find_replace_zoom_percent": 140,
            "find_replace_report_location": "Hidden",
            "find_replace_geometry": [20, 30, 700, 360],
        },
    )

    result = store.prepare()

    assert result.migrated is True
    assert result.settings.find_replace_zoom_percent == 140
    assert result.settings.find_replace_report_location == "Hidden"
    assert result.settings.find_replace_geometry == (20, 30, 700, 360)
    payload = _read(path)
    assert payload["schema"] == SETTINGS_SCHEMA
    assert payload["find_replace_zoom_percent"] == 140
    assert payload["find_replace_report_location"] == "Hidden"
    assert payload["find_replace_geometry"] == [20, 30, 700, 360]


def test_schema_two_settings_migrate_visibility_defaults(
    path: Path, store: SettingsStore
):
    _write(path, {"schema": 2, "theme_mode": "Dark"})

    prepared = store.prepare()

    assert prepared.migrated is True
    assert prepared.settings.theme_mode == "Dark"
    assert prepared.settings.theme_contrast == "Standard"
    assert prepared.settings.whitespace_mode == "off"
    assert _read(path)["schema"] == SETTINGS_SCHEMA


def test_prepare_preserves_malformed_before_writing_defaults(
    path: Path, store: SettingsStore
):
    path.write_text("broken", encoding="utf-8")

    result = store.prepare()

    assert result.migrated is True
    assert result.preserved_path is not None
    assert result.preserved_path.read_text(encoding="utf-8") == "broken"
    # Spelled out on purpose: this pins the on-disk format and every default.
    assert _read(path) == {
        "editor_zoom_percent": 100,
        "editor_font_weight": 400,
        "editor_tab_width": 4,
        "find_replace_geometry": None,
        "find_replace_attached_height": None,
        "find_replace_report_location": "Right",
        "find_replace_zoom_percent": 100,
        "find_replace_report_zoom_percent": 100,
        "toggle_window_geometry": {},
        "toggle_window_zoom_percent": {},
        "toggle_window_splitter_sizes": {},
        "read_only_folders": [],
        "last_directory": None,
        "performance_mode": "Automatic",
        "schema": 5,
        "shortcut_overrides": {},
        "soft_wrap": False,
        "syntax_extension_overrides": {},
        "grouped_tabs": False,
        "theme_contrast": "Standard",
        "theme_mode": "System",
        "whitespace_mode": "off",
    }


def test_prepare_refuses_future_schema_without_writing(
    path: Path, store: SettingsStore, monkeypatch
):
    original = json.dumps({"schema": FUTURE_SCHEMA, "last_directory": None})
    path.write_text(original, encoding="utf-8")
    writes: list[object] = []
    monkeypatch.setattr(
        "uniti.app.settings.atomic_write_json",
        lambda *_args, **_kwargs: writes.append(object()) or _file_synced("write"),
    )

    with pytest.raises(UnsupportedSettingsSchema, match=f"schema {FUTURE_SCHEMA}"):
        store.prepare()

    assert writes == []
    assert path.read_text(encoding="utf-8") == original


# --- sibling stores ---------------------------------------------------------


def test_theme_profiles_migrate_using_existing_mode_without_changing_settings(
    store: SettingsStore,
):
    store.save(Settings(theme_mode="Dark", soft_wrap=True))
    before = store.path.read_bytes()

    state = store.theme_profiles.load(store.load().theme_mode)

    assert state.active_id == "Dark"
    assert store.theme_profiles.path.parent == store.path.parent
    assert store.path.read_bytes() == before


@pytest.mark.parametrize(
    ("attr", "filename", "empty"),
    [
        ("document_groups", "document-groups.json", default_groups()),
        ("find_replace_recipes", "find-replace-recipes.json", ()),
        ("recent_files", "recent-files.json", ()),
    ],
)
def test_sibling_store_is_a_separate_atomic_file_beside_settings(
    store: SettingsStore, attr: str, filename: str, empty
):
    store.save(Settings(theme_mode="Dark", soft_wrap=True))
    before = store.path.read_bytes()
    sibling = getattr(store, attr)

    assert sibling.load() == empty
    assert sibling.path == store.path.with_name(filename)
    assert store.path.read_bytes() == before
