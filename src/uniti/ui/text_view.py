"""Virtualized PySide6 text viewport backed by UNITI's Document engine."""

from __future__ import annotations

from PySide6.QtCore import QPointF, Qt, Signal
from PySide6.QtGui import (
    QFontDatabase,
    QFontMetrics,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QPalette,
    QTextLayout,
    QWheelEvent,
)
from PySide6.QtWidgets import QAbstractScrollArea

from uniti.app.editor_state import EditorState
from uniti.regex.match_store import MatchStore
from uniti.regex.results import MatchIndex


class UNITITextView(QAbstractScrollArea):
    """Paint only visible logical text; the UNITI Document remains authoritative."""

    stateChanged = Signal()
    cursorPositionChanged = Signal(int, int)

    def __init__(self, state: EditorState, parent=None) -> None:
        super().__init__(parent)
        self.state = state
        self.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self._metrics = QFontMetrics(self.font())
        self._line_height = max(1, self._metrics.height())
        self._gutter_width = max(48, self._metrics.horizontalAdvance("00000000") + 12)
        self._max_visible_chars = 8192
        self._cell_width = max(1, self._metrics.horizontalAdvance("M"))
        self._max_seen_line_width = 0
        self._drag_selecting = False
        self._match_index = MatchIndex(())
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.verticalScrollBar().valueChanged.connect(self._on_scroll_changed)
        self.horizontalScrollBar().valueChanged.connect(self.viewport().update)
        self._refresh_scrollbars(advance_index=False)

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

    def _line_text(self, line: int, column_start: int) -> str:
        return self.document.read_line_window(
            line,
            column_start=column_start,
            max_chars=self._max_visible_chars,
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
        column_start, text_x = self._horizontal_window()
        visible = self._visible_line_capacity()
        selection = self.state.selection
        cursor_line = self.document.line_for_char(self.state.cursor)

        gutter_color = palette.color(QPalette.ColorRole.AlternateBase)
        painter.fillRect(0, 0, self._gutter_width, self.viewport().height(), gutter_color)

        for row in range(visible):
            line_number = first_line + row
            try:
                line_start = self.document.line_start(line_number)
                text = self._line_text(line_number, column_start)
            except ValueError:
                break

            y = row * self._line_height
            baseline = y + self._metrics.ascent()
            painter.setPen(palette.color(QPalette.ColorRole.PlaceholderText))
            painter.drawText(
                4,
                baseline,
                f"{line_number + 1:>{max(1, (self._gutter_width - 12) // max(1, self._metrics.horizontalAdvance('0')))}}",
            )

            width = self._metrics.horizontalAdvance(text)
            known_columns = column_start + len(text)
            if len(text) >= self._max_visible_chars:
                known_columns += self._max_visible_chars
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

            painter.setPen(palette.color(QPalette.ColorRole.Text))
            self._paint_line_text(painter, text, float(text_x), float(y))

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
        line = self.verticalScrollBar().value() + max(0, int(y) // self._line_height)
        try:
            line_start = self.document.line_start(line)
            column_start, text_x = self._horizontal_window()
            text = self._line_text(line, column_start)
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
        return {
            "CRLF": "\r\n",
            "CR": "\r",
            "LF": "\n",
        }.get(self.document.output_eol or "LF", "\n")

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
            self.state.insert_text(self._newline_text())
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
