"""USFM projects in the window: Open USFM Project… and Recent Projects
(plan P2, ADR-0018).

A project is a Paratext folder with a `Settings.xml` (`ParatextProject`).
Opening one never opens it whole: it opens one book — where the project was
left, else its first — in the USFM environment window of the project's
document group, and the Book selector opens the rest on demand. UNITI
remembers only the Recent Projects list and where each project was left
(book, chapter:verse, group); it never writes into a project folder.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QFileDialog, QMenu, QMessageBox

from uniti.core.environments.sfm.paratext_project import ParatextProject, project_for_file

if TYPE_CHECKING:
    from uniti.app.recent_projects import RecentProject
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

logger = logging.getLogger("uniti.ui.usfm_projects")

USFM = "usfm"
_POSITION_DELAY_MS = 1500


class UsfmProjectController(QObject):
    """Owns the project commands and Recent Projects for one window."""

    def __init__(self, window: "UNITIMainWindow") -> None:
        super().__init__(window)
        self._window = window
        self.menu: QMenu | None = None
        self._pending: "UNITITextView | None" = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_POSITION_DELAY_MS)
        self._timer.timeout.connect(self._save_position)

    @property
    def store(self):
        settings_store = self._window._settings_store
        return None if settings_store is None else settings_store.recent_projects

    # --- menu ------------------------------------------------------------------

    def build_menu(self, file_menu: QMenu) -> None:
        self.menu = file_menu.addMenu("Recent Projects")
        self.menu.aboutToShow.connect(self.populate_menu)

    def populate_menu(self) -> None:
        menu = self.menu
        if menu is None:
            return
        menu.clear()
        entries = self.store.load() if self.store is not None else ()
        if not entries:
            menu.addAction("(No Recent Projects)").setEnabled(False)
            return
        for entry in entries:
            available = (Path(entry.folder) / "Settings.xml").is_file()
            label = entry.name if available else f"{entry.name} (unavailable)"
            action = menu.addAction(label)
            action.setToolTip(entry.folder)
            action.setEnabled(available)
            action.triggered.connect(lambda _checked=False, folder=entry.folder: self.open_project(Path(folder)))
        menu.addSeparator()
        menu.addAction("Clear Recent Projects", self.clear_recent)

    def clear_recent(self) -> None:
        if self.store is not None:
            self.store.clear()

    # --- opening ----------------------------------------------------------------

    def open_project_dialog(self) -> "UNITITextView | None":
        folder = QFileDialog.getExistingDirectory(
            self._window, "Open USFM Project", self._window._settings.last_directory or ""
        )
        return self.open_project(Path(folder)) if folder else None

    def open_project(self, folder: Path) -> "UNITITextView | None":
        """Open `folder`'s project at the book and reference it was left at."""

        window = self._window
        project = ParatextProject.load(folder)
        if project is None:
            QMessageBox.warning(
                window,
                "Open USFM Project",
                f"{folder}\n\nThis folder isn't a Paratext project: it has no valid Settings.xml.",
            )
            return None
        books = project.books()
        if not books:
            QMessageBox.information(
                window, "Open USFM Project", f"The project {project.name} has no book files in\n{folder}"
            )
            return None
        remembered = self.store.find(project.folder) if self.store is not None else None
        book = next((item for item in books if remembered is not None and item.code == remembered.book), books[0])
        group_id = self._window._project_groups.group(USFM, project.folder) or self._group_for(remembered)
        target = self._target_window(book.path)
        view = target.open_path(book.path)
        if view is None:
            return None
        service = target._service
        entry = None if service is None else service.documents.entry_for_view(view.view_id)
        if group_id is not None and entry is not None and entry.group_id != group_id:
            # The project comes back in the group it was left in.
            target._set_document_group(entry.document_id, group_id)
        if remembered is not None and remembered.book == book.code and remembered.reference:
            _go_to_reference(target, view, remembered.reference)
        if self.store is not None:
            self.store.record_opened(project.folder, project.name, group_id=group_id, book=book.code)
        return view

    def _group_for(self, remembered: "RecentProject | None") -> str | None:
        """The remembered group, if USFM still has it."""

        if remembered is not None and self._window._group_by_id(remembered.group_id, USFM) is not None:
            return remembered.group_id
        return None

    def _target_window(self, book_path: Path) -> "UNITIMainWindow":
        """The USFM window showing this project, else the most recent one,
        else a new one (round 3 T3)."""

        window = self._window
        service = window._service
        if service is None:
            return window
        target = service.environment_window_target(USFM, book_path)
        if target is None:
            target = service.new_environment_window(USFM)
        target.show()
        target.raise_()
        target.activateWindow()
        return target

    # --- remembering where a project was left ------------------------------------

    def note_opened(self, view: "UNITITextView") -> None:
        """A file was opened: if it is a project book, it takes its
        project's group (round 3 T5) and the project is recent."""

        project = project_for_file(view.document.path)
        if project is None:
            return
        service = self._window._service
        entry = None if service is None else service.documents.entry_for_view(view.view_id)
        if entry is not None:
            self._window._groups_and_recent_files.apply_project_group(entry.document_id)
        if self.store is None:
            return
        book = _book_of(project, view.document.path)
        try:
            self.store.record_opened(project.folder, project.name, group_id=self._group_of(view), book=book)
        except (OSError, ValueError):
            logger.warning("could not record recent project %s", project.folder, exc_info=True)

    def note_caret(self, view: "UNITITextView") -> None:
        """The caret moved in the active tab; remember its place shortly."""

        self._pending = view
        self._timer.start()

    def _save_position(self) -> None:
        view = self._pending
        self._pending = None
        if view is None or self.store is None or self._window.view_for_id(view.view_id) is not view:
            return
        project = project_for_file(view.document.path)
        if project is None or self.store.find(project.folder) is None:
            return
        reference_map = self._window._reference_sync.maps.for_document(view.document)
        if reference_map is None:
            return
        reference = reference_map.reference_at(view.state.cursor)
        text = None
        if reference.chapter is not None:
            text = reference.chapter if reference.verse is None else f"{reference.chapter}:{reference.verse}"
        try:
            self.store.update(
                project.folder,
                book=reference_map.book or _book_of(project, view.document.path),
                reference=text,
                group_id=self._group_of(view),
            )
        except (OSError, ValueError):
            logger.warning("could not remember project position", exc_info=True)

    def _group_of(self, view: "UNITITextView") -> str | None:
        service = self._window._service
        entry = None if service is None else service.documents.entry_for_view(view.view_id)
        return None if entry is None else entry.group_id


def _book_of(project: ParatextProject, path: Path) -> str | None:
    book = next((item for item in project.books() if _same(item.path, path)), None)
    return None if book is None else book.code


def _same(first: Path, second: Path) -> bool:
    try:
        return first.resolve() == second.resolve()
    except OSError:
        return first == second


def _go_to_reference(window: "UNITIMainWindow", view: "UNITITextView", reference: str) -> None:
    reference_map = window._reference_sync.maps.for_document(view.document)
    if reference_map is None:
        return
    chapter, _, verse = reference.partition(":")
    found = reference_map.find(chapter, verse) if verse else None
    offset = found.start if found is not None else reference_map.chapter_start(chapter)
    if offset is None:
        return
    view.state.move_to(min(offset, view.document.total_chars()))
    view._state_changed()


def is_project_book(path: Path) -> bool:
    """Whether `path` sits in a Paratext project folder."""

    return project_for_file(Path(path)) is not None


__all__ = ["UsfmProjectController", "is_project_book"]
