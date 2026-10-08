"""One tab per project in a USFM window (field test round 3, T4).

In an environment window of a project environment (USFM), each split shows
one tab per Paratext project. Every open book is still its own
`UNITITextView` and its own tab, so undo history, caret, scroll, view mode,
session capture, Find/Replace and transfer keep working on it; only the
project's current book has a visible tab (`setTabVisible`, as Grouped Tabs
does). The visible tab is titled with the project's short name and sits
where the project's first tab is, so changing the book doesn't move it.

Changing the book (the toolbar's Book list) shows another book in the same
tab: its hidden tab, or a newly opened one. When the current book has
unsaved changes it asks first (D1): Yes saves; No keeps the changes in the
book, which stays open, hidden in the tab.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtWidgets import QMessageBox

from uniti.core.environments.catalog import PROJECT_ENVIRONMENTS
from uniti.core.environments.sfm.paratext_project import ParatextProject, project_for_file

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.panes import PaneLeaf
    from uniti.ui.text_view import UNITITextView


def ask_save_before_switch(parent, view: "UNITITextView", project_name: str) -> bool:
    """Ask whether to save `view`'s unsaved changes before another book is
    shown in its tab; True for Yes. Tests replace this."""

    book = book_code(view) or view.document.path.name
    answer = QMessageBox.question(
        parent,
        "Change Book",
        f"Save changes to {book} ({project_name})?\n\n"
        "No keeps the changes: the book stays open in the tab, unsaved.",
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        QMessageBox.StandardButton.Yes,
    )
    return answer == QMessageBox.StandardButton.Yes


def book_code(view: "UNITITextView") -> str | None:
    from uniti.core.environments.sfm.references import ID_PROBE_BYTES, book_header

    document = view.document
    return book_header(document.read(0, min(document.total_chars(), ID_PROBE_BYTES))).code


class ProjectTabs:
    """The project tabs of one window's splits."""

    def __init__(self, window: "UNITIMainWindow") -> None:
        self._window = window
        # (pane id, project folder) -> the project's current book there.
        self._current: dict[tuple[str, str], str] = {}
        self._modified: dict[str, bool] = {}
        self._refreshing = False

    @property
    def active(self) -> bool:
        identity = self._window.environment_window
        return identity is not None and identity[0] in PROJECT_ENVIRONMENTS

    # --- model --------------------------------------------------------------------

    @staticmethod
    def project_of(view: "UNITITextView") -> ParatextProject | None:
        return project_for_file(view.document.path)

    @staticmethod
    def _key(view: "UNITITextView") -> str:
        project = project_for_file(view.document.path)
        path = Path(view.document.path)
        return str((project.folder if project is not None else path).resolve())

    def _views(self, leaf: "PaneLeaf") -> list["UNITITextView"]:
        from uniti.ui.text_view import UNITITextView

        views = []
        for view_id in leaf.view_ids:
            view = self._window.view_for_id(view_id)
            if isinstance(view, UNITITextView):
                views.append(view)
        return views

    def members(self, leaf: "PaneLeaf") -> dict[str, list["UNITITextView"]]:
        """Per project (by folder), its books open in `leaf`, in tab order."""

        found: dict[str, list[UNITITextView]] = {}
        for view in self._views(leaf):
            found.setdefault(self._key(view), []).append(view)
        return found

    def books_of(self, view: "UNITITextView") -> list["UNITITextView"]:
        """The books open in `view`'s tab: its project's, in its split."""

        leaf = self._window._panes.leaf_for_view(view.view_id)
        if leaf is None or not self.active:
            return [view]
        return self.members(leaf).get(self._key(view), [view])

    def book_in_tab(self, view: "UNITITextView", path: Path) -> "UNITITextView | None":
        """The book at `path` if it's open in `view`'s tab."""

        target = _resolved(path)
        return next((book for book in self.books_of(view) if _resolved(book.document.path) == target), None)

    # --- presentation ----------------------------------------------------------------

    def refresh_all(self) -> None:
        panes = self._window._panes
        for pane_id in panes.pane_ids:
            try:
                self.refresh_leaf(panes.leaf(pane_id))
            except (KeyError, ValueError):
                continue

    def refresh_leaf(self, leaf: "PaneLeaf") -> None:
        """Show one tab per project in `leaf`: its current book's, at the
        project's first tab position, titled with the short name."""

        if self._refreshing or leaf is None:
            return
        if not self.active:
            return
        self._refreshing = True
        try:
            tab_bar = leaf.tabBar()
            selected = leaf.selected_view_id
            for key, books in self.members(leaf).items():
                ids = [book.view_id for book in books]
                remembered = self._current.get((leaf.pane_id, key))
                if selected in ids:
                    shown = selected
                elif remembered in ids:
                    shown = remembered
                else:
                    shown = ids[0]
                self._current[(leaf.pane_id, key)] = shown
                first = min(leaf.index_of(view_id) for view_id in ids)
                index = leaf.index_of(shown)
                if index != first:
                    tab_bar.moveTab(index, first)
                for view_id in ids:
                    tab_bar.setTabVisible(leaf.index_of(view_id), view_id == shown)
                index = leaf.index_of(shown)
                shown_view = next(book for book in books if book.view_id == shown)
                leaf.setTabText(index, self.label(shown_view, books))
                leaf.setTabToolTip(index, self.tooltip(shown_view))
                set_tint = getattr(tab_bar, "set_tab_tint", None)
                if callable(set_tint):
                    # The project's group colours its tab (T5).
                    for view_id in ids:
                        set_tint(view_id, self.group_color(shown_view) if view_id == shown else None)
        finally:
            self._refreshing = False

    def label(self, view: "UNITITextView", books: list["UNITITextView"] | None = None) -> str:
        """The tab's title: the project's short name, starred while any of
        its books in the tab has unsaved changes."""

        project = self.project_of(view)
        name = project.name if project is not None else view.document.path.name
        books = books if books is not None else self.books_of(view)
        return name + ("*" if any(book.document.modified for book in books) else "")

    def group_color(self, view: "UNITITextView") -> str | None:
        window = self._window
        service = window._service
        entry = None if service is None else service.documents.entry_for_view(view.view_id)
        if entry is None or entry.group_id is None:
            return None
        group = window._group_by_id(entry.group_id, window._environment.environment_key_for(view.document))
        return None if group is None else group.color

    def tooltip(self, view: "UNITITextView") -> str:
        code = book_code(view)
        return f"{code}\n{view.document.path}" if code else str(view.document.path)

    def note_state(self, view: "UNITITextView", leaf: "PaneLeaf") -> None:
        """A book's state changed: retitle its tab when its unsaved state
        did (the star), without redoing the tabs on every caret move."""

        modified = view.document.modified
        if self._modified.get(view.view_id) is modified:
            return
        self._modified[view.view_id] = modified
        self.refresh_leaf(leaf)

    def forget(self, pane_id: str) -> None:
        for key in [key for key in self._current if key[0] == pane_id]:
            del self._current[key]


def _resolved(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


__all__ = ["ProjectTabs", "ask_save_before_switch", "book_code"]
