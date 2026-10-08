"""Environment windows and side-by-side reference sync (ADR-0017).

2026-10-07 field test: "undock from MAIN panel, create 'environment panel',
move text file to the 'environment panel'". An environment window is an
ordinary UNITI window (tabs, splits, Find/Replace, save, session — all
unchanged) that belongs to one environment and one document group, e.g.
"USFM — NIV", and carries that environment's frame: an `EnvironmentBar`
toolbar with the Plain Text / Standard / Preview mode switch and, for
USFM, a Book / Chapter / Verse selector.

`ReferenceSync` runs in every window: when the caret moves in a USFM tab,
every other split showing a file of the same document group and the same
book scrolls to the same chapter:verse, and the matched verse is
highlighted in all of them.
"""

from __future__ import annotations

import weakref
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QColor
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QSizePolicy,
    QStyle,
    QStyleOptionComboBox,
    QToolBar,
    QWidget,
)

from uniti.core.environments.catalog import descriptor_for_key
from uniti.core.environments.sfm.paratext_project import ParatextProject, project_for_file
from uniti.core.environments.sfm.references import (
    ID_PROBE_BYTES,
    BookHeader,
    ReferenceMap,
    Verse,
    book_header,
    book_header_for_path,
    book_rank,
)
from uniti.ui.rich_view import PLAIN_TEXT_LABEL, reference_highlight_color

if TYPE_CHECKING:
    from uniti.core.document import Document
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

# Environments whose documents carry \\id / \\c / \\v references.
REFERENCE_ENVIRONMENTS = frozenset({"usfm", "sfm"})
_SYNC_DELAY_MS = 120


class ReferenceMaps:
    """One `ReferenceMap` per document, rebuilt when its revision changes."""

    def __init__(self) -> None:
        self._maps: weakref.WeakKeyDictionary[Document, tuple[int, ReferenceMap]] = weakref.WeakKeyDictionary()

    def for_document(self, document: "Document") -> ReferenceMap | None:
        from uniti.core.resource_profile import ResourceProfile

        if not ResourceProfile(size_bytes=document.source.size).allow_full_parse:
            return None
        cached = self._maps.get(document)
        if cached is not None and cached[0] == document.revision:
            return cached[1]
        built = ReferenceMap(document.read(0, document.total_chars()))
        self._maps[document] = (document.revision, built)
        return built


class ReferenceSync(QObject):
    """Side-by-side sync by scripture reference within one window."""

    def __init__(self, window: "UNITIMainWindow") -> None:
        super().__init__(window)
        self._window = window
        self.maps = ReferenceMaps()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SYNC_DELAY_MS)
        self._timer.timeout.connect(self._sync_now)
        self._source: weakref.ReferenceType | None = None
        self._syncing = False
        # Highlighted verse per view (sync, or a jump).
        self._highlighted: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
        # A jump's highlight: (view, start, end), kept until its caret leaves.
        self._pinned: tuple[weakref.ReferenceType, int, int] | None = None
        self.action = QAction("Sync Side-by-Side by Reference", window)
        self.action.setCheckable(True)
        self.action.setChecked(True)
        self.action.setToolTip(
            "Moving the caret in one file scrolls the other splits showing the same book "
            "of the same document group to the same chapter:verse"
        )
        self.action.toggled.connect(self._toggled)

    @property
    def enabled(self) -> bool:
        return self.action.isChecked()

    def _toggled(self, enabled: bool) -> None:
        if not enabled:
            self._timer.stop()
            self.clear()

    # --- helpers -------------------------------------------------------------

    def _environment_key(self, view: "UNITITextView") -> str | None:
        environment = self._window._environment
        if environment.is_plain_mode(view):
            return None
        return environment.environment_key_for(view.document)

    def _group_of(self, view: "UNITITextView") -> str | None:
        service = self._window._service
        if service is None:
            return None
        entry = service.documents.entry_for_view(view.view_id)
        return None if entry is None else entry.group_id

    def _visible_views(self) -> list["UNITITextView"]:
        """The tab shown in each split of this window."""

        from uniti.ui.text_view import UNITITextView

        found = []
        for pane_id in self._window._panes.pane_ids:
            try:
                leaf = self._window._panes.leaf(pane_id)
            except (KeyError, ValueError):
                continue
            widget = leaf.active_view
            if isinstance(widget, UNITITextView):
                found.append(widget)
        return found

    # --- sync ------------------------------------------------------------------

    def schedule(self, view: "UNITITextView") -> None:
        """The caret moved in `view`; sync shortly if it is the active tab."""

        self._release_pin_if_left(view)
        if self._syncing or not self.enabled or view is not self._window.current_view:
            return
        self._source = weakref.ref(view)
        self._timer.start()

    def _sync_now(self) -> None:
        view = self._source() if self._source is not None else None
        if view is None or view is not self._window.current_view or not self.enabled:
            return
        self.sync_from(view)

    def sync_from(self, source: "UNITITextView") -> int:
        """Bring the other splits to `source`'s reference; returns how many moved."""

        group = self._group_of(source)
        key = self._environment_key(source)
        source_map = self.maps.for_document(source.document) if key in REFERENCE_ENVIRONMENTS else None
        if group is None or source_map is None or source_map.book is None:
            self.clear()
            return 0
        reference = source_map.reference_at(source.state.cursor)
        source_verse = source_map.find(reference.chapter, reference.verse)
        matched: list[tuple[UNITITextView, ReferenceMap, Verse]] = []
        source_leaf = self._window._panes.leaf_for_view(source.view_id)
        for target in self._targets(source, source_leaf, group, source_map.book):
            target_map = self.maps.for_document(target.document)
            verse = None if target_map is None else target_map.find(reference.chapter, reference.verse)
            if verse is not None:
                matched.append((target, target_map, verse))
        self._syncing = True
        try:
            self.clear()
            if not matched or source_verse is None:
                return 0
            self._highlight(source, source_map.verse_range(source_verse))
            for target, target_map, verse in matched:
                start, end = target_map.verse_range(verse)
                self._move(target, start)
                self._highlight(target, (start, end))
        finally:
            self._syncing = False
        return len(matched)

    def _targets(self, source, source_leaf, group: str, book: str) -> list["UNITITextView"]:
        """Per other split: its shown tab if it has `book` of `group`, else
        another tab of that split that does (which is then shown)."""

        targets = []
        for shown in self._visible_views():
            if shown is source:
                continue
            leaf = self._window._panes.leaf_for_view(shown.view_id)
            if leaf is None or leaf is source_leaf:
                continue
            if self._matches(shown, group, book):
                targets.append(shown)
                continue
            for view_id in leaf.view_ids:
                candidate = self._window.view_for_id(view_id)
                if candidate is not None and candidate is not shown and self._matches(candidate, group, book):
                    self._show_tab(leaf, candidate, source)
                    targets.append(candidate)
                    break
        return targets

    def _matches(self, view: "UNITITextView", group: str, book: str) -> bool:
        if self._group_of(view) != group or self._environment_key(view) not in REFERENCE_ENVIRONMENTS:
            return False
        reference_map = self.maps.for_document(view.document)
        return reference_map is not None and reference_map.book == book

    def _show_tab(self, leaf, view: "UNITITextView", source: "UNITITextView") -> None:
        # Selecting a tab activates its split; hand activation straight back.
        self._syncing = True
        try:
            leaf.select_view(view.view_id)
            self._window._panes.activate_view(source.view_id)
        finally:
            self._syncing = False

    def _move(self, view: "UNITITextView", offset: int) -> None:
        document = view.document
        view.state.move_to(max(0, min(offset, document.total_chars())))
        view._state_changed()
        # Verse near the top third rather than wherever "just visible" lands.
        line = document.line_for_char(view.state.cursor)
        row = view.visual_row_for_line(line)
        view.verticalScrollBar().setValue(max(0, row - max(1, view._visible_line_capacity()) // 3))
        pane = self._window._rich_views.pane_for(view)
        if pane is not None:
            pane.scroll_to_source(offset)

    def _highlight(self, view: "UNITITextView", source_range: tuple[int, int]) -> None:
        start, end = source_range
        document = view.document
        first = document.line_for_char(start)
        last = document.line_for_char(max(start, end - 1))
        color = QColor(reference_highlight_color(view.theme_tokens))
        view.set_line_highlights({line: color for line in range(first, last + 1)})
        pane = self._window._rich_views.pane_for(view)
        if pane is not None:
            pane.set_highlight(source_range)
        self._highlighted[view] = source_range

    def _unhighlight(self, view: "UNITITextView") -> None:
        self._highlighted.pop(view, None)
        view.set_line_highlights()
        pane = self._window._rich_views.pane_for(view)
        if pane is not None:
            pane.set_highlight(None)

    def clear(self) -> None:
        """Clear every highlight but a jump's, while its caret is still inside."""

        pinned = self._pinned_view()
        for view in list(self._highlighted.keys()):
            if view is not pinned:
                self._unhighlight(view)

    def restore_highlight(self, view: "UNITITextView") -> None:
        """A rich pane was just built for `view`: give it the view's highlight."""

        source_range = self._highlighted.get(view)
        pane = self._window._rich_views.pane_for(view)
        if source_range is not None and pane is not None:
            pane.set_highlight(source_range)

    # --- jumps (R4) -----------------------------------------------------------------

    def navigate_to(self, view: "UNITITextView", offset: int) -> None:
        """Jump to `offset` (Book/Chapter/Verse, Go to Chapter:Verse) and, when
        it starts a verse or chapter, highlight that verse — or the chapter
        line — in every view mode until the caret leaves it."""

        self._unpin()
        self._move(view, offset)
        target = self._range_at(view, offset)
        if target is not None:
            self._highlight(view, target)
            self._pinned = (weakref.ref(view), *target)
        view.setFocus()

    def _range_at(self, view: "UNITITextView", offset: int) -> tuple[int, int] | None:
        if self._environment_key(view) not in REFERENCE_ENVIRONMENTS:
            return None
        reference_map = self.maps.for_document(view.document)
        if reference_map is None:
            return None
        verse = next((item for item in reference_map.verses if item.start == offset), None)
        if verse is not None:
            return reference_map.verse_range(verse)
        if any(chapter.start == offset for chapter in reference_map.chapters):
            document = view.document
            line = document.line_for_char(offset)
            end = document.line_start(line + 1) if line + 1 < document.line_count() else document.total_chars()
            return offset, max(offset + 1, end)
        return None

    def _pinned_view(self) -> "UNITITextView | None":
        if self._pinned is None:
            return None
        view = self._pinned[0]()
        if view is None or not self._pinned[1] <= view.state.cursor <= self._pinned[2]:
            return None
        return view

    def _release_pin_if_left(self, view: "UNITITextView") -> None:
        if self._pinned is not None and self._pinned[0]() is view and self._pinned_view() is None:
            self._unpin()

    def _unpin(self) -> None:
        if self._pinned is None:
            return
        view = self._pinned[0]()
        self._pinned = None
        if view is not None:
            self._unhighlight(view)


class EnvironmentBar(QToolBar):
    """The environment frame of an environment window."""

    def __init__(self, window: "UNITIMainWindow", environment_key: str, group_id: str | None) -> None:
        super().__init__("Environment", window)
        self.setObjectName("environmentBar")
        self.setMovable(False)
        self._window = window
        self.environment_key = environment_key
        self.group_id = group_id
        self._updating = False
        self._books_project: Path | None = None
        self._books: tuple[tuple[str, Path], ...] = ()
        self._map: ReferenceMap | None = None

        self.title = QLabel(self)
        self.title.setContentsMargins(6, 0, 10, 0)
        self.addWidget(self.title)
        self.addSeparator()
        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)
        self.mode_actions: dict[str | None, QAction] = {}
        self._mode_separator = self.addSeparator()

        references = environment_key in REFERENCE_ENVIRONMENTS
        self.book = _BookCombo(self)
        self.book.setAccessibleName("Book")
        self.book.activated.connect(self._book_chosen)
        self.chapter = QComboBox(self)
        self.chapter.setAccessibleName("Chapter")
        self.chapter.activated.connect(self._chapter_chosen)
        self.verse = QComboBox(self)
        self.verse.setAccessibleName("Verse")
        self.verse.activated.connect(self._verse_chosen)
        # Fixed display widths: the book's id and header, and up to three
        # digits of chapter and verse.
        for combo, ems in ((self.book, BOOK_EMS), (self.chapter, NUMBER_EMS), (self.verse, NUMBER_EMS)):
            _fix_display_width(combo, ems)
        if references:
            # Book : Chapter : Verse sits at the right end of the toolbar.
            spacer = QWidget(self)
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.addWidget(spacer)
            self.addAction(window._reference_sync.action)
            self.addSeparator()
            for text, combo in (("Book", self.book), ("Chapter", self.chapter), ("Verse", self.verse)):
                label = QLabel(text, self)
                label.setContentsMargins(6, 0, 3, 0)
                self.addWidget(label)
                self.addWidget(combo)
        else:
            for combo in (self.book, self.chapter, self.verse):
                combo.hide()
        self.refresh()

    # --- state -------------------------------------------------------------------

    def _view(self) -> "UNITITextView | None":
        view = self._window.current_view
        if view is None:
            return None
        if self._window._environment.environment_key_for(view.document) != self.environment_key:
            return None
        return view

    def refresh(self) -> None:
        """Rebuild for the active tab (mode list, books, chapters)."""

        self._refresh_title()
        self._refresh_modes()
        if self.environment_key in REFERENCE_ENVIRONMENTS:
            self._refresh_books()
            self._refresh_chapters()

    def _project(self) -> ParatextProject | None:
        """The Paratext project of the active tab, if it is a project book."""

        view = self._view()
        return None if view is None else project_for_file(view.document.path)

    def _refresh_title(self) -> None:
        label = descriptor_for_key(self.environment_key).label
        group = self._window._group_by_id(self.group_id) if self.group_id else None
        text = f"<b>{label}</b> — " + (
            "Ungrouped" if group is None else f'<span style="color:{group.color}">■</span> {group.name}'
        )
        project = self._project()
        if project is not None:
            text += f" — <b>{project.name}</b>"
            self.title.setToolTip(f"{project.full_name or project.name}\n{project.folder}")
        else:
            self.title.setToolTip("")
        self.title.setText(text)

    def window_title_prefix(self) -> str:
        label = descriptor_for_key(self.environment_key).label
        group = self._window._group_by_id(self.group_id) if self.group_id else None
        prefix = f"{label} — {group.name if group is not None else 'Ungrouped'}"
        project = self._project()
        return prefix if project is None else f"{prefix} — {project.name}"

    def _refresh_modes(self) -> None:
        rich_views = self._window._rich_views
        view = self._view()
        providers = rich_views.providers_for(view) if view is not None else ()
        entries = [(None, PLAIN_TEXT_LABEL)] + [(provider.key, provider.label) for provider in providers]
        if [key for key, _label in entries] != list(self.mode_actions):
            for action in self.mode_actions.values():
                self._mode_group.removeAction(action)
                self.removeAction(action)
                action.deleteLater()
            self.mode_actions = {}
            for key, label in entries:
                action = QAction(label, self)
                action.setCheckable(True)
                action.triggered.connect(lambda _checked=False, key=key: self._mode_chosen(key))
                self._mode_group.addAction(action)
                self.insertAction(self._mode_separator, action)
                self.mode_actions[key] = action
        showing = rich_views.key_for(view)
        for key, action in self.mode_actions.items():
            action.setEnabled(view is not None and (key is None or bool(providers)))
            blocked = action.blockSignals(True)
            action.setChecked(key == showing)
            action.blockSignals(blocked)

    def _mode_chosen(self, key: str | None) -> None:
        view = self._view()
        if view is not None:
            self._window._rich_views.set_mode(key, view)
            view.setFocus()
        self._refresh_modes()

    # --- book / chapter / verse ---------------------------------------------------

    def _book_entries(self, view: "UNITITextView", *, rescan: bool) -> list[tuple[str, Path]]:
        """(label, path) per book: the project's books when the tab is a
        project book, otherwise the open files of this group (plan P3) —
        an unrelated folder never lists stray files."""

        project = project_for_file(view.document.path)
        if project is None:
            self._books_project = None
            return self._group_files()
        if project.folder != self._books_project or rescan or not self._books:
            self._books_project = project.folder
            books = []
            for book in project.books():
                # The book's id and its \h line; BookNames.xml's name when
                # the book has no \h in its header block.
                name = self._header_of(book.path).header or book.name
                books.append((f"{book.code} {name}" if name else book.code, book.path))
            self._books = tuple(books)
        return list(self._books)

    def _header_of(self, path: Path, document=None) -> BookHeader:
        """`\\id` and `\\h` of a book: from its open document when it is open
        (unsaved edits count), else from the file's first lines."""

        if document is None:
            service = self._window._service
            entry = None if service is None else service.documents.find_path(path)
            document = None if entry is None else entry.document
        if document is not None:
            return book_header(document.read(0, min(document.total_chars(), ID_PROBE_BYTES)))
        return book_header_for_path(path)

    def _group_files(self) -> list[tuple[str, Path]]:
        window = self._window
        service = window._service
        if service is not None:
            documents = [(entry.document, entry.group_id) for entry in service.documents.entries if entry.view_ids]
        else:
            documents = [(view.document, None) for view in window.views]
        found = []
        seen: set[int] = set()
        for document, group_id in documents:
            if group_id != self.group_id or id(document) in seen:
                continue
            if window._environment.environment_key_for(document) != self.environment_key:
                continue
            seen.add(id(document))
            header = self._header_of(document.path, document)
            label = header.label or document.path.name
            found.append((book_rank(header.code), header.code or "", document.path.name.lower(), label, document.path))
        found.sort(key=lambda item: item[:3])
        return [(label, path) for _rank, _code, _name, label, path in found]

    def _refresh_books(self, *, rescan: bool = False) -> None:
        view = self._view()
        entries = [] if view is None else self._book_entries(view, rescan=rescan)
        current_path = None if view is None else view.document.path
        self._updating = True
        try:
            self.book.clear()
            selected = -1
            for index, (label, path) in enumerate(entries):
                self.book.addItem(label, str(path))
                self.book.setItemData(index, f"{label}\n{path}", Qt.ItemDataRole.ToolTipRole)
                if current_path is not None and _same_path(path, current_path):
                    selected = index
            if selected < 0 and view is not None:
                # Not listed (unsaved, no \id yet, or outside the project): still show it.
                label = self._header_of(view.document.path, view.document).label or view.document.path.name
                self.book.addItem(label, str(view.document.path))
                selected = self.book.count() - 1
                self.book.setItemData(selected, f"{label}\n{view.document.path}", Qt.ItemDataRole.ToolTipRole)
            self.book.setCurrentIndex(selected)
            self.book.setEnabled(view is not None)
            self.book.setToolTip(self.book.itemData(selected, Qt.ItemDataRole.ToolTipRole) if selected >= 0 else "Book")
            # The field stays 10 em; the list opens wide enough for whole headers.
            popup = self.book.view()
            popup.setMinimumWidth(popup.sizeHintForColumn(0) + 2 * popup.frameWidth() + 24)
        finally:
            self._updating = False

    def _refresh_chapters(self) -> None:
        view = self._view()
        self._map = None if view is None else self._window._reference_sync.maps.for_document(view.document)
        self._updating = True
        try:
            self.chapter.clear()
            if self._map is not None:
                for chapter in self._map.chapters:
                    self.chapter.addItem(chapter.label, chapter.label)
            self.chapter.setEnabled(self.chapter.count() > 0)
        finally:
            self._updating = False
        self.follow_caret(view)

    def _fill_verses(self, chapter: str | None) -> None:
        self.verse.clear()
        if self._map is not None and chapter is not None:
            for verse in self._map.verses_in(chapter):
                self.verse.addItem(verse.label, verse.start)
        self.verse.setEnabled(self.verse.count() > 0)

    def follow_caret(self, view: "UNITITextView | None") -> None:
        """Show the reference at the caret (without navigating)."""

        if self.environment_key not in REFERENCE_ENVIRONMENTS or view is None or view is not self._view():
            return
        reference_map = self._window._reference_sync.maps.for_document(view.document)
        if reference_map is not self._map:
            self._refresh_chapters()
            return
        if reference_map is None:
            return
        reference = reference_map.reference_at(view.state.cursor)
        self._updating = True
        try:
            index = self.chapter.findData(reference.chapter)
            if index != self.chapter.currentIndex() or self.verse.count() == 0:
                self.chapter.setCurrentIndex(index)
                self._fill_verses(reference.chapter)
            verse = reference_map.find(reference.chapter, reference.verse)
            self.verse.setCurrentIndex(-1 if verse is None else self.verse.findData(verse.start))
        finally:
            self._updating = False

    def _navigate(self, offset: int | None) -> None:
        view = self._view()
        if view is None or offset is None:
            return
        self._window._reference_sync.navigate_to(view, offset)

    def _chapter_chosen(self, index: int) -> None:
        if self._updating or self._map is None:
            return
        chapter = self.chapter.itemData(index)
        self._updating = True
        try:
            self._fill_verses(chapter)
        finally:
            self._updating = False
        self._navigate(self._map.chapter_start(chapter))

    def _verse_chosen(self, index: int) -> None:
        if not self._updating:
            self._navigate(self.verse.itemData(index))

    def _book_chosen(self, index: int) -> None:
        if self._updating:
            return
        path = self.book.itemData(index)
        if isinstance(path, str):
            self.open_book(Path(path))

    def open_book(self, path: Path) -> "UNITITextView | None":
        """Show the book at `path` here: its open tab, or open it into this
        window and this window's group, in the current tab's mode."""

        window = self._window
        previous = window.current_view
        mode = window._rich_views.key_for(previous)
        for view in window.views:
            if _same_path(view.document.path, path):
                window._select_view(view)
                view.setFocus()
                return view
        opened = window.open_path(path)
        if opened is None or window.view_for_id(opened.view_id) is not opened:
            return opened  # open elsewhere: the service focused that window
        service = window._service
        if service is not None and self.group_id is not None:
            entry = service.documents.entry_for_view(opened.view_id)
            if entry is not None and entry.group_id != self.group_id:
                window._set_document_group(entry.document_id, self.group_id)
        if mode is not None:
            window._rich_views.show(mode, opened)
        self.refresh()
        return opened


BOOK_EMS = 10
NUMBER_EMS = 3


def _fix_display_width(combo: QComboBox, ems: float) -> None:
    """Fix `combo`'s width so its display area is `ems` em wide (plus the
    style's frame and drop-down arrow)."""

    metrics = combo.fontMetrics()
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    contents = QSize(round(ems * metrics.horizontalAdvance("M")), metrics.height())
    size = combo.style().sizeFromContents(QStyle.ContentsType.CT_ComboBox, option, contents, combo)
    combo.setFixedWidth(size.width())


class _BookCombo(QComboBox):
    """Re-reads the book list each time it opens (files come and go)."""

    def __init__(self, bar: "EnvironmentBar") -> None:
        super().__init__(bar)
        self._bar = bar

    def showPopup(self) -> None:  # noqa: N802 - Qt override
        self._bar._refresh_books(rescan=True)
        super().showPopup()


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.resolve() == second.resolve()
    except OSError:
        return first == second


__all__ = ["EnvironmentBar", "REFERENCE_ENVIRONMENTS", "ReferenceMaps", "ReferenceSync"]
