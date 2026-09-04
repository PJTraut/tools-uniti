import pytest

from uniti.app.commands import (
    CommandCategory,
    CommandDefinition,
    CommandRegistry,
    CommandScope,
    PANE_COMMAND_DEFINITIONS,
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


def test_pane_and_multi_window_commands_have_stable_ids_and_scopes():
    assert tuple(item.command_id for item in PANE_COMMAND_DEFINITIONS) == (
        "window.new",
        "view.split_right",
        "view.split_down",
        "view.close_split",
        "view.move_new_window",
    )
    assert PANE_COMMAND_DEFINITIONS[0] == CommandDefinition(
        "window.new",
        "New Window",
        CommandCategory.FILE,
        CommandScope.WINDOW,
        "Ctrl+Shift+N",
    )
    assert all(
        item.category == CommandCategory.EDITOR_VIEW
        and item.scope == CommandScope.EDITOR
        and item.default_shortcut == ""
        for item in PANE_COMMAND_DEFINITIONS[1:]
    )
