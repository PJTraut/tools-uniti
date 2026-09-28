"""Whitespace & Unicode Legend: a static reference toggle window listing
every whitespace/invisible-Unicode marker the editor draws, each glyph
rendered via the exact same drawing code the live editor uses so the two
can never visually drift apart, tinted with the active theme's own marker
colors. Replaces the earlier "hold Ctrl+Alt/Cmd+Option" gesture, which only
listed marker types currently visible on screen and required holding the
combo the whole time; this is an ordinary toggle (`Ctrl+Alt+U`,
`Cmd+Option+U` on macOS) showing the complete reference regardless of what's
on screen or which Whitespace mode is active.
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QPoint, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from uniti.ui.theme import active_theme
from uniti.ui.whitespace import WhitespaceKind
from uniti.ui.whitespace_painter import paint_compact_marker

MIN_ZOOM_PERCENT = 50
MAX_ZOOM_PERCENT = 500
DEFAULT_ZOOM_PERCENT = 100
_ZOOM_STEP = 10
_BASE_GLYPH_SIZE = (32, 20)

# (kind, label, name, codepoint) -- `kind`/`label` select the exact same
# drawing branch `UNITITextView._paint_whitespace_marker` uses; `label` for
# WhitespaceKind.INVISIBLE rows matches a `paint_compact_marker` case (or
# falls through to its generic diamond, e.g. "OTHER" below).
_CATEGORIES: tuple[tuple[str, tuple[tuple[object, str, str, str], ...]], ...] = (
    (
        "ORDINARY",
        (
            (WhitespaceKind.SPACE, "SPACE", "Space", "U+0020"),
            (WhitespaceKind.TAB, "TAB", "Tab", "U+0009"),
            ("eol", "LF", "Line Feed", "U+000A"),
            ("eol", "CR", "Carriage Return", "U+000D"),
            ("eol", "CRLF", "CRLF", "U+000D U+000A"),
        ),
    ),
    (
        "SPACING VARIANTS",
        (
            (WhitespaceKind.INVISIBLE, "EMSP", "Em Space", "U+2003"),
            (WhitespaceKind.INVISIBLE, "ENSP", "En Space", "U+2002"),
            (WhitespaceKind.INVISIBLE, "THINSP", "Thin Space", "U+2009"),
            (WhitespaceKind.INVISIBLE, "HAIRSP", "Hair Space", "U+200A"),
            (WhitespaceKind.INVISIBLE, "IDSP", "Ideographic Space", "U+3000"),
            (WhitespaceKind.INVISIBLE, "NBSP", "No-Break Space", "U+00A0"),
            (WhitespaceKind.INVISIBLE, "NNBSP", "Narrow No-Break Space", "U+202F"),
        ),
    ),
    (
        "ZERO-WIDTH & JOINERS",
        (
            (WhitespaceKind.INVISIBLE, "ZWSP", "Zero-Width Space", "U+200B"),
            (WhitespaceKind.INVISIBLE, "ZWNJ", "Zero-Width Non-Joiner", "U+200C"),
            (WhitespaceKind.INVISIBLE, "ZWJ", "Zero-Width Joiner", "U+200D"),
            (WhitespaceKind.INVISIBLE, "WJ", "Word Joiner", "U+2060"),
        ),
    ),
    (
        "DIRECTION & OTHER",
        (
            (WhitespaceKind.INVISIBLE, "LRM", "Left-to-Right Mark", "U+200E"),
            (WhitespaceKind.INVISIBLE, "RLM", "Right-to-Left Mark", "U+200F"),
            (WhitespaceKind.INVISIBLE, "BOM", "Byte Order Mark", "U+FEFF"),
            (WhitespaceKind.INVISIBLE, "OTHER", "Other Invisible", "U+xxxx"),
        ),
    ),
)


class _MarkerGlyphWidget(QWidget):
    """Paints one marker glyph in `color`, reusing the exact same drawing
    branch the live editor uses for that `kind`/`label` -- see
    `UNITITextView._paint_whitespace_marker` for the SPACE/TAB/eol cases,
    and `paint_compact_marker` (shared, imported directly) for everything
    else."""

    def __init__(self, kind: object, label: str, color: QColor, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._kind = kind
        self._label = label
        self._color = QColor(color)
        self.setFixedSize(*_BASE_GLYPH_SIZE)

    def set_scale(self, scale: float) -> None:
        width, height = _BASE_GLYPH_SIZE
        self.setFixedSize(max(1, round(width * scale)), max(1, round(height * scale)))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            rect = QRectF(self.rect()).adjusted(2, 2, -2, -2)
            if self._kind == WhitespaceKind.SPACE:
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(self._color)
                diameter = min(rect.width() * 0.35, rect.height() * 0.7)
                painter.drawEllipse(rect.center(), diameter / 2, diameter / 2)
                return
            painter.setPen(self._color)
            if self._kind == WhitespaceKind.TAB:
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, "»")
                return
            if self._kind == "eol":
                glyph = {"LF": "␊", "CR": "␍", "CRLF": "␍␊"}[self._label]
                painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, glyph)
                return
            paint_compact_marker(painter, self._label, rect)
        finally:
            painter.end()


class _WhitespaceLegendTitleBar(QWidget):
    """Custom draggable title bar, no close button -- Esc or the hotkey
    toggle closes this window, matching every other toggle window's own
    frameless chrome (`_CharacterInspectorTitleBar` is the precedent)."""

    def __init__(self, dialog: QDialog, title: str) -> None:
        super().__init__(dialog)
        self._dialog = dialog
        self._drag_offset: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        label = QLabel(title, self)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        font = label.font()
        font.setBold(True)
        label.setFont(font)
        layout.addWidget(label)
        layout.addStretch(1)

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


class WhitespaceLegendWindow(QDialog):
    """The toggle window itself. Non-modal, frameless, always-on-top Tool
    window -- built and populated fresh from the currently active theme
    every time it's opened, since it's a `_toggle_window` factory product,
    not a long-lived singleton.

    Class lineage note: this is a `QDialog`, the same base
    `CharacterInspectorDialog` uses -- not the same class as Find/Replace
    (`FindReplaceWindow(QDockWidget)`) or its Match Report display
    (`self.capture_view`, a `QListView`). Zoom (Ctrl/Cmd+wheel and
    Ctrl+=/Ctrl+-/Ctrl+0) is implemented independently here, mirroring the
    modifier-gated pattern both of those already use
    (`FindReplaceWindow._handle_zoom_wheel`,
    `CharacterInspectorDialog.wheelEvent`) rather than sharing code with
    them -- no common zoom mixin exists in this codebase to inherit from.
    """

    def __init__(
        self,
        *,
        initial_zoom_percent: int = DEFAULT_ZOOM_PERCENT,
        initial_geometry: tuple[int, int, int, int] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._base_font = QFont(self.font())
        self._base_point_size = self._base_font.pointSizeF()
        if self._base_point_size <= 0:
            self._base_point_size = 12.0
        self._zoom_percent = max(
            MIN_ZOOM_PERCENT, min(MAX_ZOOM_PERCENT, int(initial_zoom_percent))
        )
        self._glyphs: list[_MarkerGlyphWidget] = []

        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        # Every widget here (labels, glyphs) is non-focusable, so without
        # this a `Tool`-flagged window never becomes the real key/active
        # window on some platforms (notably macOS, which doesn't hand
        # keyboard focus to a floating panel unless something inside it
        # explicitly claims it) -- Ctrl+=/Ctrl+-/Ctrl+0 would then keep
        # reaching the editor's own zoom shortcuts underneath instead of
        # this window's, even though this window is visibly on top.
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(_WhitespaceLegendTitleBar(self, "Whitespace & Unicode Legend"))

        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(12, 8, 12, 12)
        content_layout.setSpacing(10)

        app = QApplication.instance()
        tokens = active_theme(app).editor
        color_for_kind = {
            WhitespaceKind.SPACE: tokens.space_marker,
            WhitespaceKind.TAB: tokens.tab_marker,
            "eol": tokens.eol_marker,
        }

        # One `QGridLayout` for the *entire* table (every category), not
        # one per category: Qt sizes each column to the widest cell it
        # contains across all rows given to it, so with separate grids
        # per category each one's codepoint column started at a different
        # x position (e.g. "ORDINARY"'s "U+000D U+000A" row is far wider
        # than any other category's codepoints, widening only that grid's
        # name column to compensate) -- one shared grid makes every
        # category's glyph/name/codepoint line up at the same "tab" down
        # the whole window, and column widths still rescale with zoom
        # since it's still just one live layout recalculated on font
        # changes.
        table = QGridLayout()
        table.setContentsMargins(12, 0, 0, 0)
        table.setHorizontalSpacing(12)
        table.setColumnStretch(1, 1)
        row_index = 0
        for category, rows in _CATEGORIES:
            heading = QLabel(category, content)
            heading.setAlignment(Qt.AlignmentFlag.AlignCenter)
            heading_font = heading.font()
            heading_font.setBold(True)
            heading.setFont(heading_font)
            table.addWidget(heading, row_index, 0, 1, 3)
            row_index += 1

            for kind, label, name, codepoint in rows:
                color = color_for_kind.get(kind, tokens.invisible_marker)
                glyph = _MarkerGlyphWidget(kind, label, color, content)
                self._glyphs.append(glyph)
                name_label = QLabel(name, content)
                name_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
                codepoint_label = QLabel(codepoint, content)
                codepoint_label.setAlignment(
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
                )
                table.addWidget(glyph, row_index, 0)
                table.addWidget(name_label, row_index, 1)
                table.addWidget(codepoint_label, row_index, 2)
                row_index += 1
        content_layout.addLayout(table)

        scroll_area = QScrollArea(self)
        scroll_area.setWidget(content)
        scroll_area.setWidgetResizable(True)
        scroll_area.setFrameShape(QScrollArea.Shape.NoFrame)
        outer.addWidget(scroll_area)
        self._scroll_area = scroll_area
        # A `QWidget` that doesn't override `wheelEvent` (every label and
        # glyph here) silently swallows an unhandled wheel event instead of
        # it reaching the containing `QScrollArea` -- Qt does not forward
        # ignored wheel events up the parent chain on its own. Since rows
        # fill nearly the full content width, that left wheel-scrolling
        # only working over the thin sliver of empty margin or the
        # scrollbar itself. Installing this filter on every content
        # descendant and redirecting Wheel events to the scroll area makes
        # scrolling work anywhere over the content, as expected.
        for widget in (content, *content.findChildren(QWidget)):
            widget.installEventFilter(self)

        if initial_geometry is not None:
            x, y, width, height = initial_geometry
            self.setGeometry(x, y, width, height)
        else:
            self.resize(340, 460)

        # `WidgetWithChildrenShortcut` rather than the default
        # `WindowShortcut`: the latter only fires while Qt considers this
        # window's the *active* top-level window, which a frameless
        # `Tool`-flagged window doesn't reliably become on every platform
        # (see the `setFocusPolicy` note above) -- scoping to "this widget
        # or a descendant has focus" instead ties activation directly to
        # the `setFocus()` this class already claims in `showEvent`,
        # sidestepping window-manager activation quirks entirely.
        for shortcut in (
            QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomIn), self, activated=self.zoom_in),
            QShortcut(QKeySequence(QKeySequence.StandardKey.ZoomOut), self, activated=self.zoom_out),
            QShortcut(QKeySequence("Ctrl+0"), self, activated=self.reset_zoom),
            QShortcut(QKeySequence("Ctrl+="), self, activated=self.zoom_in),
        ):
            shortcut.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._apply_zoom_fonts()

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
        scale = self._zoom_percent / 100.0
        font = QFont(self._base_font)
        font.setPointSizeF(max(1.0, self._base_point_size * scale))
        self.setFont(font)
        for widget in self.findChildren(QWidget):
            widget.setFont(font)
        for glyph in self._glyphs:
            glyph.set_scale(scale)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        # Claim focus every time this window becomes visible (including
        # the initial open) -- see the `setFocusPolicy` note in `__init__`
        # for why this can't just rely on the window manager's default.
        # `raise_`/`activateWindow` are redundant with `_toggle_window`'s
        # own calls right after construction, but cheap insurance against
        # any ordering where this fires before that.
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Wheel:
            # Same modifier-gated zoom-vs-scroll split as
            # `UNITITextView.wheelEvent`/`FindReplaceWindow._handle_zoom_wheel`:
            # Ctrl/Cmd+wheel zooms instead of scrolling.
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
                return True
            QApplication.sendEvent(self._scroll_area.viewport(), event)
            return True
        return super().eventFilter(watched, event)


__all__ = ["WhitespaceLegendWindow"]
