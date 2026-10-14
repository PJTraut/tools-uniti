"""Check Spelling: the per-project-tab toggle (spellcheck plan S5, D3, D4, D7).

A tab's setting lives on its books (`UNITITextView.check_spelling`, saved
in each book's view `extra`); `ProjectTabs` keeps every book of a tab in
step. The word lists load on a worker the first time a tab turns checking
on and are re-read when their files change. One `SpellingCache` per
document serves every view of it.
"""

from __future__ import annotations

import weakref
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction

from uniti.core.environments.sfm.paratext_project import project_for_file
from uniti.core.environments.sfm.spellcheck import CheckContext, SpellingCache
from uniti.core.environments.sfm.spelling import (
    HYPHENATED_WORDS_FILE,
    SPELLING_STATUS_FILE,
    SpellingList,
    lists_changed,
    spelling_list_for,
)
from uniti.resources import TaskKind, TaskSpec
from uniti.ui.task_bridge import TaskBridge

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

# One cache per document, shared by every view and window.
_CACHES: "weakref.WeakKeyDictionary[object, SpellingCache]" = weakref.WeakKeyDictionary()


def has_spelling_list(folder: Path) -> bool:
    """Whether the project has either word list (D4)."""

    return (Path(folder) / SPELLING_STATUS_FILE).exists() or (Path(folder) / HYPHENATED_WORDS_FILE).exists()


def _styles_for(document_path: Path):
    from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
    from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline

    return LayeredStyleRegistry(build_layers(load_usfm_baseline(), Path(document_path)))


class SpellingController(QObject):
    """One window's Check Spelling toggle and the plumbing behind it."""

    def __init__(self, window: "UNITIMainWindow") -> None:
        super().__init__(window)
        self._window = window
        self._pending: dict[str, list] = {}
        self._bridge = TaskBridge(window._resources.tasks, self)
        self._bridge.taskFinished.connect(self._task_finished, Qt.ConnectionType.QueuedConnection)
        self.action = QAction("Check Spelling", window)
        self.action.setCheckable(True)
        self.action.triggered.connect(lambda checked: self.set_tab(window.current_view, checked))

    # --- what a view can do --------------------------------------------------------

    @staticmethod
    def project_of(view: "UNITITextView"):
        return None if view is None else project_for_file(view.document.path)

    def describe(self, view: "UNITITextView | None") -> tuple[bool, bool, str]:
        """(enabled, checked, tooltip) of the toggle for `view`'s tab."""

        project = self.project_of(view)
        if view is None or project is None or not self._window._project_tabs.active:
            return False, False, "Check Spelling works on a Paratext project's tab in a USFM window"
        if not has_spelling_list(project.folder):
            return False, False, f"{project.name} has no spelling list ({SPELLING_STATUS_FILE} or {HYPHENATED_WORDS_FILE})"
        return True, bool(view.check_spelling), "Underline wrong and unknown words, from Paratext's spelling lists"

    def refresh(self) -> None:
        enabled, checked, tooltip = self.describe(self._window.current_view)
        self.action.setEnabled(enabled)
        self.action.blockSignals(True)
        self.action.setChecked(checked)
        self.action.blockSignals(False)
        self.action.setToolTip(tooltip)

    def make_action(self, view: "UNITITextView", parent) -> QAction:
        enabled, checked, tooltip = self.describe(view)
        action = QAction("Check Spelling", parent)
        action.setCheckable(True)
        action.setChecked(checked)
        action.setEnabled(enabled)
        action.setToolTip(tooltip)
        action.triggered.connect(lambda state: self.set_tab(view, state))
        return action

    # --- the tab's setting -----------------------------------------------------------

    def set_tab(self, view: "UNITITextView | None", enabled: bool) -> None:
        """Turn Check Spelling on or off for `view`'s project tab: every
        book in it, and the books that join it later."""

        if view is None or not self.describe(view)[0]:
            self.refresh()
            return
        self._window._project_tabs.set_spelling(view, bool(enabled))
        self.refresh()

    def apply(self, view: "UNITITextView") -> None:
        """Make `view` (and its rich pane) show or hide the underlines to
        match its setting; idempotent."""

        wanted = bool(view.check_spelling) and self.describe(view)[0]
        if not wanted:
            self._attach(view, None)
            return
        project = self.project_of(view)
        folder = str(project.folder)
        if lists_changed(project.folder):
            self._load(project.folder, view)
            return
        self._attach(view, self._cache_for(view.document, spelling_list_for(project.folder), project))

    def _attach(self, view: "UNITITextView", cache: SpellingCache | None) -> None:
        if view.spelling is cache:
            return
        view.set_spelling(cache)
        pane = self._window._rich_views.pane_for(view)
        if pane is not None:
            pane.set_spelling(cache)

    def _cache_for(self, document, words: SpellingList, project) -> SpellingCache:
        cache = _CACHES.get(document)
        context = CheckContext(words, _styles_for(document.path), project.name)
        if cache is None:
            cache = _CACHES[document] = SpellingCache(document, context)
        elif cache.context.words is not words:
            cache.set_context(context)
        return cache

    # --- loading the lists off the UI thread ----------------------------------------------

    def _load(self, folder: Path, view: "UNITITextView") -> None:
        key = str(folder)
        waiting = self._pending.get(key)
        if waiting is not None:
            return  # already loading; the finish re-applies every view of the project
        self._pending[key] = []
        spec = TaskSpec.create(TaskKind.SPELLING, foreground=False, estimated_memory_bytes=32 << 20)
        handle = self._window._resources.tasks.submit(spec, lambda _context: spelling_list_for(folder))
        self._pending[key] = [handle, folder]
        self._bridge.watch(handle)

    def _task_finished(self, handle) -> None:
        for key, entry in list(self._pending.items()):
            if entry and entry[0] is handle:
                del self._pending[key]
                folder = entry[1]
                break
        else:
            return
        try:
            handle.future.result()
        except Exception:
            return  # the lists couldn't be read: nothing is underlined
        for window in self._windows():
            for view in window.views:
                project = project_for_file(view.document.path)
                if project is not None and Path(project.folder) == Path(folder):
                    window._spelling.apply(view)

    def _windows(self):
        service = self._window._service
        if service is None:
            return [self._window]
        return [window for _window_id, window in service.windows.items]

    def shutdown(self) -> None:
        """The window is closing: stop listening to the task coordinator."""

        self._pending.clear()
        self._bridge.close()

    def window_activated(self) -> None:
        """The window became active: re-read lists Paratext changed, and
        bring the underlines of its Standard and Preview up to date (D7)."""

        for view in self._window.views:
            if not view.check_spelling:
                continue
            self.apply(view)
            pane = self._window._rich_views.pane_for(view)
            if pane is not None:
                pane._apply_highlights()


__all__ = ["SpellingController", "has_spelling_list"]
