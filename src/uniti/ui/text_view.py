"""Virtualized PySide6 text viewport backed by UNITI's Document engine."""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QFont,
    QFontDatabase,
    QFontMetrics,
    QGuiApplication,
    QInputMethodEvent,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QRawFont,
    QTextLayout,
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea

from uniti.app.editor_state import EditorState
from uniti.regex.match_store import MatchStore
from uniti.regex.results import MatchIndex
from uniti.ui.wrap_index import WrappedRowIndex


class UNITITextView(QAbstractScrollArea):
    """Paint only visible logical text; the UNITI Document remains authoritative."""

    stateChanged = Signal()
    cursorPositionChanged = Signal(int, int)
    zoomChanged = Signal(int)
    wrapChanged = Signal(bool)

    def __init__(self, state: EditorState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self._base_font = self._fixed_pitch_font()
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
        self._line_height = max(1, self._metrics.height())
        self._gutter_width = max(48, self._metrics.horizontalAdvance("00000000") + 12)
        self._max_visible_chars = 8192
        self._cell_width = max(1, self._metrics.horizontalAdvance("M"))
        self._max_seen_line_width = 0
        self._drag_selecting = False
        self._preedit_text = ""
        self._match_index = MatchIndex(())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setMouseTracking(True)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.horizontalScrollBar().valueChanged.connect(self.viewport().update)
        self._refresh_scrollbars(advance_index=False)

    @staticmethod
    def _fixed_pitch_font() -> QFont:
        families = set(QFontDatabase.families())
        preferred = (
            "Menlo",
            "Cascadia Mono",
            "Consolas",
            "DejaVu Sans Mono",
            "Liberation Mono",
            "Noto Sans Mono",
            "Courier New",
            "Monaco",
            "Andale Mono",
        )
        ordered = [family for family in preferred if family in families]
        ordered.extend(sorted(families.difference(ordered)))
        for family in ordered:
            if not QFontDatabase.isFixedPitch(family):
                continue
            font = QFont(family)
            raw_font = QRawFont.fromFont(font)
            if (
                raw_font.isValid()
                and raw_font.supportsCharacter(ord("A"))
                and raw_font.supportsCharacter(ord("Ж"))
            ):
                return font
        return QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont)

    @property
    def zoom_percent(self) -> int:
        return self._zoom_percent

    @property
    def soft_wrap(self) -> bool:
        return self._soft_wrap

    def _wrap_columns(self) -> int:
        width = max(1, self.viewport().width() - self._gutter_width - 8)
        return max(1, width // self._cell_width)

    def _wrapped_row_index(self) -> WrappedRowIndex:
        columns = self._wrap_columns()
        signature = (id(self.document), self.document.revision, columns)
        if self._wrap_index is None or signature != self._wrap_signature:
            self._wrap_index = WrappedRowIndex(self.document, columns)
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

    def _rebuild_metrics(self) -> None:
        self._metrics = QFontMetrics(self.font())
        self._line_height = max(1, self._metrics.height())
        self._gutter_width = max(
            48,
            self._metrics.horizontalAdvance("00000000") + 12,
        )
        self._cell_width = max(1, self._metrics.horizontalAdvance("M"))
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

    def set_match_index(self, match_index: MatchIndex | MatchStore | None) -> None:
        self._match_index = MatchIndex(()) if match_index is None else match_index
        self.viewport().update()

    def _visible_line_capacity(self) -> int:
        return max(1, self.viewport().height() // self._line_height + 1)

    def _on_scroll_changed(self, _value: int) -> None:
        self._refresh_scrollbars(advance_index=True)
        self.viewport().update()

    def _refresh_scrollbars(self, *, advance_index: bool) -> None:
        visible = self._visible_line_capacity()
        if self._soft_wrap:
            index = self._wrapped_row_index()
            first_row = self.verticalScrollBar().value()
            index.ensure_row(first_row + visible)
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

    def _horizontal_window(self) -> tuple[int, int]:
        horizontal = self.horizontalScrollBar().value()
        column_start = horizontal // self._cell_width
        text_x = self._gutter_width - (horizontal % self._cell_width)
        return column_start, text_x

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
        self, painter: QPainter, annotated, window_start: int, text: str, text_x: int, y: int
    ) -> None:
        if not annotated.invalid_bytes:
            return
        color = self.palette().color(QPalette.ColorRole.BrightText)
        painter.setPen(color)
        for span in annotated.invalid_bytes:
            local = span.start - window_start
            if local < 0 or local >= len(text):
                continue
            x1 = text_x + self._metrics.horizontalAdvance(text[:local])
            x2 = text_x + self._metrics.horizontalAdvance(text[: local + 1])
            painter.drawRect(
                int(x1),
                y + 1,
                max(2, int(x2 - x1)),
                max(2, self._line_height - 3),
            )

    def _paint_line_text(self, painter: QPainter, text: str, x: float, y: float) -> None:
        layout = QTextLayout(text, self.font())
        layout.beginLayout()
        line = layout.createLine()
        if line.isValid():
            line.setLineWidth(max(1.0, float(self._metrics.horizontalAdvance(text) + 8)))
            line.setPosition(QPointF(0.0, 0.0))
        layout.endLayout()
        layout.draw(painter, QPointF(x, y))

    def paintEvent(self, event) -> None:
        del event
        painter = QPainter(self.viewport())
        palette = self.palette()
        painter.fillRect(self.viewport().rect(), palette.color(QPalette.ColorRole.Base))
        painter.setFont(self.font())

        first_line = self.verticalScrollBar().value()
        visible = self._visible_line_capacity()
        selection = self.state.selection
        cursor_line = self.document.line_for_char(self.state.cursor)

        gutter_color = palette.color(QPalette.ColorRole.AlternateBase)
        painter.fillRect(0, 0, self._gutter_width, self.viewport().height(), gutter_color)

        display_rows: list[tuple[int, int, int, int]] = []
        if self._soft_wrap:
            wrapped = self._wrapped_row_index()
            wrapped.ensure_row(first_line + visible)
            for row in range(visible):
                try:
                    visual = wrapped.row(first_line + row)
                except ValueError:
                    break
                display_rows.append(
                    (visual.line, visual.column_start, self._gutter_width, row)
                )
        else:
            column_start, text_x = self._horizontal_window()
            display_rows = [
                (first_line + row, column_start, text_x, row)
                for row in range(visible)
            ]

        for line_number, column_start, text_x, row in display_rows:
            try:
                line_start = self.document.line_start(line_number)
                annotated = self._line_content(
                    line_number,
                    column_start,
                    max_chars=self._wrap_columns() if self._soft_wrap else None,
                )
                text = annotated.text
            except ValueError:
                break

            y = row * self._line_height
            baseline = y + self._metrics.ascent()
            painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
            if not self._soft_wrap or column_start == 0:
                painter.drawText(
                    4,
                    baseline,
                    f"{line_number + 1:>{max(1, (self._gutter_width - 12) // max(1, self._metrics.horizontalAdvance('0')))}}",
                )

            width = self._metrics.horizontalAdvance(text)
            known_columns = column_start + len(text)
            if len(text) >= self._max_visible_chars:
                known_columns += self._max_visible_chars
            if not self._soft_wrap:
                self._max_seen_line_width = max(
                    self._max_seen_line_width,
                    known_columns * self._cell_width,
                    self.horizontalScrollBar().value() + width,
                )

            line_window_start = line_start + column_start
            line_end = line_window_start + len(text)
            if len(self._match_index):
                match_color = palette.color(QPalette.ColorRole.Highlight)
                match_color.setAlpha(70)
                for record in self._match_index.intersecting(line_window_start, line_end + 1):
                    a = max(record.start, line_window_start) - line_window_start
                    b = min(record.end, line_end) - line_window_start
                    a = max(0, min(len(text), a))
                    b = max(0, min(len(text), b))
                    x1 = text_x + self._metrics.horizontalAdvance(text[:a])
                    if record.start == record.end or b <= a:
                        painter.fillRect(
                            int(x1), y, 2, self._line_height, match_color
                        )
                    else:
                        x2 = text_x + self._metrics.horizontalAdvance(text[:b])
                        painter.fillRect(
                            int(x1),
                            y,
                            max(1, int(x2 - x1)),
                            self._line_height,
                            match_color,
                        )

            if selection is not None:
                sel_start, sel_end = selection
                visible_start = max(sel_start, line_window_start)
                visible_end = min(sel_end, line_end)
                if visible_start < visible_end:
                    a = visible_start - line_window_start
                    b = visible_end - line_window_start
                    x1 = text_x + self._metrics.horizontalAdvance(text[:a])
                    x2 = text_x + self._metrics.horizontalAdvance(text[:b])
                    painter.fillRect(
                        int(x1),
                        y,
                        max(1, int(x2 - x1)),
                        self._line_height,
                        palette.color(QPalette.ColorRole.Highlight),
                    )

            self._paint_invalid_byte_annotations(
                painter, annotated, line_window_start, text, text_x, y
            )
            painter.setPen(palette.color(QPalette.ColorRole.Text))
            self._paint_line_text(painter, text, float(text_x), float(y))

            if line_number == cursor_line and self._preedit_text:
                local_column = self.state.cursor - line_window_start
                if 0 <= local_column <= len(text):
                    preedit_x = text_x + self._metrics.horizontalAdvance(text[:local_column])
                    painter.drawText(int(preedit_x), baseline, self._preedit_text)
                    preedit_width = self._metrics.horizontalAdvance(self._preedit_text)
                    painter.drawLine(
                        int(preedit_x),
                        y + self._line_height - 2,
                        int(preedit_x + preedit_width),
                        y + self._line_height - 2,
                    )

            if line_number == cursor_line and self.hasFocus():
                local_column = self.state.cursor - line_window_start
                if 0 <= local_column <= len(text):
                    cursor_x = text_x + self._metrics.horizontalAdvance(text[:local_column])
                    painter.drawLine(
                        int(cursor_x),
                        y + 1,
                        int(cursor_x),
                        y + self._line_height - 1,
                    )

        self._refresh_scrollbars(advance_index=False)

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
            column_start, text_x = self._horizontal_window()
        try:
            line_start = self.document.line_start(line)
            text = self._line_text(line, column_start)
            if self._soft_wrap:
                text = text[: self._wrap_columns()]
        except ValueError:
            return self.state.cursor

        target = max(0.0, x - text_x)
        low = 0
        high = len(text)
        while low < high:
            middle = (low + high) // 2
            width = self._metrics.horizontalAdvance(text[: middle + 1])
            if width < target:
                low = middle + 1
            else:
                high = middle
        if low < len(text):
            before = self._metrics.horizontalAdvance(text[:low])
            after = self._metrics.horizontalAdvance(text[: low + 1])
            if target > (before + after) / 2:
                low += 1
        return line_start + column_start + low

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.setFocus()
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
        if replacement_length or replacement_start:
            start = max(0, self.state.cursor + replacement_start)
            end = max(start, start + replacement_length)
            self.state.move_to(start)
            self.state.move_to(end, selecting=True)
        if commit:
            self.state.insert_text(commit)
        self._preedit_text = event.preeditString()
        if commit:
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
                visual_row = first
                wrapped_column = 0
            else:
                wrapped_column = wrapped.column_start
            x = self._gutter_width + (column - wrapped_column) * self._cell_width
            y = (visual_row - first) * self._line_height
        else:
            horizontal = self.horizontalScrollBar().value()
            x = self._gutter_width + column * self._cell_width - horizontal
            y = (line - first) * self._line_height
        return QRectF(float(x), float(y), 2.0, float(self._line_height))

    def inputMethodQuery(self, query):
        if query == Qt.InputMethodQuery.ImEnabled:
            return True
        if query == Qt.InputMethodQuery.ImCursorRectangle:
            return self._cursor_rectangle()
        surrounding, cursor_relative, anchor_relative = self.state.ime_surrounding_text()
        if query == Qt.InputMethodQuery.ImCursorPosition:
            return cursor_relative
        if query == Qt.InputMethodQuery.ImAnchorPosition:
            return anchor_relative
        if query == Qt.InputMethodQuery.ImCurrentSelection:
            return self.state.selected_text()
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
            try:
                visual_row = self._wrapped_row_index().row_for_position(line, column)
            except ValueError:
                visual_row = first
            if visual_row < first:
                self.verticalScrollBar().setValue(visual_row)
            elif visual_row >= first + visible:
                self.verticalScrollBar().setValue(
                    max(0, visual_row - visible + 1)
                )
            self.horizontalScrollBar().setValue(0)
            return
        if line < first:
            self.verticalScrollBar().setValue(line)
        elif line >= first + visible:
            self.verticalScrollBar().setValue(max(0, line - visible + 1))

        line_start = self.document.line_start(line)
        column = self.state.cursor - line_start
        cursor_pixel = column * self._cell_width
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
