"""Export Preview as HTML: the window's side (text direction plan W8).

The USFM environment declares the command as a host feature, since an
environment command sees the document but not the tab's Preview settings.
This exports the whole book as the tab's Preview shows it: its footnote
category filter, Hyphenate Preview and reading direction apply; Show One
Chapter doesn't (the user, 2026-10-20: "export entire book/document at a
time"). The page itself is `sfm.html_export`'s.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction

from uniti.core.resource_profile import ResourceProfile
from uniti.core.environment_commands import SaveTextFile
from uniti.core.environments.sfm.html_export import export_preview_html
from uniti.core.environments.sfm.paratext_project import project_for_file
from uniti.core.environments.sfm.stylesheet_support import EXPORT_PREVIEW_HTML_FEATURE
from uniti.core.environments.sfm.views import SfmPreviewView, body_font_size
from uniti.ui.rich_view import PROJECTIONS

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

TITLE = "Export Preview as HTML"


class PreviewExport(QObject):
    """One window's Export Preview as HTML… action."""

    def __init__(self, window: "UNITIMainWindow") -> None:
        super().__init__(window)
        self._window = window
        self.action = QAction(f"{TITLE}…", window)
        self.action.setToolTip("Save the whole book as an HTML page, as the Preview shows it")
        self.action.triggered.connect(lambda _checked=False: self.export())
        window._environment.register_host_action(EXPORT_PREVIEW_HTML_FEATURE, self.action)

    def html_for(self, view: "UNITITextView") -> str | None:
        """`view`'s book as the HTML page, or None when it has no Preview."""

        controller = self._window._rich_views
        provider = next(
            (provider for provider in controller.providers_for(view) if isinstance(provider, SfmPreviewView)),
            None,
        )
        if provider is None:
            return None
        document = view.document
        projection = PROJECTIONS.project(
            document,
            provider,
            lambda: document.read(0, document.total_chars()),
            view.hidden_note_categories or None,
            self._window._hyphenation.rules_for(view),
            controller.direction_for(view),
        )
        project = project_for_file(document.path)
        stem = document.path.stem if document.path is not None else "Preview"
        project_name = (project.full_name or project.name) if project is not None else None
        return export_preview_html(
            projection,
            title=f"{stem} — {project_name}" if project_name else stem,
            base_size=body_font_size(provider.styles),
            language=project.language if project is not None else None,
            direction=controller.direction_for(view),
            font=project.default_font if project is not None else None,
        )

    def export(self, view: "UNITITextView | None" = None, path=None) -> bool:
        """Ask where to save `view`'s book (default: the current tab) as HTML
        next to it, and write it; `path` skips the dialog."""

        view = view if view is not None else self._window.current_view
        if view is None:
            return False
        if not ResourceProfile(size_bytes=view.document.source.size).allow_full_parse:
            # Preview itself refuses a book this large.
            self._window.statusBar().showMessage(f"{TITLE}: this book is too large for Preview (above 1 MiB)", 5000)
            return False
        text = self.html_for(view)
        if text is None:
            return False
        stem = view.document.path.stem if view.document.path is not None else "Preview"
        result = SaveTextFile(TITLE, f"{stem}.html", text, "HTML (*.html *.htm);;All Files (*)")
        return self._window._environment.save_text_file(view, result, path)


__all__ = ["PreviewExport", "TITLE"]
