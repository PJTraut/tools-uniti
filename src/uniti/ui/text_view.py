"""Virtualized PySide6 text viewport backed by UNITI's Document engine."""

from __future__ import annotations

from dataclasses import dataclass
from collections import Counter, OrderedDict
import time
import math
import uuid
import weakref

from PySide6.QtCore import QPointF, QRectF, Qt, Signal, QTimer
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QFontMetricsF,
    QGuiApplication,
    QInputMethodEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QTextCharFormat,
    QTextLayout,
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea, QApplication

from uniti.app.editor_state import EditorState, EditorStateSnapshot
from uniti.app.session import DockReturnRecord, ViewRecord
from uniti.regex.match_store import MatchStore
from uniti.regex.results import MatchIndex
from uniti.ui.theme import EditorThemeTokens, active_theme
from uniti.ui.font_policy import resolve_editor_font
from uniti.ui.text_layout import ShapedWindow, Utf16Map
from uniti.ui.horizontal_layout import HorizontalLayouts
from uniti.ui.shaped_wrap import ShapedRowProvider
from uniti.ui.whitespace import (
    WhitespaceKind,
    WhitespaceMode,
    iter_character_markers,
    parse_whitespace_mode,
    shows_eol,
    marker_detail,
    character_detail,
)
from uniti.ui.whitespace_painter import paint_compact_marker
from uniti.ui.unicode_inspection import unicode_inspection
from uniti.ui.wrap_index import WrappedRowIndex


MAX_WHITESPACE_MARKERS_PER_FRAME = 4096


@dataclass(slots=True)
class _MarkerBudget:
    remaining: int = MAX_WHITESPACE_MARKERS_PER_FRAME
    overflow: int = 0
    last_position: tuple[float, float, int] | None = None


def _consume_marker(budget: _MarkerBudget) -> bool:
    if budget.remaining > 1:
        budget.remaining -= 1
        return True
    budget.overflow += 1
    return False


def _zero_width_visible(
    position: int,
    row_start: int,
    row_end: int,
    *,
    owns_end: bool,
) -> bool:
    return row_start <= position < row_end or (owns_end and position == row_end)


class UNITITextView(QAbstractScrollArea):
    """Paint only visible logical text; the UNITI Document remains authoritative."""

    stateChanged = Signal()
    cursorPositionChanged = Signal(int, int)
    zoomChanged = Signal(int)
    wrapChanged = Signal(bool)
    navigationRequested = Signal(str, bool)
    viewFocused = Signal(str)
    _documentRevisionChanged = Signal()

    def __init__(
        self,
        state: EditorState,
        parent=None,
        *,
        view_id: str | None = None,
    ) -> None:
        super().__init__(parent)
        if not isinstance(state, EditorState):
            raise TypeError("state must be an EditorState")
        if view_id is not None and (not isinstance(view_id, str) or not view_id):
            raise ValueError("view ID must be a nonempty string")
        self.state = state
        self.view_id = uuid.uuid4().hex if view_id is None else view_id
        self._disposed = False
        self._document_refresh_queued = False
        self._font_resolution = resolve_editor_font()
        self._base_font = QFont(self._font_resolution.font)
        self._base_point_size = self._base_font.pointSizeF()
        if self._base_point_size <= 0:
            self._base_point_size = 12.0
            self._base_font.setPointSizeF(self._base_point_size)
        self._zoom_percent = 100
        self._soft_wrap = False
        self._wrap_index: WrappedRowIndex | None = None
        self._wrap_signature: tuple[int, int, int] | None = None
        self.setFont(self._base_font)
        self._metrics = QFontMetrics(self.font())
        self._row_ascent, self._line_height = self._font_envelope()
        self._gutter_font = QFont(self.font())
        self._gutter_font.setPointSizeF(self.font().pointSizeF() * 0.8)
        self._gutter_metrics = QFontMetrics(self._gutter_font)
        self._gutter_width = 48
        self._max_visible_chars = 8192
        self._cell_width = max(
            1, math.ceil(QFontMetricsF(self.font()).horizontalAdvance("M"))
        )
        self._max_seen_line_width = 0
        self._drag_selecting = False
        self._click_count = 0
        self._last_click_at = 0.0
        self._last_click_position = (0.0, 0.0)
        self._preedit_text = ""
        self._preedit_cursor = 0
        self._preedit_formats = ()
        self._preedit_cursor_visible = True
        self._shape_cache = OrderedDict()
        self._horizontal_layouts = None
        self._horizontal_signature = None
        self.geometry_pending = False
        self._match_index = MatchIndex(())
        self._progressive_navigation = False
        self._dock_return: DockReturnRecord | None = None
        self._whitespace_mode = WhitespaceMode.OFF
        self._inspection_labels: dict[str, None] = {}
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            raise RuntimeError("UNITITextView requires an existing QApplication")
        self._inspection = unicode_inspection(app)
        self._inspection.changed.connect(self.viewport().update)
        self._theme_tokens = active_theme(app).editor
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setMouseTracking(True)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.horizontalScrollBar().valueChanged.connect(self.viewport().update)
        self._documentRevisionChanged.connect(
            self.refresh_document_revision,
            Qt.ConnectionType.QueuedConnection,
        )
        self._remove_document_listener = None
        self._bind_document_listener()
        self._refresh_scrollbars(advance_index=False)

    def _bind_document_listener(self) -> None:
        view_ref = weakref.ref(self)

        def document_changed(_event) -> None:
            view = view_ref()
            if view is not None:
                view._queue_document_revision_refresh()

        self._remove_document_listener = self.document.add_history_listener(
            document_changed
        )

    def replace_state(self, state: EditorState) -> None:
        """Rebind this view to a replacement authoritative document."""

        if self._disposed:
            raise RuntimeError("cannot replace state on a disposed view")
        if not isinstance(state, EditorState):
            raise TypeError("state must be an EditorState")
        remove = self._remove_document_listener
        self._remove_document_listener = None
        if remove is not None:
            remove()
        self.state = state
        self._document_refresh_queued = False
        self._bind_document_listener()

    @property
    def zoom_percent(self) -> int:
        return self._zoom_percent

    @property
    def soft_wrap(self) -> bool:
        return self._soft_wrap

    @property
    def whitespace_mode(self) -> WhitespaceMode:
        return self._whitespace_mode

    @property
    def whitespace_details_visible(self) -> bool:
        return self._inspection.active and self._whitespace_mode != WhitespaceMode.OFF

    @property
    def selected_character_detail(self) -> str | None:
        if self._disposed or not self._inspection.active or not self.hasFocus():
            return None
        selection = self.state.selection
        if selection is None or selection[1] - selection[0] != 1:
            return None
        return character_detail(self.document.read(*selection))

    @property
    def inspection_entries(self) -> tuple[str, ...]:
        if not self.whitespace_details_visible:
            return ()
        return tuple(marker_detail(label) for label in self._inspection_labels)

    @property
    def theme_tokens(self) -> EditorThemeTokens:
        return self._theme_tokens

    def set_whitespace_mode(self, mode: WhitespaceMode | str) -> None:
        selected = parse_whitespace_mode(mode)
        if selected == self._whitespace_mode:
            return
        self._whitespace_mode = selected
        self.viewport().update()

    def set_theme_tokens(self, tokens: EditorThemeTokens) -> None:
        if not isinstance(tokens, EditorThemeTokens):
            raise TypeError("theme tokens must be EditorThemeTokens")
        if tokens == self._theme_tokens:
            return
        self._theme_tokens = tokens
        self.viewport().update()

    @property
    def dock_return(self) -> DockReturnRecord | None:
        return self._dock_return

    def set_dock_return(self, record: DockReturnRecord | None) -> None:
        if record is not None and not isinstance(record, DockReturnRecord):
            raise TypeError("dock return must be a DockReturnRecord or None")
        self._dock_return = record

    def _wrap_width(self) -> int:
        return max(1, self.viewport().width() - self._gutter_width - 8)

    def _wrap_columns(self) -> int:
        width = self._wrap_width()
        return max(1, int(width // QFontMetricsF(self.font()).horizontalAdvance("M")))

    def _wrapped_row_index(self) -> WrappedRowIndex:
        columns = self._wrap_columns()
        signature = (
            id(self.document),
            self.document.revision,
            columns,
            self._wrap_width(),
            self.font().key(),
        )
        if self._wrap_index is None or signature != self._wrap_signature:
            width = self._wrap_width()
            provider = ShapedRowProvider(
                self.document, self.font(), width, self._cell_width * 4
            )
            self._wrap_index = WrappedRowIndex(
                self.document, columns, row_provider=provider
            )
            self._wrap_signature = signature
        return self._wrap_index

    def set_soft_wrap(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled == self._soft_wrap:
            return
        self._soft_wrap = enabled
        self._wrap_index = None
        self._wrap_signature = None
        self.horizontalScrollBar().setValue(0)
        self.verticalScrollBar().setValue(0)
        self._refresh_scrollbars(advance_index=False)
        self.wrapChanged.emit(enabled)
        self.viewport().update()

    def _font_envelope(self):
        ascent = self._metrics.ascent()
        descent = self._metrics.descent()
        # Full family metrics include marks outside primary Latin ascent.
        for family in self.font().families():
            font = QFont(self.font())
            font.setFamily(family)
            metrics = QFontMetrics(font)
            ascent, descent = (
                max(ascent, metrics.ascent()),
                max(descent, metrics.descent()),
            )
        sample = ShapedWindow(
            "क्षि ক্কি ક્કિ ਕਿ ಕ್ಕಿ ക്കി କ୍କି க்கி క్కి 中文 한국어 👩‍💻", self.font()
        )
        for line in sample.lines:
            ascent, descent = (
                max(ascent, math.ceil(line.ascent())),
                max(descent, math.ceil(line.descent())),
            )
        return ascent, max(1, ascent + descent)

    def _rebuild_metrics(self) -> None:
        self._metrics = QFontMetrics(self.font())
        self._row_ascent, self._line_height = self._font_envelope()
        self._gutter_font = QFont(self.font())
        self._gutter_font.setPointSizeF(self.font().pointSizeF() * 0.8)
        self._gutter_metrics = QFontMetrics(self._gutter_font)
        self._cell_width = max(
            1, math.ceil(QFontMetricsF(self.font()).horizontalAdvance("M"))
        )
        self._max_seen_line_width = 0
        self._wrap_index = None
        self._wrap_signature = None
        self._refresh_scrollbars(advance_index=False)
        self.viewport().update()

    def set_zoom_percent(self, percent: int) -> None:
        percent = max(50, min(300, int(percent)))
        if percent == self._zoom_percent:
            return
        self._zoom_percent = percent
        font = QFont(self._base_font)
        font.setPointSizeF(self._base_point_size * percent / 100.0)
        self.setFont(font)
        self._rebuild_metrics()
        self.zoomChanged.emit(percent)

    def zoom_in(self) -> None:
        self.set_zoom_percent(self._zoom_percent + 10)

    def zoom_out(self) -> None:
        self.set_zoom_percent(self._zoom_percent - 10)

    def reset_zoom(self) -> None:
        self.set_zoom_percent(100)

    @property
    def document(self):
        return self.state.document

    def export_state(self, document_id: str) -> ViewRecord:
        editor = self.state.export_state()
        vertical = self.verticalScrollBar().value()
        return ViewRecord(
            self.view_id,
            document_id,
            editor.cursor,
            editor.anchor,
            editor.preferred_column,
            vertical,
            self.horizontalScrollBar().value(),
            vertical if self._soft_wrap else 0,
            self._soft_wrap,
            self._zoom_percent,
            self._dock_return,
        )

    def _restore_vertical_scroll(self, requested: int) -> None:
        scrollbar = self.verticalScrollBar()
        if self._soft_wrap:
            complete = self._wrapped_row_index().complete
        else:
            complete = self.document.document_line_index.complete
        if not complete and requested > scrollbar.maximum():
            upper_bound = self.document.total_chars()
            scrollbar.setMaximum(min(requested, upper_bound))
        scrollbar.setValue(requested)

    def _restore_horizontal_scroll(self, requested: int) -> None:
        scrollbar = self.horizontalScrollBar()
        if self._soft_wrap:
            scrollbar.setValue(0)
            return
        # A saved pixel offset cannot be capped using code-point cell counts.
        # The bounded layout resolves the actual line width progressively.
        selected = max(0, min(requested, 2_147_483_647))
        index = self.document.document_line_index
        if index.complete and index.indexed_line_count == 1:
            start, offset, shape, resolved = self._horizontal_geometry(0)
            if resolved and not self.document.read_line_window(
                0, column_start=start + len(shape.text), max_chars=1
            ):
                selected = min(
                    selected, max(0, int(offset + shape.width) - scrollbar.pageStep())
                )
        if selected > scrollbar.maximum():
            scrollbar.setMaximum(selected)
        scrollbar.setValue(selected)

    def restore_state(self, record: ViewRecord) -> None:
        if not isinstance(record, ViewRecord):
            raise TypeError("record must be a ViewRecord")
        if record.view_id != self.view_id:
            raise ValueError("view record ID does not match this view")
        self.set_dock_return(record.dock_return)
        self.set_zoom_percent(record.zoom_percent)
        self.set_soft_wrap(record.soft_wrap)
        self.state.restore_state(
            EditorStateSnapshot(
                record.cursor,
                record.anchor,
                record.preferred_column,
            )
        )
        self._refresh_scrollbars(advance_index=False)
        self._restore_horizontal_scroll(record.horizontal_scroll)
        vertical = (
            record.wrap_viewport_row if record.soft_wrap else record.vertical_scroll
        )
        self._restore_vertical_scroll(vertical)
        line = self.document.line_for_char(self.state.cursor)
        column = self.state.cursor - self.document.line_start(line)
        self.cursorPositionChanged.emit(line, column)
        self.stateChanged.emit()
        self.viewport().update()

    def _queue_document_revision_refresh(self) -> None:
        if self._disposed or self._document_refresh_queued:
            return
        self._document_refresh_queued = True
        self._documentRevisionChanged.emit()

    def refresh_document_revision(self) -> None:
        self._document_refresh_queued = False
        if self._disposed:
            return
        total = self.document.total_chars()
        self.state.cursor = max(0, min(total, self.state.cursor))
        self.state.anchor = max(0, min(total, self.state.anchor))
        self._wrap_index = None
        self._wrap_signature = None
        self._match_index = MatchIndex(())
        self._refresh_scrollbars(advance_index=False)
        line = self.document.line_for_char(self.state.cursor)
        column = self.state.cursor - self.document.line_start(line)
        self.cursorPositionChanged.emit(line, column)
        self.stateChanged.emit()
        self.viewport().update()

    def dispose(self) -> None:
        if self._disposed:
            return
        self._disposed = True
        self._inspection.changed.disconnect(self.viewport().update)
        self._document_refresh_queued = False
        remove = self._remove_document_listener
        self._remove_document_listener = None
        if remove is not None:
            remove()

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        if not self._disposed:
            self.viewport().update()
            self.viewFocused.emit(self.view_id)

    def focusOutEvent(self, event) -> None:
        super().focusOutEvent(event)
        self.viewport().update()

    def closeEvent(self, event) -> None:
        self.dispose()
        super().closeEvent(event)

    def set_progressive_navigation(self, enabled: bool) -> None:
        self._progressive_navigation = bool(enabled)

    def set_match_index(self, match_index: MatchIndex | MatchStore | None) -> None:
        self._match_index = MatchIndex(()) if match_index is None else match_index
        self.viewport().update()

    def _visible_line_capacity(self) -> int:
        return max(1, self.viewport().height() // self._line_height + 1)

    def _on_scroll_changed(self, _value: int) -> None:
        self._refresh_scrollbars(advance_index=True)
        self.viewport().update()

    def _update_gutter_width(self) -> None:
        # Use the indexed range without forcing a scan of a large document.
        largest = max(1, self.document.document_line_index.indexed_line_count)
        width = max(48, self._gutter_metrics.horizontalAdvance(str(largest)) + 12)
        if width != self._gutter_width:
            self._gutter_width = width
            self.viewport().update()

    def _prepare_wrapped_rows(self, first_row: int, visible: int) -> WrappedRowIndex:
        while True:
            index = self._wrapped_row_index()
            index.ensure_row(first_row + visible)
            # Indexing can discover another line-number digit, reducing the
            # available text columns. Rebuild rows before using that layout.
            self._update_gutter_width()
            if index._row_provider.width_px == self._wrap_width():
                if (
                    not index.complete
                    and index.known_count <= first_row + visible
                    and not index._row_provider.blocked
                ):
                    QTimer.singleShot(0, self.viewport().update)
                return index

    def _refresh_scrollbars(self, *, advance_index: bool) -> None:
        self._update_gutter_width()
        visible = self._visible_line_capacity()
        if self._soft_wrap:
            first_row = self.verticalScrollBar().value()
            index = self._prepare_wrapped_rows(first_row, visible)
            if index.complete:
                maximum = max(0, index.known_count - visible)
            else:
                maximum = max(first_row, index.known_count - visible)
            self.verticalScrollBar().setPageStep(visible)
            self.verticalScrollBar().setSingleStep(1)
            self.verticalScrollBar().setRange(0, maximum)
            self.horizontalScrollBar().setPageStep(1)
            self.horizontalScrollBar().setRange(0, 0)
            return
        index = self.document.document_line_index
        if advance_index and not index.complete:
            target = index.indexed_char_end + 65_536
            try:
                index.ensure_char(target)
            except ValueError:
                pass
        self._update_gutter_width()
        known_lines = index.indexed_line_count
        if index.complete:
            maximum = max(0, known_lines - visible)
        else:
            maximum = max(self.verticalScrollBar().value(), known_lines - 1)
        self.verticalScrollBar().setPageStep(visible)
        self.verticalScrollBar().setSingleStep(1)
        self.verticalScrollBar().setRange(0, maximum)

        horizontal_page = max(1, self.viewport().width() - self._gutter_width)
        self.horizontalScrollBar().setPageStep(horizontal_page)
        self.horizontalScrollBar().setSingleStep(self._cell_width)
        self.horizontalScrollBar().setRange(
            0,
            max(0, self._max_seen_line_width - horizontal_page),
        )

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._refresh_scrollbars(advance_index=False)

    def _horizontal_window(self, line: int = 0) -> tuple[int, float]:
        start, offset, _, resolved = self._horizontal_geometry(line)
        return start, self._gutter_width + offset - self.horizontalScrollBar().value()

    def _horizontal_geometry(self, line, *, column=None):
        signature = (id(self.document), self.document.revision, self.font().key())
        if signature != self._horizontal_signature:
            self._horizontal_layouts = HorizontalLayouts(
                self.document, self.font(), self._cell_width * 4
            )
            self._horizontal_signature = signature
        result = self._horizontal_layouts.window(
            line, pixel=self.horizontalScrollBar().value(), column=column
        )
        self.geometry_pending = not result[3]
        if self.geometry_pending and result[2].text:
            QTimer.singleShot(0, self.viewport().update)
        return result

    def _window_owns_cursor(self, text: str, window_start: int) -> bool:
        """Internal seams belong to the following row; logical EOL stays here."""
        local = self.state.cursor - window_start
        if 0 <= local < len(text):
            return True
        if local != len(text):
            return False
        # A one-code-point probe distinguishes EOL/EOF from a bounded window or
        # soft-wrap seam without discovering/materializing the full line.
        iterator = self.document.iter_text(self.state.cursor, chunk_chars=1)
        try:
            _, following = next(iterator)
        except StopIteration:
            return True
        return following[:1] in {"\r", "\n"}

    def _shape(self, text, window_start=None, *, origin=0):
        preedit = None
        if (
            window_start is not None
            and self._preedit_text
            and self._window_owns_cursor(text, window_start)
        ):
            preedit = (self.state.cursor - window_start, self._preedit_text)
        key = (text, self.font().key(), preedit, origin % (self._cell_width * 4))
        shaped = self._shape_cache.pop(key, None)
        if shaped is None:
            shaped = ShapedWindow(
                text,
                self.font(),
                tab_stop_px=self._cell_width * 4,
                preedit=preedit,
                tab_origin=origin,
            )
        self._shape_cache[key] = shaped
        while len(self._shape_cache) > 64:
            self._shape_cache.popitem(last=False)
        return shaped

    def _composition_pan(self, shaped: ShapedWindow, text_x: float) -> float:
        """Pan only the virtual composition row; preserve document scroll state."""
        if shaped.preedit is None:
            return 0.0
        caret = text_x + shaped.preedit_x(self._preedit_cursor)
        left = float(self._gutter_width + 2)
        right = max(left, float(self.viewport().width() - 4))
        return min(right, max(left, caret)) - caret

    def _line_content(
        self,
        line: int,
        column_start: int,
        *,
        max_chars: int | None = None,
    ):
        return self.document.read_line_window_annotated(
            line,
            column_start=column_start,
            max_chars=self._max_visible_chars if max_chars is None else max_chars,
        )

    def _line_text(self, line: int, column_start: int) -> str:
        return self._line_content(line, column_start).text

    def _paint_invalid_byte_annotations(
        self,
        painter: QPainter,
        annotated,
        window_start: int,
        text: str,
        text_x: int,
        y: int,
        shaped=None,
    ) -> None:
        if not annotated.invalid_bytes:
            return
        shaped = self._shape(text) if shaped is None else shaped
        painter.setPen(self._theme_tokens.invalid_byte)
        for span in annotated.invalid_bytes:
            local = span.start - window_start
            if local < 0 or local >= len(text):
                continue
            x1 = text_x + shaped.x_for_cp(local)
            x2 = text_x + shaped.x_for_cp(local + 1)
            painter.drawRect(
                int(x1),
                y + 1,
                max(2, int(x2 - x1)),
                max(2, self._line_height - 3),
            )

    def _paint_line_text(
        self,
        painter: QPainter,
        text: str,
        x: float,
        y: float,
        *,
        selection: tuple[int, int] | None = None,
        shaped=None,
    ) -> QTextLayout:
        shaped = self._shape(text) if shaped is None else shaped
        layout = shaped.layout
        formats: list[QTextLayout.FormatRange] = []
        if selection is not None:
            start, end = selection
            if 0 <= start < end <= len(text):
                selected_format = QTextCharFormat()
                selected_format.setForeground(self._theme_tokens.selected_text)
                selected_range = QTextLayout.FormatRange()
                selected_range.start = shaped.unit_for_cp(start)
                selected_range.length = shaped.unit_for_cp(end) - selected_range.start
                selected_range.format = selected_format
                formats.append(selected_range)
        if shaped.preedit is not None:
            fmt = QTextCharFormat()
            fmt.setFontUnderline(True)
            item = QTextLayout.FormatRange()
            item.start = shaped.mapping.cp_to_u16(shaped.preedit[0])
            item.length = len(shaped.preedit[1].encode("utf-16-le")) // 2
            item.format = fmt
            formats.append(item)
            for attribute in self._preedit_formats:
                if (
                    0 <= attribute.start <= item.length
                    and 0 <= attribute.length <= item.length - attribute.start
                ):
                    styled = QTextLayout.FormatRange()
                    styled.start = item.start + attribute.start
                    styled.length = attribute.length
                    styled.format = QTextCharFormat(attribute.value)
                    formats.append(styled)
        layout.draw(
            painter,
            QPointF(
                x,
                y
                + self._row_ascent
                - (shaped.lines[0].ascent() if shaped.lines else self._row_ascent),
            ),
            formats,
        )
        return layout

    @staticmethod
    def _layout_cursor_x(line, index: int) -> float:
        value = line.cursorToX(index)
        return float(value[0] if isinstance(value, tuple) else value)

    def _paint_whitespace_marker(
        self,
        painter: QPainter,
        kind: WhitespaceKind | str,
        label: str,
        x1: float,
        x2: float,
        y: float,
    ) -> None:
        tokens = self._theme_tokens
        baseline = y + self._row_ascent
        left = int(round(x1))
        if kind == "overflow":
            painter.setPen(tokens.invisible_marker)
            painter.drawText(left + 3, baseline, label)
            return
        if self.whitespace_details_visible:
            for item in label.split(" / "):
                self._inspection_labels[item.partition("×")[0]] = None
        if kind == WhitespaceKind.SPACE:
            painter.save()
            try:
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(tokens.space_marker)
                center = QPointF((x1 + x2) / 2.0, y + self._line_height / 2.0)
                diameter = min(abs(x2 - x1) * 0.5, self._metrics.height() * 0.25)
                radius = max(0.5, diameter / 2.0)
                painter.drawEllipse(center, radius, radius)
            finally:
                painter.restore()
            return
        elif kind == WhitespaceKind.TAB:
            painter.setPen(tokens.tab_marker)
            painter.drawText(left + 1, baseline, "»")
            return
        elif kind == "eol":
            painter.setPen(tokens.eol_marker)
            painter.drawText(
                left + 3, baseline, {"LF": "␊", "CR": "␍", "CRLF": "␍␊"}[label]
            )
            return
        else:
            painter.setPen(tokens.invisible_marker)
            width = max(4.0, self._cell_width * 0.8)
            center = (x1 + x2) / 2 if abs(x2 - x1) >= 0.5 else x1
            paint_compact_marker(
                painter,
                label,
                QRectF(center - width / 2, y + 1, width, self._line_height - 2),
            )
            return

    def _paint_whitespace_for_row(
        self,
        painter: QPainter,
        layout: QTextLayout,
        text: str,
        text_x: int,
        y: int,
        line_number: int,
        *,
        owns_end: bool,
        budget: _MarkerBudget,
        shaped=None,
        end_offset=None,
    ) -> None:
        if self._whitespace_mode == WhitespaceMode.OFF or layout.lineCount() == 0:
            return
        layout_line = layout.lineAt(0)
        viewport_right = float(self.viewport().width())
        viewport_left = float(self._gutter_width)
        markers = tuple(iter_character_markers(text, self._whitespace_mode))
        # Document offsets count code points; QTextLine offsets count UTF-16 units.
        mapping = Utf16Map(text)
        utf16_positions = [
            shaped.unit_for_cp(i) if shaped is not None else mapping.cp_to_u16(i)
            for i in range(len(text) + 1)
        ]
        index = 0
        while index < len(markers):
            marker = markers[index]
            x1 = float(text_x) + self._layout_cursor_x(
                layout_line, utf16_positions[marker.index]
            )
            x2 = float(text_x) + self._layout_cursor_x(
                layout_line,
                utf16_positions[marker.index + 1],
            )
            label = marker.label
            if marker.kind == WhitespaceKind.INVISIBLE and abs(x2 - x1) < 0.5:
                group_end = index + 1
                while group_end < len(markers):
                    candidate = markers[group_end]
                    if (
                        candidate.kind != WhitespaceKind.INVISIBLE
                        or candidate.index != markers[group_end - 1].index + 1
                    ):
                        break
                    candidate_x1 = float(text_x) + self._layout_cursor_x(
                        layout_line,
                        utf16_positions[candidate.index],
                    )
                    candidate_x2 = float(text_x) + self._layout_cursor_x(
                        layout_line,
                        utf16_positions[candidate.index + 1],
                    )
                    if (
                        abs(candidate_x2 - candidate_x1) >= 0.5
                        or abs(candidate_x1 - x1) >= 0.5
                    ):
                        break
                    group_end += 1
                count = group_end - index
                if count > 1:
                    counts = Counter(item.label for item in markers[index:group_end])
                    label = " / ".join(
                        f"{name}×{total}" if total > 1 else name
                        for name, total in counts.items()
                    )
                index = group_end
            else:
                index += 1
            if x2 < viewport_left or x1 > viewport_right:
                continue
            budget.last_position = (x1, x2, y)
            if _consume_marker(budget):
                self._paint_whitespace_marker(
                    painter,
                    marker.kind,
                    label,
                    x1,
                    x2,
                    y,
                )

        if shows_eol(self._whitespace_mode) and owns_end:
            iterator = self.document.iter_text(end_offset, chunk_chars=2)
            try:
                _, tail = next(iterator)
            except StopIteration:
                tail = ""
            terminator = "\r\n" if tail.startswith("\r\n") else tail[:1]
            label = {"\n": "LF", "\r\n": "CRLF", "\r": "CR"}.get(terminator)
            if label is not None:
                x = float(text_x) + self._layout_cursor_x(
                    layout_line, utf16_positions[-1]
                )
                if viewport_left <= x <= viewport_right:
                    budget.last_position = (x, x, y)
                    if _consume_marker(budget):
                        self._paint_whitespace_marker(
                            painter,
                            "eol",
                            label,
                            x,
                            x,
                            y,
                        )

    def paintEvent(self, event) -> None:
        del event
        self._inspection_labels.clear()
        painter = QPainter(self.viewport())
        tokens = self._theme_tokens
        painter.fillRect(self.viewport().rect(), tokens.base)
        painter.setFont(self.font())
        marker_budget = _MarkerBudget()

        first_line = self.verticalScrollBar().value()
        visible = self._visible_line_capacity()
        selection = self.state.selection
        cursor_line = self.document.line_for_char(self.state.cursor)
        wrapped = (
            self._prepare_wrapped_rows(first_line, visible) if self._soft_wrap else None
        )

        painter.fillRect(
            0,
            0,
            self._gutter_width,
            self.viewport().height(),
            tokens.gutter_base,
        )

        display_rows: list[tuple[int, int, float, int, int]] = []
        if wrapped is not None:
            for row in range(min(visible, max(0, wrapped.known_count - first_line))):
                try:
                    visual = wrapped.row(first_line + row)
                except ValueError:
                    break
                display_rows.append(
                    (
                        visual.line,
                        visual.column_start,
                        self._gutter_width,
                        row,
                        visual.length,
                    )
                )
        else:
            for row in range(visible):
                try:
                    column_start, offset, geometry, _ = self._horizontal_geometry(
                        first_line + row
                    )
                    text_x = (
                        self._gutter_width + offset - self.horizontalScrollBar().value()
                    )
                except ValueError:
                    break
                display_rows.append(
                    (first_line + row, column_start, text_x, row, len(geometry.text))
                )

        for line_number, column_start, text_x, row, row_length in display_rows:
            try:
                line_start = self.document.line_start(line_number)
                annotated = self._line_content(
                    line_number,
                    column_start,
                    max_chars=max(1, row_length),
                )
                text = annotated.text
                text = text[:row_length]
            except ValueError:
                break

            y = row * self._line_height
            baseline = y + self._row_ascent
            painter.setPen(tokens.gutter_text)
            if not self._soft_wrap or column_start == 0:
                label = str(line_number + 1)
                painter.setFont(self._gutter_font)
                painter.drawText(
                    self._gutter_width
                    - 8
                    - self._gutter_metrics.horizontalAdvance(label),
                    baseline,
                    label,
                )
                painter.setFont(self.font())

            shaped = self._shape(
                text,
                line_start + column_start,
                origin=(
                    0
                    if self._soft_wrap
                    else text_x
                    - self._gutter_width
                    + self.horizontalScrollBar().value()
                ),
            )
            ascent = max((math.ceil(line.ascent()) for line in shaped.lines), default=0)
            descent = max(
                (math.ceil(line.descent()) for line in shaped.lines), default=0
            )
            if (
                ascent > self._row_ascent
                or descent > self._line_height - self._row_ascent
            ):
                self._row_ascent = max(self._row_ascent, ascent)
                self._line_height = max(self._line_height, self._row_ascent + descent)
                painter.end()
                self.viewport().update()
                return
            painter.save()
            painter.setClipRect(
                QRectF(
                    self._gutter_width,
                    0,
                    max(0, self.viewport().width() - self._gutter_width),
                    self.viewport().height(),
                )
            )
            width = shaped.width
            if shaped.preedit is not None:
                width = self._shape(
                    text,
                    origin=(
                        0
                        if self._soft_wrap
                        else text_x
                        - self._gutter_width
                        + self.horizontalScrollBar().value()
                    ),
                ).width
            if not self._soft_wrap:
                self._max_seen_line_width = max(
                    self._max_seen_line_width,
                    int(
                        text_x
                        - self._gutter_width
                        + self.horizontalScrollBar().value()
                        + width
                        + (self.viewport().width() if len(text) >= 8191 else 0)
                    ),
                )

            text_x += self._composition_pan(shaped, text_x)
            line_window_start = line_start + column_start
            line_end = line_window_start + len(text)
            owns_end = not self.document.read_line_window(
                line_number, column_start=column_start + len(text), max_chars=1
            )
            if len(self._match_index):
                match_color = tokens.match
                for record in self._match_index.intersecting(
                    line_window_start, line_end + 1
                ):
                    if record.start == record.end and not _zero_width_visible(
                        record.start,
                        line_window_start,
                        line_end,
                        owns_end=owns_end,
                    ):
                        continue
                    a = max(record.start, line_window_start) - line_window_start
                    b = min(record.end, line_end) - line_window_start
                    a = max(0, min(len(text), a))
                    b = max(0, min(len(text), b))
                    x1 = text_x + shaped.x_for_cp(a)
                    if record.start == record.end:
                        marker_width = max(2.0, self.devicePixelRatioF())
                        marker_x = max(
                            0.0,
                            min(
                                float(x1),
                                max(0.0, self.viewport().width() - marker_width),
                            ),
                        )
                        painter.fillRect(
                            QRectF(
                                marker_x,
                                float(y),
                                marker_width,
                                float(self._line_height),
                            ),
                            match_color,
                        )
                    elif b > a:
                        x2 = text_x + shaped.x_for_cp(b)
                        painter.fillRect(
                            int(x1),
                            y,
                            max(1, int(x2 - x1)),
                            self._line_height,
                            match_color,
                        )

            selected_range: tuple[int, int] | None = None
            if selection is not None:
                sel_start, sel_end = selection
                visible_start = max(sel_start, line_window_start)
                visible_end = min(sel_end, line_end)
                if visible_start < visible_end:
                    a = visible_start - line_window_start
                    b = visible_end - line_window_start
                    x1 = text_x + shaped.x_for_cp(a)
                    x2 = text_x + shaped.x_for_cp(b)
                    painter.fillRect(
                        int(x1),
                        y,
                        max(1, int(x2 - x1)),
                        self._line_height,
                        tokens.selection,
                    )
                    selected_range = (a, b)

            self._paint_invalid_byte_annotations(
                painter, annotated, line_window_start, text, text_x, y, shaped
            )
            painter.setPen(tokens.text)
            layout = self._paint_line_text(
                painter,
                text,
                float(text_x),
                float(y),
                selection=selected_range,
                shaped=shaped,
            )
            self._paint_whitespace_for_row(
                painter,
                layout,
                text,
                text_x,
                y,
                line_number,
                owns_end=owns_end,
                budget=marker_budget,
                shaped=shaped,
                end_offset=line_end,
            )

            if (
                line_number == cursor_line
                and self.hasFocus()
                and self._preedit_cursor_visible
            ):
                local_column = self.state.cursor - line_window_start
                if self._window_owns_cursor(text, line_window_start):
                    cursor_x = text_x + (
                        shaped.preedit_x(self._preedit_cursor)
                        if shaped.preedit
                        else shaped.x_for_cp(local_column)
                    )
                    painter.drawLine(
                        math.ceil(cursor_x),
                        y + 1,
                        math.ceil(cursor_x),
                        y + self._line_height - 1,
                    )
            painter.restore()

        if marker_budget.overflow and marker_budget.last_position is not None:
            x1, x2, y = marker_budget.last_position
            self._paint_whitespace_marker(
                painter,
                "overflow",
                f"+{marker_budget.overflow}",
                x1,
                x2,
                y,
            )
            marker_budget.remaining -= 1

        self._paint_inspection_key(painter)
        self._refresh_scrollbars(advance_index=False)

    def _paint_inspection_key(self, painter: QPainter) -> None:
        detail = self.selected_character_detail
        entries = self.inspection_entries
        if detail is None and not entries:
            return
        width = self.viewport().width() - self._gutter_width - 8
        if width < 40:
            return
        font = QFont(self.font())
        font.setPointSizeF(max(6, font.pointSizeF() * 0.85))
        metrics = QFontMetrics(font)
        row_height = metrics.height() + 4
        columns = max(
            1, min(3, width // max(240, metrics.horizontalAdvance("NNBSP U+202F") + 36))
        )
        header_rows = 2 if detail is not None else 1
        capacity = max(
            0, int(self.viewport().height() * 0.45) // row_height - header_rows
        )
        if capacity == 0 and detail is None:
            return
        shown = min(len(entries), capacity * columns)
        truncated = shown < len(entries)
        if truncated:
            shown = max(0, shown - columns)
        rows = (shown + columns - 1) // columns
        height = (header_rows + rows + int(truncated)) * row_height + 8
        box = QRectF(
            self._gutter_width + 4, self.viewport().height() - height - 4, width, height
        )
        painter.save()
        try:
            painter.setFont(font)
            painter.fillRect(box, self._theme_tokens.gutter_base)
            painter.setPen(self._theme_tokens.text)
            painter.drawRect(box)

            def text(value, x, y, available):
                value = metrics.elidedText(
                    value, Qt.TextElideMode.ElideRight, max(1, int(available))
                )
                painter.drawText(QPointF(x, y + metrics.ascent()), value)

            text(
                "Unicode inspection — visible marker types",
                box.left() + 6,
                box.top() + 4,
                width - 12,
            )
            if detail is not None:
                text(detail, box.left() + 6, box.top() + row_height + 4, width - 12)
            labels = tuple(self._inspection_labels)
            for index, entry in enumerate(entries[:shown]):
                row, column = divmod(index, columns)
                x = box.left() + column * width / columns + 6
                y = box.top() + (header_rows + row) * row_height + 4
                label = labels[index]
                glyph = {
                    "SPACE": "·",
                    "TAB": "»",
                    "LF": "␊",
                    "CR": "␍",
                    "CRLF": "␍␊",
                }.get(label)
                painter.setPen(self._theme_tokens.invisible_marker)
                if glyph is not None:
                    text(glyph, x, y, 28)
                else:
                    paint_compact_marker(
                        painter, label, QRectF(x + 3, y, 12, row_height - 3)
                    )
                painter.setPen(self._theme_tokens.text)
                text(entry, x + 28, y, width / columns - 40)
            if truncated:
                text(
                    f"+{len(entries) - shown} types; select one character for details",
                    box.left() + 6,
                    box.top() + (header_rows + rows) * row_height + 4,
                    width - 12,
                )
        finally:
            painter.restore()

    def _char_for_point(self, x: float, y: float) -> int:
        visual_row = self.verticalScrollBar().value() + max(
            0, int(y) // self._line_height
        )
        if self._soft_wrap:
            try:
                wrapped_row = self._wrapped_row_index().row(visual_row)
            except ValueError:
                return self.state.cursor
            line = wrapped_row.line
            column_start = wrapped_row.column_start
            text_x = self._gutter_width
        else:
            line = visual_row
            column_start, offset, geometry, resolved = self._horizontal_geometry(line)
            if not resolved:
                return self.state.cursor
            text_x = self._gutter_width + offset - self.horizontalScrollBar().value()
        try:
            line_start = self.document.line_start(line)
            text = (
                self._line_text(line, column_start)[: wrapped_row.length]
                if self._soft_wrap
                else geometry.text
            )
        except ValueError:
            return self.state.cursor

        shaped = self._shape(
            text,
            line_start + column_start,
            origin=(
                0
                if self._soft_wrap
                else text_x - self._gutter_width + self.horizontalScrollBar().value()
            ),
        )
        text_x += self._composition_pan(shaped, text_x)
        return line_start + column_start + shaped.cp_for_x(max(0.0, x - text_x))

    def _select_range(self, start: int, end: int) -> None:
        self.state.move_to(start)
        self.state.move_to(end, selecting=True)
        self._state_changed()

    def _word_range(self, position: int) -> tuple[int, int]:
        total = self.document.total_chars()
        if position >= total:
            return total, total
        character = self.document.read(position, position + 1)
        if not self.state._is_word_character(character) and position > 0:
            previous = self.document.read(position - 1, position)
            if self.state._is_word_character(previous):
                position -= 1
                character = previous
        if not self.state._is_word_character(character):
            return position, position
        start = position
        while start > 0:
            character = self.document.read(start - 1, start)
            if not self.state._is_word_character(character):
                break
            start -= 1
        end = position + 1
        while end < total:
            character = self.document.read(end, end + 1)
            if not self.state._is_word_character(character):
                break
            end += 1
        return start, end

    def _visual_line_range(self, y: float) -> tuple[int, int]:
        visual_row = self.verticalScrollBar().value() + max(
            0, int(y) // self._line_height
        )
        if self._soft_wrap:
            try:
                wrapped_row = self._wrapped_row_index().row(visual_row)
            except ValueError:
                return self.state.cursor, self.state.cursor
            line_start = self.document.line_start(wrapped_row.line)
            start = line_start + wrapped_row.column_start
            return start, start + wrapped_row.length
        try:
            start = self.document.line_start(visual_row)
            return start, self.document.line_end(visual_row)
        except ValueError:
            return self.state.cursor, self.state.cursor

    def _logical_line_range(self, position: int) -> tuple[int, int]:
        line = self.document.line_for_char(position)
        start = self.document.line_start(line)
        try:
            end = self.document.line_start(line + 1)
        except ValueError:
            end = self.document.total_chars()
        return start, end

    def _select_click_unit(self, x: float, y: float, click_count: int) -> None:
        position = self._char_for_point(x, y)
        if click_count == 2:
            start, end = self._word_range(position)
        elif click_count == 3:
            start, end = self._visual_line_range(y)
        elif click_count >= 4:
            start, end = self._logical_line_range(position)
        else:
            start = end = position
        self._select_range(start, end)

    def _register_click(self, event: QMouseEvent) -> int:
        now = time.monotonic()
        position = event.position()
        last_x, last_y = self._last_click_position
        distance = abs(position.x() - last_x) + abs(position.y() - last_y)
        interval = QApplication.doubleClickInterval() / 1000.0
        if (
            now - self._last_click_at <= interval
            and distance <= QApplication.startDragDistance()
        ):
            self._click_count = self._click_count % 4 + 1
        else:
            self._click_count = 1
        self._last_click_at = now
        self._last_click_position = (position.x(), position.y())
        return self._click_count

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            click_count = self._register_click(event)
            if click_count > 1:
                self._select_click_unit(
                    event.position().x(),
                    event.position().y(),
                    click_count,
                )
                self._drag_selecting = True
                event.accept()
                return
            selecting = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
            self.state.move_to(
                self._char_for_point(event.position().x(), event.position().y()),
                selecting=selecting,
            )
            self._drag_selecting = True
            self._state_changed()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
            click_count = self._register_click(event)
            self._select_click_unit(
                event.position().x(),
                event.position().y(),
                max(2, click_count),
            )
            self._drag_selecting = True
            event.accept()
            return
        super().mouseDoubleClickEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_selecting and event.buttons() & Qt.MouseButton.LeftButton:
            self.state.move_to(
                self._char_for_point(event.position().x(), event.position().y()),
                selecting=True,
            )
            self._state_changed()
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_selecting = False
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        delta = event.angleDelta().y()
        primary = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )
        if primary and delta:
            steps = max(1, abs(delta) // 120)
            for _ in range(steps):
                self.zoom_in() if delta > 0 else self.zoom_out()
            event.accept()
            return
        if delta:
            steps = max(1, abs(delta) // 120) * 3
            direction = -1 if delta > 0 else 1
            self.verticalScrollBar().setValue(
                self.verticalScrollBar().value() + direction * steps
            )
            event.accept()
            return
        super().wheelEvent(event)

    def _newline_text(self) -> str:
        return {"CRLF": "\r\n", "CR": "\r", "LF": "\n"}[self.document.insertion_eol]

    def copy_selection(self) -> str:
        text = self.state.selected_text()
        if text:
            QGuiApplication.clipboard().setText(text)
        return text

    def cut_selection(self) -> str:
        text = self.state.cut_selection()
        if text:
            QGuiApplication.clipboard().setText(text)
            self._state_changed()
        return text

    def paste_clipboard(self) -> None:
        text = QGuiApplication.clipboard().text()
        if text:
            self.state.paste_text(text)
            self._state_changed()

    def inputMethodEvent(self, event: QInputMethodEvent) -> None:
        commit = event.commitString()
        replacement_length = event.replacementLength()
        replacement_start = event.replacementStart()
        surrounding, cursor, _ = self.state.ime_surrounding_text()
        mapping = Utf16Map(surrounding)
        changed = bool(commit or replacement_length)
        if replacement_length or replacement_start:
            start_unit = mapping.cp_to_u16(cursor) + replacement_start
            end_unit = start_unit + replacement_length
            try:
                start = (
                    self.state.cursor
                    - cursor
                    + mapping.u16_to_cp(start_unit, bias="floor")
                )
                end = (
                    self.state.cursor
                    - cursor
                    + mapping.u16_to_cp(end_unit, bias="ceil")
                )
            except ValueError:
                event.ignore()
                return
            self.state.move_to(start)
            self.state.move_to(end, selecting=True)
        if changed:
            self.state._replace_selection(commit)
        self._preedit_text = event.preeditString()[:2048]
        self._preedit_cursor = len(self._preedit_text)
        self._preedit_cursor_visible = True
        self._preedit_formats = tuple(
            a
            for a in event.attributes()[:256]
            if a.type == QInputMethodEvent.AttributeType.TextFormat
        )
        for attribute in event.attributes()[:256]:
            if attribute.type == QInputMethodEvent.AttributeType.Selection:
                surrounding, relative, _ = self.state.ime_surrounding_text()
                context = Utf16Map(surrounding)
                base = self.state.cursor - relative
                try:
                    anchor = base + context.u16_to_cp(attribute.start, bias="floor")
                    cursor = base + context.u16_to_cp(
                        attribute.start + attribute.length, bias="ceil"
                    )
                except ValueError:
                    continue
                self.state.move_to(anchor)
                self.state.move_to(cursor, selecting=True)
                changed = True
            if attribute.type == QInputMethodEvent.AttributeType.Cursor:
                self._preedit_cursor_visible = attribute.length != 0
                self._preedit_cursor = Utf16Map(self._preedit_text).u16_to_cp(
                    max(
                        0,
                        min(
                            Utf16Map(self._preedit_text).positions[-1], attribute.start
                        ),
                    )
                )
        if changed:
            self._state_changed()
        else:
            self.viewport().update()
        event.accept()

    def _cursor_rectangle(self) -> QRectF:
        line = self.document.line_for_char(self.state.cursor)
        first = self.verticalScrollBar().value()
        line_start = self.document.line_start(line)
        column = self.state.cursor - line_start
        if self._soft_wrap:
            try:
                visual_row = self._wrapped_row_index().row_for_position(line, column)
                wrapped = self._wrapped_row_index().row(visual_row)
            except ValueError:
                return QRectF()
            else:
                wrapped_column = wrapped.column_start
            text = self._line_text(line, wrapped_column)[: wrapped.length]
            shaped = self._shape(text, line_start + wrapped_column)
            x = self._gutter_width + (
                shaped.preedit_x(self._preedit_cursor)
                if shaped.preedit
                else shaped.x_for_cp(min(len(text), column - wrapped_column))
            )
            y = (visual_row - first) * self._line_height
        else:
            horizontal = self.horizontalScrollBar().value()
            start, offset, shaped, resolved = self._horizontal_geometry(
                line, column=column
            )
            if not resolved:
                return QRectF()
            shaped = self._shape(shaped.text, line_start + start, origin=offset)
            x = (
                self._gutter_width
                + offset
                + (
                    shaped.preedit_x(self._preedit_cursor)
                    if shaped.preedit
                    else shaped.x_for_cp(min(len(shaped.text), column - start))
                )
                - horizontal
            )
            y = (line - first) * self._line_height
        if shaped.preedit is not None:
            text_x = x - shaped.preedit_x(self._preedit_cursor)
            x += self._composition_pan(shaped, text_x)
        return QRectF(float(x), float(y), 2.0, float(self._line_height))

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImEnabled:
            return True
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            return self._cursor_rectangle()
        surrounding, cursor_relative, anchor_relative = (
            self.state.ime_surrounding_text()
        )
        if query == Qt.InputMethodQuery.ImCursorPosition:
            return Utf16Map(surrounding).cp_to_u16(cursor_relative)
        if query == Qt.InputMethodQuery.ImAnchorPosition:
            return Utf16Map(surrounding).cp_to_u16(anchor_relative)
        if query == Qt.InputMethodQuery.ImCurrentSelection:
            selection = self.state.selection
            return (
                self.document.read(*selection)
                if selection and selection[1] - selection[0] <= 4096
                else ""
            )
        if query == Qt.InputMethodQuery.ImSurroundingText:
            return surrounding
        return super().inputMethodQuery(query)

    def keyPressEvent(self, event: QKeyEvent) -> None:
        key = event.key()
        modifiers = event.modifiers()
        selecting = bool(modifiers & Qt.KeyboardModifier.ShiftModifier)
        primary = bool(
            modifiers
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )

        if primary and key == Qt.Key.Key_A:
            self.state.select_all()
        elif primary and key == Qt.Key.Key_C:
            self.copy_selection()
        elif primary and key == Qt.Key.Key_X:
            self.cut_selection()
            event.accept()
            return
        elif primary and key == Qt.Key.Key_V:
            self.paste_clipboard()
            event.accept()
            return
        elif primary and key == Qt.Key.Key_Left:
            self.state.move_word_left(selecting=selecting)
        elif primary and key == Qt.Key.Key_Right:
            self.state.move_word_right(selecting=selecting)
        elif primary and key in (Qt.Key.Key_Home, Qt.Key.Key_Up):
            self.state.move_document_start(selecting=selecting)
        elif primary and key in (Qt.Key.Key_End, Qt.Key.Key_Down):
            if self._progressive_navigation:
                self.navigationRequested.emit("document_end", selecting)
                event.accept()
                return
            self.state.move_document_end(selecting=selecting)
        elif key == Qt.Key.Key_PageUp:
            self.state.move_page(
                -max(1, self._visible_line_capacity() - 1),
                selecting=selecting,
            )
        elif key == Qt.Key.Key_PageDown:
            self.state.move_page(
                max(1, self._visible_line_capacity() - 1),
                selecting=selecting,
            )
        elif key == Qt.Key.Key_Left:
            self.state.move_left(selecting=selecting)
        elif key == Qt.Key.Key_Right:
            self.state.move_right(selecting=selecting)
        elif key == Qt.Key.Key_Up:
            self.state.move_up(selecting=selecting)
        elif key == Qt.Key.Key_Down:
            self.state.move_down(selecting=selecting)
        elif key == Qt.Key.Key_Home:
            self.state.move_home(selecting=selecting)
        elif key == Qt.Key.Key_End:
            self.state.move_end(selecting=selecting)
        elif key == Qt.Key.Key_Backspace:
            self.state.backspace()
        elif key == Qt.Key.Key_Delete:
            self.state.delete_forward()
        elif key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.state.insert_newline()
        elif key == Qt.Key.Key_Tab and not primary:
            self.state.insert_text("\t")
        elif not primary and not (modifiers & Qt.KeyboardModifier.AltModifier):
            text = event.text()
            if text:
                self.state.insert_text(text)
            else:
                super().keyPressEvent(event)
                return
        else:
            super().keyPressEvent(event)
            return

        self._state_changed()
        event.accept()

    def _ensure_cursor_visible(self) -> None:
        line = self.document.line_for_char(self.state.cursor)
        first = self.verticalScrollBar().value()
        visible = self._visible_line_capacity()
        if self._soft_wrap:
            line_start = self.document.line_start(line)
            column = self.state.cursor - line_start
            index = self._wrapped_row_index()
            previous_count = index.known_count
            try:
                visual_row = index.row_for_position(line, column)
            except ValueError:
                if index.known_count > previous_count:
                    QTimer.singleShot(0, self._ensure_cursor_visible)
                return
            if visual_row < first:
                self.verticalScrollBar().setValue(visual_row)
            elif visual_row >= first + visible:
                self.verticalScrollBar().setValue(max(0, visual_row - visible + 1))
            self.horizontalScrollBar().setValue(0)
            return
        if line < first:
            self.verticalScrollBar().setValue(line)
        elif line >= first + visible:
            self.verticalScrollBar().setValue(max(0, line - visible + 1))

        line_start = self.document.line_start(line)
        column = self.state.cursor - line_start
        start, offset, shaped, resolved = self._horizontal_geometry(line, column=column)
        if not resolved:
            if shaped.text:
                QTimer.singleShot(0, self._ensure_cursor_visible)
            return
        cursor_pixel = int(offset + shaped.x_for_cp(column - start))
        horizontal = self.horizontalScrollBar()
        page = max(1, horizontal.pageStep())
        if cursor_pixel < horizontal.value():
            horizontal.setValue(cursor_pixel)
        elif cursor_pixel >= horizontal.value() + page:
            self._max_seen_line_width = max(
                self._max_seen_line_width, cursor_pixel + self._cell_width
            )
            horizontal.setRange(0, max(0, self._max_seen_line_width - page))
            horizontal.setValue(max(0, cursor_pixel - page + self._cell_width))

    def _state_changed(self) -> None:
        self._ensure_cursor_visible()
        self._refresh_scrollbars(advance_index=False)
        line = self.document.line_for_char(self.state.cursor)
        column = self.state.cursor - self.document.line_start(line)
        self.cursorPositionChanged.emit(line, column)
        self.stateChanged.emit()
        self.viewport().update()
