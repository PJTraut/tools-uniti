"""Character-level Unicode and encoding inspection for UNITI (BF-003/004),
extended to a whole-selection per-character list+detail view (BF-073,
replacing BF-065's table, in the style of r12a's Uniview:
https://r12a.github.io/uniview/) and zoomable, with a dedicated large
glyph-preview area (2026-09-20 follow-up)."""

from __future__ import annotations

from collections.abc import Callable

import unicodedataplus as unicodedata

from PySide6.QtCore import (
    QAbstractListModel,
    QEvent,
    QModelIndex,
    QPoint,
    QRect,
    QSize,
    Qt,
)
from PySide6.QtGui import QFont, QFontMetrics, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListView,
    QPushButton,
    QSplitter,
    QStyle,
    QStyledItemDelegate,
    QVBoxLayout,
    QWidget,
)

# A per-character list beyond this size stops being useful UI regardless of
# how fast it renders — mirrors the app's general bounded-work philosophy
# (e.g. the whitespace-marker paint budget) rather than being a performance
# limit as such. Lowered from an earlier 4096 (2026-09-20 direction): a
# selection worth inspecting character-by-character is a small one in
# practice, not a whole document.
MAX_INSPECT_SELECTION_CHARACTERS = 128

MIN_ZOOM_PERCENT = 50
MAX_ZOOM_PERCENT = 500
DEFAULT_ZOOM_PERCENT = 100
_ZOOM_STEP = 10
# The large glyph-preview area reads at this multiple of the dialog's
# ordinary text size at 100% zoom, then scales with it — the "character
# area" is the whole point of this dialog, so it must never be the same
# small size as a table cell (2026-09-20 report).
_GLYPH_FONT_SCALE = 4.0
# The glyph-preview box's fixed height, in multiples of its own (zoomed)
# font's line height — "3 em" (2026-09-20 request), so the box stays
# proportional to the glyph itself as zoom changes rather than clipping a
# tall glyph or leaving a small one lost in too much empty space.
_GLYPH_BOX_EM = 3.0


def _encoded_hex(character: str, encoding: str) -> str:
    try:
        payload = character.encode(encoding, errors="strict")
    except UnicodeEncodeError:
        return "not representable"
    return " ".join(f"{byte:02X}" for byte in payload)


def _display_glyph(character: str) -> str:
    # A control/format character (category Cc/Cf, e.g. tab, newline, ZWJ)
    # renders as nothing or corrupts the row's line height — show its
    # code point notation instead, matching how the single-character form
    # already only ever shows a real, printable character.
    if not character:
        return ""
    if unicodedata.category(character) in ("Cc", "Cf") or character in "\r\n":
        return f"U+{ord(character):04X}"
    return character


def _codepoints(text: str) -> str:
    return " ".join(f"U+{ord(letter):04X}" for letter in text)


def _mapping_or_dash(character: str, mapper) -> str:
    # 2026-09-20: show the mapped codepoint(s) alongside the glyph, not
    # just the glyph itself -- relevant since the mapping can be more
    # than one character (e.g. German "ß".upper() == "SS").
    mapped = mapper(character)
    if not mapped or mapped == character:
        return "—"
    return f"{mapped} ({_codepoints(mapped)})"


def _decomposition_or_dash(character: str) -> str:
    # `unicodedata.decomposition` already returns hex codepoints, but bare
    # ("0065 0301") rather than in the app's own "U+XXXX" notation used
    # everywhere else in this dialog; a leading compatibility tag like
    # "<super>" (2026-09-20) is passed through as-is, only the hex values
    # themselves get the "U+" prefix.
    raw = unicodedata.decomposition(character)
    if not raw:
        return "—"
    return " ".join(
        part if part.startswith("<") else f"U+{part.upper()}"
        for part in raw.split()
    )


class CharacterListModel(QAbstractListModel):
    """One row per character: code point, display glyph, and name — the
    left-hand list of the multi-character Inspect Selection view."""

    CharRole = int(Qt.ItemDataRole.UserRole) + 1
    CodePointRole = int(Qt.ItemDataRole.UserRole) + 2
    NameRole = int(Qt.ItemDataRole.UserRole) + 3

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self._text = text

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._text)

    def character(self, row: int) -> str:
        return self._text[row]

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._text):
            return None
        character = self._text[index.row()]
        if role == self.CharRole:
            return _display_glyph(character)
        if role == self.CodePointRole:
            return f"U+{ord(character):04X}"
        if role == self.NameRole:
            return unicodedata.name(character, "<unknown>")
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.AccessibleTextRole):
            return (
                f"{_display_glyph(character)}  U+{ord(character):04X}  "
                f"{unicodedata.name(character, '<unknown>')}"
            )
        return None


class CharacterListDelegate(QStyledItemDelegate):
    """Three left-aligned, borderless columns (CHR / CODE POINT / NAME) —
    the Find/Replace Match Report's plain-list, no-grid-lines style
    (BF-073's own request), not a `QTableWidget` grid.

    Column widths and row height are derived from the current font's own
    metrics rather than fixed pixel constants, so the whole list scales
    coherently with `CharacterInspectorDialog`'s zoom (2026-09-20 request)
    with no separate zoom-tracking needed here — changing the list's font
    is the only input this delegate needs.
    """

    @staticmethod
    def _char_column_width(metrics) -> int:
        return metrics.horizontalAdvance("W") + 16

    @staticmethod
    def _codepoint_column_width(metrics) -> int:
        return metrics.horizontalAdvance("U+000000") + 8

    def sizeHint(self, option, index) -> QSize:
        result = super().sizeHint(option, index)
        return QSize(result.width(), option.fontMetrics.height() + 8)

    def paint(self, painter, option, index) -> None:
        character = index.data(CharacterListModel.CharRole)
        codepoint = index.data(CharacterListModel.CodePointRole)
        name = index.data(CharacterListModel.NameRole)
        if character is None:
            super().paint(painter, option, index)
            return
        styled = option.__class__(option)
        self.initStyleOption(styled, index)
        styled.text = ""
        style = (
            option.widget.style() if option.widget is not None else QApplication.style()
        )
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem, styled, painter, option.widget
        )
        painter.save()
        try:
            vertical = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine
            rect = option.rect
            char_width = self._char_column_width(option.fontMetrics)
            codepoint_width = self._codepoint_column_width(option.fontMetrics)
            char_rect = QRect(rect.left() + 4, rect.top(), char_width, rect.height())
            codepoint_rect = QRect(
                char_rect.right(), rect.top(), codepoint_width, rect.height()
            )
            name_rect = QRect(
                codepoint_rect.right() + 4,
                rect.top(),
                max(0, rect.right() - codepoint_rect.right() - 4),
                rect.height(),
            )
            painter.drawText(char_rect, vertical | Qt.AlignmentFlag.AlignLeft, character)
            painter.drawText(
                codepoint_rect, vertical | Qt.AlignmentFlag.AlignLeft, codepoint
            )
            painter.drawText(
                name_rect,
                vertical | Qt.AlignmentFlag.AlignLeft,
                option.fontMetrics.elidedText(
                    name, Qt.TextElideMode.ElideRight, name_rect.width()
                ),
            )
        finally:
            painter.restore()


class _CharacterInspectorTitleBar(QWidget):
    """Custom title bar for the frameless window (2026-09-20 request: match
    the Find/Replace detached window's own chrome, not the native OS
    dialog frame -- which draws rounded corners and minimize/close
    controls no matter what window-type flags are set, only a fully
    frameless window with its own title bar avoids that). Identical
    drag-to-move mechanism to `_FindReplaceTitleBar` (`find_replace.py`):
    a custom title bar widget disables Qt's built-in native drag gesture,
    so this reimplements it directly. No close button, matching
    Find/Replace's own detached title bar -- closing is Escape or the
    hotkey toggle, not a title-bar control.

    An optional Refresh button (BF-076: the dialog otherwise only ever
    shows the selection captured at open time, and stays open across
    later selection changes per its toggle-window behavior) sits at the
    opposite end from the draggable title label."""

    def __init__(
        self,
        dialog: QDialog,
        title: str,
        *,
        on_refresh: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._drag_offset: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 2, 2)
        self._label = QLabel(title, self)
        self._label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(self._label)
        layout.addStretch(1)
        if on_refresh is not None:
            refresh_button = QPushButton("Refresh", self)
            refresh_button.setFlat(True)
            refresh_button.setAccessibleName("Refresh")
            refresh_button.setToolTip("Re-inspect the current selection (F5)")
            refresh_button.clicked.connect(on_refresh)
            layout.addWidget(refresh_button)

    def set_title(self, title: str) -> None:
        self._label.setText(title)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._dialog.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            self._dialog.move(global_pos - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class CharacterInspectorDialog(QDialog):
    """A single character's Unicode/encoding properties, or (BF-073) a
    list+detail view for a whole multi-character selection. Zoomable via
    Ctrl/Cmd+scroll or the standard zoom hotkeys (2026-09-20): the whole
    dialog's text scales together, including the large glyph-preview area
    and the list+detail view's column widths/row heights."""

    def __init__(
        self,
        text: str,
        *,
        output_encoding: str,
        invalid_bytes: bytes | None = None,
        initial_zoom_percent: int = DEFAULT_ZOOM_PERCENT,
        initial_geometry: tuple[int, int, int, int] | None = None,
        initial_splitter_sizes: tuple[int, int] | None = None,
        on_refresh: Callable[[], None] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        if not text:
            raise ValueError("character inspector requires at least one character")
        self._base_font = QFont(self.font())
        self._base_point_size = self._base_font.pointSizeF()
        if self._base_point_size <= 0:
            self._base_point_size = 12.0
        # Remembers the previous window size and zoom level across
        # reopens (2026-09-20 request) -- the caller (`UNITIMainWindow`)
        # is responsible for persisting `zoom_percent`/`geometry()` on
        # close and passing them back in here on the next open.
        self._zoom_percent = max(
            MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, int(initial_zoom_percent))
        )
        # BF-087: the list/detail splitter's position, same persistence
        # contract as zoom/geometry above (the caller persists `splitter_sizes`
        # on close). Kept live (not just the constructor's initial value) so
        # a BF-076 `refresh()` rebuild preserves whatever the user last
        # dragged it to, rather than resetting to the original reopen value.
        self._splitter_sizes = initial_splitter_sizes
        self._selection_splitter: QSplitter | None = None
        self._glyph_labels: list[QLabel] = []
        self._character_list: QListView | None = None
        # BF-076: re-reads and repaints the current selection in place on
        # Refresh, rather than requiring close/reopen. The dialog itself
        # stays unaware of the live document/view -- the caller supplies
        # this closure, which reads the current selection and calls
        # `refresh()` back.
        self._on_refresh = on_refresh

        # Styled/behaved like the Find/Replace detached window (2026-09-20
        # request): a `Tool` window that stays on top of the editor so it
        # can be referenced while typing, plus `FramelessWindowHint` --
        # `Qt.WindowType.Tool` alone still gets the native OS frame
        # (rounded corners, a title bar) on every platform tested;
        # eliminating that natively-drawn chrome entirely, in favor of
        # `_CharacterInspectorTitleBar` below, is the only reliable way to
        # match Find/Replace's own square-cornered, button-free look. No
        # redundant in-content Close button either -- the title bar's own
        # drag area plus Escape (QDialog's default reject()) both work.
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        self._title_bar = _CharacterInspectorTitleBar(
            self, "", on_refresh=self._request_refresh if on_refresh is not None else None
        )
        outer_layout.addWidget(self._title_bar)

        self._content = QWidget(self)
        outer_layout.addWidget(self._content, 1)
        self._content_layout = QVBoxLayout(self._content)

        default_size = self._populate_content(text, output_encoding, invalid_bytes)
        if initial_geometry is not None:
            self.setGeometry(*initial_geometry)
        else:
            self.resize(*default_size)

        QShortcut(
            QKeySequence(QKeySequence.StandardKey.ZoomIn), self, activated=self.zoom_in
        )
        QShortcut(
            QKeySequence(QKeySequence.StandardKey.ZoomOut), self, activated=self.zoom_out
        )
        QShortcut(QKeySequence("Ctrl+0"), self, activated=self.reset_zoom)
        QShortcut(QKeySequence("Ctrl+="), self, activated=self.zoom_in)
        if on_refresh is not None:
            QShortcut(
                QKeySequence(QKeySequence.StandardKey.Refresh),
                self,
                activated=self._request_refresh,
            )

    @staticmethod
    def _clear_layout(layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
                continue
            sub_layout = item.layout()
            if sub_layout is not None:
                CharacterInspectorDialog._clear_layout(sub_layout)

    def _populate_content(
        self,
        text: str,
        output_encoding: str,
        invalid_bytes: bytes | None,
    ) -> tuple[int, int]:
        """(Re-)builds the dialog's content for `text`, either the
        single-character form or the list+detail selection view. Returns
        the default window size for this shape -- used at construction
        only; `refresh()` deliberately keeps whatever size/position the
        window already has."""

        self._clear_layout(self._content_layout)
        self._glyph_labels = []
        self._character_list = None
        self._selection_splitter = None

        title = "Character Inspector" if len(text) == 1 else "Inspect Selection"
        self.setWindowTitle(f"UNITI — {title}")
        self._title_bar.set_title(title)
        if len(text) == 1:
            self._content_layout.addLayout(
                self._single_character_form(text, output_encoding, invalid_bytes)
            )
            default_size = (420, 480)
        else:
            truncated = text[:MAX_INSPECT_SELECTION_CHARACTERS]
            if len(truncated) < len(text):
                self._content_layout.addWidget(
                    QLabel(
                        f"Showing the first {len(truncated)} of {len(text)} characters."
                    )
                )
            self._content_layout.addWidget(self._selection_list_and_detail(truncated), 1)
            default_size = (720, 480)
        self._apply_zoom_fonts()
        return default_size

    def _request_refresh(self) -> None:
        if self._on_refresh is not None:
            self._on_refresh()

    def refresh(
        self,
        text: str,
        *,
        output_encoding: str,
        invalid_bytes: bytes | None = None,
    ) -> None:
        """Re-inspects `text` in place (BF-076), keeping the window's
        current size, position, and zoom -- only the content rebuilds,
        even when switching between the single-character and
        list+detail shapes."""

        if not text:
            raise ValueError("character inspector requires at least one character")
        self._populate_content(text, output_encoding, invalid_bytes)

    def _make_glyph_label(self, character: str, parent: QWidget) -> QLabel:
        label = QLabel(_display_glyph(character), parent)
        label.setAccessibleName("Character Preview")
        # Horizontal *and* vertical centering within the fixed-height box
        # (2026-09-20 request) -- the box's height is set in
        # `_apply_zoom_fonts`, proportional to the glyph's own font size.
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._glyph_labels.append(label)
        return label

    @property
    def zoom_percent(self) -> int:
        return self._zoom_percent

    def zoom_in(self) -> None:
        self.set_zoom_percent(self._zoom_percent + _ZOOM_STEP)

    def zoom_out(self) -> None:
        self.set_zoom_percent(self._zoom_percent - _ZOOM_STEP)

    def reset_zoom(self) -> None:
        self.set_zoom_percent(DEFAULT_ZOOM_PERCENT)

    def set_zoom_percent(self, percent: int) -> None:
        percent = max(MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, int(percent)))
        if percent == self._zoom_percent:
            return
        self._zoom_percent = percent
        self._apply_zoom_fonts()

    def _apply_zoom_fonts(self) -> None:
        """(Re-)apply fonts for the current `self._zoom_percent` to every
        widget, plus the large glyph-preview area(s) at their own bigger
        multiple of it. Called once at the end of construction (so the
        glyph area already reads larger than ordinary text before any
        zoom change happens) and again from `set_zoom_percent`."""

        scale = self._zoom_percent / 100.0

        text_font = QFont(self._base_font)
        text_font.setPointSizeF(max(1.0, self._base_point_size * scale))
        self.setFont(text_font)
        for widget in self.findChildren(QWidget):
            widget.setFont(text_font)

        glyph_font = QFont(self._base_font)
        glyph_font.setPointSizeF(
            max(1.0, self._base_point_size * scale * _GLYPH_FONT_SCALE)
        )
        glyph_box_height = int(QFontMetrics(glyph_font).height() * _GLYPH_BOX_EM)
        for label in self._glyph_labels:
            label.setFont(glyph_font)
            label.setFixedHeight(glyph_box_height)

        if self._character_list is not None:
            self._character_list.doItemsLayout()

    def wheelEvent(self, event) -> None:
        primary = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )
        delta = event.angleDelta().y()
        if primary and delta:
            steps = max(1, abs(delta) // 120)
            for _ in range(steps):
                self.zoom_in() if delta > 0 else self.zoom_out()
            event.accept()
            return
        super().wheelEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.Type.Wheel
            and event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        ):
            self.wheelEvent(event)
            return True
        return super().eventFilter(watched, event)

    def _single_character_form(
        self,
        character: str,
        output_encoding: str,
        invalid_bytes: bytes | None,
    ) -> QVBoxLayout:
        codepoint = f"U+{ord(character):04X}"
        name = unicodedata.name(character, "<unknown>")
        container = QVBoxLayout()
        glyph_label = self._make_glyph_label(character, self)
        container.addWidget(glyph_label)
        form = QFormLayout()
        # Titles left-aligned at a fixed column (2026-09-20 request):
        # unset, `QFormLayout`'s label alignment falls back to the
        # platform style hint (right-aligned/ragged on macOS), which
        # reads inconsistently against titles of very different lengths
        # ("Unicode" vs. "Character decomposition mapping"). The field
        # (content) column already starts at one fixed x regardless --
        # `QFormLayout` sizes that column to the widest label in the
        # form -- left-aligning the titles just makes that boundary
        # legible as a consistent left-hand column instead of a ragged
        # right/centered one.
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.addRow("Unicode", QLabel(codepoint))
        form.addRow("Name", QLabel(name))
        if invalid_bytes is not None:
            raw = " ".join(f"{byte:02X}" for byte in invalid_bytes)
            form.addRow("Decode error bytes", QLabel(raw))
        form.addRow("UTF-8", QLabel(_encoded_hex(character, "utf-8")))
        form.addRow("Windows-1252", QLabel(_encoded_hex(character, "windows-1252")))
        form.addRow("UTF-16LE", QLabel(_encoded_hex(character, "utf-16-le")))
        form.addRow("UTF-16BE", QLabel(_encoded_hex(character, "utf-16-be")))
        form.addRow(output_encoding, QLabel(_encoded_hex(character, output_encoding)))
        container.addLayout(form)
        # Anchor content to the top of the window (2026-09-20 request)
        # rather than letting `QVBoxLayout` spread it across any extra
        # vertical space the dialog is resized to.
        container.addStretch(1)
        return container

    def _selection_list_and_detail(self, text: str) -> QSplitter:
        self._character_model = CharacterListModel(text, self)
        self._character_list = QListView(self)
        self._character_list.setModel(self._character_model)
        self._character_list.setItemDelegate(CharacterListDelegate(self._character_list))
        self._character_list.setAccessibleName("Character List")
        self._character_list.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        # `clicked` only fires for a mouse click -- Up/Down arrow-key
        # navigation moves the selection highlight without emitting it,
        # leaving the detail panel stale (2026-09-20 report).
        # `currentChanged` fires for both, and also covers the initial
        # `setCurrentIndex` call below, so no separate explicit call is
        # needed to populate the panel on first open.
        self._character_list.selectionModel().currentChanged.connect(
            lambda current, _previous: self._show_character_detail(current)
        )
        self._character_list.viewport().installEventFilter(self)

        self._detail_widget = QWidget(self)
        detail_container = QVBoxLayout(self._detail_widget)
        self._detail_glyph_label = self._make_glyph_label("", self._detail_widget)
        detail_container.addWidget(self._detail_glyph_label)
        self._detail_layout = QFormLayout()
        # See `_single_character_form` for why these are set explicitly.
        self._detail_layout.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        self._detail_layout.setFormAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop
        )
        detail_container.addLayout(self._detail_layout)
        self._detail_placeholder = QLabel(
            "Click a character to see its properties.", self._detail_widget
        )
        self._detail_layout.addRow(self._detail_placeholder)
        # Anchor content to the top of the detail pane, not centered in
        # whatever extra height the splitter gives it (2026-09-20 request).
        detail_container.addStretch(1)

        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._character_list)
        splitter.addWidget(self._detail_widget)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setChildrenCollapsible(False)
        if self._splitter_sizes is not None:
            splitter.setSizes(list(self._splitter_sizes))
        splitter.splitterMoved.connect(self._on_selection_splitter_moved)
        self._selection_splitter = splitter
        if text:
            self._character_list.setCurrentIndex(self._character_model.index(0, 0))
        return splitter

    def _on_selection_splitter_moved(self, _position: int, _index: int) -> None:
        if self._selection_splitter is None:
            return
        sizes = self._selection_splitter.sizes()
        if len(sizes) == 2 and all(size > 0 for size in sizes):
            self._splitter_sizes = (sizes[0], sizes[1])

    @property
    def splitter_sizes(self) -> tuple[int, int] | None:
        """BF-087: the list/detail splitter's current position, for
        `UNITIMainWindow._on_toggle_window_closed` to persist across
        reopens (mirrors the existing `zoom_percent` property) -- `None`
        for a single-character dialog, which never builds a splitter.
        Reads the live splitter directly (not just `self._splitter_sizes`,
        which only updates once the user actually drags it or an initial
        value was supplied) so closing without ever dragging still
        persists whatever position it actually opened at."""

        if self._selection_splitter is None:
            return None
        sizes = self._selection_splitter.sizes()
        if len(sizes) == 2 and all(size > 0 for size in sizes):
            return (sizes[0], sizes[1])
        return self._splitter_sizes

    def _show_character_detail(self, index) -> None:
        if not index.isValid():
            return
        character = self._character_model.character(index.row())
        self._detail_glyph_label.setText(_display_glyph(character))
        while self._detail_layout.rowCount():
            self._detail_layout.removeRow(0)
        rows = (
            ("Unicode", f"U+{ord(character):04X}"),
            ("Name", unicodedata.name(character, "<unknown>")),
            ("General category", unicodedata.category(character)),
            ("Canonical combining class", str(unicodedata.combining(character))),
            ("Bidirectional category", unicodedata.bidirectional(character) or "—"),
            ("Character decomposition mapping", _decomposition_or_dash(character)),
            ("Uppercase mapping", _mapping_or_dash(character, str.upper)),
            ("Titlecase mapping", _mapping_or_dash(character, str.title)),
            ("Unicode version", unicodedata.age(character) or "—"),
        )
        for label, value in rows:
            self._detail_layout.addRow(label, QLabel(value, self._detail_widget))
