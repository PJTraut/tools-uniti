"""Qt-native shortcut definitions with portable persisted overrides."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType

from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import QApplication

from uniti.app.commands import (
    CommandCategory,
    CommandDefinition,
    CommandRegistry,
    CommandScope,
    ShortcutCollision,
)


MAX_SHORTCUT_NOTICES = 32
MAX_SHORTCUT_TEXT = 256
_NOTICE_REASONS = frozenset({"unknown", "invalid", "conflict"})
_UNITI_FALLBACKS = {
    "file.reload": "Ctrl+Shift+R",
    "window.new": "Ctrl+Shift+N",
    "editor.zoom_reset": "Ctrl+0",
    "find.zoom_reset": "Ctrl+0",
    "editor.weight_increase": "Ctrl+Shift+=",
    "editor.weight_decrease": "Ctrl+Shift+-",
    "editor.weight_reset": "Ctrl+Shift+0",
    "editor.wrap": "Ctrl+Alt+W",
    "view.pause_background": "",
    "find.report_cycle": "Ctrl+Alt+R",
}


@dataclass(frozen=True, slots=True)
class ShortcutNotice:
    command_id: str
    reason: str

    def __post_init__(self) -> None:
        if not isinstance(self.command_id, str) or not self.command_id:
            raise ValueError("shortcut notice command ID must be nonempty")
        if self.reason not in _NOTICE_REASONS:
            raise ValueError("shortcut notice reason is invalid")


@dataclass(frozen=True, slots=True)
class ShortcutPolicy:
    definitions: tuple[CommandDefinition, ...]
    overrides: Mapping[str, str]
    notices: tuple[ShortcutNotice, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.definitions, tuple) or any(
            not isinstance(item, CommandDefinition) for item in self.definitions
        ):
            raise TypeError("shortcut definitions must be a tuple")
        if not isinstance(self.notices, tuple) or any(
            not isinstance(item, ShortcutNotice) for item in self.notices
        ):
            raise TypeError("shortcut notices must be a tuple")
        cleaned = dict(self.overrides)
        if any(
            not isinstance(command_id, str) or not isinstance(shortcut, str)
            for command_id, shortcut in cleaned.items()
        ):
            raise TypeError("shortcut overrides must contain portable strings")
        object.__setattr__(self, "overrides", MappingProxyType(cleaned))


def _portable_standard(
    key: QKeySequence.StandardKey,
    *,
    fallback_command_id: str | None = None,
) -> str:
    shortcut = QKeySequence(key).toString(
        QKeySequence.SequenceFormat.PortableText
    )
    if shortcut or fallback_command_id is None:
        return shortcut
    return _UNITI_FALLBACKS[fallback_command_id]


def _definitions() -> tuple[CommandDefinition, ...]:
    category = CommandCategory
    scope = CommandScope
    standard = QKeySequence.StandardKey
    records = (
        ("file.new", "New", category.FILE, scope.WINDOW, standard.New),
        ("file.open", "Open…", category.FILE, scope.WINDOW, standard.Open),
        (
            "file.open_folder_by_type",
            "Open Folder by Type…",
            category.FILE,
            scope.WINDOW,
            None,
        ),
        ("file.save", "Save", category.FILE, scope.WINDOW, standard.Save),
        ("file.save_as", "Save As…", category.FILE, scope.WINDOW, standard.SaveAs),
        ("file.reload", "Reload/Revert from Disk", category.FILE, scope.WINDOW, "file.reload"),
        ("file.close", "Close", category.FILE, scope.WINDOW, standard.Close),
        ("file.quit", "Quit", category.FILE, scope.WINDOW, standard.Quit),
        ("editing.undo", "Undo", category.EDITING, scope.WINDOW, standard.Undo),
        ("editing.redo", "Redo", category.EDITING, scope.WINDOW, standard.Redo),
        ("editing.cut", "Cut", category.EDITING, scope.WINDOW, standard.Cut),
        ("editing.copy", "Copy", category.EDITING, scope.WINDOW, standard.Copy),
        ("editing.paste", "Paste", category.EDITING, scope.WINDOW, standard.Paste),
        ("editing.select_all", "Select All", category.EDITING, scope.WINDOW, standard.SelectAll),
        ("navigation.go_to_line", "Go to Line…", category.NAVIGATION, scope.EDITOR, None),
        (
            "navigation.page_up",
            "Page Up",
            category.NAVIGATION,
            scope.EDITOR,
            standard.MoveToPreviousPage,
        ),
        (
            "navigation.page_down",
            "Page Down",
            category.NAVIGATION,
            scope.EDITOR,
            standard.MoveToNextPage,
        ),
        (
            "navigation.document_start",
            "Document Start",
            category.NAVIGATION,
            scope.EDITOR,
            standard.MoveToStartOfDocument,
        ),
        (
            "navigation.document_end",
            "Document End",
            category.NAVIGATION,
            scope.EDITOR,
            standard.MoveToEndOfDocument,
        ),
        (
            "navigation.word_left",
            "Word Left",
            category.NAVIGATION,
            scope.EDITOR,
            standard.MoveToPreviousWord,
        ),
        (
            "navigation.word_right",
            "Word Right",
            category.NAVIGATION,
            scope.EDITOR,
            standard.MoveToNextWord,
        ),
        ("find.open", "Find", category.FIND_REPLACE, scope.WINDOW, standard.Find),
        ("find.replace", "Replace", category.FIND_REPLACE, scope.WINDOW, standard.Replace),
        ("find.next", "Find Next", category.FIND_REPLACE, scope.WINDOW, standard.FindNext),
        (
            "find.previous",
            "Find Previous",
            category.FIND_REPLACE,
            scope.WINDOW,
            standard.FindPrevious,
        ),
        ("editor.zoom_in", "Zoom In", category.EDITOR_VIEW, scope.EDITOR, standard.ZoomIn),
        ("editor.zoom_out", "Zoom Out", category.EDITOR_VIEW, scope.EDITOR, standard.ZoomOut),
        (
            "editor.zoom_reset",
            "Reset Zoom",
            category.EDITOR_VIEW,
            scope.EDITOR,
            "editor.zoom_reset",
        ),
        (
            "editor.weight_increase",
            "Increase Font Weight",
            category.EDITOR_VIEW,
            scope.EDITOR,
            "editor.weight_increase",
        ),
        (
            "editor.weight_decrease",
            "Decrease Font Weight",
            category.EDITOR_VIEW,
            scope.EDITOR,
            "editor.weight_decrease",
        ),
        (
            "editor.weight_reset",
            "Reset Font Weight",
            category.EDITOR_VIEW,
            scope.EDITOR,
            "editor.weight_reset",
        ),
        ("editor.wrap", "Soft Line Wrap", category.EDITOR_VIEW, scope.EDITOR, "editor.wrap"),
        (
            "view.pause_background",
            "Pause Background Work",
            category.EDITOR_VIEW,
            scope.WINDOW,
            "view.pause_background",
        ),
        (
            "find.zoom_in",
            "Zoom In",
            category.FIND_REPLACE_VIEW,
            scope.FIND_REPLACE,
            standard.ZoomIn,
        ),
        (
            "find.zoom_out",
            "Zoom Out",
            category.FIND_REPLACE_VIEW,
            scope.FIND_REPLACE,
            standard.ZoomOut,
        ),
        (
            "find.zoom_reset",
            "Reset Zoom",
            category.FIND_REPLACE_VIEW,
            scope.FIND_REPLACE,
            "find.zoom_reset",
        ),
        (
            "find.report_cycle",
            "Toggle Match Report",
            category.FIND_REPLACE_VIEW,
            scope.FIND_REPLACE,
            "find.report_cycle",
        ),
        ("window.new", "New Window", category.FILE, scope.WINDOW, "window.new"),
        ("view.split_right", "Split Right", category.EDITOR_VIEW, scope.EDITOR, None),
        ("view.split_down", "Split Down", category.EDITOR_VIEW, scope.EDITOR, None),
        ("view.close_split", "Close Split", category.EDITOR_VIEW, scope.EDITOR, None),
        (
            "view.move_new_window",
            "Move Tab to New Window",
            category.EDITOR_VIEW,
            scope.EDITOR,
            None,
        ),
        (
            "find.toggle_attachment",
            "Attach/Detach Find & Replace",
            category.FIND_REPLACE_VIEW,
            scope.FIND_REPLACE,
            None,
        ),
        (
            "find.toggle_visibility",
            "Show/Hide Find & Replace",
            category.FIND_REPLACE,
            scope.WINDOW,
            None,
        ),
    )

    def resolve(specification: object) -> str:
        if isinstance(specification, QKeySequence.StandardKey):
            return _portable_standard(specification)
        if isinstance(specification, tuple):
            key, fallback_command_id = specification
            return _portable_standard(
                key,
                fallback_command_id=fallback_command_id,
            )
        if isinstance(specification, str):
            return _UNITI_FALLBACKS[specification]
        return ""

    return tuple(
        CommandDefinition(command_id, label, item_category, item_scope, resolve(spec))
        for command_id, label, item_category, item_scope, spec in records
    )


def _portable_override(value: str) -> str | None:
    if value == "":
        return ""
    if len(value) > MAX_SHORTCUT_TEXT:
        return None
    sequence = QKeySequence.fromString(
        value,
        QKeySequence.SequenceFormat.PortableText,
    )
    portable = sequence.toString(QKeySequence.SequenceFormat.PortableText)
    return portable or None


def build_shortcut_policy(raw_overrides: Mapping[object, object]) -> ShortcutPolicy:
    """Resolve native defaults and admit only safe portable overrides."""

    if not isinstance(QApplication.instance(), QApplication):
        raise RuntimeError("shortcut policy requires an existing QApplication")
    if not isinstance(raw_overrides, Mapping):
        raise TypeError("shortcut overrides must be a mapping")
    definitions = _definitions()
    registry = CommandRegistry(definitions)
    known = {item.command_id for item in definitions}
    notices: list[ShortcutNotice] = []
    seen_notices: set[tuple[str, str]] = set()

    def notice(command_id: object, reason: str) -> None:
        selected = command_id if isinstance(command_id, str) else "<invalid>"
        selected = selected[:512] or "<empty>"
        key = (selected, reason)
        if key in seen_notices or len(notices) >= MAX_SHORTCUT_NOTICES:
            return
        seen_notices.add(key)
        notices.append(ShortcutNotice(selected, reason))

    for command_id, raw_shortcut in raw_overrides.items():
        if not isinstance(command_id, str) or command_id not in known:
            notice(command_id, "unknown")
            continue
        if not isinstance(raw_shortcut, str):
            notice(command_id, "invalid")
            continue
        shortcut = _portable_override(raw_shortcut)
        if shortcut is None:
            notice(command_id, "invalid")
            continue
        try:
            registry.assign(command_id, shortcut)
        except ShortcutCollision:
            notice(command_id, "conflict")

    return ShortcutPolicy(definitions, registry.overrides, tuple(notices))


__all__ = [
    "MAX_SHORTCUT_NOTICES",
    "MAX_SHORTCUT_TEXT",
    "ShortcutNotice",
    "ShortcutPolicy",
    "build_shortcut_policy",
]
