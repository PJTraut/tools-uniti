import pytest

from uniti.app.commands import (
    CommandCategory,
    CommandDefinition,
    CommandRegistry,
    CommandScope,
    ShortcutCollision,
)


def _registry() -> CommandRegistry:
    return CommandRegistry(
        (
            CommandDefinition(
                "file.open", "Open", CommandCategory.FILE, CommandScope.WINDOW, "Ctrl+O"
            ),
            CommandDefinition(
                "editor.zoom_in",
                "Zoom In",
                CommandCategory.EDITOR_VIEW,
                CommandScope.EDITOR,
                "Ctrl++",
            ),
            CommandDefinition(
                "editor.zoom_out",
                "Zoom Out",
                CommandCategory.EDITOR_VIEW,
                CommandScope.EDITOR,
                "Ctrl+-",
            ),
            CommandDefinition(
                "find.zoom_in",
                "Zoom In",
                CommandCategory.FIND_REPLACE_VIEW,
                CommandScope.FIND_REPLACE,
                "Ctrl++",
            ),
        )
    )


def test_same_shortcut_is_allowed_in_disjoint_editor_and_find_scopes():
    registry = _registry()

    registry.assign("editor.zoom_in", "Ctrl+K")
    registry.assign("find.zoom_in", "Ctrl+K")

    assert registry.current("editor.zoom_in") == "Ctrl+K"
    assert registry.current("find.zoom_in") == "Ctrl+K"


def test_collision_in_overlapping_scope_is_rejected_without_mutation():
    registry = _registry()
    registry.assign("editor.zoom_in", "Ctrl+K")

    with pytest.raises(ShortcutCollision) as error:
        registry.assign("editor.zoom_out", "Ctrl+K")

    assert error.value.conflicting_command_id == "editor.zoom_in"
    assert registry.current("editor.zoom_out") == "Ctrl+-"


def test_clear_and_resets_update_only_override_state():
    registry = _registry()
    registry.assign("editor.zoom_in", "Ctrl+K")
    registry.clear("editor.zoom_out")
    registry.assign("file.open", "Ctrl+Shift+O")
    assert registry.overrides == {
        "editor.zoom_in": "Ctrl+K",
        "editor.zoom_out": "",
        "file.open": "Ctrl+Shift+O",
    }

    registry.reset("editor.zoom_in")
    assert registry.current("editor.zoom_in") == "Ctrl++"
    registry.reset_category(CommandCategory.EDITOR_VIEW)
    assert registry.current("editor.zoom_out") == "Ctrl+-"
    assert registry.current("file.open") == "Ctrl+Shift+O"
    registry.reset_all()
    assert registry.overrides == {}


def test_unknown_command_and_empty_definition_set_are_rejected():
    with pytest.raises(ValueError, match="at least one"):
        CommandRegistry(())
    with pytest.raises(KeyError):
        _registry().assign("missing", "Ctrl+M")


def test_registry_keeps_portable_override_strings_without_qt_presentation():
    registry = _registry()

    registry.assign("editor.zoom_in", "Meta+K")

    assert registry.current("editor.zoom_in") == "Meta+K"
    assert registry.overrides == {"editor.zoom_in": "Meta+K"}
