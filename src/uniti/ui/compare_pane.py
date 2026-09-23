"""Side-by-side document comparison (BF-070: Phase 1 plain view, Phase 2
merge-style apply/reject, Phase 3 doc-vs-disk mode is not implemented;
"full editor parity" follow-up: standalone window, real `UNITITextView`
panes, zoom sync, and cross-pane current-line highlight).

Scope, confirmed with the user and recorded in
`docs/project/02_plans/2026-09-17-compare-diff-plan.md`: this covers two
currently-open documents only (doc-vs-saved-disk is Phase 3). `ComparePane`
is its own standalone, non-modal top-level window (not embedded in
`UNITIMainWindow._central_splitter`, and not the fuller Find/Replace-style
attach/detach mechanism — no splitter-embedding option at all, per the
2026-09-18 follow-up finding). Each side is a genuine read-only
`UNITITextView` bound directly to the compared `Document` (the same
pattern an ordinary editor tab uses, and the same one `split_right()`
already relies on for two views sharing one document) rather than a
bespoke `QPlainTextEdit` fed with `setPlainText` — this is what gives
Compare whitespace markers, syntax highlighting, zoom, and theming for
free, and lets an edit to a compared document from an ordinary tab
elsewhere repaint through the view's own existing live-document machinery
instead of a separate text-refresh path. The two sides synchronize
scrolling through a line-alignment mapping derived from the diff's own
hunk list (`uniti.core.text_diff`), not a raw scrollbar link. Each pane's
vertical scrollbar is a first-visible-logical-line index whenever wrap is
off (`_refresh_scrollbars`) but a wrapped-row index when it's on; scroll
sync (`_on_left_scrolled`/`_on_right_scrolled`/`_go_to_hunk`) converts
through `UNITITextView.line_for_visual_row`/`visual_row_for_line` at each
pane's own boundary (BF-077) so the hunk-alignment math itself always
operates in logical-line coordinates regardless of which pane, if any,
has wrap enabled.

Applying a hunk (or all remaining hunks) copies the *other* side's exact
text for that line range — terminators and all, read straight from the
source document rather than rejoined with a guessed separator — onto the
target document via `Document.replace`/`replace_many`, each one atomic
undoable transaction. There is no separate "reject" action: rejecting a
hunk is simply not applying it and moving on with Next/Previous, since
there is no third "resolved but intentionally left different" state to
track — two arbitrary documents have no "ours/theirs" base to reconcile
against, unlike a three-way merge.

Deliberately not done (each a possible follow-up, not an oversight):
neither side is padded with blank placeholder lines to keep the two panes
row-for-row aligned — they scroll in sync via the hunk mapping instead;
and within a changed (`REPLACE`) hunk, only the whole line is
highlighted, not the specific differing segment within it
(`uniti.core.text_diff` is purely line-level).

Line wrap (BF-077, per-pane via the right-click context menu, off by
default like an ordinary editor tab): each pane still only knows its own
wrapped-row index, so scroll sync converts at both boundaries — the
source pane's scrollbar value to a logical line via `line_for_visual_row`
before the hunk-alignment math, and the aligned result back to the target
pane's own scrollbar value via `visual_row_for_line` — rather than
teaching `uniti.core.text_diff` anything about wrapped rows. Toggling wrap
resets that pane's scrollbar to 0 (`UNITITextView.set_soft_wrap`'s own
existing behavior for a single view), which the sync wiring then carries
over to the other pane like any other scroll event.
"""

from __future__ import annotations

import weakref
from collections.abc import Mapping, Sequence
from difflib import SequenceMatcher

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QActionGroup, QColor
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from uniti.app.editor_state import EditorState
from uniti.core.document import Document
from uniti.core.syntax_profiles import PROFILES, profile_for_extension
from uniti.core.text_diff import (
    Hunk,
    HunkKind,
    align_left_to_right,
    align_right_to_left,
    changed_hunks,
    diff_lines,
)
from uniti.ui.text_view import UNITITextView
from uniti.ui.theme import THEME_MODES, active_theme, resolve_editor_tokens
from uniti.ui.whitespace import WhitespaceMode

# Provisional, not yet empirically tuned (see the BF-070 plan's open
# question on sizing): Compare reads two whole buffers and runs a diff
# pass, so it needs its own bound rather than reusing Format Document's
# MAX_REFORMAT_CHARS (16 MiB), which only pays for one buffer and no diff.
# This bounds the *diff*, not display — `UNITITextView` itself is
# huge-file-safe regardless (virtualized rendering, no whole-buffer widget
# content), unlike the old `QPlainTextEdit.setPlainText` approach.
MAX_COMPARE_CHARS = 4 * 1024 * 1024

_HUNK_COLORS = {
    HunkKind.INSERT: QColor(46, 160, 67, 60),
    HunkKind.DELETE: QColor(248, 81, 73, 60),
    HunkKind.REPLACE: QColor(210, 153, 34, 60),
}

# A more saturated version of the REPLACE line tint, layered on top of it
# for the specific character range that differs within a changed line
# (2026-09-18 follow-up: "cat"/"fat" should highlight just the "c"/"f",
# not the whole line uniformly).
_INTRA_LINE_CHANGE_COLOR = QColor(210, 153, 34, 150)

# The cross-pane current-line indicator's background tint (BF-078: the
# 2026-09-18 cross-pane marker was gutter-only -- a thin 3px accent bar,
# `tokens.current_match` -- with no row background of its own). A blue
# hue, deliberately distinct from every hunk color above (green/red/amber)
# and from the app's own current-line token (which marks the *locally*
# focused line, a different thing from the line *mapped from the other
# pane*) so the two concepts stay visually distinguishable even layered
# on top of a hunk background.
_CROSS_PANE_CURRENT_LINE_COLOR = QColor(88, 166, 255, 70)


def _blend_over(base: QColor, overlay: QColor) -> QColor:
    """Alpha-composite `overlay` over `base` (the standard "over"
    operator) so a marker line that already has a hunk-kind background
    reads as visibly layered rather than one color silently replacing
    the other."""

    overlay_alpha = overlay.alphaF()
    base_alpha = base.alphaF()
    out_alpha = overlay_alpha + base_alpha * (1 - overlay_alpha)
    if out_alpha <= 0:
        return QColor(0, 0, 0, 0)

    def channel(overlay_component: int, base_component: int) -> int:
        return round(
            (
                overlay_component * overlay_alpha
                + base_component * base_alpha * (1 - overlay_alpha)
            )
            / out_alpha
        )

    return QColor(
        channel(overlay.red(), base.red()),
        channel(overlay.green(), base.green()),
        channel(overlay.blue(), base.blue()),
        round(out_alpha * 255),
    )


def document_lines(document: Document) -> list[str]:
    """Split `document` into lines the same way UNITI defines a line
    everywhere else (`Document.line_start`/`line_end`), not Python's
    broader `str.splitlines()` — keeps the diff consistent with the rest
    of the app's EOL model instead of a subtly different notion of "line".
    """

    return [
        document.read(document.line_start(index), document.line_end(index))
        for index in range(document.line_count())
    ]


def _line_range_span(document: Document, start: int, end: int) -> tuple[int, int]:
    """The char-offset span covering lines `[start, end)` of `document`,
    including each line's own trailing terminator — so a hunk's line range
    can be read or replaced as a whole, terminators and all, rather than
    needing a guessed separator to rejoin stripped lines. `end` reaching
    the document's last line is the one case with no terminator to
    include, so it clamps to `total_chars()` instead of `line_start(end)`,
    which would not exist.
    """

    total_lines = document.line_count()
    span_start = (
        document.line_start(start) if start < total_lines else document.total_chars()
    )
    span_end = (
        document.line_start(end) if end < total_lines else document.total_chars()
    )
    return span_start, span_end


_EOL_TERMINATORS = {"LF": "\n", "CRLF": "\r\n", "CR": "\r"}


def _insertion_text(document: Document, position: int, text: str) -> str:
    """`text`, prefixed with a terminator if inserting it at `position`
    would otherwise glue it directly onto a preceding line that has no
    terminator of its own — the one place `_line_range_span` gives a pure
    insertion point (`start == end == line_count`) with nothing already
    separating it from the document's existing final line. Every other
    insertion point sits right after some line's own terminator (or is
    position 0), so this is a no-op there.
    """

    if not text or position == 0:
        return text
    preceding = document.read(position - 1, position)
    if preceding in ("\n", "\r"):
        return text
    return _EOL_TERMINATORS[document.insertion_eol] + text


def _line_kind_map(hunks: Sequence[Hunk], *, side: str) -> dict[int, HunkKind]:
    result: dict[int, HunkKind] = {}
    for hunk in hunks:
        if hunk.kind is HunkKind.EQUAL:
            continue
        start, end = (
            (hunk.left_start, hunk.left_end)
            if side == "left"
            else (hunk.right_start, hunk.right_end)
        )
        for line in range(start, end):
            result[line] = hunk.kind
    return result


def _char_diff_spans(
    hunks: Sequence[Hunk], left_lines: Sequence[str], right_lines: Sequence[str]
) -> tuple[
    dict[int, tuple[tuple[int, int, QColor], ...]],
    dict[int, tuple[tuple[int, int, QColor], ...]],
]:
    """Character-level highlight spans within each `REPLACE` hunk's paired
    lines — the specific differing segment of a changed line (e.g. just
    the "c"/"f" of "cat"/"fat"), on top of `_line_kind_map`'s whole-line
    coloring rather than replacing it.

    Only `REPLACE` hunks are considered: a pure `INSERT`/`DELETE` hunk has
    no counterpart line on the other side to diff against character by
    character, so it stays whole-line-only. Within a `REPLACE` hunk whose
    two sides have different line counts, lines are paired 1:1 from the
    hunk's start up to the shorter side's length — the common heuristic
    other diff tools use — leaving any excess lines on the longer side
    whole-line-only too, since they have no natural counterpart either.
    """

    left_spans: dict[int, tuple[tuple[int, int, QColor], ...]] = {}
    right_spans: dict[int, tuple[tuple[int, int, QColor], ...]] = {}
    for hunk in hunks:
        if hunk.kind is not HunkKind.REPLACE:
            continue
        paired = min(hunk.left_end - hunk.left_start, hunk.right_end - hunk.right_start)
        for offset in range(paired):
            left_line_no = hunk.left_start + offset
            right_line_no = hunk.right_start + offset
            matcher = SequenceMatcher(
                a=left_lines[left_line_no], b=right_lines[right_line_no], autojunk=False
            )
            left_ranges = tuple(
                (i1, i2, _INTRA_LINE_CHANGE_COLOR)
                for tag, i1, i2, _j1, _j2 in matcher.get_opcodes()
                if tag != "equal" and i2 > i1
            )
            right_ranges = tuple(
                (j1, j2, _INTRA_LINE_CHANGE_COLOR)
                for tag, _i1, _i2, j1, j2 in matcher.get_opcodes()
                if tag != "equal" and j2 > j1
            )
            if left_ranges:
                left_spans[left_line_no] = left_ranges
            if right_ranges:
                right_spans[right_line_no] = right_ranges
    return left_spans, right_spans


class _CompareTitleBar(QWidget):
    """Custom title bar for the frameless window (2026-09-20 request:
    styled/behaved the same way as the Character Inspector's and Find/
    Replace's own detached window -- square corners, no minimize/close
    controls -- which for a plain `QWidget`/`QDialog` top-level window
    means fully frameless, since `Qt.WindowType.Tool` alone still draws
    the native OS frame on every platform tested). Same drag-to-move
    mechanism as `_CharacterInspectorTitleBar`/`_FindReplaceTitleBar`: a
    custom title bar widget disables Qt's built-in native drag gesture,
    so this reimplements it directly. No close button -- Compare already
    has its own explicit Close button in the header below."""

    def __init__(self, pane: QWidget, title: str) -> None:
        super().__init__(pane)
        self._pane = pane
        self._drag_offset: QPoint | None = None
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 2, 2)
        label = QLabel(title, self)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        layout.addWidget(label)
        layout.addStretch(1)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._pane.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            self._pane.move(global_pos - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class ComparePane(QWidget):
    """Two synchronized read-only `UNITITextView` panes comparing two open
    documents, as its own standalone top-level window."""

    closeRequested = Signal()
    _recomputeRequested = Signal()

    def __init__(
        self,
        left_document: Document,
        left_label: str,
        right_document: Document,
        right_label: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # Frameless + `Tool` + stays-on-top (2026-09-20 request: match the
        # Character Inspector's/Find-Replace's own detached-window chrome
        # -- see `_CompareTitleBar` above for why frameless is required).
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        title = f"{left_label}  vs.  {right_label}"
        self.setWindowTitle(f"Compare — {title}")
        self._left_document = left_document
        self._right_document = right_document
        self._hunks: tuple[Hunk, ...] = ()
        self._changed: tuple[Hunk, ...] = ()
        self._hunk_index = -1
        self._syncing = False
        self._zoom_syncing = False
        self._recompute_queued = False
        self._closed = False
        self._left_kinds: dict[int, HunkKind] = {}
        self._right_kinds: dict[int, HunkKind] = {}
        self._left_char_spans: dict[int, tuple[tuple[int, int, QColor], ...]] = {}
        self._right_char_spans: dict[int, tuple[tuple[int, int, QColor], ...]] = {}
        self._left_marker_line: int | None = None
        self._right_marker_line: int | None = None
        self._syntax_extension_overrides: dict[str, str] = {}

        header = QHBoxLayout()
        header.addStretch(1)
        self._status_label = QLabel(self)
        header.addWidget(self._status_label)
        zoom_out_button = QPushButton("Zoom −", self)
        zoom_out_button.clicked.connect(lambda: self._left_view.zoom_out())
        zoom_in_button = QPushButton("Zoom +", self)
        zoom_in_button.clicked.connect(lambda: self._left_view.zoom_in())
        previous_button = QPushButton("◀ Previous", self)
        previous_button.clicked.connect(lambda: self._go_to_hunk(-1))
        next_button = QPushButton("Next ▶", self)
        next_button.clicked.connect(lambda: self._go_to_hunk(1))
        self._apply_current_right_button = QPushButton("Apply →", self)
        self._apply_current_right_button.setToolTip(
            "Copy the current change from the left document into the right."
        )
        self._apply_current_right_button.clicked.connect(
            lambda: self._apply_current(direction="left_to_right")
        )
        self._apply_current_left_button = QPushButton("Apply ←", self)
        self._apply_current_left_button.setToolTip(
            "Copy the current change from the right document into the left."
        )
        self._apply_current_left_button.clicked.connect(
            lambda: self._apply_current(direction="right_to_left")
        )
        self._apply_all_right_button = QPushButton("Apply All →", self)
        self._apply_all_right_button.clicked.connect(
            lambda: self._apply_all(direction="left_to_right")
        )
        self._apply_all_left_button = QPushButton("Apply All ←", self)
        self._apply_all_left_button.clicked.connect(
            lambda: self._apply_all(direction="right_to_left")
        )
        close_button = QPushButton("Close", self)
        close_button.clicked.connect(self.close_compare)
        header.addWidget(zoom_out_button)
        header.addWidget(zoom_in_button)
        header.addWidget(previous_button)
        header.addWidget(next_button)
        header.addWidget(self._apply_current_left_button)
        header.addWidget(self._apply_current_right_button)
        header.addWidget(self._apply_all_left_button)
        header.addWidget(self._apply_all_right_button)
        header.addWidget(close_button)

        self._left_view = UNITITextView(EditorState(left_document))
        self._right_view = UNITITextView(EditorState(right_document))
        for view in (self._left_view, self._right_view):
            view.set_read_only(True)
            view.contextMenuRequested.connect(
                lambda position, view=view: self._show_view_context_menu(view, position)
            )
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._left_view)
        splitter.addWidget(self._right_view)
        splitter.setSizes([1, 1])

        outer_layout = QVBoxLayout(self)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)
        outer_layout.addWidget(_CompareTitleBar(self, title))

        content = QWidget(self)
        outer_layout.addWidget(content, 1)
        layout = QVBoxLayout(content)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)

        self._left_view.verticalScrollBar().valueChanged.connect(
            self._on_left_scrolled
        )
        self._right_view.verticalScrollBar().valueChanged.connect(
            self._on_right_scrolled
        )
        self._left_view.cursorPositionChanged.connect(self._on_left_cursor_moved)
        self._right_view.cursorPositionChanged.connect(self._on_right_cursor_moved)
        self._left_view.zoomChanged.connect(
            lambda percent: self._sync_zoom(self._right_view, percent)
        )
        self._right_view.zoomChanged.connect(
            lambda percent: self._sync_zoom(self._left_view, percent)
        )
        self._recomputeRequested.connect(
            self._recompute, Qt.ConnectionType.QueuedConnection
        )

        self._remove_left_listener = left_document.add_history_listener(
            self._make_listener()
        )
        self._remove_right_listener = right_document.add_history_listener(
            self._make_listener()
        )

        self._recompute()

    def _make_listener(self):
        pane_ref = weakref.ref(self)

        def listener(_event) -> None:
            pane = pane_ref()
            if pane is not None:
                pane._queue_recompute()

        return listener

    def _queue_recompute(self) -> None:
        if self._closed or self._recompute_queued:
            return
        self._recompute_queued = True
        self._recomputeRequested.emit()

    def _set_apply_buttons_enabled(self, enabled: bool) -> None:
        for button in (
            self._apply_current_left_button,
            self._apply_current_right_button,
            self._apply_all_left_button,
            self._apply_all_right_button,
        ):
            button.setEnabled(enabled)

    @staticmethod
    def _with_cross_pane_tint(
        colors: dict[int, QColor], marker_line: int | None
    ) -> dict[int, QColor]:
        """Layers the cross-pane current-line tint onto `marker_line`
        (BF-078), on top of whatever hunk-kind background (if any) that
        line already has, rather than replacing it -- so a mapped line
        inside a changed hunk still shows its hunk color, distinguishably
        brightened, instead of losing it."""

        if marker_line is None:
            return colors
        base = colors.get(marker_line)
        colors = dict(colors)
        colors[marker_line] = (
            _blend_over(base, _CROSS_PANE_CURRENT_LINE_COLOR)
            if base is not None
            else _CROSS_PANE_CURRENT_LINE_COLOR
        )
        return colors

    def _refresh_left_highlights(self) -> None:
        colors = self._with_cross_pane_tint(
            {line: _HUNK_COLORS[kind] for line, kind in self._left_kinds.items()},
            self._left_marker_line,
        )
        markers = (
            {self._left_marker_line} if self._left_marker_line is not None else None
        )
        self._left_view.set_line_highlights(colors, markers, self._left_char_spans)

    def _refresh_right_highlights(self) -> None:
        colors = self._with_cross_pane_tint(
            {line: _HUNK_COLORS[kind] for line, kind in self._right_kinds.items()},
            self._right_marker_line,
        )
        markers = (
            {self._right_marker_line} if self._right_marker_line is not None else None
        )
        self._right_view.set_line_highlights(colors, markers, self._right_char_spans)

    def _recompute(self) -> None:
        self._recompute_queued = False
        if self._closed:
            return
        try:
            for document in (self._left_document, self._right_document):
                if document.total_chars() > MAX_COMPARE_CHARS:
                    self._status_label.setText(
                        f"Too large to compare (over {MAX_COMPARE_CHARS:,} characters)."
                    )
                    self._hunks = ()
                    self._changed = ()
                    self._left_kinds = {}
                    self._right_kinds = {}
                    self._left_char_spans = {}
                    self._right_char_spans = {}
                    self._refresh_left_highlights()
                    self._refresh_right_highlights()
                    self._set_apply_buttons_enabled(False)
                    return
            left_lines = document_lines(self._left_document)
            right_lines = document_lines(self._right_document)
        except ValueError:
            self._status_label.setText("A compared document is no longer available.")
            self._hunks = ()
            self._changed = ()
            self._left_kinds = {}
            self._right_kinds = {}
            self._left_char_spans = {}
            self._right_char_spans = {}
            self._refresh_left_highlights()
            self._refresh_right_highlights()
            self._set_apply_buttons_enabled(False)
            return
        self._hunks = diff_lines(left_lines, right_lines)
        self._changed = changed_hunks(self._hunks)
        self._hunk_index = -1
        self._left_kinds = _line_kind_map(self._hunks, side="left")
        self._right_kinds = _line_kind_map(self._hunks, side="right")
        self._left_char_spans, self._right_char_spans = _char_diff_spans(
            self._hunks, left_lines, right_lines
        )
        self._refresh_left_highlights()
        self._refresh_right_highlights()
        count = len(self._changed)
        self._status_label.setText(f"{count} change{'s' if count != 1 else ''}")
        self._set_apply_buttons_enabled(bool(self._changed))

    def _sync_zoom(self, target: UNITITextView, percent: int) -> None:
        if self._zoom_syncing:
            return
        self._zoom_syncing = True
        try:
            target.set_zoom_percent(percent)
        finally:
            self._zoom_syncing = False

    @property
    def zoom_percent(self) -> int:
        """Both panes always stay in sync (`_sync_zoom` above), so either
        one's own zoom represents the pane's zoom as a whole -- read by
        `UNITIMainWindow._toggle_window`'s generic geometry/zoom
        persistence (2026-09-20 request) when this window closes."""

        return self._left_view.zoom_percent

    def set_zoom_percent(self, percent: int) -> None:
        """Restores a previously-persisted zoom level on reopen. Setting
        just the left view is enough -- its `zoomChanged` signal cascades
        to the right view through the same `_sync_zoom` wiring an
        interactive zoom change already uses."""

        self._left_view.set_zoom_percent(percent)

    @staticmethod
    def _clamp_line(line: int, document: Document) -> int:
        return max(0, min(line, max(0, document.line_count() - 1)))

    def _on_left_cursor_moved(self, line: int, _column: int) -> None:
        target = self._clamp_line(
            round(align_left_to_right(self._hunks, line)), self._right_document
        )
        if target == self._right_marker_line:
            return
        self._right_marker_line = target
        self._refresh_right_highlights()

    def _on_right_cursor_moved(self, line: int, _column: int) -> None:
        target = self._clamp_line(
            round(align_right_to_left(self._hunks, line)), self._left_document
        )
        if target == self._left_marker_line:
            return
        self._left_marker_line = target
        self._refresh_left_highlights()

    def _on_left_scrolled(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            line, _column = self._left_view.line_for_visual_row(value)
            target_line = self._clamp_line(
                round(align_left_to_right(self._hunks, line)), self._right_document
            )
            target = self._right_view.visual_row_for_line(target_line)
            bar = self._right_view.verticalScrollBar()
            bar.setValue(max(bar.minimum(), min(bar.maximum(), target)))
        finally:
            self._syncing = False

    def _on_right_scrolled(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            line, _column = self._right_view.line_for_visual_row(value)
            target_line = self._clamp_line(
                round(align_right_to_left(self._hunks, line)), self._left_document
            )
            target = self._left_view.visual_row_for_line(target_line)
            bar = self._left_view.verticalScrollBar()
            bar.setValue(max(bar.minimum(), min(bar.maximum(), target)))
        finally:
            self._syncing = False

    def _go_to_hunk(self, delta: int) -> None:
        if not self._changed:
            return
        self._hunk_index = (self._hunk_index + delta) % len(self._changed)
        hunk = self._changed[self._hunk_index]
        self._syncing = True
        try:
            self._left_view.verticalScrollBar().setValue(
                self._left_view.visual_row_for_line(hunk.left_start)
            )
            self._right_view.verticalScrollBar().setValue(
                self._right_view.visual_row_for_line(hunk.right_start)
            )
        finally:
            self._syncing = False

    def _current_hunk_index(self) -> int:
        """The hunk `Apply` (as opposed to `Apply All`) acts on: whichever
        one Previous/Next last navigated to, defaulting to the first
        changed hunk before the user has navigated at all.
        """

        if not self._changed:
            return -1
        return self._hunk_index if self._hunk_index >= 0 else 0

    def _apply_current(self, *, direction: str) -> None:
        index = self._current_hunk_index()
        if index < 0:
            return
        self._apply_hunk(self._changed[index], direction=direction)

    def _apply_hunk(self, hunk: Hunk, *, direction: str) -> None:
        source_doc, target_doc, source_range, target_range = self._resolve_direction(
            hunk, direction
        )
        source_a, source_b = _line_range_span(source_doc, *source_range)
        text = source_doc.read(source_a, source_b)
        target_a, target_b = _line_range_span(target_doc, *target_range)
        if target_a == target_b:
            text = _insertion_text(target_doc, target_a, text)
        target_doc.replace(target_a, target_b, text)

    def _apply_all(self, *, direction: str) -> None:
        if not self._changed:
            return
        replacements: list[tuple[int, int, str]] = []
        target_doc: Document | None = None
        for hunk in self._changed:
            source_doc, target_doc, source_range, target_range = (
                self._resolve_direction(hunk, direction)
            )
            source_a, source_b = _line_range_span(source_doc, *source_range)
            text = source_doc.read(source_a, source_b)
            target_a, target_b = _line_range_span(target_doc, *target_range)
            if target_a == target_b:
                text = _insertion_text(target_doc, target_a, text)
            replacements.append((target_a, target_b, text))
        target_doc.replace_many(replacements)

    def _resolve_direction(
        self, hunk: Hunk, direction: str
    ) -> tuple[Document, Document, tuple[int, int], tuple[int, int]]:
        if direction == "left_to_right":
            return (
                self._left_document,
                self._right_document,
                (hunk.left_start, hunk.left_end),
                (hunk.right_start, hunk.right_end),
            )
        if direction == "right_to_left":
            return (
                self._right_document,
                self._left_document,
                (hunk.right_start, hunk.right_end),
                (hunk.left_start, hunk.left_end),
            )
        raise ValueError(f"unknown apply direction: {direction!r}")

    def apply_view_defaults(
        self,
        *,
        whitespace_mode: str,
        tab_width: int,
        syntax_extension_overrides: Mapping[str, str],
    ) -> None:
        """Match an ordinary editor tab's per-file appearance (whitespace
        mode, tab width, syntax highlighting) on each pane. Needed because
        these panes are built directly rather than through
        `UNITIMainWindow._add_document`, which is what normally seeds a
        new view from the current settings — without this, "full editor
        parity" panes still looked like plain, unstyled text (2026-09-18
        regression report: no whitespace markers, no syntax highlighting)."""

        self._syntax_extension_overrides = dict(syntax_extension_overrides)
        for view, document in (
            (self._left_view, self._left_document),
            (self._right_view, self._right_document),
        ):
            view.set_whitespace_mode(whitespace_mode)
            view.set_tab_width(tab_width)
            view.set_syntax_profile(
                profile_for_extension(document.path.suffix, syntax_extension_overrides)
            )

    def _show_view_context_menu(self, view: UNITITextView, global_position) -> None:
        """Compare has no menu bar of its own, so per-view display
        settings (whitespace, tab width, syntax profile, editor theme —
        the same ones `UNITIMainWindow`'s View menu offers an ordinary
        tab) need a context menu here instead — otherwise there is no way
        to change them at all after `apply_view_defaults` seeds them
        (2026-09-20 report: "cannot change whitespace highlight state").
        Applies only to the pane that was right-clicked, not both."""

        document = self._left_document if view is self._left_view else self._right_document
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)

        wrap_action = menu.addAction("Line Wrap")
        wrap_action.setCheckable(True)
        wrap_action.setChecked(view.soft_wrap)
        wrap_action.triggered.connect(
            lambda checked, view=view: view.set_soft_wrap(checked)
        )
        menu.addSeparator()

        whitespace_menu = menu.addMenu("Whitespace")
        whitespace_group = QActionGroup(menu)
        whitespace_group.setExclusive(True)
        for mode, label in (
            (WhitespaceMode.OFF, "Off"),
            (WhitespaceMode.EOL, "EOL"),
            (WhitespaceMode.SPACES_TABS, "Spaces & Tabs"),
            (WhitespaceMode.INVISIBLE_UNICODE, "Invisible Unicode"),
            (WhitespaceMode.ALL, "All"),
        ):
            action = whitespace_menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(view.whitespace_mode is mode)
            action.triggered.connect(
                lambda _checked=False, mode=mode, view=view: view.set_whitespace_mode(mode)
            )
            whitespace_group.addAction(action)

        tab_width_menu = menu.addMenu("Tab Width")
        tab_width_group = QActionGroup(menu)
        tab_width_group.setExclusive(True)
        for width in (2, 4, 8):
            action = tab_width_menu.addAction(str(width))
            action.setCheckable(True)
            action.setChecked(view.tab_width == width)
            action.triggered.connect(
                lambda _checked=False, width=width, view=view: view.set_tab_width(width)
            )
            tab_width_group.addAction(action)

        syntax_menu = menu.addMenu("Syntax Profile")
        syntax_group = QActionGroup(menu)
        syntax_group.setExclusive(True)
        auto_action = syntax_menu.addAction("Auto (by File Type)")
        auto_action.setCheckable(True)
        auto_action.setChecked(view.syntax_choice_key is None)

        def _use_auto(_checked=False, view=view, document=document) -> None:
            view.set_syntax_choice(
                None,
                profile_for_extension(
                    document.path.suffix, self._syntax_extension_overrides
                ),
            )

        auto_action.triggered.connect(_use_auto)
        syntax_group.addAction(auto_action)
        for profile in PROFILES:
            action = syntax_menu.addAction(profile.label)
            action.setCheckable(True)
            action.setChecked(view.syntax_choice_key == profile.key)
            action.triggered.connect(
                lambda _checked=False, key=profile.key, profile=profile, view=view: (
                    view.set_syntax_choice(key, profile)
                )
            )
            syntax_group.addAction(action)

        theme_menu = menu.addMenu("Editor Theme")
        theme_group = QActionGroup(menu)
        theme_group.setExclusive(True)
        app = QApplication.instance()
        follow_action = theme_menu.addAction("Follow App Theme")
        follow_action.setCheckable(True)
        follow_action.setChecked(view.theme_choice_id is None)

        def _follow_app_theme(_checked=False, view=view, app=app) -> None:
            tokens = active_theme(app).editor if isinstance(app, QApplication) else None
            view.set_theme_choice(None, tokens)

        follow_action.triggered.connect(_follow_app_theme)
        theme_group.addAction(follow_action)
        if isinstance(app, QApplication):
            contrast = active_theme(app).contrast
            for mode in THEME_MODES:
                action = theme_menu.addAction(mode)
                action.setCheckable(True)
                action.setChecked(view.theme_choice_id == mode)

                def _choose_mode(
                    _checked=False, mode=mode, view=view, app=app, contrast=contrast
                ) -> None:
                    view.set_theme_choice(mode, resolve_editor_tokens(app, mode, contrast))

                action.triggered.connect(_choose_mode)
                theme_group.addAction(action)

        menu.popup(global_position)

    def close_compare(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._remove_left_listener is not None:
            self._remove_left_listener()
            self._remove_left_listener = None
        if self._remove_right_listener is not None:
            self._remove_right_listener()
            self._remove_right_listener = None
        self._left_view.close()
        self._right_view.close()
        self.closeRequested.emit()

    def closeEvent(self, event) -> None:
        self.close_compare()
        super().closeEvent(event)


class CompareDocumentPickerDialog(QDialog):
    """Picks two of `candidates` (label, `Document`) to compare."""

    def __init__(
        self,
        candidates: Sequence[tuple[str, Document]],
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Compare Documents")
        self._candidates = tuple(candidates)
        layout = QFormLayout(self)
        self._left_combo = QComboBox(self)
        self._right_combo = QComboBox(self)
        for label, _ in self._candidates:
            self._left_combo.addItem(label)
            self._right_combo.addItem(label)
        if len(self._candidates) > 1:
            self._right_combo.setCurrentIndex(1)
        layout.addRow("Left:", self._left_combo)
        layout.addRow("Right:", self._right_combo)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addRow(buttons)

    def left_choice(self) -> tuple[str, Document]:
        return self._candidates[self._left_combo.currentIndex()]

    def right_choice(self) -> tuple[str, Document]:
        return self._candidates[self._right_combo.currentIndex()]
