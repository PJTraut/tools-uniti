"""Rich-view pane (ADR-0015, spec Phase E7; in place per ADR-0017).

Shows one document through an environment's `EditorViewProvider` (SFM
Standard/Preview, Markdown Rendered). The pane never edits its own text:
every keystroke is mapped through the projection's `SourceMap` to
`Document.replace_many` (one undo step) and the view is re-projected from
the canonical source. Caret/selection follow the source editor and vice
versa.

The pane sits *on top of* its tab's Source editor (`UNITITextView`), filling
it, so Plain Text / Standard / Preview are modes of one tab rather than a
second pane beside it (2026-10-07 field test). The tab still holds the
`UNITITextView`: every editor path in the window (Find/Replace, save,
recovery, splits, session capture) keeps working on it unchanged, and the
pane mirrors its caret.

Preview adds a notes frame below the text: one stacked section per note
class (footnotes, cross references, …) from `Projection.notes`.
"""

from __future__ import annotations

import bisect
import logging
import weakref
from collections.abc import Callable
from dataclasses import dataclass, field

from PySide6.QtCore import QEvent, QMimeData, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QFont,
    QKeySequence,
    QPalette,
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
    QSplitter,
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
from uniti.core.rich_views.source_map import SegmentRole
from uniti.ui.theme import EditorThemeTokens

logger = logging.getLogger("uniti.ui.rich_view")

_INCH_PX = 96.0
# The ordinary Source editor on its own, as the view switchers name it.
PLAIN_TEXT_LABEL = "Plain Text"


def _float(value: str | None, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except ValueError:
        return default


# Marker tags are one uniform size, smaller than body text, whatever block
# (heading, note) they sit in.
TAG_SCALE = 0.75
_MONOSPACE = ["Menlo", "Consolas", "DejaVu Sans Mono", "monospace"]


def _blend(first: QColor, second: QColor, amount: float) -> QColor:
    """`amount` of the way from `first` to `second`."""

    return QColor.fromRgbF(
        first.redF() + (second.redF() - first.redF()) * amount,
        first.greenF() + (second.greenF() - first.greenF()) * amount,
        first.blueF() + (second.blueF() - first.blueF()) * amount,
    )


def _luminance(color: QColor) -> float:
    def channel(value: float) -> float:
        return value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4

    return 0.2126 * channel(color.redF()) + 0.7152 * channel(color.greenF()) + 0.0722 * channel(color.blueF())


def contrast_ratio(first: QColor, second: QColor) -> float:
    lighter, darker = sorted((_luminance(first), _luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def readable(color: QColor, background: QColor, minimum: float = 3.0) -> QColor:
    """`color` with its lightness moved away from `background` until the
    two contrast by at least `minimum` (STY colours are chosen for print
    on white, e.g. dark green, and vanish on a dark theme)."""

    if contrast_ratio(color, background) >= minimum:
        return color
    hue, saturation, lightness, _alpha = color.getHslF()
    lighten = _luminance(background) < 0.5
    adjusted = QColor(color)
    for step in range(1, 21):
        value = lightness + (1 - lightness) * step / 20 if lighten else lightness * (1 - step / 20)
        adjusted = QColor.fromHslF(max(hue, 0.0), saturation, value)
        if contrast_ratio(adjusted, background) >= minimum:
            break
    return adjusted


@dataclass(frozen=True, slots=True)
class RichPalette:
    """The colours a rich view draws with, taken from its Source editor's
    theme so both panes always look like one editor."""

    base: QColor
    text: QColor
    muted: QColor
    tag_text: QColor
    tag_background: QColor
    selection: QColor
    selected_text: QColor
    # The synced verse in side-by-side reference sync.
    highlight: QColor = field(default_factory=QColor)
    # The spelling underlines (spellcheck plan S4).
    spelling_wrong: QColor = field(default_factory=lambda: QColor("#c4281b"))
    spelling_unknown: QColor = field(default_factory=lambda: QColor("#9a6700"))

    @classmethod
    def from_tokens(cls, tokens: EditorThemeTokens) -> "RichPalette":
        tag = QColor(tokens.syntax.get("keyword", tokens.text))
        return cls(
            base=QColor(tokens.base),
            text=QColor(tokens.text),
            muted=_blend(tokens.text, tokens.base, 0.45),
            tag_text=readable(tag, tokens.base, 4.5),
            tag_background=_blend(tokens.base, tag, 0.12),
            selection=QColor(tokens.selection),
            selected_text=QColor(tokens.selected_text),
            highlight=reference_highlight_color(tokens),
            spelling_wrong=QColor(tokens.spelling_wrong),
            spelling_unknown=QColor(tokens.spelling_unknown),
        )

    @classmethod
    def from_widget_palette(cls, palette: QPalette) -> "RichPalette":
        base = palette.color(QPalette.ColorRole.Base)
        text = palette.color(QPalette.ColorRole.Text)
        tag = QColor("#8ab4f8") if _luminance(base) < 0.5 else QColor("#1a56db")
        return cls(
            base=base,
            text=text,
            muted=_blend(text, base, 0.45),
            tag_text=tag,
            tag_background=_blend(base, tag, 0.12),
            selection=palette.color(QPalette.ColorRole.Highlight),
            selected_text=palette.color(QPalette.ColorRole.HighlightedText),
            highlight=_blend(base, palette.color(QPalette.ColorRole.Highlight), 0.25),
        )


def reference_highlight_color(tokens: EditorThemeTokens) -> QColor:
    """The tint of a synced verse: the theme's current-match colour, faint
    enough to read through (the same role Compare's cross-pane marker uses)."""

    return _blend(QColor(tokens.base), QColor(tokens.current_match), 0.35)


def char_format(attrs, base: QFont, palette: RichPalette) -> QTextCharFormat:
    fmt = QTextCharFormat()
    if attrs.get("marker_token") == "yes":
        # A tag looks the same everywhere: it resets anything a heading or
        # character style around it would otherwise lend it.
        fmt.setFontFamilies(_MONOSPACE)
        fmt.setFontWeight(QFont.Weight.Normal)
        fmt.setFontItalic(False)
        fmt.setFontUnderline(False)
        fmt.setFontCapitalization(QFont.Capitalization.MixedCase)
        fmt.setVerticalAlignment(QTextCharFormat.VerticalAlignment.AlignNormal)
        fmt.setForeground(QBrush(palette.tag_text))
        fmt.setBackground(QBrush(palette.tag_background))
        if base.pointSizeF() > 0:
            fmt.setFontPointSize(base.pointSizeF() * TAG_SCALE)
        return fmt
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
        fmt.setFontFamilies(_MONOSPACE)
    scale = _float(attrs.get("font_scale"), 1.0)
    if abs(scale - 1.0) > 0.01 and base.pointSizeF() > 0:
        fmt.setFontPointSize(base.pointSizeF() * scale)
    color = attrs.get("color")
    if color:
        fmt.setForeground(QBrush(readable(QColor(color), palette.base)))
    if attrs.get("muted") == "yes":
        fmt.setForeground(QBrush(palette.muted))
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


class Utf16Offsets:
    """Python string offsets <-> Qt text positions, which count UTF-16
    code units: every character outside the BMP is two Qt positions."""

    def __init__(self, text: str) -> None:
        astral = [index for index, char in enumerate(text) if ord(char) > 0xFFFF]
        self._astral = astral
        # Qt position just after each astral character.
        self._qt_ends = [index + order + 2 for order, index in enumerate(astral)]

    def to_qt(self, offset: int) -> int:
        return offset + bisect.bisect_left(self._astral, offset) if self._astral else offset

    def from_qt(self, position: int) -> int:
        return position - bisect.bisect_right(self._qt_ends, position) if self._astral else position


# Block attributes that also format the block's characters (headings' size
# and weight reach their text through the block).
_BLOCK_CHAR_KEYS = ("bold", "italic", "font_scale", "color", "muted", "smallcaps", "underline", "monospace")


def render_projection(document: QTextDocument, projection: Projection, base: QFont, palette: RichPalette) -> None:
    """Fill `document` with `projection`'s text and formats.

    The text goes in as runs, each inserted once with its final character
    format (field test R1, 2026-10-08). Inserting everything plain and then
    merging tens of thousands of span formats took ~20 s for a 220 KB book
    when the document was on screen, since every merge re-lays-out the
    text; callers render into a detached document and hand it over.

    Formats layer in this order: block character attributes, then spans
    (outer before inner), then marker tags, so a character style or note
    around a tag never recolours or resizes it.
    """

    document.clear()
    document.setDefaultFont(base)
    text = projection.text
    length = len(text)
    layers: list[tuple[int, int, object]] = []
    for block in projection.blocks:
        char_attrs = {key: value for key, value in block.attrs.items() if key in _BLOCK_CHAR_KEYS}
        start, end = max(0, block.view_start), min(length, block.view_end)
        if char_attrs and end > start:
            layers.append((start, end, char_attrs))
    for span in sorted(projection.spans, key=lambda span: span.attrs.get("marker_token") == "yes"):
        start, end = max(0, span.view_start), min(length, span.view_end)
        if end > start:
            layers.append((start, end, span.attrs))

    # Identical attribute maps share one id, so runs with the same stack of
    # formats share one QTextCharFormat.
    attr_ids: dict[tuple, int] = {}
    layer_attr: list[int] = []
    starts_at: dict[int, list[int]] = {}
    ends_at: dict[int, list[int]] = {}
    attr_maps: list[object] = []
    for index, (start, end, attrs) in enumerate(layers):
        key = tuple(sorted(attrs.items()))
        attr_id = attr_ids.get(key)
        if attr_id is None:
            attr_id = attr_ids[key] = len(attr_maps)
            attr_maps.append(attrs)
        layer_attr.append(attr_id)
        starts_at.setdefault(start, []).append(index)
        ends_at.setdefault(end, []).append(index)
    boundaries = sorted({0, length, *starts_at, *ends_at})
    active: set[int] = set()
    formats: dict[tuple[int, ...], QTextCharFormat] = {}
    cursor = QTextCursor(document)
    for position, following in zip(boundaries, boundaries[1:]):
        for index in ends_at.get(position, ()):
            active.discard(index)
        active.update(starts_at.get(position, ()))
        if following <= position:
            continue
        stack = tuple(layer_attr[index] for index in sorted(active))
        fmt = formats.get(stack)
        if fmt is None:
            fmt = QTextCharFormat()
            for attr_id in stack:
                fmt.merge(char_format(attr_maps[attr_id], base, palette))
            formats[stack] = fmt
        cursor.insertText(text[position:following], fmt)

    if projection.blocks:
        offsets = Utf16Offsets(text)
        for block in projection.blocks:
            start, end = max(0, block.view_start), min(length, block.view_end)
            cursor.setPosition(offsets.to_qt(start))
            cursor.setPosition(offsets.to_qt(max(start, end - 1 if end > start else end)), QTextCursor.MoveMode.KeepAnchor)
            cursor.mergeBlockFormat(block_format(block.attrs))


def render_into(editor: QTextEdit, projection: Projection, base: QFont, palette: RichPalette) -> None:
    """Render off screen, then give `editor` the finished document in one step."""

    previous = editor.document()
    document = QTextDocument(editor)
    document.setUndoRedoEnabled(False)
    document.setDocumentMargin(previous.documentMargin())
    document.setDefaultTextOption(previous.defaultTextOption())
    render_projection(document, projection, base, palette)
    # The editor deletes its previous document itself when it owned it.
    editor.setDocument(document)


def show_blocks_in(
    document: QTextDocument, offsets: Utf16Offsets, source_map, window: tuple[int, int] | None
) -> tuple[int, int] | None:
    """Hide the blocks whose start isn't in the source `window`, the USFM
    per-chapter view (None shows every block). Returns the Qt positions of
    the first and last caret positions shown; None when every block is
    shown, or when none is."""

    shown: tuple[int, int] | None = None
    changed = False
    block = document.begin()
    while block.isValid():
        visible = True
        if window is not None:
            source = source_map.view_to_source(offsets.from_qt(block.position()), prefer_left=False)
            visible = window[0] <= source < window[1]
        if block.isVisible() != visible:
            block.setVisible(visible)
            changed = True
        if visible and window is not None:
            end = block.position() + block.length() - 1
            shown = (block.position(), end) if shown is None else (shown[0], end)
        block = block.next()
    if changed:
        document.markContentsDirty(0, document.characterCount())
    return shown


class ProjectionCache:
    """The last projection per document and view, reused while the
    document's revision and the provider's stylesheets are unchanged — so
    switching Standard ↔ Preview ↔ Plain Text and back doesn't re-project
    (R1). Held weakly by document; a closed document drops out."""

    def __init__(self) -> None:
        self._entries: weakref.WeakKeyDictionary[Document, dict[str, tuple[int, tuple, Projection, object]]] = (
            weakref.WeakKeyDictionary()
        )

    @staticmethod
    def _token(provider: EditorViewProvider) -> tuple:
        cache_token = getattr(provider, "cache_token", None)
        return (provider, cache_token() if callable(cache_token) else None)

    def project(
        self,
        document: Document,
        provider: EditorViewProvider,
        source: Callable[[], str],
        variant: frozenset[str] | None = None,
        hyphenation: object | None = None,
    ) -> Projection:
        """`variant` (the hidden footnote categories, Preview) and
        `hyphenation` (a project's hyphenation rules, Preview) are part of
        the cache key: a filtered or hyphenated projection is kept beside
        the plain one. Rules are compared by identity, so a re-read list
        projects again."""

        token = self._token(provider)
        per_document = self._entries.setdefault(document, {})
        slot = provider.key if not variant else f"{provider.key}|{'|'.join(sorted(variant))}"
        if hyphenation is not None:
            slot += "|hyphen"
        cached = per_document.get(slot)
        if (
            cached is not None
            and cached[0] == document.revision
            and cached[1][0] is token[0]
            and cached[1][1] is token[1]
            and cached[3] is hyphenation
        ):
            return cached[2]
        if not variant and hyphenation is None:
            projection = provider.project(source())
        else:
            projection = provider.project_filtered(source(), variant or frozenset(), hyphenation)
        per_document[slot] = (document.revision, token, projection, hyphenation)
        return projection


PROJECTIONS = ProjectionCache()


class _RichEditor(QTextEdit):
    """QTextEdit whose every modification is rerouted to the owner."""

    def __init__(self, owner: "RichViewPane") -> None:
        super().__init__(owner)
        self._owner = owner
        self.setAcceptRichText(False)
        self.setUndoRedoEnabled(False)
        self.setTabChangesFocus(False)

    # Keys this editor handles itself, ahead of the window's and the Source
    # editor's shortcuts (the pane sits inside the Source editor, so its
    # navigation shortcuts would otherwise move the hidden source caret).
    _OWN_KEYS = tuple(
        getattr(QKeySequence.StandardKey, name)
        for name in (
            "Undo", "Redo", "Cut", "Copy", "Paste", "SelectAll", "ZoomIn", "ZoomOut",
            "MoveToPreviousPage", "MoveToNextPage", "MoveToStartOfDocument", "MoveToEndOfDocument",
            "MoveToPreviousWord", "MoveToNextWord", "SelectPreviousPage", "SelectNextPage",
            "SelectStartOfDocument", "SelectEndOfDocument", "SelectPreviousWord", "SelectNextWord",
        )
    )

    def event(self, event) -> bool:  # noqa: A003 - Qt override
        if event.type() == QEvent.Type.ShortcutOverride and any(event.matches(key) for key in self._OWN_KEYS):
            event.accept()
            return True
        if event.type() == QEvent.Type.ToolTip and self._owner.show_spelling_tooltip(event):
            return True
        return super().event(event)

    def focusInEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().focusInEvent(event)
        # The tab's Source editor never sees focus while this covers it;
        # tell the host so the pane tree still activates the right tab.
        self._owner.focused.emit()

    def wheelEvent(self, event) -> None:  # noqa: N802 - Qt override
        # Ctrl+wheel zooms the Source editor (and so this view with it)
        # rather than QTextEdit's own zoom, which only rescales text that
        # has no explicit size — headings and notes would stay put.
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta:
                self._owner.zoomRequested.emit(1 if delta > 0 else -1)
            event.accept()
            return
        super().wheelEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt override
        owner = self._owner
        if event.matches(QKeySequence.StandardKey.ZoomIn):
            owner.zoomRequested.emit(1)
            return
        if event.matches(QKeySequence.StandardKey.ZoomOut):
            owner.zoomRequested.emit(-1)
            return
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

    def createMimeDataFromSelection(self) -> QMimeData:  # noqa: N802
        """Copy the selection as text; Hyphenate Preview's soft hyphens are
        the view's, not the document's, so they never reach the clipboard
        (H-D5)."""

        data = super().createMimeDataFromSelection()
        if self._owner._hyphenation is not None:
            data = QMimeData()
            data.setText(self.textCursor().selection().toPlainText().replace("\u00ad", ""))
        return data

    def insertFromMimeData(self, source: QMimeData) -> None:  # noqa: N802
        if source.hasText():
            self._owner.type_text(source.text())

    def canInsertFromMimeData(self, source: QMimeData) -> bool:  # noqa: N802
        return source.hasText()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.context_menu().exec(event.globalPos())

    def context_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        editable = self._owner.editable
        menu.addAction("Cut", self._owner.cut).setEnabled(editable and self.textCursor().hasSelection())
        menu.addAction("Copy", self.copy).setEnabled(self.textCursor().hasSelection())
        menu.addAction("Paste", self._owner.paste).setEnabled(editable)
        if self._owner.commands:
            menu.addSeparator()
        for command in self._owner.commands:
            menu.addAction(command.label, lambda command_id=command.command_id: self._owner.run_view_command(command_id))
        hook = self._owner.context_menu_hook
        if hook is not None:
            hook(menu)  # the host's entries (Document Group)
        return menu


class _NoteSectionView(QWidget):
    """One note class (Footnotes, Cross References, …) of the notes frame."""

    def __init__(self, owner: "RichViewPane") -> None:
        super().__init__(owner)
        self._owner = owner
        self.section = None
        self.offsets = Utf16Offsets("")
        self.title = QLabel(self)
        self.title.setContentsMargins(6, 6, 6, 2)
        self.editor = QTextEdit(self)
        self.editor.setReadOnly(True)
        self.editor.setUndoRedoEnabled(False)
        self.editor.cursorPositionChanged.connect(self._clicked)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.title)
        layout.addWidget(self.editor, 1)

    def show_section(self, section, font: QFont, palette: "RichPalette") -> None:
        self.section = section
        self.title.setText(section.label)
        self.offsets = Utf16Offsets(section.projection.text)
        self.editor.setFont(font)
        self.editor.setPalette(self._owner.editor.palette())
        blocked = self.editor.blockSignals(True)
        try:
            render_into(self.editor, section.projection, font, palette)
        finally:
            self.editor.blockSignals(blocked)

    def show_window(self, window: tuple[int, int] | None) -> None:
        """Only the notes in the source `window` (the per-chapter view); the
        section is hidden when none is."""

        if self.section is None:
            return
        shown = show_blocks_in(self.editor.document(), self.offsets, self.section.projection.source_map, window)
        self.setVisible(window is None or shown is not None)

    def entry_starts(self) -> list[tuple[int, int]]:
        """(source offset of the entry's first text, view line start) per entry."""

        result: list[tuple[int, int]] = []
        line_start = 0
        seen_text = False
        text = self.section.projection.text
        for segment in self.section.projection.source_map.segments:
            if segment.role is SegmentRole.GENERATED and "\n" in text[segment.view_start : segment.view_end]:
                line_start = segment.view_end
                seen_text = False
            elif segment.role is SegmentRole.TEXT and not seen_text and segment.view_end > segment.view_start:
                result.append((segment.source_start, line_start))
                seen_text = True
        return result

    def highlight_entry(self, view_line_start: int | None) -> None:
        if view_line_start is None:
            self.editor.setExtraSelections([])
            return
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(self.offsets.to_qt(view_line_start))
        selection = QTextEdit.ExtraSelection()
        selection.cursor = cursor
        palette = self._owner._palette
        if palette is not None:
            selection.format.setBackground(QBrush(palette.tag_background))
        selection.format.setProperty(QTextCharFormat.Property.FullWidthSelection, True)
        self.editor.setExtraSelections([selection])
        view_cursor = QTextCursor(cursor)
        blocked = self.editor.blockSignals(True)
        try:
            self.editor.setTextCursor(view_cursor)
            self.editor.ensureCursorVisible()
        finally:
            self.editor.blockSignals(blocked)

    def _clicked(self) -> None:
        if self.section is None:
            return
        position = self.offsets.from_qt(self.editor.textCursor().position())
        source = self.section.projection.source_map.view_to_source(position, prefer_left=False)
        self._owner.note_activated(source)


class RichViewPane(QWidget):
    """One document shown through one provider, editable via the source map."""

    caretSourceChanged = Signal(int, int)  # cursor, anchor (source offsets)
    closeRequested = Signal()
    providerChangeRequested = Signal(str)
    zoomRequested = Signal(int)  # +1 zoom in, -1 zoom out
    focused = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        # The tab's Source editor this pane covers (set by the controller).
        self.target_view = None
        self.document: Document | None = None
        self.provider: EditorViewProvider | None = None
        self.projection: Projection | None = None
        self.commands: tuple[ViewCommand, ...] = ()
        self.last_message: str | None = None
        # Called after the pane changed the document (edit, undo, redo) so
        # the host can repaint the Source editors of the same document.
        self.document_applied: Callable[[], None] | None = None
        # Whether the document may be edited right now; the host returns
        # False while the Source editor is disabled (e.g. during a save).
        self.can_edit: Callable[[], bool] = lambda: True
        # False while the pane's window is frozen (not the active window):
        # edits made elsewhere then wait until the window is activated.
        self.is_live: Callable[[], bool] = lambda: True
        # Adds the host's entries to the right-click menu.
        self.context_menu_hook: Callable[[QMenu], None] | None = None
        self._providers: tuple[EditorViewProvider, ...] = ()
        self._remove_listener: Callable[[], None] | None = None
        self._applying = False
        self._syncing_caret = False
        self._palette: RichPalette | None = None
        self._highlight: tuple[int, int] | None = None
        # Check Spelling (spellcheck plan S4): the document's `SpellingCache`,
        # its book-wide spans (remembered per revision) and the spans now
        # underlined, as (view start, view end, span).
        # Preview: the footnote categories left out (filter, plan 2026-10-14).
        self._hidden_categories: frozenset[str] = frozenset()
        self._hyphenation = None  # a project's `HyphenationRules` while Hyphenate Preview is on
        self._spelling = None
        self._spelling_book: tuple[tuple, object] | None = None
        self._spelling_shown: list[tuple[int, int, object]] = []
        self._spelling_timer = QTimer(self)
        self._spelling_timer.setSingleShot(True)
        self._spelling_timer.setInterval(0)
        self._spelling_timer.timeout.connect(self._apply_highlights)
        # The per-chapter view: the source window shown (the target view's
        # chapter) and the Qt positions the caret may take within it.
        self._window: tuple[int, int] | None = None
        self._window_positions: tuple[int, int] | None = None
        self._offsets = Utf16Offsets("")
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(0)
        self._refresh_timer.timeout.connect(self.refresh)

        # Opaque: the pane covers its tab's Source editor, which must not
        # show through the header row.
        self.setAutoFillBackground(True)
        # Re-project when next shown: edits to a document whose tab is
        # hidden don't pay for a projection nobody sees.
        self._stale = False
        self.note_sections: list[_NoteSectionView] = []

        self.mode = QComboBox(self)
        self.mode.setAccessibleName("Rich view mode")
        self.mode.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        self.mode.activated.connect(self._mode_activated)
        self.status = QLabel(self)
        self.command_bar = QHBoxLayout()
        self.command_bar.setContentsMargins(0, 0, 0, 0)
        header = QHBoxLayout()
        header.setContentsMargins(4, 2, 4, 2)
        header.addWidget(self.mode)
        header.addLayout(self.command_bar)
        header.addStretch(1)
        header.addWidget(self.status)
        self.editor = _RichEditor(self)
        self.editor.cursorPositionChanged.connect(self._caret_moved)
        self.editor.selectionChanged.connect(self._caret_moved)
        self.editor.verticalScrollBar().valueChanged.connect(lambda _value: self._schedule_spelling())
        # The text, then one stacked section per note class (Preview only).
        self.body = QSplitter(Qt.Orientation.Vertical, self)
        self.body.setChildrenCollapsible(False)
        self.body.addWidget(self.editor)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addLayout(header)
        layout.addWidget(self.body, 1)

    # --- binding ------------------------------------------------------------

    @property
    def editable(self) -> bool:
        if self.document is not None and getattr(self.document, "read_only", False):
            return False  # a file in a read-only folder (round 3 T7)
        if self.document is not None and getattr(self.document, "locked", False):
            return False  # a locked USFM book (book-lock plan L2)
        return self.provider is not None and getattr(self.provider, "editable", True)

    def bind(
        self,
        document: Document,
        providers: tuple[EditorViewProvider, ...],
        key: str,
        font: QFont,
        palette: RichPalette | None = None,
    ) -> None:
        if self._remove_listener is not None and self.document is not document:
            self._remove_listener()
            self._remove_listener = None
        if self.document is not document:
            self._remove_listener = document.add_edit_listener(self._document_edited)
        self.document = document
        self._providers = providers
        self._apply_appearance(font, palette)
        self.provider = next((p for p in providers if p.key == key), providers[0])
        self.commands = self.provider.view_commands()
        self.mode.blockSignals(True)
        self.mode.clear()
        self.mode.addItem(PLAIN_TEXT_LABEL, None)
        for provider in providers:
            self.mode.addItem(provider.label, provider.key)
        self.mode.setCurrentIndex(self.mode.findData(self.provider.key))
        self.mode.blockSignals(False)
        # Size to the longest label now that the items exist.
        self.mode.setMinimumWidth(self.mode.sizeHint().width())
        self._rebuild_command_bar()
        self.refresh()

    def _apply_appearance(self, font: QFont, palette: RichPalette | None) -> None:
        if palette is None:
            palette = RichPalette.from_widget_palette(self.editor.palette())
        self._palette = palette
        self.editor.setFont(font)
        widget_palette = self.editor.palette()
        widget_palette.setColor(QPalette.ColorRole.Base, palette.base)
        widget_palette.setColor(QPalette.ColorRole.Text, palette.text)
        widget_palette.setColor(QPalette.ColorRole.Highlight, palette.selection)
        widget_palette.setColor(QPalette.ColorRole.HighlightedText, palette.selected_text)
        self.editor.setPalette(widget_palette)
        pane_palette = self.palette()
        pane_palette.setColor(QPalette.ColorRole.Window, palette.base)
        pane_palette.setColor(QPalette.ColorRole.WindowText, palette.text)
        self.setPalette(pane_palette)

    def set_appearance(self, font: QFont, palette: RichPalette | None) -> None:
        """Follow the Source editor's zoomed font and theme."""

        if font == self.editor.font() and palette == self._palette:
            return
        self._apply_appearance(font, palette)
        self.refresh()

    def unbind(self) -> None:
        if self._remove_listener is not None:
            self._remove_listener()
            self._remove_listener = None
        self.document = None

    def _rebuild_command_bar(self) -> None:
        while self.command_bar.count():
            widget = self.command_bar.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)  # gone now, not at the next idle
                widget.deleteLater()
        if not getattr(self.provider, "command_buttons", True):
            return  # the provider's commands are on the right-click menu only
        for command in self.commands:
            button = QToolButton(self)
            button.setText(command.label)
            if command.shortcut:
                button.setToolTip(f"{command.label} ({QKeySequence(command.shortcut).toString(QKeySequence.SequenceFormat.NativeText)})")
            button.clicked.connect(lambda _checked=False, command_id=command.command_id: self.run_view_command(command_id))
            button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            self.command_bar.addWidget(button)

    def set_mode_selector_visible(self, visible: bool) -> None:
        """Hide the pane's own mode selector where the window already has
        one (an environment window's toolbar)."""

        self.mode.setVisible(visible)

    def _mode_activated(self, index: int) -> None:
        key = self.mode.itemData(index)
        if isinstance(key, str):
            self.providerChangeRequested.emit(key)
        elif key is None:
            self.closeRequested.emit()

    # --- projection ---------------------------------------------------------

    def source_text(self) -> str:
        assert self.document is not None
        return self.document.read(0, self.document.total_chars())

    def showEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().showEvent(event)
        if self._stale:
            self.refresh()

    def refresh(self, caret_source: int | None = None, anchor_source: int | None = None) -> None:
        if self.document is None or self.provider is None:
            return
        window = self.window()
        if window is not self and not self.isVisibleTo(window):
            # A background tab: catch up when it is shown.
            self._stale = True
            return
        self._stale = False
        if not ResourceProfile(size_bytes=self.document.source.size).allow_full_parse:
            self.projection = None
            self.editor.setPlainText("This document is too large for a rich view (above 1 MiB). Use the Source editor.")
            self.editor.setReadOnly(True)
            return
        self.editor.setReadOnly(not self.editable)
        if caret_source is None and self.projection is not None:
            cursor = self.editor.textCursor()
            caret_source = self.projection.source_map.view_to_source(self._offsets.from_qt(cursor.position()))
            anchor_source = self.projection.source_map.view_to_source(self._offsets.from_qt(cursor.anchor()))
        try:
            variant = hasattr(self.provider, "project_filtered")
            projection = PROJECTIONS.project(
                self.document,
                self.provider,
                self.source_text,
                self._hidden_categories if variant and self._hidden_categories else None,
                self._hyphenation if variant else None,
            )
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
            self._offsets = Utf16Offsets(projection.text)
            assert self._palette is not None
            render_into(self.editor, projection, self.editor.font(), self._palette)
            self._render_notes(projection)
            self.apply_window(force=True)
            self._apply_highlights()
            self._place_caret(caret_source or 0, anchor_source)
        finally:
            self._syncing_caret = False
        self.editor.verticalScrollBar().setValue(scroll)
        self._sync_note_highlight()
        self._schedule_spelling()

    # --- the USFM per-chapter view -----------------------------------------------

    def apply_window(self, *, force: bool = False) -> None:
        """Show only the target view's chapter (its `source_window`), or
        every block when it has none."""

        if self.projection is None:
            return
        view = self.target_view
        window = view.source_window() if view is not None and hasattr(view, "source_window") else None
        if window == self._window and not force:
            return
        self._window = window
        source_map = self.projection.source_map
        self._window_positions = show_blocks_in(self.editor.document(), self._offsets, source_map, window)
        if window is not None and self._window_positions is None:
            show_blocks_in(self.editor.document(), self._offsets, source_map, None)  # nothing in it: show all
        for section in self.note_sections:
            section.show_window(window)

    def _keep_caret_in_window(self) -> bool:
        """Put a caret the user moved outside the shown chapter back (QTextEdit
        walks into hidden blocks); True when it was moved."""

        if self._window_positions is None:
            return False
        low, high = self._window_positions
        cursor = self.editor.textCursor()
        position, anchor = cursor.position(), cursor.anchor()
        kept_position, kept_anchor = min(max(position, low), high), min(max(anchor, low), high)
        if (kept_position, kept_anchor) == (position, anchor):
            return False
        cursor.setPosition(kept_anchor)
        cursor.setPosition(kept_position, QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)
        return True

    # --- notes frame (Preview) -------------------------------------------------

    def _render_notes(self, projection: Projection) -> None:
        """One stacked section per note class, below the text."""

        sections = tuple(getattr(projection, "notes", ()) or ())
        while len(self.note_sections) > len(sections):
            widget = self.note_sections.pop()
            widget.setParent(None)
            widget.deleteLater()
        added = len(self.note_sections) < len(sections)
        while len(self.note_sections) < len(sections):
            widget = _NoteSectionView(self)
            self.body.addWidget(widget)
            self.note_sections.append(widget)
            self.body.setStretchFactor(self.body.indexOf(widget), 0)
        self.body.setStretchFactor(0, 3)
        if added:
            # The text keeps most of the height; the user can drag it.
            total = max(self.body.height(), 400)
            notes = int(total * 0.3)
            self.body.setSizes([total - notes] + [notes // len(sections)] * len(sections))
        assert self._palette is not None
        for widget, section in zip(self.note_sections, sections):
            widget.show_section(section, self.editor.font(), self._palette)

    def note_activated(self, source: int) -> None:
        """A click in the notes frame: move the caret to that note."""

        if self._syncing_caret or self.projection is None:
            return
        self.caretSourceChanged.emit(source, source)

    def _caller_source_at_caret(self) -> int | None:
        """The source position of the note caller the caret is on, if any."""

        if self.projection is None or not self.note_sections:
            return None
        source_map = self.projection.source_map
        position = self._offsets.from_qt(self.editor.textCursor().position())
        text = self.projection.text
        for probe in (position, position - 1):
            segment = source_map.segment_at_view(probe) if probe >= 0 else None
            if (
                segment is not None
                and segment.role is SegmentRole.GENERATED
                and text[segment.view_start : segment.view_end].strip()
            ):
                return segment.source_start
        return None

    def _sync_note_highlight(self) -> None:
        """Highlight the note whose caller the caret is on."""

        if not self.note_sections:
            return
        caller = self._caller_source_at_caret()
        best: tuple[int, _NoteSectionView, int] | None = None
        if caller is not None:
            for widget in self.note_sections:
                for source, line_start in widget.entry_starts():
                    if source >= caller and (best is None or source < best[0]):
                        best = (source, widget, line_start)
                        break
        for widget in self.note_sections:
            widget.highlight_entry(best[2] if best is not None and best[1] is widget else None)

    # --- reference highlight (side-by-side sync) ---------------------------------

    def set_highlight(self, source_range: tuple[int, int] | None) -> None:
        """Tint the view text of a source range (the synced verse), or clear."""

        self._highlight = source_range
        self._apply_highlights()

    def _apply_highlights(self) -> None:
        """The editor's extra selections: the synced verse, and the visible
        flagged words (a few hundred at most)."""

        selections: list[QTextEdit.ExtraSelection] = []
        self._spelling_shown = []
        if self.projection is not None:
            if self._highlight is not None:
                source_map = self.projection.source_map
                start = source_map.source_to_view(self._highlight[0])
                end = source_map.source_to_view(self._highlight[1])
                if end > start:
                    cursor = QTextCursor(self.editor.document())
                    cursor.setPosition(self._offsets.to_qt(start))
                    cursor.setPosition(self._offsets.to_qt(end), QTextCursor.MoveMode.KeepAnchor)
                    selection = QTextEdit.ExtraSelection()
                    selection.cursor = cursor
                    if self._palette is not None:
                        selection.format.setBackground(QBrush(self._palette.highlight))
                    selections.append(selection)
            selections.extend(self._spelling_selections())
        self.editor.setExtraSelections(selections)

    def set_hidden_categories(self, hidden: frozenset[str], *, refresh: bool = True) -> None:
        """Leave the notes of these categories out of Preview (a provider
        without `project_filtered` ignores it); re-renders when it changed."""

        hidden = frozenset(hidden)
        if hidden == self._hidden_categories:
            return
        self._hidden_categories = hidden
        if refresh and hasattr(self.provider, "project_filtered"):
            self.refresh()

    def set_hyphenation(self, rules, *, refresh: bool = True) -> None:
        """Hyphenate Preview's paragraphs with these `HyphenationRules`
        (None: don't); a provider without `project_filtered` ignores it.
        Re-renders when it changed."""

        if rules is self._hyphenation:
            return
        self._hyphenation = rules
        if refresh and hasattr(self.provider, "project_filtered"):
            self.refresh()

    # --- spelling (spellcheck plan S4) ---------------------------------------------

    def set_spelling(self, cache) -> None:
        """Underline flagged words, from the document's `SpellingCache`; None
        turns it off. Spelling isn't part of the render: nothing re-renders."""

        self._spelling = cache
        self._spelling_book = None
        self._apply_highlights()

    def _schedule_spelling(self) -> None:
        if self._spelling is not None and not self._spelling_timer.isActive():
            self._spelling_timer.start()

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt override
        super().resizeEvent(event)
        self._schedule_spelling()

    def _book_spans(self):
        cache = self._spelling
        key = (self.document.revision, cache.generation)
        if self._spelling_book is None or self._spelling_book[0] != key:
            self._spelling_book = (key, cache.book_spans())
        return self._spelling_book[1]

    def _visible_source_range(self) -> tuple[int, int] | None:
        """The source range of the text on screen, a screen's margin each way."""

        if self.projection is None:
            return None
        height = self.editor.viewport().height()
        source_map = self.projection.source_map
        ends = []
        for y in (-height, 2 * height):
            position = self.editor.cursorForPosition(QPoint(0, y)).position()
            ends.append(source_map.view_to_source(self._offsets.from_qt(position)))
        start, end = min(ends), max(ends)
        if self._window is not None:
            start, end = max(start, self._window[0]), min(end, self._window[1])
        return (start, end) if end > start else None

    def _spelling_selections(self) -> list[QTextEdit.ExtraSelection]:
        """Wavy underlines under the flagged words now on screen. Only a
        live window works; a frozen one catches up when it is activated."""

        if self._spelling is None or self.projection is None or self.document is None or not self.is_live():
            return []
        if self._stale or self._palette is None:
            return []
        from uniti.core.environments.sfm.spelling import SpellingState

        visible = self._visible_source_range()
        if visible is None:
            return []
        source_map = self.projection.source_map
        length = len(self.projection.text)
        selections = []
        for span in self._book_spans().overlapping(*visible):
            start = source_map.source_to_view(span.start)
            end = source_map.source_to_view(span.end)
            if end <= start or end > length:
                continue  # hidden here (a note's text lives in the notes frame)
            cursor = QTextCursor(self.editor.document())
            cursor.setPosition(self._offsets.to_qt(start))
            cursor.setPosition(self._offsets.to_qt(end), QTextCursor.MoveMode.KeepAnchor)
            selection = QTextEdit.ExtraSelection()
            selection.cursor = cursor
            unknown = span.spelling.state is SpellingState.UNKNOWN
            selection.format.setUnderlineStyle(QTextCharFormat.UnderlineStyle.SpellCheckUnderline)
            selection.format.setUnderlineColor(self._palette.spelling_unknown if unknown else self._palette.spelling_wrong)
            selections.append(selection)
            self._spelling_shown.append((start, end, span))
        return selections

    def show_spelling_tooltip(self, event) -> bool:
        """The hover text of the flagged word under the pointer (plan D6)."""

        if self._spelling is None or not self._spelling_shown:
            return False
        from PySide6.QtWidgets import QToolTip

        from uniti.core.environments.sfm.spellcheck import describe

        position = self._offsets.from_qt(self.editor.cursorForPosition(event.pos()).position())
        for start, end, span in self._spelling_shown:
            if start <= position < end:
                QToolTip.showText(event.globalPos(), describe(span.spelling, self._spelling.context.project_name), self.editor)
                return True
        return False

    def scroll_to_source(self, source: int) -> None:
        """Bring a source offset into view without moving the caret."""

        if self.projection is None:
            return
        cursor = QTextCursor(self.editor.document())
        cursor.setPosition(self._offsets.to_qt(self.projection.source_map.source_to_view(source)))
        rect = self.editor.cursorRect(cursor)
        bar = self.editor.verticalScrollBar()
        bar.setValue(bar.value() + rect.top() - self.editor.viewport().height() // 3)

    def _place_caret(self, caret_source: int, anchor_source: int | None) -> None:
        if self.projection is None:
            return
        source_map = self.projection.source_map
        cursor = self.editor.textCursor()
        caret = source_map.source_to_view(caret_source)
        anchor = caret if anchor_source is None else source_map.source_to_view(anchor_source)
        length = len(self.projection.text)
        cursor.setPosition(self._offsets.to_qt(min(anchor, length)))
        cursor.setPosition(self._offsets.to_qt(min(caret, length)), QTextCursor.MoveMode.KeepAnchor)
        self.editor.setTextCursor(cursor)

    def show_source_caret(self, cursor_source: int, anchor_source: int) -> None:
        """Follow the Source editor's caret (no echo back)."""

        if self.projection is None or self._applying:
            return
        self._syncing_caret = True
        try:
            self.apply_window()  # a move from elsewhere may show another chapter
            self._place_caret(cursor_source, anchor_source)
            self.editor.ensureCursorVisible()
        finally:
            self._syncing_caret = False

    def _caret_moved(self, *, keep_in_window: bool = True) -> None:
        if self.projection is None:
            return
        self._sync_note_highlight()
        if self._syncing_caret:
            return
        if keep_in_window and self._keep_caret_in_window():
            return  # moved back; that move reported it
        cursor = self.editor.textCursor()
        source_map = self.projection.source_map
        self.caretSourceChanged.emit(
            source_map.view_to_source(self._offsets.from_qt(cursor.position())),
            source_map.view_to_source(self._offsets.from_qt(cursor.anchor())),
        )
        # The source caret is now here; an edit that added or removed a
        # `\c` may have put it in another chapter.
        self.apply_window()

    def _document_edited(self, _operation) -> None:
        if self._applying:
            return
        if not self.is_live():
            # A frozen window: re-render when it's activated (`catch_up`).
            self._stale = True
            return
        self._refresh_timer.start()

    @property
    def stale(self) -> bool:
        """Whether the shown text is behind the document's."""

        return self._stale

    # --- editing --------------------------------------------------------------

    def _selection(self) -> tuple[int, int]:
        cursor = self.editor.textCursor()
        position = self._offsets.from_qt(cursor.position())
        anchor = self._offsets.from_qt(cursor.anchor())
        return min(position, anchor), max(position, anchor)

    def _edit_blocked(self) -> bool:
        if not self.editable:
            self.last_message = f"{self.provider.label} is read-only. Edit in Standard or the Source editor."
        elif not self.can_edit():
            self.last_message = "The document cannot be edited right now."
        else:
            return False
        self.status.setText(self.last_message)
        return True

    def _with_document_line_breaks(self, plan: EditPlan) -> EditPlan:
        """Inserted line breaks follow the document's own (CRLF stays CRLF)."""

        if self.document is None or not any("\n" in text for _s, _e, text in plan.replacements):
            return plan
        head = self.document.read(0, min(self.document.total_chars(), 65_536))
        if "\r\n" not in head:
            return plan
        caret = plan.caret_source
        replacements = []
        for start, end, text in plan.replacements:
            converted = text.replace("\r\n", "\n").replace("\n", "\r\n")
            if caret == start + len(text):
                caret = start + len(converted)
            replacements.append((start, end, converted))
        return EditPlan(tuple(replacements), caret)

    def apply_plan(self, plan: EditPlan) -> None:
        assert self.document is not None
        if self._edit_blocked():
            return
        plan = self._with_document_line_breaks(plan)
        if plan.replacements:
            self._applying = True
            try:
                self.document.replace_many(sorted(plan.replacements))
            finally:
                self._applying = False
        self.refresh(plan.caret_source, plan.caret_source)
        # Push the new caret to the Source editor first, then let the host
        # repaint it — never the other way round, or the Source editor's
        # pre-edit caret would be echoed back into this view. An edit's
        # caret isn't a move: it isn't held in the chapter shown before.
        self._caret_moved(keep_in_window=False)
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
            # The shown chapter's edges, like the document's: never joined
            # to the hidden chapter beside them.
            shown = self._window_positions
            if backwards:
                if start == 0 or (shown is not None and self._offsets.to_qt(start) <= shown[0]):
                    return False
                start -= 1
            else:
                if end >= len(self.projection.text) or (shown is not None and self._offsets.to_qt(end) >= shown[1]):
                    return False
                end += 1
        if self._replace_view_range(start, end, ""):
            return True
        # Stepping over protected syntax instead of deleting it.
        cursor = self.editor.textCursor()
        cursor.setPosition(self._offsets.to_qt(start if backwards else end))
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
        if self.document is not None and self.document.can_undo and not self._edit_blocked():
            self.document.undo()
            self.refresh()
            self._notify_applied()

    def redo(self) -> None:
        if self.document is not None and self.document.can_redo and not self._edit_blocked():
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
