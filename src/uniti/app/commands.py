"""Qt-free command and shortcut registry for UNITI."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum


class CommandScope(StrEnum):
    WINDOW = "WINDOW"
    EDITOR = "EDITOR"
    FIND_REPLACE = "FIND_REPLACE"


class CommandCategory(StrEnum):
    FILE = "File"
    EDITING = "Editing"
    NAVIGATION = "Navigation"
    FIND_REPLACE = "Find/Replace"
    EDITOR_VIEW = "Editor View"
    FIND_REPLACE_VIEW = "F/R View"


@dataclass(frozen=True, slots=True)
class CommandDefinition:
    command_id: str
    label: str
    category: CommandCategory
    scope: CommandScope
    default_shortcut: str


PANE_COMMAND_DEFINITIONS = (
    CommandDefinition(
        "window.new",
        "New Window",
        CommandCategory.FILE,
        CommandScope.WINDOW,
        "Ctrl+Shift+N",
    ),
    CommandDefinition(
        "view.split_right",
        "Split Right",
        CommandCategory.EDITOR_VIEW,
        CommandScope.EDITOR,
        "",
    ),
    CommandDefinition(
        "view.split_down",
        "Split Down",
        CommandCategory.EDITOR_VIEW,
        CommandScope.EDITOR,
        "",
    ),
    CommandDefinition(
        "view.close_split",
        "Close Split",
        CommandCategory.EDITOR_VIEW,
        CommandScope.EDITOR,
        "",
    ),
    CommandDefinition(
        "view.move_new_window",
        "Move Tab to New Window",
        CommandCategory.EDITOR_VIEW,
        CommandScope.EDITOR,
        "",
    ),
)


FIND_REPLACE_DOCK_COMMAND_DEFINITION = CommandDefinition(
    "find.toggle_attachment",
    "Attach/Detach Find & Replace",
    CommandCategory.FIND_REPLACE_VIEW,
    CommandScope.FIND_REPLACE,
    "",
)


class ShortcutCollision(ValueError):
    def __init__(
        self,
        command_id: str,
        conflicting_command_id: str,
        shortcut: str,
    ) -> None:
        self.command_id = command_id
        self.conflicting_command_id = conflicting_command_id
        self.shortcut = shortcut
        super().__init__(
            f"{shortcut} is already assigned to {conflicting_command_id}"
        )


def _normalized(shortcut: str) -> str:
    return "".join(shortcut.split()).casefold()


def _scopes_overlap(left: CommandScope, right: CommandScope) -> bool:
    return left == right or CommandScope.WINDOW in {left, right}


class CommandRegistry:
    def __init__(
        self,
        definitions: Iterable[CommandDefinition],
        *,
        overrides: Mapping[str, str] | None = None,
    ) -> None:
        ordered = tuple(definitions)
        if not ordered:
            raise ValueError("command registry requires at least one definition")
        self._definitions: dict[str, CommandDefinition] = {}
        for definition in ordered:
            if not definition.command_id:
                raise ValueError("command_id must not be empty")
            if definition.command_id in self._definitions:
                raise ValueError(f"duplicate command_id: {definition.command_id}")
            self._definitions[definition.command_id] = definition
        self._ordered_ids = tuple(self._definitions)
        self._overrides: dict[str, str] = {}
        self._listeners: list[Callable[[str, str], None]] = []
        for command_id, shortcut in dict(overrides or {}).items():
            if command_id not in self._definitions or not isinstance(shortcut, str):
                continue
            try:
                self.assign(command_id, shortcut)
            except ShortcutCollision:
                continue

    @property
    def overrides(self) -> dict[str, str]:
        return dict(self._overrides)

    def add_listener(self, listener: Callable[[str, str], None]) -> Callable[[], None]:
        self._listeners.append(listener)

        def remove() -> None:
            try:
                self._listeners.remove(listener)
            except ValueError:
                pass

        return remove

    def definition(self, command_id: str) -> CommandDefinition:
        try:
            return self._definitions[command_id]
        except KeyError:
            raise KeyError(command_id) from None

    def definitions(
        self,
        *,
        category: CommandCategory | None = None,
    ) -> tuple[CommandDefinition, ...]:
        definitions = tuple(
            self._definitions[command_id] for command_id in self._ordered_ids
        )
        if category is None:
            return definitions
        return tuple(item for item in definitions if item.category == category)

    def current(self, command_id: str) -> str:
        definition = self.definition(command_id)
        return self._overrides.get(command_id, definition.default_shortcut)

    def _notify(self, command_id: str) -> None:
        current = self.current(command_id)
        for listener in tuple(self._listeners):
            listener(command_id, current)

    def assign(self, command_id: str, shortcut: str) -> None:
        definition = self.definition(command_id)
        if not isinstance(shortcut, str):
            raise TypeError("shortcut must be a string")
        normalized = _normalized(shortcut)
        if normalized:
            for other in self.definitions():
                if other.command_id == command_id:
                    continue
                if not _scopes_overlap(definition.scope, other.scope):
                    continue
                other_shortcut = self.current(other.command_id)
                if other_shortcut and _normalized(other_shortcut) == normalized:
                    raise ShortcutCollision(
                        command_id,
                        other.command_id,
                        shortcut,
                    )
        if shortcut == definition.default_shortcut:
            self._overrides.pop(command_id, None)
        else:
            self._overrides[command_id] = shortcut
        self._notify(command_id)

    def clear(self, command_id: str) -> None:
        self.assign(command_id, "")

    def reset(self, command_id: str) -> None:
        self.definition(command_id)
        self._overrides.pop(command_id, None)
        self._notify(command_id)

    def reset_category(self, category: CommandCategory) -> None:
        for definition in self.definitions(category=category):
            self.reset(definition.command_id)

    def reset_all(self) -> None:
        changed = tuple(self._overrides)
        self._overrides.clear()
        for command_id in changed:
            self._notify(command_id)
