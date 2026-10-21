"""Window-side lifecycle of rich views shown in place (ADR-0017).

Plain Text / Standard / Preview are modes of one tab (2026-10-07 field
test: "display plain text/standard/preview in the same window"). A tab in a
rich mode gets its own `RichViewPane`, laid over its Source editor
(`UNITITextView`) as a child widget that fills it; Plain Text removes the
pane. The tab keeps holding the `UNITITextView`, so Find/Replace, save,
recovery, splits, transfer and session capture are unaffected, and the
pane mirrors its caret both ways.

The choice is per tab (`UNITITextView.rich_view_key`, saved in the
session). A tab whose environment stops offering its view (Plain Text
Mode, reassignment) loses the pane but keeps the choice, so the view comes
back when it is available again. The pane follows the Source editor's
zoomed font and theme (zooming in the pane zooms the Source editor).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QApplication

from uniti.app.editor_state import EditorStateSnapshot
from uniti.core.environments.sfm.paratext_project import project_for_file
from uniti.core.environments.sfm.views import SfmPreviewView
from uniti.core.rich_views.provider import EditorViewProvider, environment_view_providers

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.rich_view import RichViewPane
    from uniti.ui.text_view import UNITITextView


class _Fitter(QObject):
    """Keeps each pane covering its Source editor as the editor resizes."""

    def __init__(self, controller: "RichViewController") -> None:
        super().__init__()
        self._controller = controller

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt override
        if event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            pane = self._controller._panes.get(getattr(watched, "view_id", None))
            if pane is not None and pane.target_view is watched:
                pane.setGeometry(watched.rect())
        return False


class RichViewController:
    def __init__(self, window: "UNITIMainWindow") -> None:
        self._window = window
        self._panes: dict[str, RichViewPane] = {}  # view id -> its pane
        self._appearance_slots: dict[str, object] = {}
        self._fitter = _Fitter(self)
        self._pushing_caret = False
        self._showing: set[str] = set()  # views mid-`show()`
        # Environment windows show the mode selector in their toolbar.
        self.pane_mode_selector = True

    # --- lookup -----------------------------------------------------------------

    def pane_for(self, view: "UNITITextView | None") -> "RichViewPane | None":
        if view is None:
            return None
        pane = self._panes.get(view.view_id)
        return pane if pane is not None and pane.target_view is view else None

    @property
    def pane(self) -> "RichViewPane | None":
        """The current tab's pane, if it is in a rich mode."""

        return self.pane_for(self._window.current_view)

    @property
    def target_view(self) -> "UNITITextView | None":
        pane = self.pane
        return None if pane is None else pane.target_view

    @property
    def current_key(self) -> str | None:
        return self.key_for(self._window.current_view)

    def key_for(self, view: "UNITITextView | None") -> str | None:
        """The rich mode `view` is showing now (None: Plain Text)."""

        pane = self.pane_for(view)
        if pane is None or pane.provider is None:
            return None
        return pane.provider.key

    def _context_entries(self, menu, view, pane) -> None:
        """What the host adds to a pane's right-click menu: the spelling
        entries for the word under the click (at the top), Preview's HTML
        export, then the document's own."""

        self._window._spelling.add_context_entries(menu, view, pane.context_source_offset, editable=pane.editable)
        export = getattr(self._window, "_preview_export", None)
        if export is not None and pane.provider is not None and pane.provider.key == SfmPreviewView.key:
            menu.addSeparator()
            menu.addAction(export.action)
        self._window.add_view_context_entries(menu, view)

    def providers_for(self, view: "UNITITextView | None") -> tuple[EditorViewProvider, ...]:
        environment = self._window._environment
        if view is None or environment.is_plain_mode(view):
            return ()
        return environment_view_providers(environment.active_for(view.document).environment)

    # --- mode changes -------------------------------------------------------------

    def show(self, provider_key: str, view: "UNITITextView | None" = None) -> bool:
        view = view if view is not None else self._window.current_view
        providers = self.providers_for(view)
        if view is None or not any(provider.key == provider_key for provider in providers):
            return False
        view.rich_view_key = provider_key
        self._showing.add(view.view_id)
        try:
            pane = self._ensure_pane(view)
            pane.set_hidden_categories(view.hidden_note_categories, refresh=False)
            pane.set_hyphenation(self._window._hyphenation.rules_for(view), refresh=False)
            pane.set_direction(self.direction_for(view), refresh=False)
            pane.bind(view.document, providers, provider_key, *self._appearance(view, provider_key, providers))
            pane.set_spelling(view.spelling)
            pane.show_source_caret(view.state.cursor, view.state.anchor)
            reference_sync = getattr(self._window, "_reference_sync", None)
            if reference_sync is not None:
                reference_sync.restore_highlight(view)
            # Only now hand focus over: the focus change re-activates the
            # tab, and a pane that isn't bound yet would be shown again
            # (rendering the whole book twice).
            if view.focusProxy() is not pane.editor:
                had_focus = view.hasFocus()
                view.setFocusProxy(pane.editor)
                if had_focus:
                    pane.editor.setFocus()
        finally:
            self._showing.discard(view.view_id)
        self._refresh_window_actions()
        return True

    @staticmethod
    def direction_for(view: "UNITITextView | None") -> str | None:
        """The reading direction a rich view gives `view`'s paragraphs
        (text direction plan W-D2): the tab's Auto / Left-to-Right /
        Right-to-Left choice, else its Paratext project's `LeftToRight`
        setting, else None (the text decides)."""

        if view is None:
            return None
        choice = view.text_direction_override
        if choice in ("ltr", "rtl"):
            return choice
        project = project_for_file(view.document.path)
        if project is None or project.right_to_left is None:
            return None
        return "rtl" if project.right_to_left else "ltr"

    def direction_status(self, view: "UNITITextView | None") -> tuple[str, str]:
        """What the status bar says about `view`'s reading direction: the
        label (`RTL`, `LTR`, `Auto`; with the project's when the tab's
        choice overrides a different one) and a tooltip naming its source.
        Plain Text follows only the tab's choice; Standard and Preview also
        the project's (`direction_for`)."""

        if view is None:
            return "—", ""
        words = {"ltr": "left to right", "rtl": "right to left"}
        choice = view.text_direction_override
        menu = "View → Text Direction"
        if self.key_for(view) is None:
            if choice in words:
                return choice.upper(), f"Text direction: {words[choice]}, every line ({menu})."
            return "Auto", f"Text direction: each line's first letter decides ({menu} is Auto)."
        project = project_for_file(view.document.path)
        project_direction = None
        if project is not None and project.right_to_left is not None:
            project_direction = "rtl" if project.right_to_left else "ltr"
        styles = " A style's \\Direction can change a paragraph or a span."
        if choice in words:
            label = choice.upper()
            tooltip = f"Text direction: {words[choice]}, this tab's {menu} choice."
            if project_direction is not None and project_direction != choice:
                label += f" (project {project_direction.upper()})"
                tooltip += f" The project {project.name} is {words[project_direction]}."
            return label, tooltip + styles
        if project_direction is not None:
            return (
                project_direction.upper(),
                f"Text direction: {words[project_direction]}, from the project {project.name}'s settings ({menu} is Auto)."
                + styles,
            )
        return "Auto", f"Text direction: each paragraph's first letter decides ({menu} is Auto, and no project sets one)." + styles

    def apply_direction(self, view: "UNITITextView | None") -> None:
        """Make `view`'s pane lay out with its current direction;
        idempotent (the pane re-renders only when it changed)."""

        pane = self.pane_for(view)
        if pane is not None:
            pane.set_direction(self.direction_for(view))

    def close(self, view: "UNITITextView | None" = None) -> None:
        """Plain Text for `view` (default: the current tab): forget its choice."""

        view = view if view is not None else self._window.current_view
        if view is None:
            return
        view.rich_view_key = None
        had_focus = self.pane_for(view) is not None and view.hasFocus()
        self._remove(view)
        if had_focus:
            view.setFocus()
        self._refresh_window_actions()

    def set_mode(self, key: str | None, view: "UNITITextView | None" = None) -> bool:
        if key is None:
            self.close(view)
            return True
        return self.show(key, view)

    def sync(self, view: "UNITITextView | None") -> None:
        """Make `view`'s pane match its saved choice and environment."""

        if view is None or view.view_id in self._showing:
            return
        key = view.rich_view_key
        if key is not None and any(provider.key == key for provider in self.providers_for(view)):
            if self.key_for(view) != key:
                self.show(key, view)
        elif self.pane_for(view) is not None:
            self._remove(view)
            self._refresh_window_actions()

    def forget(self, view: "UNITITextView") -> None:
        """`view` leaves this window (closed or transferred): drop its pane,
        keep its choice (the receiving window rebuilds it)."""

        self._remove(view)

    # --- panes ----------------------------------------------------------------------

    def catch_up(self) -> None:
        """Re-render the shown panes that were frozen while this window
        was inactive (edits made in another window)."""

        for view in self._window.views:
            pane = self.pane_for(view)
            if pane is not None and pane.stale and pane.isVisible():
                pane.refresh()

    def _ensure_pane(self, view: "UNITITextView") -> "RichViewPane":
        pane = self.pane_for(view)
        if pane is not None:
            return pane
        from uniti.ui.rich_view import RichViewPane

        pane = RichViewPane(view)
        pane.target_view = view
        pane.set_mode_selector_visible(self.pane_mode_selector)
        pane.setGeometry(view.rect())
        pane.caretSourceChanged.connect(lambda cursor, anchor: self._push_caret_to_source(view, cursor, anchor))
        pane.closeRequested.connect(lambda: self.close(view))
        pane.providerChangeRequested.connect(lambda key: self.show(key, view))
        pane.zoomRequested.connect(lambda direction: self._zoom_source(view, direction))
        pane.focused.connect(lambda: view.viewFocused.emit(view.view_id))
        pane.document_applied = lambda: self._after_rich_edit(view)
        pane.can_edit = view.isEnabled
        # The window the pane is in now (a tab can move between windows).
        pane.is_live = lambda: getattr(pane.window(), "is_live_window", True)
        pane.context_menu_hook = lambda menu: self._context_entries(menu, view, pane)
        slot = lambda: self._sync_appearance(view)  # noqa: E731
        view.appearanceChanged.connect(slot)
        self._appearance_slots[view.view_id] = slot
        view.installEventFilter(self._fitter)
        self._panes[view.view_id] = pane
        pane.show()
        pane.raise_()
        # `show()` makes the pane the tab's focus proxy once it is bound, so
        # focus given to the tab (activation, Go To, transfer) lands in it.
        return pane

    def _remove(self, view: "UNITITextView") -> None:
        pane = self._panes.get(view.view_id)
        if pane is None or pane.target_view is not view:
            return
        del self._panes[view.view_id]
        slot = self._appearance_slots.pop(view.view_id, None)
        if slot is not None:
            try:
                view.appearanceChanged.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        view.removeEventFilter(self._fitter)
        if view.focusProxy() is pane.editor:
            view.setFocusProxy(None)
        pane.unbind()
        pane.hide()
        pane.setParent(None)
        pane.deleteLater()

    # --- appearance -------------------------------------------------------------------

    def _appearance(self, view: "UNITITextView", provider_key: str, providers):
        from uniti.ui.rich_view import RichPalette

        return self._font_for(provider_key, providers, view), RichPalette.from_tokens(view.theme_tokens)

    def _sync_appearance(self, view: "UNITITextView") -> None:
        pane = self.pane_for(view)
        key = self.key_for(view)
        if pane is None or key is None:
            return
        pane.set_appearance(*self._appearance(view, key, self.providers_for(view)))

    @staticmethod
    def _font_for(provider_key: str, providers, view):
        """Proportional UI font for formatted views (sized from the Source
        editor's zoomed font), the editor's own font otherwise."""

        provider = next(p for p in providers if p.key == provider_key)
        font = view.font()
        if getattr(provider, "proportional", False):
            from PySide6.QtGui import QFont

            ui_font = QFont(QApplication.font())
            if font.pointSizeF() > 0:
                ui_font.setPointSizeF(font.pointSizeF() * 1.1)
            return ui_font
        return font

    def set_mode_selector_visible(self, visible: bool) -> None:
        self.pane_mode_selector = visible
        for pane in self._panes.values():
            pane.set_mode_selector_visible(visible)

    @staticmethod
    def _zoom_source(view: "UNITITextView", direction: int) -> None:
        if view.isEnabled():
            view.zoom_in() if direction > 0 else view.zoom_out()

    # --- edits and caret ----------------------------------------------------------------

    def _refresh_window_actions(self) -> None:
        # `refresh()` gates host-feature actions on the current view's
        # environment; re-sync Markdown Preview so an open preview stays
        # closable when the current tab isn't Markdown.
        self._window._environment.refresh()
        self._window._refresh_markdown_preview_action()
        self._window._refresh_status_direction()
        environment_bar = getattr(self._window, "_environment_bar", None)
        if environment_bar is not None:
            environment_bar.refresh()

    def _after_rich_edit(self, edited: "UNITITextView") -> None:
        document = edited.document
        for view in self._window.views:
            if view.document is document:
                view._state_changed()

    def _push_caret_to_source(self, view: "UNITITextView", cursor: int, anchor: int) -> None:
        if self._window.view_for_id(view.view_id) is not view:
            return
        self._pushing_caret = True
        try:
            view.state.restore_state(EditorStateSnapshot(cursor, anchor, None))
            view._state_changed()
        finally:
            self._pushing_caret = False

    # --- window events --------------------------------------------------------------------

    def on_view_state_changed(self, view: "UNITITextView") -> None:
        pane = self.pane_for(view)
        if pane is not None and not self._pushing_caret:
            pane.show_source_caret(view.state.cursor, view.state.anchor)

    def on_current_view_changed(self, view: "UNITITextView | None") -> None:
        """Panes are per tab, so a tab switch only has to build a restored
        tab's pane the first time it is shown."""

        self.sync(view)

    def on_environment_changed(self, view: "UNITITextView | None") -> None:
        """Plain Text Mode / reassignment / pinning changed environments."""

        # Reassigning extensions can change any tab's environment, not just
        # `view`'s, so every tab is re-checked.
        for each in self._window.views:
            if each is view and self.pane_for(each) is not None:
                # Rebind: the provider objects belong to the old environment.
                self._remove(each)
            self.sync(each)
