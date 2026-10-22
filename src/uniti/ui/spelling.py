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
from uniti.core.environments.sfm.spellcheck import WORD_RE, CheckContext, Span, SpellingCache, word_frequencies
from uniti.core.environments.sfm.spelling import (
    HYPHENATED_WORDS_FILE,
    SPELLING_STATUS_FILE,
    SpellingList,
    SpellingState,
    effective_spelling_list,
    lists_changed,
    spelling_list_for,
)
from uniti.core.environments.sfm.user_words import user_words_for
from uniti.resources import TaskKind, TaskSpec
from uniti.ui.task_bridge import TaskBridge

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

# One cache per document, shared by every view and window.
_CACHES: "weakref.WeakKeyDictionary[object, SpellingCache]" = weakref.WeakKeyDictionary()
# A document's word counts and the revision they were made at, for ranking suggestions.
_FREQUENCIES: "weakref.WeakKeyDictionary[object, tuple[int, dict[str, int]]]" = weakref.WeakKeyDictionary()


def frequencies_of(document) -> dict[str, int]:
    """The document's word counts, made again only after it changed."""

    cached = _FREQUENCIES.get(document)
    if cached is None or cached[0] != document.revision:
        cached = _FREQUENCIES[document] = (
            document.revision,
            word_frequencies(document.read(0, document.total_chars())),
        )
    return cached[1]


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
        self.next_action = window._command_action(
            "spelling.next_issue", lambda: self.go_to_issue(window.current_view, True)
        )
        self.previous_action = window._command_action(
            "spelling.previous_issue", lambda: self.go_to_issue(window.current_view, False)
        )
        # Attached to the window, like the environment slots, so the shortcuts
        # resolve whichever menu the entries are in; they're off unless
        # checking is on (`refresh`).
        window.addAction(self.next_action)
        window.addAction(self.previous_action)

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
        for action in (self.next_action, self.previous_action):
            action.setEnabled(enabled and checked)
            action.setToolTip("Move to the next or previous wrong or unknown word of the shown book")

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
        if lists_changed(project.folder):
            self._load(project.folder, view)
            return
        self._attach(view, self._cache_for(view.document, effective_spelling_list(project), project))

    def _attach(self, view: "UNITITextView", cache: SpellingCache | None) -> None:
        if view.spelling is cache:
            return
        view.set_spelling(cache)
        pane = self._window._rich_views.pane_for(view)
        if pane is not None:
            pane.set_spelling(cache)
        if cache is not None and view is self._window.current_view:
            self._window.statusBar().showMessage(self.summary(view), 6000)

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

    # --- what is flagged: counts, Next and Previous (F4) ------------------------------

    @staticmethod
    def issues(view: "UNITITextView") -> list[Span]:
        """The shown book's flagged words, in order (none while checking is off)."""

        cache = view.spelling
        return [] if cache is None else list(cache.book_spans())

    def summary(self, view: "UNITITextView") -> str:
        """"GEN: 2 wrong, 14 unknown words" for the status bar."""

        spans = self.issues(view)
        code = view.document.path.stem
        project = self.project_of(view)
        if not spans:
            return f"{code}: no spelling issues" if project is None else f"{code} ({project.name}): no spelling issues"
        unknown = sum(1 for span in spans if span.spelling.state is SpellingState.UNKNOWN)
        wrong = len(spans) - unknown
        return f"{code}: {wrong} wrong, {unknown} unknown word{'' if unknown == 1 else 's'}"

    def go_to_issue(self, view: "UNITITextView | None", forward: bool) -> bool:
        """Select the next (or previous) flagged word after (before) the
        caret, wrapping round the book; every mode and synced window
        follows the caret."""

        if view is None or view.spelling is None:
            return False
        spans = self.issues(view)
        bar = self._window.statusBar()
        if not spans:
            bar.showMessage(self.summary(view), 6000)
            return False
        state = view.state
        low, high = min(state.cursor, state.anchor), max(state.cursor, state.anchor)
        wrapped = False
        if forward:
            index = next((i for i, span in enumerate(spans) if span.start >= high), None)
            if index is None:
                index, wrapped = 0, True
        else:
            index = next((i for i in range(len(spans) - 1, -1, -1) if spans[i].start < low), None)
            if index is None:
                index, wrapped = len(spans) - 1, True
        span = spans[index]
        view._select_range(span.start, span.end)
        kind = "unknown" if span.spelling.state is SpellingState.UNKNOWN else "wrong"
        word = view.document.read(span.start, span.end)
        note = " (wrapped round the book)" if wrapped else ""
        bar.showMessage(f"Spelling issue {index + 1} of {len(spans)}: {kind} “{word}”{note}", 6000)
        return True

    # --- the right-click entries (F1, F2) ---------------------------------------------

    def span_at(self, view: "UNITITextView", offset: int | None) -> Span | None:
        """The flagged word at a document offset (or just before it: the
        caret lands after a word's last letter)."""

        if offset is None or view.spelling is None:
            return None
        spans = view.spelling.book_spans()
        for position in (offset, offset - 1):
            found = spans.overlapping(position, position + 1) if position >= 0 else []
            if found:
                return found[0]
        return None

    def add_context_entries(
        self, menu, view: "UNITITextView", offset: int | None, *, editable: bool
    ) -> None:
        """At the top of `menu`, for a flagged word at `offset`: Paratext's
        correction and the suggestions (when `editable`), then Approve, Mark
        Wrong and Remove, for your own spelling list."""

        span = self.span_at(view, offset)
        project = self.project_of(view)
        if project is None or view.spelling is None:
            return
        document = view.document
        words = view.spelling.context.words
        user = user_words_for(project.name)
        actions: list[QAction] = []
        if span is None:
            pair = self.selected_pair(view)
            if pair is not None:
                text = f"{pair[0]} {pair[1]}"
                if not user.is_rejected(text):
                    reject = QAction(f"Mark “{text}” Wrong Together", menu)
                    reject.setToolTip("Flag these two words whenever they stand together, in your own spelling list")
                    reject.triggered.connect(lambda _checked=False: self.reject(view, text))
                    actions.append(reject)
            self._insert_actions(menu, actions)
            return
        word = document.read(span.start, span.end)
        spelling = span.spelling
        if editable:
            offered: list[str] = []
            if spelling.correction:
                offered.append(spelling.correction)
            if not spelling.pair:
                offered.extend(item for item in words.suggestions(word, frequency=frequencies_of(document)) if item not in offered)
            for item in offered:
                label = f"Use “{item}”" if item == spelling.correction else f"Change to “{item}”"
                action = QAction(label, menu)
                action.triggered.connect(
                    lambda _checked=False, item=item: self.replace_word(view, span, item)
                )
                actions.append(action)
            if actions:
                actions.append(None)
        if not spelling.pair:
            if not user.is_approved(word):
                approve = QAction(f"Approve “{word}”", menu)
                approve.setToolTip("Count this word as correct from now on, in your own spelling list")
                approve.triggered.connect(lambda _checked=False: self.approve(view, word))
                actions.append(approve)
            if not user.is_rejected(word):
                reject = QAction(f"Mark “{word}” Wrong", menu)
                reject.setToolTip("Count this word as wrong from now on, in your own spelling list")
                reject.triggered.connect(lambda _checked=False: self.reject(view, word))
                actions.append(reject)
        elif not user.is_rejected(word):
            approve = QAction(f"Approve “{word}”", menu)
            approve.setToolTip("Count these two words as correct together from now on, in your own spelling list")
            approve.triggered.connect(lambda _checked=False: self.approve(view, word))
            actions.append(approve)
        if word in user:
            forget = QAction(f"Remove “{word}” from Your Spelling List", menu)
            forget.triggered.connect(lambda _checked=False: self.forget(view, word))
            actions.append(forget)
        self._insert_actions(menu, actions)

    @staticmethod
    def selected_pair(view: "UNITITextView") -> tuple[str, str] | None:
        """The two words of a selection that is exactly two words separated
        by one space, in Standard (F3)."""

        state = view.state
        low, high = min(state.cursor, state.anchor), max(state.cursor, state.anchor)
        if low == high or high - low > 200:
            return None
        parts = view.document.read(low, high).split(" ")
        if len(parts) != 2 or not all(WORD_RE.fullmatch(part) for part in parts):
            return None
        return parts[0], parts[1]

    @staticmethod
    def _insert_actions(menu, actions: list) -> None:
        while actions and actions[-1] is None:
            actions.pop()
        if not actions:
            return
        existing = menu.actions()
        first = existing[0] if existing else None
        for action in actions:
            if action is None:
                menu.insertSeparator(first) if first is not None else menu.addSeparator()
                continue
            if first is not None:
                menu.insertAction(first, action)
            else:
                menu.addAction(action)
        if first is not None:
            menu.insertSeparator(first)

    def replace_word(self, view: "UNITITextView", span: Span, text: str) -> bool:
        """Replace a flagged word with `text`, unless its book is read-only
        or locked."""

        if self._window._refuse_edit(view):
            return False
        return view.replace_range(span.start, span.end, text)

    def approve(self, view: "UNITITextView", word: str) -> None:
        self._change_user_list(view, lambda words: words.approve(word), f"Approved “{word}”")

    def reject(self, view: "UNITITextView", word: str) -> None:
        self._change_user_list(view, lambda words: words.reject(word), f"Marked “{word}” wrong")

    def forget(self, view: "UNITITextView", word: str) -> None:
        self._change_user_list(view, lambda words: words.forget(word), f"Removed “{word}” from your spelling list")

    def _change_user_list(self, view: "UNITITextView", change, message: str) -> None:
        project = self.project_of(view)
        if project is None:
            return
        change(user_words_for(project.name))
        self.refresh_project(project)
        self._window.statusBar().showMessage(f"{message} in {project.name}'s list of your own words", 6000)

    def refresh_project(self, project) -> None:
        """The project's word lists changed: every view of it, in every
        window, checks again and repaints."""

        for window in self._windows():
            for view in window.views:
                other = project_for_file(view.document.path)
                if other is None or Path(other.folder) != Path(project.folder) or not view.check_spelling:
                    continue
                window._spelling.apply(view)
                view.viewport().update()
                pane = window._rich_views.pane_for(view)
                if pane is not None:
                    pane._apply_highlights()

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
            project = self.project_of(view)
            if project is not None:
                user_words_for(project.name).reload_if_changed()  # another UNITI may have changed it
            self.apply(view)
            pane = self._window._rich_views.pane_for(view)
            if pane is not None:
                pane._apply_highlights()


__all__ = ["SpellingController", "has_spelling_list"]
