"""Hyphenate Preview: the per-project-tab toggle (plan
2026-10-15-usfm-hyphenation-and-spelling-followups, H3, H-D2).

A tab's setting lives on its books (`UNITITextView.hyphenate_preview`,
saved in each book's view `extra`); `ProjectTabs` keeps every book of a
tab in step. The project's `hyphenatedWords.txt` is read once (and again
when its file changes) into `HyphenationRules`, which the Preview pane
renders with.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from uniti.core.environments.sfm.hyphenation import (
    HyphenationRules,
    has_hyphenation_list,
    hyphenation_rules_for,
)
from uniti.core.environments.sfm.paratext_project import project_for_file
from uniti.core.environments.sfm.spelling import HYPHENATED_WORDS_FILE

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

_TITLE = "Hyphenate Preview"


class HyphenationController(QObject):
    """One window's Hyphenate Preview toggle."""

    def __init__(self, window: "UNITIMainWindow") -> None:
        super().__init__(window)
        self._window = window
        self.action = QAction(_TITLE, window)
        self.action.setCheckable(True)
        self.action.triggered.connect(lambda checked: self.set_tab(window.current_view, checked))

    @staticmethod
    def project_of(view: "UNITITextView | None"):
        return None if view is None else project_for_file(view.document.path)

    def describe(self, view: "UNITITextView | None") -> tuple[bool, bool, str]:
        """(enabled, checked, tooltip) of the toggle for `view`'s tab."""

        project = self.project_of(view)
        if view is None or project is None or not self._window._project_tabs.active:
            return False, False, "Hyphenate Preview works on a Paratext project's tab in a USFM window"
        if not has_hyphenation_list(project.folder):
            return False, False, f"{project.name} has no hyphenation list ({HYPHENATED_WORDS_FILE})"
        return (
            True,
            bool(view.hyphenate_preview),
            "Break words at the end of a line in Preview, at the points in the project's hyphenation list",
        )

    def rules_for(self, view: "UNITITextView | None") -> HyphenationRules | None:
        """What Preview renders `view` with: the project's rules while the
        tab's toggle is on and the list is there, otherwise None."""

        if view is None or not view.hyphenate_preview or not self.describe(view)[0]:
            return None
        return hyphenation_rules_for(self.project_of(view).folder)

    def refresh(self) -> None:
        enabled, checked, tooltip = self.describe(self._window.current_view)
        self.action.setEnabled(enabled)
        self.action.blockSignals(True)
        self.action.setChecked(checked)
        self.action.blockSignals(False)
        self.action.setToolTip(tooltip)

    def make_action(self, view: "UNITITextView", parent) -> QAction:
        enabled, checked, tooltip = self.describe(view)
        action = QAction(_TITLE, parent)
        action.setCheckable(True)
        action.setChecked(checked)
        action.setEnabled(enabled)
        action.setToolTip(tooltip)
        action.triggered.connect(lambda state: self.set_tab(view, state))
        return action

    def set_tab(self, view: "UNITITextView | None", enabled: bool) -> None:
        """Turn Hyphenate Preview on or off for `view`'s project tab: every
        book in it, and the books that join it later."""

        if view is None or not self.describe(view)[0]:
            self.refresh()
            return
        self._window._project_tabs.set_hyphenation(view, bool(enabled))
        self.refresh()

    def apply(self, view: "UNITITextView") -> None:
        """Make `view`'s Preview pane render with the tab's setting;
        idempotent (the pane re-renders only when the rules changed)."""

        pane = self._window._rich_views.pane_for(view)
        if pane is not None:
            pane.set_hyphenation(self.rules_for(view))

    def window_activated(self) -> None:
        """The window became active: pick up a list Paratext changed."""

        for view in self._window.views:
            if view.hyphenate_preview:
                self.apply(view)


__all__ = ["HyphenationController"]
