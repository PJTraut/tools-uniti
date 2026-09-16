"""Read-only Markdown preview pane (BF-062).

Scope, confirmed with the user: a read-only preview (not in-place WYSIWYG
editing), placed as a resizable split beside the editor pane tree, updated
on a debounce after the tracked document's text changes. Rendering is Qt's
own `QTextBrowser.setMarkdown` (its CommonMark-subset support, not a full
CommonMark implementation) — tables, footnotes, and other extensions may
render incompletely or not at all.
"""
from __future__ import annotations

from PySide6.QtWidgets import QTextBrowser, QVBoxLayout, QWidget

# Reading the whole document into memory to render it is only reasonable up
# to a bounded size; UNITI's other whole-document operations (reformatters)
# use the same kind of cap for the same reason.
MAX_PREVIEW_CHARS = 2_000_000
_TOO_LARGE_MESSAGE = "*Document is too large to preview.*"


class MarkdownPreviewPane(QWidget):
    """Wraps a read-only `QTextBrowser` rendering the current Markdown text."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._browser = QTextBrowser(self)
        self._browser.setReadOnly(True)
        self._browser.setOpenExternalLinks(False)
        self._browser.setOpenLinks(False)
        self._browser.setAccessibleName("Markdown Preview")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._browser)

    def set_text(self, markdown_text: str) -> None:
        scroll = self._browser.verticalScrollBar()
        position = scroll.value()
        if len(markdown_text) > MAX_PREVIEW_CHARS:
            self._browser.setMarkdown(_TOO_LARGE_MESSAGE)
        else:
            self._browser.setMarkdown(markdown_text)
        scroll.setValue(min(position, scroll.maximum()))
