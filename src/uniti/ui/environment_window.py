"""Environment windows and side-by-side reference sync (ADR-0017, ADR-0019).

2026-10-07 field test: "undock from MAIN panel, create 'environment panel',
move text file to the 'environment panel'". An environment window is an
ordinary UNITI window (tabs, splits, Find/Replace, save, session — all
unchanged) that belongs to one environment, e.g. "SFM/1", and carries that
environment's frame: an `EnvironmentBar` toolbar with the window's name,
the Plain Text / Standard / Preview mode switch and, for USFM, a Book /
Chapter / Verse selector.

`ReferenceSync` runs in every window: when the caret moves in a USFM tab,
every other split, in any window, showing a text of the same group scrolls
to the same chapter:verse (changing its book when needed), and the matched
verse is highlighted in all of them. A group binds projects across windows
(round 3 T5).
"""

from __future__ import annotations

import weakref
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QFont,
    QKeySequence,
    QPainter,
    QPalette,
)
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QLabel,
    QMenu,
    QMessageBox,
    QSizePolicy,
    QStyle,
    QStyleOptionComboBox,
    QToolBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from uniti.core.environments.catalog import descriptor_for_key
from uniti.core.environments.sfm.paratext_project import (
    ParatextProject,
    project_for_file,
)
from uniti.core.environments.sfm.references import (
    ID_PROBE_BYTES,
    BookHeader,
    Reference,
    ReferenceMap,
    book_header,
    book_header_for_path,
)
from uniti.core.environments.sfm.versification import map_reference
from uniti.ui.rich_view import reference_highlight_color

if TYPE_CHECKING:
    from uniti.core.document import Document
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

# Environments whose documents carry \\id / \\c / \\v references.
REFERENCE_ENVIRONMENTS = frozenset({"usfm"})
STEP_WIDTH = 16  # the stacked ▲ ▼ beside each of Book, Chapter and Verse
STEP_HEIGHT = 12
FRONT = "0"  # chapter and verse shown for the front matter, and verse for a chapter heading
_SYNC_DELAY_MS = 120


class ReferenceMaps:
    """One `ReferenceMap` per document, rebuilt when its revision changes."""

    def __init__(self) -> None:
        self._maps: weakref.WeakKeyDictionary[Document, tuple[int, ReferenceMap]] = weakref.WeakKeyDictionary()

    def for_document(self, document: Document) -> ReferenceMap | None:
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
    """Side-by-side sync by scripture reference, across every window.

    Each window has one; the one in the source's window does the work. The
    guard and the highlights are shared (round 3 T5): a move made by one
    window's sync never starts another's, and any sync clears the last
    one's highlights wherever they are.
    """

    _busy = 0
    _shared_highlights: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()
    _instances: weakref.WeakSet[ReferenceSync] = weakref.WeakSet()

    def __init__(self, window: UNITIMainWindow) -> None:
        super().__init__(window)
        self._window = window
        self.maps = ReferenceMaps()
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(_SYNC_DELAY_MS)
        self._timer.timeout.connect(self._sync_now)
        self._source: weakref.ReferenceType | None = None
        # Highlighted verse per view (sync, or a jump), in every window.
        self._highlighted = ReferenceSync._shared_highlights
        ReferenceSync._instances.add(self)
        # A jump's highlight: (view, start, end), kept until its caret leaves.
        self._pinned: tuple[weakref.ReferenceType, int, int] | None = None
        self.action = QAction("Sync Side-by-Side by Reference", window)
        # Short on the environment toolbar, which is crowded; the menu and
        # the tooltip keep the full name.
        self.action.setIconText("Sync")
        self.action.setCheckable(True)
        self.action.setChecked(True)
        self.action.setToolTip(
            "Moving the caret in one text scrolls the other splits, in any window, showing a text "
            "of the same group to the same chapter:verse"
        )
        self.action.toggled.connect(self._toggled)

    @property
    def enabled(self) -> bool:
        return self.action.isChecked()

    @property
    def _syncing(self) -> bool:
        return ReferenceSync._busy > 0

    @_syncing.setter
    def _syncing(self, value: bool) -> None:
        # Paired True/False, so nested syncing (a tab shown mid-sync) nests.
        ReferenceSync._busy = max(0, ReferenceSync._busy + (1 if value else -1))

    def _windows(self) -> list:
        service = self._window._service
        return [self._window] if service is None else [window for _window_id, window in service.windows.items]

    def _window_of(self, view: UNITITextView):
        service = self._window._service
        window = None if service is None else service.windows.window_for_view(view.view_id)
        return window if window is not None else self._window

    def _toggled(self, enabled: bool) -> None:
        if not enabled:
            self._timer.stop()
            self.clear()

    # --- helpers -------------------------------------------------------------

    def _environment_key(self, view: UNITITextView) -> str | None:
        environment = self._window._environment
        if environment.is_plain_mode(view):
            return None
        return environment.environment_key_for(view.document)

    def _group_of(self, view: UNITITextView) -> str | None:
        service = self._window._service
        if service is None:
            return None
        entry = service.documents.entry_for_view(view.view_id)
        return None if entry is None else entry.group_id

    def _visible_views(self) -> list[UNITITextView]:
        """The tab shown in each split of every window."""

        from uniti.ui.text_view import UNITITextView

        found = []
        for window in self._windows():
            panes = getattr(window, "_panes", None)
            if panes is None:
                continue
            for pane_id in panes.pane_ids:
                try:
                    leaf = panes.leaf(pane_id)
                except (KeyError, ValueError):
                    continue
                widget = leaf.active_view
                if isinstance(widget, UNITITextView):
                    found.append(widget)
        return found

    # --- sync ------------------------------------------------------------------

    def schedule(self, view: UNITITextView) -> None:
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

    def sync_from(self, source: UNITITextView) -> int:
        """Bring the other splits to `source`'s reference; returns how many moved.

        Plan P5: the reference is mapped into each text's own
        versification; a project text showing another book opens the
        project's file of this book in its split; a single file without
        this book stays where it is, with a notice.
        """

        group = self._group_of(source)
        key = self._environment_key(source)
        source_map = self.maps.for_document(source.document) if key in REFERENCE_ENVIRONMENTS else None
        if group is None or source_map is None or source_map.book is None:
            self.clear()
            return 0
        book = source_map.book
        reference = source_map.reference_at(source.state.cursor)
        source_verse = source_map.find(reference.chapter, reference.verse)
        source_span = (
            source_map.verse_range(source_verse) if source_verse is not None else source_map.heading_range(reference.chapter)
        )
        environment = self._window._environment
        source_versification = environment.versification_for(source.document)
        source_leaf = self._window._panes.leaf_for_view(source.view_id)
        missing: list[str] = []
        unsaved: list[str] = []
        moves: list[tuple[UNITITextView, int, tuple[int, int] | None]] = []
        for target in self._targets(source, source_leaf, group, book, missing, unsaved):
            target_map = self.maps.for_document(target.document)
            if target_map is None:
                continue
            target_versification = environment.versification_for(target.document)
            landing = self._landing(book, reference, source_versification, target_versification, target_map)
            if landing is not None:
                moves.append((target, *landing))
        self._syncing = True
        try:
            self.clear()
            if source_span is not None and any(span is not None for _target, _start, span in moves):
                self._highlight(source, source_span)
            for target, start, span in moves:
                self._move(target, start)
                if span is not None:
                    self._highlight(target, span)
        finally:
            self._syncing = False
        if unsaved:
            self._window.statusBar().showMessage(
                f"{', '.join(unsaved)} {'has' if len(unsaved) == 1 else 'have'} unsaved changes: "
                f"{'that split stays' if len(unsaved) == 1 else 'those splits stay'} where it is",
                6000,
            )
        elif missing:
            self._window.statusBar().showMessage(
                f"{book} isn't in {', '.join(missing)}: {'that split stays' if len(missing) == 1 else 'those splits stay'} where it is",
                6000,
            )
        return len(moves)

    @staticmethod
    def _landing(
        book: str, reference: Reference, source_versification, target_versification, target_map: ReferenceMap
    ) -> tuple[int, tuple[int, int] | None] | None:
        """Where `reference` lands in a target text, and what to highlight
        there; None when it has no such place.

        Verse 0 is a chapter's title: Russian numbers psalm titles as verse
        1, English as 0, so ruCARS Ps 11:1 lands on NIV Ps 12's title, and
        a caret in NIV Ps 12's heading lands on ruCARS Ps 11:1.
        """

        def mapped(verse: str) -> tuple[str | None, str | None]:
            return map_reference(book, reference.chapter, verse, source_versification, target_versification)

        if reference.verse is not None:
            chapter, verse = mapped(reference.verse)
            if verse == "0":
                heading = target_map.heading_range(chapter)
                if heading is not None:
                    return heading[0], heading
            found = target_map.find(chapter, verse)
            if found is None and (chapter, verse) != (reference.chapter, reference.verse):
                # The text doesn't have the mapped verse (its versification
                # and its text disagree): the same reference, if it has it.
                found = target_map.find(reference.chapter, reference.verse)
            return None if found is None else (found.start, target_map.verse_range(found))
        if reference.chapter is None:
            return 0, None  # before the first chapter: the book's start
        # The caret is in a chapter's heading, its verse 0. It lands where
        # the target numbers the title (a heading, or Russian psalms' verse
        # 1) when that agrees with where verse 1 lands — a versification
        # file without the title's mapping would put it a chapter off; else
        # where verse 1 lands (English Ps 10 starts at Russian 9:22); else on
        # the same chapter (the text and its versification disagree).
        first_chapter, first_verse = mapped("1")
        title_chapter, title_verse = mapped("0")
        candidates = [(title_chapter, title_verse)] if title_chapter == first_chapter else []
        candidates += [(first_chapter, "0" if first_verse == "1" else first_verse), (reference.chapter, "0")]
        for chapter, verse in candidates:
            if verse == "0":
                start = None if chapter is None else target_map.chapter_start(chapter)
                if start is not None:
                    return start, None
                continue
            found = target_map.find(chapter, verse)
            if found is not None:
                return found.start, target_map.verse_range(found)
        return 0, None

    def _targets(
        self, source, source_leaf, group: str, book: str, missing: list[str], unsaved: list[str]
    ) -> list[UNITITextView]:
        """Per other split showing a text of `group`: its shown tab when it
        has `book`; else another tab of that split that does (then shown);
        else, for a Paratext project text, the project's file of `book`
        (opened in that split). A single file without `book` is listed in
        `missing` and stays. A project has one open book, so a sync never
        replaces one with unsaved changes (it can't ask): that split is
        listed in `unsaved` and stays."""

        from uniti.core.environments.sfm.paratext_project import project_for_file

        targets = []
        for shown in self._visible_views():
            if shown is source:
                continue
            window = self._window_of(shown)
            leaf = window._panes.leaf_for_view(shown.view_id)
            if leaf is None or leaf is source_leaf or not self._in_group(shown, group):
                continue
            if self._matches(shown, group, book):
                targets.append(shown)
                continue
            project = project_for_file(shown.document.path)
            # A project's tab changes its own book (T5): another project's
            # tab with `book` in this split isn't this tab.
            candidate = next(
                (
                    view
                    for view in (window.view_for_id(view_id) for view_id in leaf.view_ids)
                    if view is not None
                    and view is not shown
                    and self._matches(view, group, book)
                    and (project is None or _same_project(view, project))
                ),
                None,
            )
            if candidate is not None:
                self._show_tab(leaf, candidate, source)
                targets.append(candidate)
                continue
            project_book = None if project is None else project.book_for(book)
            if project_book is not None and shown.document.modified:
                unsaved.append(shown.document.path.name)
                continue
            opened = None if project_book is None else self._open_in_split(shown, project_book.path, source, group)
            if opened is not None:
                targets.append(opened)
            else:
                missing.append(shown.document.path.name)
        return targets

    def _in_group(self, view: UNITITextView, group: str) -> bool:
        return self._group_of(view) == group and self._environment_key(view) in REFERENCE_ENVIRONMENTS

    def _open_in_split(self, shown: UNITITextView, path: Path, source: UNITITextView, group: str):
        """Open `path` in `shown`'s split, in `shown`'s view mode and group,
        without a popup and without taking activation from `source`."""

        from uniti.ui.open_mode import OpenMode

        window = self._window_of(shown)
        mode = window._rich_views.key_for(shown)
        leaf = window._panes.leaf_for_view(shown.view_id)
        opened = None
        self._syncing = True
        window._quiet_open = True
        try:
            window._panes.activate_view(shown.view_id)
            opened = window.open_path(path, open_mode=OpenMode.HERE)
            if opened is not None and window.view_for_id(opened.view_id) is opened:
                service = window._service
                entry = None if service is None else service.documents.entry_for_view(opened.view_id)
                if entry is not None and entry.group_id != group:
                    window._set_document_group(entry.document_id, group)
                if mode is not None:
                    window._rich_views.show(mode, opened)
            else:
                opened = None
        except Exception:  # an unreadable book never breaks sync
            opened = None
        finally:
            window._quiet_open = False
            if window is self._window:
                window._panes.activate_view(source.view_id)
            self._syncing = False
        if opened is not None and window._panes.leaf_for_view(opened.view_id) is not leaf:
            return None
        return opened

    def _matches(self, view: UNITITextView, group: str, book: str) -> bool:
        if self._group_of(view) != group or self._environment_key(view) not in REFERENCE_ENVIRONMENTS:
            return False
        reference_map = self.maps.for_document(view.document)
        return reference_map is not None and reference_map.book == book

    def _show_tab(self, leaf, view: UNITITextView, source: UNITITextView) -> None:
        # Selecting a tab activates its split; hand activation straight back.
        self._syncing = True
        try:
            leaf.select_view(view.view_id)
            self._window._panes.activate_view(source.view_id)
        finally:
            self._syncing = False

    def _move(self, view: UNITITextView, offset: int) -> None:
        document = view.document
        view.state.move_to(max(0, min(offset, document.total_chars())))
        view._state_changed()
        # Verse near the top third rather than wherever "just visible" lands.
        line = document.line_for_char(view.state.cursor)
        row = view.visual_row_for_line(line)
        view.verticalScrollBar().setValue(max(0, row - max(1, view._visible_line_capacity()) // 3))
        pane = self._window_of(view)._rich_views.pane_for(view)
        if pane is not None:
            pane.scroll_to_source(offset)

    def _highlight(self, view: UNITITextView, source_range: tuple[int, int]) -> None:
        start, end = source_range
        document = view.document
        first = document.line_for_char(start)
        last = document.line_for_char(max(start, end - 1))
        color = QColor(reference_highlight_color(view.theme_tokens))
        view.set_line_highlights({line: color for line in range(first, last + 1)})
        pane = self._window_of(view)._rich_views.pane_for(view)
        if pane is not None:
            pane.set_highlight(source_range)
        self._highlighted[view] = source_range

    def _unhighlight(self, view: UNITITextView) -> None:
        self._highlighted.pop(view, None)
        view.set_line_highlights()
        pane = self._window_of(view)._rich_views.pane_for(view)
        if pane is not None:
            pane.set_highlight(None)

    def clear(self) -> None:
        """Clear every highlight but a jump's, while its caret is still inside."""

        pinned = {instance._pinned_view() for instance in list(ReferenceSync._instances)}
        for view in list(self._highlighted.keys()):
            if view not in pinned:
                self._unhighlight(view)

    def restore_highlight(self, view: UNITITextView) -> None:
        """A rich pane was just built for `view`: give it the view's highlight."""

        source_range = self._highlighted.get(view)
        pane = self._window_of(view)._rich_views.pane_for(view)
        if source_range is not None and pane is not None:
            pane.set_highlight(source_range)

    # --- jumps (R4) -----------------------------------------------------------------

    def navigate_to(self, view: UNITITextView, offset: int) -> None:
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

    def _range_at(self, view: UNITITextView, offset: int) -> tuple[int, int] | None:
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

    def _pinned_view(self) -> UNITITextView | None:
        if self._pinned is None:
            return None
        view = self._pinned[0]()
        if view is None or not self._pinned[1] <= view.state.cursor <= self._pinned[2]:
            return None
        return view

    def _release_pin_if_left(self, view: UNITITextView) -> None:
        if self._pinned is not None and self._pinned[0]() is view and self._pinned_view() is None:
            self._unpin()

    def _unpin(self) -> None:
        if self._pinned is None:
            return
        view = self._pinned[0]()
        self._pinned = None
        if view is not None:
            self._unhighlight(view)



_GROUP_BUTTON_STYLE = "QToolButton::menu-indicator { image: none; }"


class _GroupButton(QToolButton):
    """The toolbar's "[name]", in the group's colour (field test,
    2026-10-31)."""

    def set_group(self, name: str, color: str | None = None) -> None:
        self.setText(f"[{name}]")
        rule = "" if color is None else f"QToolButton {{ color: {color}; }} "
        self.setStyleSheet(rule + _GROUP_BUTTON_STYLE)


class _GroupRow(QWidget):
    """One row of the group pop-up: the name in the group's colour, a tick
    when it is the current group."""

    clicked = Signal()

    def __init__(
        self, text: str, color: str | None, checked: bool, parent: QWidget | None = None, shortcut: str = ""
    ) -> None:
        super().__init__(parent)
        self._text = text
        self._color = color
        self._checked = checked
        self.shortcut = shortcut  # the row's hotkey, shown greyed at the right (N30)
        self.setMouseTracking(True)
        self.setMinimumHeight(self.fontMetrics().height() + 8)

    def sizeHint(self) -> QSize:
        metrics = self.fontMetrics()
        width = metrics.horizontalAdvance(self._text) + 48
        if self.shortcut:
            width += metrics.horizontalAdvance(self.shortcut) + 24
        return QSize(width, metrics.height() + 8)

    def enterEvent(self, event) -> None:
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self.update()
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        palette = self.palette()
        hovered = self.underMouse()
        if hovered:
            painter.fillRect(self.rect(), palette.highlight())
        if self._color is not None and not hovered:
            painter.setPen(QColor(self._color))
        else:
            painter.setPen(palette.highlightedText().color() if hovered else palette.text().color())
        if self._checked:
            painter.drawText(self.rect().adjusted(10, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, "\u2713")
        painter.drawText(self.rect().adjusted(30, 0, -10, 0), Qt.AlignmentFlag.AlignVCenter, self._text)
        if self.shortcut:
            if not hovered:
                painter.setPen(palette.color(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text))
            painter.drawText(
                self.rect().adjusted(0, 0, -10, 0),
                Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignRight,
                self.shortcut,
            )


class _GroupPopup(QFrame):
    """The group pop-up: a plain Qt pop-up, not a native menu (a native macOS
    menu crashed when its actions changed under a click, field test,
    2026-10-31). Built fresh each time it opens, so nothing in it changes
    while a click is running; a pick closes it first and is delivered
    afterwards."""

    def __init__(self, entries, current, manage, picked, parent: QWidget) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setFrameShape(QFrame.Shape.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(0)
        self._picked = picked
        self.rows: list[_GroupRow] = []
        for position, (name, data, color) in enumerate(entries):
            # Ungrouped is Ctrl+Alt+0, the first nine groups Ctrl+Alt+1\u20269.
            shortcut = (
                QKeySequence(f"Ctrl+Alt+{position}").toString(QKeySequence.SequenceFormat.NativeText)
                if position < 10
                else ""
            )
            self._add_row(layout, name, data, color, data == current, shortcut)
        rule = QFrame(self)
        rule.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(rule)
        self._add_row(layout, "Manage Groups\u2026", manage, None, False)

    def _add_row(self, layout, text, data, color, checked, shortcut: str = "") -> None:
        row = _GroupRow(text, color, checked, self, shortcut)
        self.rows.append(row)
        row.clicked.connect(lambda data=data: self._pick(data))
        layout.addWidget(row)

    def _pick(self, data) -> None:
        picked = self._picked
        self.hide()
        self.deleteLater()
        QTimer.singleShot(0, lambda: picked(data))


class EnvironmentBar(QToolBar):
    """The environment frame of an environment window."""

    def __init__(self, window: UNITIMainWindow, environment_key: str, slot: int) -> None:
        super().__init__("Environment", window)
        self.setObjectName("environmentBar")
        self.setMovable(False)
        self._window = window
        self.environment_key = environment_key
        self.slot = slot
        self._updating = False
        self._group_entries: list[tuple[str, str | None, str | None]] = []
        self._group_popup: _GroupPopup | None = None
        self._current_group: str | None = None
        # `open_book`'s answers about the book it leaves (view id -> "keep"
        # or "discard"), so `keep_one_book` doesn't ask twice.
        self._leaving: dict[str, str] = {}
        self._keeping = False
        self._books_project: Path | None = None
        self._books: tuple[tuple[str, Path], ...] = ()
        self._map: ReferenceMap | None = None

        # The window's name ("SFM/1"): a label, no longer renamed (field
        # test, 2026-10-31).
        self.title = QLabel(self)
        self.title.setContentsMargins(6, 0, 6, 0)
        self.title.setAccessibleName("Window name")
        self.title.setToolTip("This window's name.")
        self.addWidget(self.title)
        # The current file's document group: side-by-side sync works within
        # a group.
        # A button like the window's name (field test, 2026-10-26): it shows
        # the group; clicking it lists the groups.
        self.group = _GroupButton(self)
        self.group.setAccessibleName("Group")
        self.group.setToolTip(
            "The current file's document group. Side-by-side sync works within a group."
        )
        self.group.setAutoRaise(True)
        self.group.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
        self.group.clicked.connect(self._show_group_popup)
        self.group.setStyleSheet(_GROUP_BUTTON_STYLE)
        self.group.setMinimumWidth(round(5 * self.group.fontMetrics().horizontalAdvance("M")))
        self.addWidget(self.group)
        self.project_label = QLabel(self)
        self.project_label.setContentsMargins(10, 0, 6, 0)
        self.addWidget(self.project_label)
        self.addSeparator()
        self._mode_group = QActionGroup(self)
        self._mode_group.setExclusive(True)
        self.mode_actions: dict[str | None, QAction] = {}
        self._mode_separator = self.addSeparator()

        references = environment_key in REFERENCE_ENVIRONMENTS
        self.book = _BookCombo(self)
        self.book.setAccessibleName("Book")
        self.book.activated.connect(self._book_chosen)
        self.chapter = _NumberCombo(self)
        self.chapter.setAccessibleName("Chapter")
        self.chapter.activated.connect(self._chapter_chosen)
        self.verse = _NumberCombo(self)
        self.verse.setAccessibleName("Verse")
        self.verse.activated.connect(self._verse_chosen)
        # Fixed display widths: the book's id and header, and up to three
        # digits of chapter and verse.
        for combo, ems in ((self.book, BOOK_EMS), (self.chapter, NUMBER_EMS), (self.verse, NUMBER_EMS)):
            # A short list with a scrollbar (field test, 2026-10-26): not the
            # native pop-up that stretches over a 150-chapter Psalms list.
            # No drop-down arrow inside the box: the stacked carets beside it
            # step the list, and a click on the box opens it. The border rule
            # makes the style sheet draw the box itself; without it the native
            # style (macOS) keeps drawing its own up/down chevron.
            combo.setStyleSheet(
                "QComboBox { combobox-popup: 0; border: 1px solid palette(mid); border-radius: 3px;"
                " padding: 1px 6px; background: palette(base); }"
                " QComboBox:disabled { color: palette(mid); }"
                " QComboBox::drop-down { width: 0; border: none; }"
                " QComboBox::down-arrow { image: none; width: 0; }"
            )
            combo.ensurePolished()
            _fix_display_width(combo, ems)
            combo.setMaxVisibleItems(POPUP_ITEMS)
        self._steppers: dict[QComboBox, tuple[QToolButton, QToolButton]] = {}
        if references:
            # Book : Chapter : Verse sits at the right end of the toolbar.
            spacer = QWidget(self)
            spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
            self.addWidget(spacer)
            self.addAction(window._reference_sync.action)
            self.addSeparator()
            tags: list[QWidget] = []
            for text, combo in (("Book", self.book), ("Chapter", self.chapter), ("Verse", self.verse)):
                if combo is self.book:
                    # The lock before the Book list stands for "Book" and is
                    # Unlock Book / Lock Book: no extra button on a toolbar
                    # that must stay short.
                    abbreviation = QLabel("BK", self)
                    abbreviation.setContentsMargins(6, 0, 3, 0)
                    abbreviation.setToolTip("Book")
                    self.addWidget(abbreviation)
                    tags.append(abbreviation)
                    self.lock_toggle = QToolButton(self)
                    self.lock_toggle.setDefaultAction(window._book_lock.action)
                    self.lock_toggle.setAutoRaise(True)
                    self.lock_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                    self.addWidget(self.lock_toggle)
                    tags.append(self.lock_toggle)
                elif combo is self.chapter:
                    # "Chapter" is also the Show One Chapter toggle: no
                    # extra button on a toolbar that must stay short.
                    self.chapter_toggle = QToolButton(self)
                    self.chapter_toggle.setDefaultAction(window._chapter_view.action)
                    self.chapter_toggle.setAutoRaise(True)
                    self.chapter_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
                    self.addWidget(self.chapter_toggle)
                    tags.append(self.chapter_toggle)
                else:
                    label = QLabel("VS", self)
                    label.setContentsMargins(6, 0, 3, 0)
                    label.setToolTip(text)
                    self.addWidget(label)
                    tags.append(label)
                self.addWidget(combo)
                self.addWidget(self._make_steppers(combo))
            # BK, CH and VS: one font, size and weight (a label, a toggle
            # button and a lock button would otherwise each draw their own).
            tag_font = QFont(self.font())
            tag_font.setBold(False)
            for tag in tags:
                tag.setFont(tag_font)
                tag.setStyleSheet(f"font-size: {tag_font.pointSizeF():g}pt; font-weight: normal;")
        else:
            for combo in (self.book, self.chapter, self.verse):
                combo.hide()
        self.refresh()

    # --- state -------------------------------------------------------------------

    def _make_steppers(self, combo: QComboBox) -> QWidget:
        """Up and down carets stacked at the right of `combo`, like a spin
        box: up is the next item of its list (Book GEN ▲ is EXO), down the
        previous one (Chapter 3 ▼ is 2)."""

        stack = QWidget(self)
        layout = QVBoxLayout(stack)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        buttons = {}
        for arrow, delta, name in ((Qt.ArrowType.UpArrow, 1, "Next"), (Qt.ArrowType.DownArrow, -1, "Previous")):
            button = QToolButton(stack)
            button.setArrowType(arrow)
            button.setAutoRaise(True)
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            button.setFixedSize(STEP_WIDTH, STEP_HEIGHT)  # the toolbar must stay short
            button.setAccessibleName(f"{name} {combo.accessibleName()}")
            button.setToolTip(f"{name} {combo.accessibleName().lower()}")
            button.clicked.connect(lambda _checked=False, combo=combo, delta=delta: self.step(combo, delta))
            layout.addWidget(button)
            buttons[delta] = button
        self._steppers[combo] = (buttons[-1], buttons[1])
        return stack

    def step(self, combo: QComboBox, delta: int) -> bool:
        """Move `combo` to the previous (-1) or next (+1) item and act on it
        as if it had been chosen; False at either end of the list."""

        index = combo.currentIndex() + delta
        if self._updating or not combo.isEnabled() or not 0 <= index < combo.count():
            return False
        combo.setCurrentIndex(index)
        chosen = {self.book: self._book_chosen, self.chapter: self._chapter_chosen, self.verse: self._verse_chosen}[combo]
        chosen(index)
        self._refresh_steppers()
        return True

    def _refresh_steppers(self) -> None:
        for combo, (previous, following) in getattr(self, "_steppers", {}).items():
            previous.setEnabled(combo.isEnabled() and combo.currentIndex() > 0)
            following.setEnabled(combo.isEnabled() and combo.currentIndex() < combo.count() - 1)

    def _view(self) -> UNITITextView | None:
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
        self.title.setText(self._window.environment_window_name() or descriptor_for_key(self.environment_key).label)
        font = self.title.font()
        font.setBold(True)
        self.title.setFont(font)
        self._refresh_group_choices()
        project = self._project()
        if project is not None:
            # Only the project's short name, everywhere (round 3, answer 5).
            self.project_label.setText(f"<b>{project.name}</b>")
            self.project_label.setToolTip(str(project.folder))
        else:
            self.project_label.setText("")
            self.project_label.setToolTip("")

    # --- group ---------------------------------------------------------------------

    _MANAGE_GROUPS = "\0manage"

    def _entry(self):
        """The registry entry of the current file, if any."""

        view = self._view()
        service = self._window._service
        return None if view is None or service is None else service.documents.entry_for_view(view.view_id)

    def _refresh_group_choices(self) -> None:
        window = self._window
        entry = self._entry()
        current = None if entry is None else entry.group_id
        groups = window.groups_for(self.environment_key)
        shown, color = "Ungrouped", None
        for group in groups:
            if group.id == current:
                shown, color = group.name, group.color
        # "[A]" next to the window's name, in the group's colour.
        self.group.set_group(shown, color)
        self.group.setEnabled(entry is not None)
        self._group_entries = [("Ungrouped", None, None)] + [(g.name, g.id, g.color) for g in groups]
        self._current_group = current
        # Ctrl+Alt+0…9 are the window's own actions (every window has them,
        # N30); the pop-up only shows them.

    def _show_group_popup(self) -> None:
        popup = _GroupPopup(
            self._group_entries, self._current_group, self._MANAGE_GROUPS, self._group_chosen, self.group
        )
        self._group_popup = popup
        popup.move(self.group.mapToGlobal(QPoint(0, self.group.height())))
        popup.show()

    def group_choices(self) -> list[str]:
        """The group pop-up's entries, in order."""

        return [name for name, _data, _color in self._group_entries] + ["Manage Groups…"]

    def choose_group(self, text: str) -> bool:
        """Pick the group pop-up's entry `text`, as a click would."""

        if text == "Manage Groups…":
            self._group_chosen(self._MANAGE_GROUPS)
            return True
        for name, data, _color in self._group_entries:
            if name == text:
                self._group_chosen(data)
                return True
        return False

    def _group_chosen(self, data) -> None:
        window = self._window
        if data == self._MANAGE_GROUPS:
            window.show_document_group_editor(self.environment_key)
            return
        entry = self._entry()
        if entry is None:
            return
        window._set_document_group(entry.document_id, data)

    def window_title_prefix(self) -> str:
        prefix = self._window.environment_window_name() or descriptor_for_key(self.environment_key).label
        project = self._project()
        return prefix if project is None else f"{prefix} — {project.name}"

    def _refresh_modes(self) -> None:
        rich_views = self._window._rich_views
        view = self._view()
        providers = rich_views.providers_for(view) if view is not None else ()
        # The same switch in every environment (field test, 2026-10-26): Text,
        # then the environment's views; one without a rich view shows a
        # disabled Preview.
        entries = [(None, TEXT_MODE_LABEL)] + [(provider.key, provider.label) for provider in providers]
        if not providers:
            entries.append((NO_PREVIEW, "Preview"))
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
            action.setEnabled(view is not None and key is not NO_PREVIEW and (key is None or bool(providers)))
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

    def _book_entries(self, view: UNITITextView, *, rescan: bool) -> list[tuple[str, Path]]:
        """(label, path) per book: the project's books (plan P3). USFM
        assumes a project (round 3 T1), so a file outside one lists none."""

        project = project_for_file(view.document.path)
        if project is None:
            self._books_project = None
            return []
        if project.folder != self._books_project or rescan or not self._books:
            self._books_project = project.folder
            books = []
            for book in project.books():
                # The book's id and its \h line; the id alone when its header
                # block has no \h (user, 2026-10-08).
                name = self._header_of(book.path).header
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

    def _refresh_books(self, *, rescan: bool = False) -> None:
        view = self._view()
        entries = [] if view is None else self._book_entries(view, rescan=rescan)
        current_path = None if view is None else view.document.path
        self._updating = True
        try:
            self.book.clear()
            selected = -1
            modified = self._modified_paths()
            for index, (label, path) in enumerate(entries):
                if _resolved(path) in modified:
                    label = f"{label} •"  # open with unsaved changes (D1)
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
        self._refresh_steppers()

    def _modified_paths(self) -> set[Path]:
        """The open files of this window with unsaved changes."""

        return {_resolved(view.document.path) for view in self._window.views if view.document.modified}

    def _refresh_chapters(self) -> None:
        view = self._view()
        self._map = None if view is None else self._window._reference_sync.maps.for_document(view.document)
        self._updating = True
        try:
            self.chapter.clear()
            if self._map is not None and self._map.chapters:
                # Chapter 0 is the front matter, before the first \c (as in Paratext).
                if all(chapter.label != FRONT for chapter in self._map.chapters):
                    self.chapter.addItem(FRONT, FRONT)
                for chapter in self._map.chapters:
                    self.chapter.addItem(chapter.label, chapter.label)
            self.chapter.setEnabled(self.chapter.count() > 0)
        finally:
            self._updating = False
        self.follow_caret(view)
        self._refresh_steppers()

    def _fill_verses(self, chapter: str | None) -> None:
        self.verse.clear()
        if self._map is not None and chapter is not None:
            # Verse 0 is the chapter's heading, between its \c and its first
            # \v; in the front matter it is the start of the text.
            verses = self._map.verses_in(chapter)
            if not verses or verses[0].label != FRONT:
                self.verse.addItem(FRONT, self._heading_start(chapter))
            for verse in verses:
                self.verse.addItem(verse.label, verse.start)
        self.verse.setEnabled(self.verse.count() > 0)

    def _heading_start(self, chapter: str) -> int:
        start = None if self._map is None else self._map.chapter_start(chapter)
        return 0 if start is None else start

    def follow_caret(self, view: UNITITextView | None) -> None:
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
        chapter = FRONT if reference.chapter is None and self.chapter.count() else reference.chapter
        self._updating = True
        try:
            index = self.chapter.findData(chapter)
            if index != self.chapter.currentIndex() or self.verse.count() == 0:
                self.chapter.setCurrentIndex(index)
                self._fill_verses(chapter)
            verse = reference_map.find(reference.chapter, reference.verse)
            if verse is not None:
                shown = self.verse.findData(verse.start)
            elif chapter is not None and self.verse.count():
                shown = 0  # verse 0: the front matter, or a chapter's heading
            else:
                shown = -1
            self.verse.setCurrentIndex(shown)
        finally:
            self._updating = False
        self._refresh_steppers()

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
        self._navigate(self._heading_start(chapter))

    def _verse_chosen(self, index: int) -> None:
        if not self._updating:
            self._navigate(self.verse.itemData(index))

    def _book_chosen(self, index: int) -> None:
        if self._updating:
            return
        path = self.book.itemData(index)
        if isinstance(path, str):
            self.open_book(Path(path))

    def open_book(self, path: Path) -> UNITITextView | None:
        """Show the book at `path` here, in the current tab's mode and group.

        In a USFM window the tab is the project's (round 3 T4): the book is
        shown in the same tab, its own hidden tab or a newly opened one.
        When the current book has unsaved changes and this is its last view
        it asks first (book-lock plan D4): Save, or Discard (the book closes
        without saving). A book another split or window shows keeps them.
        """

        window = self._window
        previous = window.current_view
        if (
            previous is not None
            and window._project_tabs.active
            and not _same_path(previous.document.path, path)
            and previous.document.modified
        ):
            decision = self._leave_book(previous)
            if decision is None:
                self._refresh_books()
                return None
            self._leaving[previous.view_id] = decision
        try:
            opened = self._show_book(path)
            if opened is not None:
                self.keep_one_book(opened)
        finally:
            self._leaving.clear()
        return opened

    def settle_restored_books(self) -> None:
        """A session saved before a project had one open book can come back
        with several in a tab: keep each tab's shown book and close the
        rest, asking about nothing (a book with unsaved changes stays)."""

        window = self._window
        tabs = window._project_tabs
        if not tabs.active:
            return
        panes = window._panes
        for pane_id in panes.pane_ids:
            try:
                leaf = panes.leaf(pane_id)
            except (KeyError, ValueError):
                continue
            for books in tabs.members(leaf).values():
                if len(books) < 2:
                    continue
                shown = next((book for book in books if book.view_id == leaf.selected_view_id), books[0])
                self.keep_one_book(shown, ask=False)

    def keep_one_book(self, shown: UNITITextView, *, ask: bool = True) -> None:
        """A project has one open book per tab: close the other books open
        in `shown`'s tab, asking about unsaved changes (book-lock plan D4)
        unless the question was just answered (`open_book`). A book whose
        question the user cancels stays open, hidden, as does one with
        unsaved changes when `ask` is False."""

        window = self._window
        tabs = window._project_tabs
        if not tabs.active or self._keeping:
            return
        self._keeping = True
        try:
            for book in tabs.books_of(shown):
                if book is shown or _same_path(book.document.path, shown.document.path):
                    continue
                decision = self._leaving.pop(book.view_id, None)
                if decision is None and book.document.modified:
                    if not ask:
                        continue
                    decision = self._leave_book(book)
                    if decision is None:
                        continue
                window.close_view_discarding(book)
            tabs.refresh_all()
            self.refresh()
        finally:
            self._keeping = False

    def _show_book(self, path: Path) -> UNITITextView | None:
        window = self._window
        previous = window.current_view
        mode = window._rich_views.key_for(previous)
        service = window._service
        previous_entry = None if previous is None or service is None else service.documents.entry_for_view(previous.view_id)
        group_id = None if previous_entry is None else previous_entry.group_id
        tabs = window._project_tabs
        if previous is not None and _same_path(previous.document.path, path):
            return previous
        if previous is not None and tabs.active:
            existing = tabs.book_in_tab(previous, path)
            if existing is not None:
                window._select_view(existing)
                existing.setFocus()
                self.refresh()
                if window._reference_sync.enabled:
                    window._reference_sync.sync_from(existing)
                return existing
            elsewhere = next((view.document for view in window.views if _same_path(view.document.path, path)), None)
            if elsewhere is None:
                # Open in another window of the environment: a second view
                # of it here too, not a move (T4).
                elsewhere = window.open_in_other_environment_window(path)
            if elsewhere is not None:
                # Open in another split or window: a second view of it, in this tab.
                window._panes.activate_view(previous.view_id)
                opened = window.open_existing_document(elsewhere)
                return self._finish_open(opened, mode, group_id)
        else:
            for view in window.views:
                if _same_path(view.document.path, path):
                    window._select_view(view)
                    view.setFocus()
                    return view
        opened = window.open_path(path)
        if opened is None or window.view_for_id(opened.view_id) is not opened:
            return opened  # open elsewhere: the service focused that window
        return self._finish_open(opened, mode, group_id)

    def _finish_open(self, opened: UNITITextView, mode: str | None, group_id: str | None) -> UNITITextView:
        window = self._window
        service = window._service
        if service is not None and group_id is not None:
            entry = service.documents.entry_for_view(opened.view_id)
            if entry is not None and entry.group_id != group_id:
                window._set_document_group(entry.document_id, group_id)
        if mode is not None:
            window._rich_views.show(mode, opened)
        self.refresh()
        if window._reference_sync.enabled:
            # Every split of the group follows to this book (P5).
            window._reference_sync.sync_from(opened)
        return opened

    def _leave_book(self, view: UNITITextView) -> str | None:
        """Before another book replaces `view` in its tab: "keep" (saved, or
        another view still shows it), "discard", or None to stay (D4)."""

        from uniti.ui import book_lock

        window = self._window
        service = window._service
        entry = None if service is None else service.documents.entry_for_view(view.view_id)
        if entry is not None and len(entry.view_ids) > 1:
            return "keep"
        document = view.document
        if document.read_only:
            # It can't be saved in place (T7): Discard its changes, or stay.
            if window._ask_save_changes(document) == QMessageBox.StandardButton.Discard:
                return "discard"
            return None
        answer = book_lock.ask_save_or_discard(
            window, book_lock.document_title(document), locked=document.locked
        )
        if answer is None:
            return None
        if not answer:
            return "discard"
        was_locked = document.locked
        document.set_locked(False)  # the prompt offered Unlock and Save
        window._select_view(view)
        if window.save_current() is None:
            document.set_locked(was_locked)
            return None
        return "keep"


BOOK_EMS = 10
NUMBER_EMS = 3
TEXT_MODE_LABEL = "Text"
NO_PREVIEW = "(no preview)"  # the key of the disabled Preview an environment without views shows
POPUP_ITEMS = 12  # rows a Book, Chapter or Verse list shows before it scrolls


def _fix_display_width(combo: QComboBox, ems: float) -> None:
    """Fix `combo`'s width so its display area is `ems` em wide (plus the
    style's frame and drop-down arrow)."""

    metrics = combo.fontMetrics()
    option = QStyleOptionComboBox()
    combo.initStyleOption(option)
    contents = QSize(round(ems * metrics.horizontalAdvance("M")), metrics.height())
    size = combo.style().sizeFromContents(QStyle.ContentsType.CT_ComboBox, option, contents, combo)
    # The style sheet's padding and border (6px + 1px a side) must fit too;
    # the style's own estimate has come out a digit short on macOS.
    combo.setFixedWidth(max(size.width(), contents.width() + 2 * (6 + 1) + 4))


class _NumberCombo(QComboBox):
    """A Chapter or Verse box whose list is as wide as its widest number and
    its scrollbar, no wider (field test, 2026-10-31: the box's own width
    left room for one digit, then for far more than three)."""

    def showPopup(self) -> None:
        super().showPopup()
        view = self.view()
        scrollbar = self.style().pixelMetric(QStyle.PixelMetric.PM_ScrollBarExtent, None, view)
        metrics = self.fontMetrics()
        widest = max([metrics.horizontalAdvance("000")] + [metrics.horizontalAdvance(self.itemText(i)) for i in range(self.count())])
        text = widest + 16
        container = view.window()
        container.setFixedWidth(text + (scrollbar if self.count() > self.maxVisibleItems() else 0) + 2 * view.frameWidth() + 8)


class _BookCombo(QComboBox):
    """Re-reads the book list each time it opens (files come and go)."""

    def __init__(self, bar: EnvironmentBar) -> None:
        super().__init__(bar)
        self._bar = bar

    def showPopup(self) -> None:
        self._bar._refresh_books(rescan=True)
        super().showPopup()

    def lock_menu(self) -> QMenu:
        """Right-click menu: Unlock Book / Lock Book, for the shown book."""

        window = self._bar._window
        window._book_lock.refresh()
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        menu.addAction(window._book_lock.action)
        return menu

    def contextMenuEvent(self, event) -> None:
        self.lock_menu().popup(event.globalPos())


def _same_path(first: Path, second: Path) -> bool:
    try:
        return first.resolve() == second.resolve()
    except OSError:
        return first == second


def _same_project(view: UNITITextView, project: ParatextProject) -> bool:
    other = project_for_file(view.document.path)
    return other is not None and _same_path(other.folder, project.folder)


def _resolved(path: Path) -> Path:
    try:
        return Path(path).resolve()
    except OSError:
        return Path(path)


__all__ = ["REFERENCE_ENVIRONMENTS", "EnvironmentBar", "ReferenceMaps", "ReferenceSync"]
