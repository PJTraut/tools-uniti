"""Preview Numerals: the numerals a project's Preview shows (2026-11-05).

A choice per Paratext project (stored by project name in the user data
folder), so every book and tab of the project follows it; or a default per
language (the project's language code), which a project without a choice of
its own follows. It changes only
what Preview and the HTML export display; the source and Standard keep the
digits as written.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtGui import QAction, QActionGroup
from PySide6.QtWidgets import QMenu

from uniti.core.environments.catalog import PROJECT_ENVIRONMENTS
from uniti.core.environments.sfm.paratext_project import project_for_file
from uniti.core.numerals import (
    effective_numerals,
    language_numerals,
    numeral_choices,
    project_numerals,
    set_language_numerals,
    set_project_numerals,
)

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

_TOOLTIP = "The numerals Preview shows for every digit of this project. The source and Standard keep the digits as written."


class PreviewNumerals:
    """One window's Preview Numerals menu."""

    def __init__(self, window: UNITIMainWindow) -> None:
        self._window = window
        self.menu = QMenu("Preview Numerals", window)
        self.menu.setToolTipsVisible(True)
        self.menu.aboutToShow.connect(lambda: self.fill(self.menu, window.current_view))

    def project_of(self, view: UNITITextView | None):
        if view is None or self._window._environment.environment_key_for(view.document) not in PROJECT_ENVIRONMENTS:
            return None
        return project_for_file(view.document.path)

    def fill(self, menu: QMenu, view: UNITITextView | None) -> None:
        menu.clear()
        project = self.project_of(view)
        if project is None:
            action = menu.addAction("Preview Numerals")
            action.setEnabled(False)
            action.setToolTip("Numerals are chosen for a Paratext project, from one of its books")
            return
        own = project_numerals(project.name)
        follow = language_numerals(project.language)
        language = (project.language or "").strip()
        shown_as = dict(numeral_choices())[effective_numerals(project.name, project.language)]
        group = QActionGroup(menu)
        if language:
            label = f"Language Default ({language}"
            label += f": {dict(numeral_choices())[follow]})" if follow else ": none)"
        else:
            label = "Language Default (the project sets no language)"
        action = QAction(label, menu)
        action.setCheckable(True)
        action.setChecked(own is None)
        action.setEnabled(bool(language))
        action.setToolTip(f"This project follows its language's choice. Showing: {shown_as}")
        group.addAction(action)
        action.triggered.connect(lambda _checked=False: self.choose(view, None))
        menu.addAction(action)
        menu.addSeparator()
        for system, text in numeral_choices():
            action = QAction(text, menu)
            action.setCheckable(True)
            action.setChecked(system == own)
            action.setToolTip(_TOOLTIP)
            group.addAction(action)
            action.triggered.connect(lambda _checked=False, system=system: self.choose(view, system))
            menu.addAction(action)
        if language:
            menu.addSeparator()
            every = menu.addMenu(f"All {language} Projects")
            every.setToolTipsVisible(True)
            every_group = QActionGroup(every)
            for system, text in (("", "No Default"), *numeral_choices()):
                action = QAction(text, every)
                action.setCheckable(True)
                action.setChecked(system == (follow or ""))
                action.setToolTip(f"The default for every project in {language} that has no choice of its own")
                every_group.addAction(action)
                action.triggered.connect(
                    lambda _checked=False, system=system or None: self.choose_language(view, system)
                )
                every.addAction(action)

    def choose_language(self, view: UNITITextView, system: str | None) -> None:
        project = self.project_of(view)
        if project is None or not (project.language or "").strip():
            return
        set_language_numerals(project.language, system)
        self.refresh_language(project.language)

    def refresh_language(self, language: str | None) -> None:
        wanted = (language or "").strip().lower()
        self._refresh_where(lambda project: (project.language or "").strip().lower() == wanted)

    def choose(self, view: UNITITextView, system: str | None) -> None:
        project = self.project_of(view)
        if project is None:
            return
        set_project_numerals(project.name, system)
        self.refresh_project(project.name)

    def refresh_project(self, name: str) -> None:
        """Re-render every Preview of the project, in every window."""

        self._refresh_where(lambda project: project.name == name)

    def _refresh_where(self, matches) -> None:
        service = self._window._service
        windows = [window for _id, window in service.windows.items] if service is not None else [self._window]
        for window in windows:
            for view in window.views:
                project = project_for_file(view.document.path)
                if project is None or not matches(project):
                    continue
                pane = window._rich_views.pane_for(view)
                if pane is not None:
                    pane.refresh()

    def make_menu(self, view: UNITITextView, parent) -> QMenu:
        menu = QMenu("Preview Numerals", parent)
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(lambda: self.fill(menu, view))
        return menu
