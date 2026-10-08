"""Document Groups (color-tag grouping, BF-081) and Recent Files (BF-082),
composed onto UNITIMainWindow.

Third slice pulled out of main_window.py's god-object, after Dogfood
Evidence and Toggle-Window Management proved the "compose a controller
object" pattern (mirroring `theme_editor.py`, `compare_pane.py`,
`whitespace_legend.py`) works there. These two features are extracted
together, not separately: Recent Files reaches directly into Document
Groups' state (restoring a reopened file's last group, rendering group
swatches in the menu), so splitting them would just move the same
entanglement into two modules instead of removing it.

Follows the same template `ToggleWindowManager` established rather than
`DogfoodEvidenceController`'s (which had no shared mutable state at
all): the raw state this cluster reads and writes --
`owner._environment_groups` (each environment's own groups, round 3
T2), `owner._recent_files_store`, `owner._recent_files_menu` -- stays declared on `UNITIMainWindow` itself
(other code, e.g. `open_folder_by_type`, reads/writes it directly), only
the *logic* moves here. `UNITIMainWindow` keeps a thin delegating
wrapper method for each of the 17 names below, so every existing caller,
signal connection, and test needs zero changes.

Deliberately excluded: `_show_assignment_menu`/`assign_document_to_pane`
(pane-splitting's "assign an open document to an empty split", a
different feature wired to a different signal, sharing no state with
this cluster) and `open_folder_by_type` (calls into this cluster's
methods/attributes but has its own large, unrelated batch-open flow).
"""

from __future__ import annotations

import re
from dataclasses import replace as dataclass_replace
from pathlib import Path

from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QMenu, QMessageBox


class DocumentGroupsAndRecentFiles:
    """Owns Document Groups and Recent Files menu/state logic for one
    main window. `owner` is the `UNITIMainWindow` this acts on behalf
    of -- see the module docstring for exactly which state stays on it."""

    _OPEN_FOLDER_GROUP_PALETTE = (
        "#e06c75",
        "#61afef",
        "#98c379",
        "#e5c07b",
        "#c678dd",
        "#56b6c2",
        "#d19a66",
    )

    def __init__(self, owner) -> None:
        self._owner = owner

    @staticmethod
    def _group_swatch_icon(color: str) -> QIcon:
        size = 12
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(1, 1, size - 2, size - 2)
        finally:
            painter.end()
        return QIcon(pixmap)

    def _refresh_group_indicator(self, view_id: str) -> None:
        owner = self._owner
        if owner._service is None:
            return
        leaf = owner._panes.leaf_for_view(view_id)
        if leaf is None:
            return
        index = leaf.index_of(view_id)
        if index < 0:
            return
        entry = owner._service.documents.entry_for_view(view_id)
        group = None if entry is None else self._group_by_id(entry.group_id, self._key_for_document(entry.document_id))
        leaf.tabs.setTabIcon(
            index, self._group_swatch_icon(group.color) if group is not None else QIcon()
        )
        grouped_tabs = getattr(owner, "_grouped_tabs", None)
        if grouped_tabs is not None and grouped_tabs.enabled:
            grouped_tabs.refresh_leaf(leaf)  # BF-082: membership changed
        project_tabs = getattr(owner, "_project_tabs", None)
        if project_tabs is not None and project_tabs.active:
            project_tabs.refresh_leaf(leaf)  # round 3 T4: a book joined a tab

    def _refresh_all_group_indicators(self) -> None:
        owner = self._owner
        for view_id in owner._panes.view_ids:
            self._refresh_group_indicator(view_id)

    def _project_of_document(self, document_id: str):
        """The Paratext project a document of a project environment (USFM)
        belongs to: its group is the project's (round 3 T5)."""

        from uniti.core.environments.catalog import PROJECT_ENVIRONMENTS
        from uniti.core.environments.sfm.paratext_project import project_for_file

        entry = self._owner._service.documents.get(document_id)
        if self._key_for_document(document_id) not in PROJECT_ENVIRONMENTS:
            return None
        return project_for_file(entry.canonical_path)

    def _set_document_group(self, document_id: str, group_id: str | None) -> None:
        """Give a document a group. A book of a project environment (USFM)
        gives its project the group instead, and with it every open book
        of the project (round 3 T5)."""

        owner = self._owner
        if owner._service is None:
            return
        project = self._project_of_document(document_id)
        if project is None:
            self._apply_document_group(document_id, group_id)
            return
        key = self._key_for_document(document_id)
        try:
            owner._project_groups.set(key, project.folder, group_id)
        except (OSError, ValueError) as exc:
            owner.statusBar().showMessage(str(exc)[:256], 5000)
        for entry in self._project_entries(project.folder):
            self._apply_document_group(entry.document_id, group_id)

    def _project_entries(self, folder: Path):
        from uniti.core.environments.sfm.paratext_project import project_for_file

        folder = _resolved(folder)
        found = []
        for entry in self._owner._service.documents.entries:
            project = project_for_file(entry.canonical_path)
            if project is not None and _resolved(project.folder) == folder:
                found.append(entry)
        return found

    def apply_project_group(self, document_id: str) -> None:
        """A project book was opened: it takes its project's group."""

        owner = self._owner
        if owner._service is None:
            return
        project = self._project_of_document(document_id)
        if project is None:
            return
        group_id = owner._project_groups.group(self._key_for_document(document_id), project.folder)
        if group_id is None or self._group_by_id(group_id, self._key_for_document(document_id)) is None:
            return
        if owner._service.documents.get(document_id).group_id != group_id:
            self._apply_document_group(document_id, group_id)

    def _apply_document_group(self, document_id: str, group_id: str | None) -> None:
        owner = self._owner
        owner._service.documents.set_group(document_id, group_id)
        entry = owner._service.documents.get(document_id)
        if owner._recent_files_store is not None:
            owner._recent_files_store.record_group(str(entry.canonical_path), group_id)
        # The tab's swatch, in whichever window shows it.
        for window in self._windows():
            for view_id in entry.view_ids:
                if window.view_for_id(view_id) is not None:
                    window._groups_and_recent_files._refresh_group_indicator(view_id)
        follow = getattr(owner, "_document_group_changed", None)
        if callable(follow):
            follow(document_id, group_id)

    def _key_for_document(self, document_id: str) -> str:
        """The environment a document's group belongs to (T2)."""

        owner = self._owner
        entry = owner._service.documents.get(document_id)
        if entry.document is not None:
            return owner._environment.environment_key_for(entry.document)
        return entry.environment_key

    def _key_for_view(self, view_id: str) -> str | None:
        owner = self._owner
        entry = None if owner._service is None else owner._service.documents.entry_for_view(view_id)
        return None if entry is None else self._key_for_document(entry.document_id)

    def _windows(self) -> list:
        owner = self._owner
        if owner._service is None:
            return [owner]
        return [window for _window_id, window in owner._service.windows.items]

    def _publish_groups(self, environment_key: str, groups) -> None:
        """Save `environment_key`'s groups and give them to every window (a
        group made in one window is at once in every other's menus and
        titles)."""

        owner = self._owner
        owner._environment_groups.save(environment_key, groups)
        for window in self._windows():
            if window._environment_groups is not owner._environment_groups:
                window._set_groups(environment_key, groups)
            window._groups_and_recent_files._refresh_all_group_indicators()
            bar = getattr(window, "_environment_bar", None)
            if bar is not None:
                bar.refresh()

    def new_group_for(self, document_id: str | None = None, environment_key: str | None = None):
        """Ask for a name, create the group (next free colour) in the
        document's environment (else `environment_key`, else the window's)
        and, with `document_id`, put that document in it."""

        from PySide6.QtWidgets import QInputDialog

        from uniti.app.document_groups import DocumentGroup

        owner = self._owner
        name, accepted = QInputDialog.getText(owner, "New Group", "Group name:")
        name = name.strip() if accepted else ""
        if not name:
            return None
        if document_id is not None and owner._service is not None:
            key = self._key_for_document(document_id)
        else:
            key = environment_key or owner.group_environment_key()
        group = DocumentGroup(self._unique_group_id(name, key), name, self._next_group_color(key))
        self._publish_groups(key, owner.groups_for(key) + (group,))
        if document_id is not None:
            self._set_document_group(document_id, group.id)
        return group

    def populate_group_menu(self, menu: QMenu, view_id: str, *, extras: bool = True) -> bool:
        """The group choices for `view_id`'s document: No Group, each group
        (its swatch, checked when current), New Group…, and with `extras`
        the saved-group and manage entries. False when there's no document."""

        from PySide6.QtGui import QActionGroup

        owner = self._owner
        entry = None if owner._service is None else owner._service.documents.entry_for_view(view_id)
        if entry is None:
            return False
        key = self._key_for_document(entry.document_id)
        groups = owner.groups_for(key)
        choices = QActionGroup(menu)
        choices.setExclusive(True)
        none_action = menu.addAction("No Group")
        none_action.setCheckable(True)
        none_action.setChecked(entry.group_id is None)
        choices.addAction(none_action)
        none_action.triggered.connect(
            lambda _checked=False, document_id=entry.document_id: self._set_document_group(document_id, None)
        )
        if groups:
            menu.addSeparator()
        for group in groups:
            action = menu.addAction(self._group_swatch_icon(group.color), group.name)
            action.setCheckable(True)
            action.setChecked(entry.group_id == group.id)
            choices.addAction(action)
            action.triggered.connect(
                lambda _checked=False, document_id=entry.document_id, group_id=group.id: self._set_document_group(
                    document_id, group_id
                )
            )
        menu.addSeparator()
        new_action = menu.addAction("New Group…")
        new_action.triggered.connect(lambda _checked=False, document_id=entry.document_id: self.new_group_for(document_id))
        if not extras:
            manage_action = menu.addAction("Manage Groups…")
            manage_action.triggered.connect(lambda _checked=False: self.show_document_group_editor(key))
            return True
        openable = [group for group in groups if group.saved_paths]
        if openable:
            menu.addSeparator()
            for group in openable:
                action = menu.addAction(f'Open Saved "{group.name}"')
                action.triggered.connect(lambda _checked=False, group_id=group.id: self._open_group(group_id, key))
        current_group = self._group_by_id(entry.group_id, key)
        if current_group is not None:
            menu.addSeparator()
            save_action = menu.addAction(f'Save Group "{current_group.name}"')
            save_action.triggered.connect(lambda _checked=False, group_id=current_group.id: self._save_group(group_id, key))
            close_action = menu.addAction(f'Close Group "{current_group.name}"')
            close_action.triggered.connect(lambda _checked=False, group_id=current_group.id: self._close_group(group_id, key))
        menu.addSeparator()
        manage_action = menu.addAction("Manage Groups…")
        manage_action.triggered.connect(lambda _checked=False: self.show_document_group_editor(key))
        return True

    def add_group_submenu(self, menu: QMenu, view_id: str) -> QMenu | None:
        """A "Document Group" submenu for a right-click menu, showing the
        current group's swatch. For a project book it's the project's group
        (round 3 T5): "Project Group"."""

        owner = self._owner
        entry = None if owner._service is None else owner._service.documents.entry_for_view(view_id)
        if entry is None:
            return None
        current = self._group_by_id(entry.group_id, self._key_for_document(entry.document_id))
        title = "Project Group" if self._project_of_document(entry.document_id) is not None else "Document Group"
        submenu = menu.addMenu(title)
        if current is not None:
            submenu.setIcon(self._group_swatch_icon(current.color))
            submenu.setTitle(f"{title} ({current.name})")
        self.populate_group_menu(submenu, view_id, extras=False)
        return submenu

    def _group_by_id(self, group_id: str | None, environment_key: str) -> object | None:
        return self._owner._environment_groups.group(environment_key, group_id)

    def _entries_of(self, group_id: str, environment_key: str):
        """The registry entries of `environment_key`'s group `group_id`."""

        service = self._owner._service
        return [
            entry
            for entry in service.documents.entries
            if entry.group_id == group_id and self._key_for_document(entry.document_id) == environment_key
        ]

    def _save_group(self, group_id: str, environment_key: str) -> None:
        """BF-081: persist the paths of every currently open document
        carrying ``group_id`` onto that group's record, so it can later be
        reopened with ``_open_group``. Untitled and already-closed
        documents have no reopenable path and are skipped."""

        owner = self._owner
        if owner._service is None:
            return
        current = owner.groups_for(environment_key)
        index = next((i for i, group in enumerate(current) if group.id == group_id), None)
        if index is None:
            return
        paths = tuple(
            str(entry.canonical_path)
            for entry in self._entries_of(group_id, environment_key)
            if entry.view_ids and not entry.is_untitled
        )
        updated = dataclass_replace(current[index], saved_paths=paths)
        groups = current[:index] + (updated,) + current[index + 1 :]
        try:
            self._publish_groups(environment_key, groups)
        except (OSError, ValueError) as exc:
            owner.statusBar().showMessage(str(exc)[:256], 5000)
            return
        owner.statusBar().showMessage(
            f'Saved {len(paths)} file(s) to group "{updated.name}".', 5000
        )

    def _close_group(self, group_id: str, environment_key: str) -> None:
        """BF-081: close every open tab currently carrying ``group_id``,
        prompting per unsaved document exactly like an ordinary Close would
        (matching ``close_all_documents``, BF-084)."""

        owner = self._owner
        if owner._service is None:
            return
        members = {entry.document_id for entry in self._entries_of(group_id, environment_key)}
        for view_id in reversed(owner.view_ids):
            entry = owner._service.documents.entry_for_view(view_id)
            if entry is not None and entry.document_id in members:
                if not owner._close_view_id(view_id, force=False):
                    return

    def _open_group(self, group_id: str, environment_key: str) -> None:
        """BF-081: reopen every path saved onto ``group_id`` (an already
        open path is focused instead, per ``open_path``) and (re)assign it
        to the group -- restoring membership, not tab order/position."""

        owner = self._owner
        group = self._group_by_id(group_id, environment_key)
        if group is None or owner._service is None:
            return
        failed = 0
        for raw_path in group.saved_paths:
            try:
                view = owner.open_path(Path(raw_path))
            except Exception:
                failed += 1
                continue
            if view is None:
                continue
            entry = owner._service.documents.entry_for_view(view.view_id)
            if (
                entry is not None
                and entry.group_id != group_id
                and self._key_for_document(entry.document_id) == environment_key
            ):
                self._set_document_group(entry.document_id, group_id)
        if failed:
            owner.statusBar().showMessage(
                f'Could not open {failed} file(s) from group "{group.name}".', 5000
            )

    def _show_group_menu(self, view_id: str, position: QPoint) -> None:
        """The tab's right-click menu: assign the document's group."""

        owner = self._owner
        menu = QMenu(owner)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        if not self.populate_group_menu(menu, view_id):
            menu.deleteLater()
            return
        menu.popup(position)

    def show_document_group_editor(self, environment_key: str | None = None) -> None:
        """Manage Groups…: each environment's groups, starting at
        `environment_key` (default: the window's or current file's)."""

        from uniti.core.environments.catalog import ENVIRONMENTS
        from uniti.ui.document_group_editor import DocumentGroupEditor

        owner = self._owner
        key = environment_key or owner.group_environment_key()
        environments = [
            (descriptor.key, descriptor.label, owner.groups_for(descriptor.key)) for descriptor in ENVIRONMENTS
        ]
        names = owner._environment_window_names
        window_names = {descriptor.key: names.names(descriptor.key, self._named_slots(descriptor.key)) for descriptor in ENVIRONMENTS}
        editor = DocumentGroupEditor(
            owner.groups_for(key), owner, environments=environments, environment=key, window_names=window_names
        )
        if not editor.exec():
            return
        edited_names = getattr(editor, "window_names_by_environment", dict)()
        for edited_key, edited in edited_names.items():
            if edited == window_names.get(edited_key):
                continue
            try:
                names.set_names(edited_key, edited)
            except (OSError, ValueError) as exc:
                QMessageBox.warning(owner, "Window Names", str(exc))
                continue
            owner._environment_window_names_changed(edited_key)
        for edited_key, groups in editor.groups_by_environment().items():
            before = owner.groups_for(edited_key)
            if tuple(groups) == tuple(before):
                continue
            removed_ids = {g.id for g in before} - {g.id for g in groups}
            if removed_ids:
                owner._project_groups.forget_groups(edited_key, removed_ids)
            if owner._service is not None and removed_ids:
                for group_id in removed_ids:
                    for entry in self._entries_of(group_id, edited_key):
                        owner._service.documents.set_group(entry.document_id, None)
            self._publish_groups(edited_key, groups)

    def _named_slots(self, environment_key: str) -> int:
        """How many window names Manage Groups… shows: every open or
        renamed slot, and at least three."""

        owner = self._owner
        slots = [slot for slot in owner._environment_window_names.renamed(environment_key)]
        if owner._service is not None:
            slots.extend(window.environment_window[1] for window in owner._service.environment_windows(environment_key))
        return max([3] + [slot + 1 for slot in slots])

    def _next_group_color(self, environment_key: str) -> str:
        groups = self._owner.groups_for(environment_key)
        used = {group.color for group in groups}
        for color in self._OPEN_FOLDER_GROUP_PALETTE:
            if color not in used:
                return color
        return self._OPEN_FOLDER_GROUP_PALETTE[
            len(groups) % len(self._OPEN_FOLDER_GROUP_PALETTE)
        ]

    def _unique_group_id(self, name: str, environment_key: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:64] or "group"
        existing = {group.id for group in self._owner.groups_for(environment_key)}
        candidate = base
        suffix = 2
        while candidate in existing:
            candidate = f"{base}-{suffix}"[:64]
            suffix += 1
        return candidate

    def _remember_directory(self, path: str | Path) -> None:
        owner = self._owner
        directory = str(Path(path).parent)
        owner._settings = dataclass_replace(owner._settings, last_directory=directory)
        owner._save_settings()

    def _record_recent_file(self, path: str | Path) -> None:
        owner = self._owner
        if owner._recent_files_store is not None:
            owner._recent_files_store.record_opened(str(Path(path)))

    def _populate_recent_files_menu(self) -> None:
        owner = self._owner
        menu = owner._recent_files_menu
        menu.clear()
        entries = (
            owner._recent_files_store.load_entries()
            if owner._recent_files_store is not None
            else ()
        )
        if not entries:
            empty_action = menu.addAction("(No Recent Files)")
            empty_action.setEnabled(False)
            return
        names = [Path(entry.path).name for entry in entries]
        duplicated_names = {name for name in names if names.count(name) > 1}
        for entry, name in zip(entries, names):
            label = (
                f"{name}  ({Path(entry.path).parent})" if name in duplicated_names else name
            )
            group = self._group_by_id(entry.group_id, self._key_for_path(entry.path))
            action = (
                menu.addAction(self._group_swatch_icon(group.color), label)
                if group is not None
                else menu.addAction(label)
            )
            action.setToolTip(entry.path)
            action.triggered.connect(
                lambda _checked=False, path=entry.path: self._open_recent_file(path)
            )
        menu.addSeparator()
        menu.addAction("Clear Recent Files", self._clear_recent_files)

    def _key_for_path(self, path: str | Path) -> str:
        """The environment a file that may not be open would get."""

        owner = self._owner
        return owner._file_environment_manager.resolve_path_key(
            Path(path), owner._settings.syntax_extension_overrides
        )

    def _open_recent_file(self, path: str) -> None:
        """BF-082: reopening a recent file restores the DocumentGroup it
        last carried, when that group still exists."""

        owner = self._owner
        group_id = None
        if owner._recent_files_store is not None:
            match = next(
                (
                    entry
                    for entry in owner._recent_files_store.load_entries()
                    if entry.path == path
                ),
                None,
            )
            group_id = match.group_id if match is not None else None
        known_group = group_id if self._group_by_id(group_id, self._key_for_path(path)) is not None else None
        try:
            view = owner.open_path(path)
        except Exception as exc:
            QMessageBox.critical(owner, "Open Failed", f"{path}\n\n{exc}")
            return
        if known_group is not None and view is not None and owner._service is not None:
            entry = owner._service.documents.entry_for_view(view.view_id)
            if (
                entry is not None
                and entry.group_id != group_id
                and self._group_by_id(group_id, self._key_for_document(entry.document_id)) is not None
            ):
                self._set_document_group(entry.document_id, group_id)

    def _clear_recent_files(self) -> None:
        owner = self._owner
        if owner._recent_files_store is not None:
            owner._recent_files_store.clear()


def _resolved(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


__all__ = ["DocumentGroupsAndRecentFiles"]
