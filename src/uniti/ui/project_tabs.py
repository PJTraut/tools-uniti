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
unsaved changes and this is its last view it asks first (book-lock plan
D4): Save, or Discard, which closes the book without saving.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from uniti.core.environments.catalog import PROJECT_ENVIRONMENTS
from uniti.core.environments.sfm.paratext_project import ParatextProject, project_for_file

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.panes import PaneLeaf
    from uniti.ui.text_view import UNITITextView


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
        # (pane id, project folder) -> whether Check Spelling is on for the
        # tab (spellcheck plan D3). A tab seen for the first time takes it
        # from its books (a restored session, a moved tab).
        self._spelling: dict[tuple[str, str], bool] = {}

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
            members = self.members(leaf)
            for tab in [tab for tab in self._spelling if tab[0] == leaf.pane_id and tab[1] not in members]:
                del self._spelling[tab]  # a closed tab forgets its setting
            for key, books in members.items():
                ids = [book.view_id for book in books]
                remembered = self._current.get((leaf.pane_id, key))
                if selected in ids:
                    shown = selected
                elif remembered in ids:
                    shown = remembered
                else:
                    shown = ids[0]
                self._current[(leaf.pane_id, key)] = shown
                self._sync_spelling((leaf.pane_id, key), books)
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

    def _sync_spelling(self, tab: tuple[str, str], books: list["UNITITextView"]) -> None:
        """Every book of a tab has the tab's Check Spelling setting: books
        that join take it from the tab; a tab seen first takes it from its
        books (any one on turns it on)."""

        setting = self._spelling.get(tab)
        if setting is None:
            setting = self._spelling[tab] = any(book.check_spelling for book in books)
        for book in books:
            if book.check_spelling != setting:
                book.check_spelling = setting
            self._window._spelling.apply(book)

    def set_spelling(self, view: "UNITITextView", enabled: bool) -> None:
        """Check Spelling for `view`'s whole tab."""

        leaf = self._window._panes.leaf_for_view(view.view_id)
        if leaf is None:
            return
        self._spelling[(leaf.pane_id, self._key(view))] = enabled
        for book in self.books_of(view):
            book.check_spelling = enabled
            self._window._spelling.apply(book)

    def forget_spelling(self, pane_id: str) -> None:
        for key in [key for key in self._spelling if key[0] == pane_id]:
            del self._spelling[key]

    def label(self, view: "UNITITextView", books: list["UNITITextView"] | None = None) -> str:
        """The tab's title: the project's short name, starred while any of
        its books in the tab has unsaved changes."""

        project = self.project_of(view)
        name = project.name if project is not None else view.document.path.name
        books = books if books is not None else self.books_of(view)
        lock = "🔒 " if view.document.read_only or view.document.locked else ""  # read-only folder (T7), locked book
        return lock + name + ("*" if any(book.document.modified for book in books) else "")

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
        self.forget_spelling(pane_id)


def _resolved(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


__all__ = ["ProjectTabs", "book_code"]
