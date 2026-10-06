"""Editable rich-view pane (ADR-0015, spec Phase E7).

Shows one document through an environment's `EditorViewProvider` (SFM
Standard/Formatted, Markdown Rendered) beside the ordinary Source editor,
like the Markdown preview split — but editable. The pane never edits its
own text: every keystroke is mapped through the projection's `SourceMap`
to `Document.replace_many` (one undo step) and the view is re-projected
from the canonical source. Caret/selection follow the source editor and
vice versa.

Why a side-by-side pane rather than swapping the tab's widget: every
editor path in the window (Find/Replace, save, recovery, splits, session
capture) assumes a tab holds a `UNITITextView`. Keeping Source in the tab
and the rich view beside it leaves all of those untouched, and lets the
user see exactly what source each formatted edit produces.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtCore import QMimeData, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeySequence,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMenu,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from uniti.core.document import Document
from uniti.core.resource_profile import ResourceProfile
from uniti.core.rich_views.editing import EditPlan, EditRejected, plan_view_edit
from uniti.core.rich_views.projection import Projection
from uniti.core.rich_views.provider import EditorViewProvider, ViewCommand

logger = logging.getLogger("uniti.ui.rich_view")

_INCH_PX = 96.0


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


def char_format(attrs, base: QFont, dark: bool) -> QTextCharFormat:
    fmt = QTextCharFormat()
    if attrs.get("bold") == "yes":
        fmt.setFontWeight(QFont.Weight.Bold)
    if attrs.get("italic") == "yes":
        fmt.setFontItalic(True)
    if attrs.get("underline") == "yes":
        fmt.setFontUnderline(True)
    if attrs.get("superscript") == "yes":
        fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignSuperScript)
    if attrs.get("smallcaps") == "yes":
        fmt.setFontCapitalization(QFont.Capitalization.SmallCaps)
    if attrs.get("monospace") == "yes":
        fmt.setFontFamilies(["Menlo", "Consolas", "DejaVu Sans Mono", "monospace"])
    scale = _float(attrs.get("font_scale"), 1.0)
    if abs(scale - 1.0) > 0.01 and base.pointSizeF() > 0:
        fmt.setFontPointSize(base.pointSizeF() * scale)
    color = attrs.get("color")
    if color:
        fmt.setForeground(QBrush(QColor(color)))
    if attrs.get("muted") == "yes":
        fmt.setForeground(QBrush(QColor("#9aa0a6" if dark else "#6b7280")))
    if attrs.get("marker_token") == "yes":
        fmt.setForeground(QBrush(QColor("#8ab4f8" if dark else "#1a56db")))
        fmt.setBackground(QBrush(QColor("#1f2a3d" if dark else "#e8f0fe")))
        fmt.setFontFamilies(["Menlo", "Consolas", "DejaVu Sans Mono", "monospace"])
        if base.pointSizeF() > 0:
            fmt.setFontPointSize(base.pointSizeF() * 0.85)
    return fmt


def block_format(attrs) -> QTextBlockFormat:
    fmt = QTextBlockFormat()
    align = attrs.get("align")
    if align == "center":
        fmt.setAlignment(Qt.AlignmentFlag.AlignHCenter)
    elif align == "right":
        fmt.setAlignment(Qt.AlignmentFlag.AlignRight)
    elif align == "justify":
        fmt.setAlignment(Qt.AlignmentFlag.AlignJustify)
    if "left_margin" in attrs:
        fmt.setLeftMargin(_float(attrs["left_margin"]) * _INCH_PX)
    if "right_margin" in attrs:
        fmt.setRightMargin(_float(attrs["right_margin"]) * _INCH_PX)
    if "first_indent" in attrs:
        fmt.setTextIndent(_float(attrs["first_indent"]) * _INCH_PX)
    if "space_before" in attrs:
        fmt.setTopMargin(_float(attrs["space_before"]))
    if "space_after" in attrs:
        fmt.setBottomMargin(_float(attrs["space_after"]))
    if attrs.get("table_row") == "yes":
        tab = QTextOption.Tab
        fmt.setTabPositions([tab(index * 1.6 * _INCH_PX, QTextOption.TabType.LeftTab) for index in range(1, 9)])
    return fmt


def render_projection(document: QTextDocument, projection: Projection, base: QFont, dark: bool) -> None:
    """Fill `document` with `projection`'s text and formats."""

    document.clear()
    document.setDefaultFont(base)
    cursor = QTextCursor(document)
    cursor.insertText(projection.text)
    length = len(projection.text)
    for block in projection.blocks:
        start, end = max(0, block.view_start), min(length, block.view_end)
        cursor.setPosition(start)
        cursor.setPosition(max(start, end - 1 if end > start else end), QTextCursor.MoveMode.KeepAnchor)
        cursor.mergeBlockFormat(block_format(block.attrs))
        char_attrs = {key: value for key, value in block.attrs.items() if key in ("bold", "italic", "font_scale", "color", "muted", "smallcaps", "underline", "monospace")}
        if char_attrs and end > start:
            cursor.setPosition(start)
            cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeCharFormat(char_format(char_attrs, base, dark))
    for span in projection.spans:
        start, end = max(0, span.view_start), min(length, span.view_end)
        if end <= start:
            continue
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        cursor.mergeCharFormat(char_format(span.attrs, base, dark))


class _RichEditor(QTextEdit):
    """QTextEdit whose every modification is rerouted to the owner."""

    def __init__(self, owner: "RichViewPane") -> None:
        super().__init__(owner)
        self._owner = owner
        self.setAcceptRichText(False)
        self.setUndoRedoEnabled(False)
        self.setTabChangesFocus(False)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        owner = self._owner
        if event.matches(QKeySequence.StandardKey.Undo):
            owner.undo()
            return
        if event.matches(QKeySequence.StandardKey.Redo):
            owner.redo()
            return
        if event.matches(QKeySequence.StandardKey.Paste):
            owner.paste()
            return
        if event.matches(QKeySequence.StandardKey.Cut):
            owner.cut()
            return
        if event.matches(QKeySequence.StandardKey.Copy) or event.matches(QKeySequence.StandardKey.SelectAll):
            super().keyPressEvent(event)
            return
        for command in owner.commands:
            if command.shortcut and QKeySequence(command.shortcut).matches(
                QKeySequence(event.keyCombination())
            ) == QKeySequence.SequenceMatch.ExactMatch:
                owner.run_view_command(command.command_id)
                return
        key = event.key()
        if key in (Qt.Key.Key_Backspace, Qt.Key.Key_Delete):
            owner.delete(backwards=key == Qt.Key.Key_Backspace)
            return
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            owner.enter()
            return
        text = event.text()
        # Option/AltGr compose real characters; only Ctrl/Cmd/Meta chords are
        # shortcuts rather than typing.
        chord = event.modifiers() & (
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier
        )
        if (text and text.isprintable() and chord == Qt.KeyboardModifier.NoModifier) or text == "\t":
            owner.type_text(text)
            return
        super().keyPressEvent(event)  # navigation, selection

    def inputMethodEvent(self, event) -> None:  # noqa: N802
        if event.commitString():
            self._owner.type_text(event.commitString())
        event.accept()

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if source.hasText():
            self._owner.type_text(source.text())

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        return source.hasText()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.addAction("Cut", self._owner.cut).setEnabled(self.textCursor().hasSelection())
        menu.addAction("Copy", self.copy).setEnabled(self.textCursor().hasSelection())
        menu.addAction("Paste", self._owner.paste)
        menu.addSeparator()
        for command in self._owner.commands:
            menu.addAction(command.label, lambda command_id=command.command_id: self._owner.run_view_command(command_id))
        menu.exec(event.globalPos())


class RichViewPane(QWidget):
    """One document shown through one provider, editable via the source map."""

    caretSourceChanged = Signal(int, int)  # cursor, anchor (source offsets)
    closeRequested = Signal()
    providerChangeRequested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document: Document | None = None
        self.provider: EditorViewProvider | None = None
        self.projection: Projection | None = None
        self.commands: tuple[ViewCommand, ...] = ()
        self.last_message: str | None = None
        # Called after the pane changed the document (edit, undo, redo) so
        # the host can repaint the Source editors of the same document.
        self.document_applied: Callable[[], None] | None = None
        self._providers: tuple[EditorViewProvider, ...] = ()
        self._remove_listener: Callable[[], None] | None = None
        self._applying = False
        self._syncing_caret = False
        self._dark = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.refresh)

        self.mode = QComboBox(self)
        self.mode.setAccessibleName("Rich view mode")
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.mode.activated.connect(self._mode_activated)
        self.status = QLabel(self)
        self.command_bar = QHBoxLayout()
        self.command_bar.setContentsMargins(0, 0, 0, 0)
        close = QToolButton(self)
        close.setText("×")
        close.setToolTip("Close rich view (Source only)")
        close.clicked.connect(self.closeRequested.emit)
        header = QHBoxLayout()
        header.setContentsMargins(4, 2, 4, 2)
        header.addWidget(self.mode)
        header.addLayout(self.command_bar)
        header.addStretch(1)
        header.addWidget(self.status)
        header.addWidget(close)
        self.editor = _RichEditor(self)
        self.editor.cursorPositionChanged.connect(self._caret_moved)
        self.editor.selectionChanged.connect(self._caret_moved)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.editor, 1)

    # --- binding ------------------------------------------------------------

    def bind(self, document: Document, providers: tuple[EditorViewProvider, ...], key: str, font: QFont, dark: bool) -> None:
        if self._remove_listener is not None and self.document is not document:
            self._remove_listener()
            self._remove_listener = None
        if self.document is not document:
            self._remove_listener = document.add_edit_listener(self._document_edited)
        self.document = document
        self._providers = providers
        self._dark = dark
        self.editor.setFont(font)
        self.provider = next((p for p in providers if p.key == key), providers[0])
        self.commands = self.provider.view_commands()
        self.mode.blockSignals(True)
        self.mode.clear()
        for provider in providers:
            self.mode.addItem(provider.label, provider.key)
        self.mode.setCurrentIndex(self.mode.findData(self.provider.key))
        self.mode.blockSignals(False)
        # Size to the longest label now that the items exist.
        self.mode.setMinimumWidth(self.mode.sizeHint().width())
        self._rebuild_command_bar()
        self.refresh()

    def unbind(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        self.document = None

    def _rebuild_command_bar(self) -> None:
        while self.command_bar.count():
            item = self.command_bar.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for command in self.commands:
            button = QToolButton(self)
            button.setText(command.label)
            if command.shortcut:
                button.setToolTip(f"{command.label} ({QKeySequence(command.shortcut).toString(QKeySequence.SequenceFormat.NativeText)})")
            button.clicked.connect(lambda _checked=False, command_id=command.command_id: self.run_view_command(command_id))
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.command_bar.addWidget(button)

    def _mode_activated(self, index: int) -> None:
        key = self.mode.itemData(index)
        if isinstance(key, str):
            self.providerChangeRequested.emit(key)

    # --- projection ---------------------------------------------------------

    def source_text(self) -> str:
        assert self.document is not None
        return self.document.read(0, self.document.total_chars())

    def refresh(self, caret_source: int | None = None, anchor_source: int | None = None) -> None:
        if self.document is None or self.provider is None:
            return
        if not ResourceProfile(size_bytes=self.document.source.size).allow_full_parse:
            self.projection = None
            self.editor.setPlainText("This document is too large for a rich view (above 1 MiB). Use the Source editor.")
            self.editor.setReadOnly(True)
            return
        self.editor.setReadOnly(False)
        if caret_source is None and self.projection is not None:
            cursor = self.editor.textCursor()
            caret_source = self.projection.source_map.view_to_source(cursor.position())
            anchor_source = self.projection.source_map.view_to_source(cursor.anchor())
        try:
            projection = self.provider.project(self.source_text())
        except Exception:
            logger.exception("rich view %r failed to project", self.provider.key)
            self.projection = None
            self.editor.setPlainText("This view could not display the document. The Source editor is unaffected.")
            self.editor.setReadOnly(True)
            return
        scroll = self.editor.verticalScrollBar().value()
        self._syncing_caret = True
        try:
            self.projection = projection
            render_projection(self.editor.document(), projection, self.editor.font(), self._dark)
            self._place_caret(caret_source or 0, anchor_source)
        finally:
            self._syncing_caret = False
        self.editor.verticalScrollBar().setValue(scroll)

    def _place_caret(self, caret_source: int, anchor_source: int | None) -> None:
        if self.projection is None:
            return
        source_map = self.projection.source_map
        cursor = self.editor.textCursor()
        caret = source_map.source_to_view(caret_source)
        anchor = caret if anchor_source is None else source_map.source_to_view(anchor_source)
        cursor.setPosition(min(anchor, len(self.projection.text)))
        cursor.setPosition(min(caret, len(self.projection.text)), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

    def show_source_caret(self, cursor_source: int, anchor_source: int) -> None:
        """Follow the Source editor's caret (no echo back)."""

        if self.projection is None or self._applying:
            return
        self._syncing_caret = True
        try:
            self._place_caret(cursor_source, anchor_source)
            self.editor.ensureCursorVisible()
        finally:
            self._syncing_caret = False

    def _caret_moved(self) -> None:
        if self._syncing_caret or self.projection is None:
            return
        cursor = self.editor.textCursor()
        source_map = self.projection.source_map
        self.caretSourceChanged.emit(
            source_map.view_to_source(cursor.position()), source_map.view_to_source(cursor.anchor())
        )

    def _document_edited(self, _operation) -> None:
        if not self._applying:
            self._refresh_timer.start()

    # --- editing --------------------------------------------------------------

    def _selection(self) -> tuple[int, int]:
        cursor = self.editor.textCursor()
        return min(cursor.position(), cursor.anchor()), max(cursor.position(), cursor.anchor())

    def apply_plan(self, plan: EditPlan) -> None:
        assert self.document is not None
        if plan.replacements:
            self._applying = True
            try:
                self.document.replace_many(sorted(plan.replacements))
            finally:
                self._applying = False
        self.refresh(plan.caret_source, plan.caret_source)
        # Push the new caret to the Source editor first, then let the host
        # repaint it — never the other way round, or the Source editor's
        # pre-edit caret would be echoed back into this view.
        self._caret_moved()
        self._notify_applied()

    def _notify_applied(self) -> None:
        if self.document_applied is None:
            return
        self._applying = True
        try:
            self.document_applied()
        finally:
            self._applying = False

    def _replace_view_range(self, start: int, end: int, text: str) -> bool:
        if self.projection is None or self.document is None:
            return False
        try:
            plan = plan_view_edit(self.projection.source_map, start, end, text)
        except EditRejected as rejected:
            self.last_message = rejected.reason
            self.status.setText(rejected.reason)
            return False
        self.status.setText("")
        self.apply_plan(plan)
        return True

    def type_text(self, text: str) -> bool:
        start, end = self._selection()
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        if "\n" in text and self.provider is not None and self.projection is not None:
            # Pasted multi-line text: each line break becomes the provider's
            # paragraph break, so structure stays valid source.
            parts = text.split("\n")
            source_map = self.projection.source_map
            source = self.source_text()
            joined = parts[0]
            position = source_map.view_to_source(start)
            for part in parts[1:]:
                joined += self.provider.enter_text(source, position) + part
            text = joined
        return self._replace_view_range(start, end, text)

    def delete(self, *, backwards: bool) -> bool:
        start, end = self._selection()
        if start == end and self.projection is not None:
            if backwards:
                if start == 0:
                    return False
                start -= 1
            else:
                if end >= len(self.projection.text):
                    return False
                end += 1
        if self._replace_view_range(start, end, ""):
            return True
        # Stepping over protected syntax instead of deleting it.
        cursor = self.editor.textCursor()
        cursor.setPosition(start if backwards else end)
        self.editor.setTextCursor(cursor)
        return False

    def enter(self) -> bool:
        if self.provider is None or self.projection is None:
            return False
        start, end = self._selection()
        source = self.source_text()
        position = self.projection.source_map.view_to_source(start)
        return self._replace_view_range(start, end, self.provider.enter_text(source, position))

    def cut(self) -> None:
        if self.editor.textCursor().hasSelection():
            self.editor.copy()
            self.delete(backwards=True)

    def paste(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self.type_text(text)

    def undo(self) -> None:
        if self.document is not None and self.document.can_undo:
            self.document.undo()
            self.refresh()
            self._notify_applied()

    def redo(self) -> None:
        if self.document is not None and self.document.can_redo:
            self.document.redo()
            self.refresh()
            self._notify_applied()

    def run_view_command(self, command_id: str, argument: str | None = None) -> bool:
        command = next((c for c in self.commands if c.command_id == command_id), None)
        if command is None or self.projection is None or self.document is None:
            return False
        if argument is None and command.choices is not None:
            choices = list(command.choices())
            if not choices:
                return False
            argument, accepted = QInputDialog.getItem(self, command.label.rstrip("…"), "Marker:", choices, 0, False)
            if not accepted:
                return False
        elif argument is None and command.prompt is not None:
            argument, accepted = QInputDialog.getText(self, command.label.rstrip("…"), command.prompt)
            if not accepted:
                return False
        start, end = self._selection()
        source_start, source_end = self.projection.source_map.view_selection_to_source(start, end)
        try:
            plan = command.run(self.source_text(), source_start, source_end, argument)
        except EditRejected as rejected:
            self.last_message = rejected.reason
            self.status.setText(rejected.reason)
            return False
        except Exception as exc:  # an environment must never break the editor
            logger.exception("view command %r failed", command_id)
            self.last_message = str(exc)
            self.status.setText(f"{command.label} failed: {exc}")
            return False
        self.status.setText("")
        self.apply_plan(plan)
        return True
