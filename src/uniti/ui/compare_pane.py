"""Side-by-side document comparison (BF-070: Phase 1 plain view, Phase 2
merge-style apply/reject; Phase 3 doc-vs-disk mode is not implemented).

Scope, confirmed with the user and recorded in
`docs/project/02_plans/2026-09-17-compare-diff-plan.md`: this covers two
currently-open documents only (doc-vs-saved-disk is Phase 3). Architecture
follows that plan's resolved decisions exactly: `ComparePane` attaches
into `UNITIMainWindow._central_splitter` beside the pane tree, the same
non-modal attachment `MarkdownPreviewPane` already uses (not a modal
`QDialog` like Character Inspector/Diagnostics), and the two sides
synchronize scrolling through a line-alignment mapping derived from the
diff's own hunk list (`uniti.core.text_diff`), not a raw scrollbar link.

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
and if a compared document closes while this pane is still open, no
further recompute happens (closing is not itself a history event this
pane listens for) — the pane just shows its last-known content, which is
safe (no crash) but visibly stale.
"""

from __future__ import annotations

import weakref
from collections.abc import Sequence

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QTextCursor, QTextFormat
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from uniti.core.document import Document
from uniti.core.text_diff import (
    Hunk,
    HunkKind,
    align_left_to_right,
    align_right_to_left,
    changed_hunks,
    diff_lines,
)
from uniti.ui.font_policy import resolve_editor_font

# Provisional, not yet empirically tuned (see the BF-070 plan's open
# question on sizing): Compare reads two whole buffers and runs a diff
# pass, so it needs its own bound rather than reusing Format Document's
# MAX_REFORMAT_CHARS (16 MiB), which only pays for one buffer and no diff.
MAX_COMPARE_CHARS = 4 * 1024 * 1024

_HUNK_COLORS = {
    HunkKind.INSERT: QColor(46, 160, 67, 60),
    HunkKind.DELETE: QColor(248, 81, 73, 60),
    HunkKind.REPLACE: QColor(210, 153, 34, 60),
}


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


class _HunkGutter(QWidget):
    def __init__(self, editor: "_ComparePlainTextEdit") -> None:
        super().__init__(editor)
        self._editor = editor

    def sizeHint(self) -> QSize:
        return QSize(self._editor.gutter_width(), 0)

    def paintEvent(self, event) -> None:
        self._editor.paint_gutter(self, event)


class _ComparePlainTextEdit(QPlainTextEdit):
    """A read-only, non-wrapping text pane with a hunk-colored gutter.

    Non-wrapping is deliberate, not just a style choice: with word wrap
    off, `verticalScrollBar().value()` is exactly the index of the first
    visible line, which is what the line-alignment scroll sync needs. Wrap
    would make that value a wrapped-row count instead, breaking the
    mapping.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.setFont(resolve_editor_font().font)
        self._line_kinds: dict[int, HunkKind] = {}
        self._gutter = _HunkGutter(self)
        self.blockCountChanged.connect(self._update_gutter_width)
        self.updateRequest.connect(self._update_gutter)
        self._update_gutter_width()

    def set_line_kinds(self, kinds: dict[int, HunkKind]) -> None:
        self._line_kinds = kinds
        self._apply_highlights()
        self._gutter.update()

    def gutter_width(self) -> int:
        digits = len(str(max(1, self.blockCount())))
        return 8 + self.fontMetrics().horizontalAdvance("9") * digits + 6

    def _update_gutter_width(self) -> None:
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _update_gutter(self, rect, dy: int) -> None:
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())
        if rect.contains(self.viewport().rect()):
            self._update_gutter_width()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        rect = self.contentsRect()
        self._gutter.setGeometry(
            rect.left(), rect.top(), self.gutter_width(), rect.height()
        )

    def paint_gutter(self, gutter_widget: QWidget, event) -> None:
        painter = QPainter(gutter_widget)
        painter.fillRect(event.rect(), self.palette().window())
        block = self.firstVisibleBlock()
        line = block.blockNumber()
        top = round(
            self.blockBoundingGeometry(block).translated(self.contentOffset()).top()
        )
        bottom = top + round(self.blockBoundingRect(block).height())
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                kind = self._line_kinds.get(line)
                if kind is not None:
                    painter.fillRect(
                        0, top, gutter_widget.width(), bottom - top, _HUNK_COLORS[kind]
                    )
                painter.setPen(self.palette().windowText().color())
                painter.drawText(
                    0,
                    top,
                    gutter_widget.width() - 4,
                    bottom - top,
                    Qt.AlignmentFlag.AlignRight,
                    str(line + 1),
                )
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            line += 1

    def _apply_highlights(self) -> None:
        selections = []
        doc = self.document()
        for line, kind in self._line_kinds.items():
            block = doc.findBlockByNumber(line)
            if not block.isValid():
                continue
            selection = QTextEdit.ExtraSelection()
            selection.format.setBackground(_HUNK_COLORS[kind])
            selection.format.setProperty(
                QTextFormat.Property.FullWidthSelection, True
            )
            cursor = QTextCursor(block)
            cursor.clearSelection()
            selection.cursor = cursor
            selections.append(selection)
        self.setExtraSelections(selections)


class ComparePane(QWidget):
    """Two synchronized read-only panes comparing two open documents."""

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
        self._left_document = left_document
        self._right_document = right_document
        self._hunks: tuple[Hunk, ...] = ()
        self._changed: tuple[Hunk, ...] = ()
        self._hunk_index = -1
        self._syncing = False
        self._recompute_queued = False
        self._closed = False

        header = QHBoxLayout()
        header.addWidget(QLabel(f"{left_label}  vs.  {right_label}", self))
        header.addStretch(1)
        self._status_label = QLabel(self)
        header.addWidget(self._status_label)
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
        header.addWidget(previous_button)
        header.addWidget(next_button)
        header.addWidget(self._apply_current_left_button)
        header.addWidget(self._apply_current_right_button)
        header.addWidget(self._apply_all_left_button)
        header.addWidget(self._apply_all_right_button)
        header.addWidget(close_button)

        self._left_edit = _ComparePlainTextEdit(self)
        self._right_edit = _ComparePlainTextEdit(self)
        splitter = QSplitter(Qt.Orientation.Horizontal, self)
        splitter.addWidget(self._left_edit)
        splitter.addWidget(self._right_edit)
        splitter.setSizes([1, 1])

        layout = QVBoxLayout(self)
        layout.addLayout(header)
        layout.addWidget(splitter, 1)

        self._left_edit.verticalScrollBar().valueChanged.connect(
            self._on_left_scrolled
        )
        self._right_edit.verticalScrollBar().valueChanged.connect(
            self._on_right_scrolled
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
                    self._set_apply_buttons_enabled(False)
                    return
            left_lines = document_lines(self._left_document)
            right_lines = document_lines(self._right_document)
        except ValueError:
            self._status_label.setText("A compared document is no longer available.")
            self._hunks = ()
            self._changed = ()
            self._set_apply_buttons_enabled(False)
            return
        self._hunks = diff_lines(left_lines, right_lines)
        self._changed = changed_hunks(self._hunks)
        self._hunk_index = -1
        self._left_edit.setPlainText("\n".join(left_lines))
        self._right_edit.setPlainText("\n".join(right_lines))
        self._left_edit.set_line_kinds(_line_kind_map(self._hunks, side="left"))
        self._right_edit.set_line_kinds(_line_kind_map(self._hunks, side="right"))
        count = len(self._changed)
        self._status_label.setText(f"{count} change{'s' if count != 1 else ''}")
        self._set_apply_buttons_enabled(bool(self._changed))

    def _on_left_scrolled(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            target = round(align_left_to_right(self._hunks, value))
            bar = self._right_edit.verticalScrollBar()
            bar.setValue(max(bar.minimum(), min(bar.maximum(), target)))
        finally:
            self._syncing = False

    def _on_right_scrolled(self, value: int) -> None:
        if self._syncing:
            return
        self._syncing = True
        try:
            target = round(align_right_to_left(self._hunks, value))
            bar = self._left_edit.verticalScrollBar()
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
            self._left_edit.verticalScrollBar().setValue(hunk.left_start)
            self._right_edit.verticalScrollBar().setValue(hunk.right_start)
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
