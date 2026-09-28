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
`owner._groups`, `owner._group_store`, `owner._recent_files_store`,
`owner._recent_files_menu` -- stays declared on `UNITIMainWindow` itself
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
        group = next(
            (g for g in owner._groups if entry is not None and g.id == entry.group_id),
            None,
        )
        leaf.tabs.setTabIcon(
            index, self._group_swatch_icon(group.color) if group is not None else QIcon()
        )

    def _refresh_all_group_indicators(self) -> None:
        owner = self._owner
        for view_id in owner._panes.view_ids:
            self._refresh_group_indicator(view_id)

    def _set_document_group(self, document_id: str, group_id: str | None) -> None:
        owner = self._owner
        if owner._service is None:
            return
        owner._service.documents.set_group(document_id, group_id)
        entry = owner._service.documents.get(document_id)
        if owner._recent_files_store is not None:
            owner._recent_files_store.record_group(str(entry.canonical_path), group_id)
        for view_id in entry.view_ids:
            self._refresh_group_indicator(view_id)

    def _group_by_id(self, group_id: str) -> object | None:
        return next(
            (group for group in self._owner._groups if group.id == group_id), None
        )

    def _save_group(self, group_id: str) -> None:
        """BF-081: persist the paths of every currently open document
        carrying ``group_id`` onto that group's record, so it can later be
        reopened with ``_open_group``. Untitled and already-closed
        documents have no reopenable path and are skipped."""

        owner = self._owner
        if owner._service is None or owner._group_store is None:
            return
        index = next(
            (i for i, group in enumerate(owner._groups) if group.id == group_id), None
        )
        if index is None:
            return
        paths = tuple(
            str(entry.canonical_path)
            for entry in owner._service.documents.entries
            if entry.group_id == group_id and entry.view_ids and not entry.is_untitled
        )
        updated = dataclass_replace(owner._groups[index], saved_paths=paths)
        groups = owner._groups[:index] + (updated,) + owner._groups[index + 1 :]
        try:
            owner._group_store.save(groups)
        except ValueError as exc:
            owner.statusBar().showMessage(str(exc)[:256], 5000)
            return
        owner._groups = groups
        owner.statusBar().showMessage(
            f'Saved {len(paths)} file(s) to group "{updated.name}".', 5000
        )

    def _close_group(self, group_id: str) -> None:
        """BF-081: close every open tab currently carrying ``group_id``,
        prompting per unsaved document exactly like an ordinary Close would
        (matching ``close_all_documents``, BF-084)."""

        owner = self._owner
        if owner._service is None:
            return
        for view_id in reversed(owner.view_ids):
            entry = owner._service.documents.entry_for_view(view_id)
            if entry is not None and entry.group_id == group_id:
                if not owner._close_view_id(view_id, force=False):
                    return

    def _open_group(self, group_id: str) -> None:
        """BF-081: reopen every path saved onto ``group_id`` (an already
        open path is focused instead, per ``open_path``) and (re)assign it
        to the group -- restoring membership, not tab order/position."""

        owner = self._owner
        group = self._group_by_id(group_id)
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
            if entry is not None and entry.group_id != group_id:
                self._set_document_group(entry.document_id, group_id)
        if failed:
            owner.statusBar().showMessage(
                f'Could not open {failed} file(s) from group "{group.name}".', 5000
            )

    def _show_group_menu(self, view_id: str, position: QPoint) -> None:
        owner = self._owner
        if owner._service is None:
            return
        entry = owner._service.documents.entry_for_view(view_id)
        if entry is None:
            return
        menu = QMenu(owner)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        none_action = menu.addAction("No Group")
        none_action.setCheckable(True)
        none_action.setChecked(entry.group_id is None)
        none_action.triggered.connect(
            lambda _checked=False, document_id=entry.document_id: (
                self._set_document_group(document_id, None)
            )
        )
        if owner._groups:
            menu.addSeparator()
        for group in owner._groups:
            action = menu.addAction(self._group_swatch_icon(group.color), group.name)
            action.setCheckable(True)
            action.setChecked(entry.group_id == group.id)
            action.triggered.connect(
                lambda _checked=False,
                document_id=entry.document_id,
                group_id=group.id: self._set_document_group(document_id, group_id)
            )
        openable = [group for group in owner._groups if group.saved_paths]
        if openable:
            menu.addSeparator()
            for group in openable:
                action = menu.addAction(f'Open Saved "{group.name}"')
                action.triggered.connect(
                    lambda _checked=False, group_id=group.id: self._open_group(group_id)
                )
        current_group = (
            self._group_by_id(entry.group_id) if entry.group_id is not None else None
        )
        if current_group is not None:
            menu.addSeparator()
            save_action = menu.addAction(f'Save Group "{current_group.name}"')
            save_action.triggered.connect(
                lambda _checked=False, group_id=current_group.id: self._save_group(group_id)
            )
            close_action = menu.addAction(f'Close Group "{current_group.name}"')
            close_action.triggered.connect(
                lambda _checked=False, group_id=current_group.id: self._close_group(group_id)
            )
        menu.addSeparator()
        manage_action = menu.addAction("Manage Groups…")
        manage_action.triggered.connect(self.show_document_group_editor)
        menu.popup(position)

    def show_document_group_editor(self) -> None:
        from uniti.ui.document_group_editor import DocumentGroupEditor

        owner = self._owner
        editor = DocumentGroupEditor(owner._groups, owner)
        if editor.exec() and owner._group_store is not None:
            groups = editor.groups()
            owner._group_store.save(groups)
            removed_ids = {g.id for g in owner._groups} - {g.id for g in groups}
            owner._groups = groups
            if owner._service is not None and removed_ids:
                for entry in owner._service.documents.entries:
                    if entry.group_id in removed_ids:
                        owner._service.documents.set_group(entry.document_id, None)
            self._refresh_all_group_indicators()

    def _next_group_color(self) -> str:
        owner = self._owner
        used = {group.color for group in owner._groups}
        for color in self._OPEN_FOLDER_GROUP_PALETTE:
            if color not in used:
                return color
        return self._OPEN_FOLDER_GROUP_PALETTE[
            len(owner._groups) % len(self._OPEN_FOLDER_GROUP_PALETTE)
        ]

    def _unique_group_id(self, name: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:64] or "group"
        existing = {group.id for group in self._owner._groups}
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
            group = (
                self._group_by_id(entry.group_id) if entry.group_id is not None else None
            )
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
        try:
            view = owner.open_path(path)
        except Exception as exc:
            QMessageBox.critical(owner, "Open Failed", f"{path}\n\n{exc}")
            return
        if (
            group_id is not None
            and view is not None
            and owner._service is not None
            and any(group.id == group_id for group in owner._groups)
        ):
            entry = owner._service.documents.entry_for_view(view.view_id)
            if entry is not None and entry.group_id != group_id:
                self._set_document_group(entry.document_id, group_id)

    def _clear_recent_files(self) -> None:
        owner = self._owner
        if owner._recent_files_store is not None:
            owner._recent_files_store.clear()


__all__ = ["DocumentGroupsAndRecentFiles"]
