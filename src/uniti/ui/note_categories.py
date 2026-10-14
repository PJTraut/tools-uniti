r"""Footnote Categories: which notes Preview shows (plan 2026-10-14-footnote-category-filter).

A note's categories are the words inside its `\cat aa bb cc\cat*`; a note
with none is "None". The checked entries are shown; unchecking one leaves
the notes whose categories are all unchecked out of Preview, caller and
body. The setting is per project tab, like Check Spelling.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu

from uniti.core.environments.catalog import PROJECT_ENVIRONMENTS
from uniti.core.environments.sfm.paratext_project import project_for_file
from uniti.core.environments.sfm.views import NO_CATEGORY, source_note_categories

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

_TOOLTIP = "Choose which footnote categories Preview shows. The source and Standard keep every note."


def category_label(category: str) -> str:
    return "None" if category == NO_CATEGORY else category


class NoteCategories:
    """One window's Footnote Categories menu."""

    def __init__(self, window: "UNITIMainWindow") -> None:
        self._window = window
        self.menu = QMenu("Footnote Categories", window)
        self.menu.setToolTipsVisible(True)
        self.menu.aboutToShow.connect(lambda: self.fill(self.menu, window.current_view))

    def applies_to(self, view: "UNITITextView | None") -> bool:
        return (
            view is not None
            and self._window._project_tabs.active
            and self._window._environment.environment_key_for(view.document) in PROJECT_ENVIRONMENTS
            and project_for_file(view.document.path) is not None
        )

    def categories_of(self, view: "UNITITextView") -> list[str]:
        """What to list: the book's categories, then any hidden ones the
        book lacks (so they can be shown again), "None" always present."""

        document = view.document
        found = list(source_note_categories(document.read(0, document.total_chars())))
        for category in sorted(view.hidden_note_categories):
            if category not in found and category != NO_CATEGORY:
                found.append(category)
        if NO_CATEGORY in found:
            found.remove(NO_CATEGORY)
        return found + [NO_CATEGORY]

    def fill(self, menu: QMenu, view: "UNITITextView | None") -> None:
        menu.clear()
        if not self.applies_to(view):
            action = menu.addAction("Footnote Categories")
            action.setEnabled(False)
            action.setToolTip("Footnote categories are chosen on a Paratext project's tab in a USFM window")
            return
        hidden = frozenset(view.hidden_note_categories)
        for category in self.categories_of(view):
            action = QAction(category_label(category), menu)
            action.setCheckable(True)
            action.setChecked(category not in hidden)
            action.setToolTip(_TOOLTIP)
            action.triggered.connect(lambda checked, category=category: self.set_shown(view, category, checked))
            menu.addAction(action)
        menu.addSeparator()
        show_all = menu.addAction("Show All")
        show_all.setEnabled(bool(hidden))
        show_all.triggered.connect(lambda _checked=False: self._window._project_tabs.set_note_filter(view, frozenset()))

    def set_shown(self, view: "UNITITextView", category: str, shown: bool) -> None:
        hidden = set(view.hidden_note_categories)
        if shown:
            hidden.discard(category)
        else:
            hidden.add(category)
        self._window._project_tabs.set_note_filter(view, frozenset(hidden))

    def make_menu(self, view: "UNITITextView", parent) -> QMenu:
        """A submenu of its own for a right-click menu on `view`."""

        menu = QMenu("Footnote Categories", parent)
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(lambda: self.fill(menu, view))
        return menu
