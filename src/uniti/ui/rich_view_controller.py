"""Window-side lifecycle of the rich-view pane (ADR-0015, Phase E7 view switcher).

One rich pane per window, beside the editor pane tree, bound to the active
tab. The choice is per tab (`UNITITextView.rich_view_key`, saved in the
session): switching tabs shows that tab's own rich view or hides the pane,
and a tab whose environment no longer offers its view (Plain Text Mode,
reassignment) just hides it until the view is available again. Choosing
"Source Only" (or the pane's ×) clears the tab's choice. Caret and selection
follow both ways.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtWidgets import QApplication

from uniti.app.editor_state import EditorStateSnapshot
from uniti.core.rich_views.provider import EditorViewProvider, environment_view_providers

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.rich_view import RichViewPane
    from uniti.ui.text_view import UNITITextView


class RichViewController:
    def __init__(self, window: "UNITIMainWindow") -> None:
        self._window = window
        self.pane: RichViewPane | None = None
        self.target_view: UNITITextView | None = None
        self._pushing_caret = False

    @property
    def current_key(self) -> str | None:
        if self.pane is None or self.pane.provider is None:
            return None
        return self.pane.provider.key

    def providers_for(self, view: "UNITITextView | None") -> tuple[EditorViewProvider, ...]:
        environment = self._window._environment
        if view is None or environment.is_plain_mode(view):
            return ()
        return environment_view_providers(environment.active_for(view.document).environment)

    def _dark(self) -> bool:
        app = QApplication.instance()
        if app is None:
            return False
        return app.palette().window().color().lightness() < 128

    def show(self, provider_key: str, view: "UNITITextView | None" = None) -> bool:
        view = view if view is not None else self._window.current_view
        providers = self.providers_for(view)
        if view is None or not any(provider.key == provider_key for provider in providers):
            return False
        view.rich_view_key = provider_key
        if self.pane is None:
            from uniti.ui.rich_view import RichViewPane

            splitter = self._window._central_splitter
            self.pane = RichViewPane(splitter)
            splitter.addWidget(self.pane)
            splitter.setSizes([1, 1])
            self.pane.caretSourceChanged.connect(self._push_caret_to_source)
            self.pane.closeRequested.connect(self.close)
            self.pane.providerChangeRequested.connect(lambda key: self.show(key))
            self.pane.document_applied = self._after_rich_edit
        self.target_view = view
        self.pane.bind(view.document, providers, provider_key, self._font_for(provider_key, providers, view), self._dark())
        self.pane.show_source_caret(view.state.cursor, view.state.anchor)
        self._window._environment.refresh()
        return True

    @staticmethod
    def _font_for(provider_key: str, providers, view):
        """Proportional UI font for formatted views, the editor's own font
        (monospace) where markers should line up with the source."""

        provider = next(p for p in providers if p.key == provider_key)
        font = view.font()
        if getattr(provider, "proportional", False):
            from PySide6.QtGui import QFont

            ui_font = QFont(QApplication.font())
            if font.pointSizeF() > 0:
                ui_font.setPointSizeF(font.pointSizeF() * 1.1)
            return ui_font
        return font

    def close(self) -> None:
        """Source Only for the current tab: forget its rich-view choice."""

        if self.target_view is not None:
            self.target_view.rich_view_key = None
        self._hide()

    def _hide(self) -> None:
        if self.pane is None:
            return
        self.pane.unbind()
        self.pane.setParent(None)
        self.pane.deleteLater()
        self.pane = None
        self.target_view = None
        self._window._environment.refresh()

    def _after_rich_edit(self) -> None:
        document = self.pane.document if self.pane is not None else None
        for view in self._window.views:
            if view.document is document:
                view._state_changed()

    def _push_caret_to_source(self, cursor: int, anchor: int) -> None:
        view = self.target_view
        if view is None or self._window.view_for_id(view.view_id) is None:
            return
        self._pushing_caret = True
        try:
            view.state.restore_state(EditorStateSnapshot(cursor, anchor, None))
            view._state_changed()
        finally:
            self._pushing_caret = False

    # --- window events ----------------------------------------------------------

    def on_view_state_changed(self, view: "UNITITextView") -> None:
        if self.pane is not None and view is self.target_view and not self._pushing_caret:
            self.pane.show_source_caret(view.state.cursor, view.state.anchor)

    def on_current_view_changed(self, view: "UNITITextView | None") -> None:
        """Show the newly active tab's own rich view, or hide the pane."""

        key = None if view is None else view.rich_view_key
        if key is not None and any(provider.key == key for provider in self.providers_for(view)):
            if self.pane is None or self.target_view is not view or self.current_key != key:
                self.show(key, view)
        else:
            self._hide()

    def on_environment_changed(self, view: "UNITITextView | None") -> None:
        """Plain Text Mode / reassignment / pinning changed `view`'s environment."""

        if view is not None and view is self._window.current_view:
            if self.pane is not None and self.target_view is view:
                self._hide()
            self.on_current_view_changed(view)
