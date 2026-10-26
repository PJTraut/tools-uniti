"""Show One Chapter: the USFM per-chapter view, per environment window
(plan 2026-10-09).

The shown chapter is the one the caret is in; nothing else is stored. A
move the user makes in a view stays in its chapter (`UNITITextView` and
`RichViewPane` keep it there); any other move — the Chapter selector, Go
to Chapter:Verse, sync, Find, undo — puts the caret in another chapter, and
the view follows it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from uniti.core.environments.sfm.references import chapter_window
from uniti.ui.environment_window import REFERENCE_ENVIRONMENTS

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView


class ChapterView(QObject):
    """One window's Show One Chapter toggle, and every view's line window."""

    def __init__(self, window: "UNITIMainWindow") -> None:
        super().__init__(window)
        self._window = window
        self.action = QAction("Show One Chapter", window)
        # On the environment toolbar it's the "Chapter" before the Chapter selector.
        self.action.setIconText("CH")
        self.action.setCheckable(True)
        self.action.setToolTip(
            "Show only the chapter the caret is in, in every mode. The Chapter selector, sync, "
            "Go to Chapter:Verse and Find change the chapter."
        )
        self.action.toggled.connect(lambda _checked: self.refresh())

    @property
    def enabled(self) -> bool:
        return self.action.isChecked()

    def set_enabled(self, enabled: bool) -> None:
        self.action.setChecked(bool(enabled))

    def refresh(self) -> None:
        """Every tab of this window shows its chapter, or its whole text."""

        for view in self._window.views:
            view.refresh_line_window()
            pane = self._window._rich_views.pane_for(view)
            if pane is not None:
                pane.apply_window()

    def line_window(self, view: "UNITITextView") -> tuple[int, int] | None:
        """`view`'s chapter lines when the window it's in shows one chapter
        (every view's `line_window_provider`; a tab moved to another window
        follows that window's toggle)."""

        service = self._window._service
        window = None if service is None else service.windows.window_for_view(view.view_id)
        chapter_view = getattr(window if window is not None else self._window, "_chapter_view", None)
        if chapter_view is None or not chapter_view.enabled:
            return None
        environment = chapter_view._window._environment
        if environment.is_plain_mode(view) or environment.environment_key_for(view.document) not in REFERENCE_ENVIRONMENTS:
            return None  # a tab opened as Plain Text has no USFM features
        # The window's own maps, shared with its toolbar and sync; None above 1 MiB.
        reference_map = chapter_view._window._reference_sync.maps.for_document(view.document)
        if reference_map is None or not reference_map.chapter_lines:
            return None
        line = view.document.line_for_char(view.state.cursor)
        return chapter_window(reference_map.chapter_lines, line, reference_map.line_count)


__all__ = ["ChapterView"]
