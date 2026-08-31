"""Qt-independent cursor, selection, and editing state."""

from __future__ import annotations

from dataclasses import dataclass

from uniti.core.document import Document


@dataclass(slots=True)
class EditorState:
    document: Document
    cursor: int = 0
    anchor: int = 0
    _preferred_column: int | None = None

    @property
    def selection(self) -> tuple[int, int] | None:
        if self.cursor == self.anchor:
            return None
        return (min(self.cursor, self.anchor), max(self.cursor, self.anchor))

    def _validate_position(self, offset: int) -> int:
        if offset < 0:
            return 0
        try:
            self.document.read(offset, offset)
        except ValueError:
            return self.document.total_chars()
        return offset

    def _set_cursor(self, offset: int, *, selecting: bool, vertical: bool = False) -> None:
        offset = self._validate_position(offset)
        if not selecting:
            self.anchor = offset
        self.cursor = offset
        if not vertical:
            self._preferred_column = None

    def move_to(self, offset: int, *, selecting: bool = False) -> None:
        self._set_cursor(offset, selecting=selecting)

    def move_left(self, *, selecting: bool = False) -> None:
        self._set_cursor(max(0, self.cursor - 1), selecting=selecting)

    def move_right(self, *, selecting: bool = False) -> None:
        try:
            self.document.read(self.cursor, self.cursor + 1)
        except ValueError:
            return
        self._set_cursor(self.cursor + 1, selecting=selecting)

    def _column(self) -> int:
        line = self.document.line_for_char(self.cursor)
        start = self.document.line_start(line)
        text = self.document.read_line(line)
        return min(self.cursor - start, len(text))

    def _move_vertical(self, delta: int, *, selecting: bool = False) -> None:
        line = self.document.line_for_char(self.cursor)
        if self._preferred_column is None:
            self._preferred_column = self._column()
        target_line = line + delta
        if target_line < 0:
            self._set_cursor(0, selecting=selecting, vertical=True)
            return
        try:
            start = self.document.line_start(target_line)
            text = self.document.read_line(target_line)
        except ValueError:
            return
        target = start + min(self._preferred_column, len(text))
        self._set_cursor(target, selecting=selecting, vertical=True)

    def move_up(self, *, selecting: bool = False) -> None:
        self._move_vertical(-1, selecting=selecting)

    def move_down(self, *, selecting: bool = False) -> None:
        self._move_vertical(1, selecting=selecting)

    def move_home(self, *, selecting: bool = False) -> None:
        line = self.document.line_for_char(self.cursor)
        self._set_cursor(self.document.line_start(line), selecting=selecting)

    def move_end(self, *, selecting: bool = False) -> None:
        line = self.document.line_for_char(self.cursor)
        start = self.document.line_start(line)
        self._set_cursor(start + len(self.document.read_line(line)), selecting=selecting)

    def select_all(self) -> None:
        self.anchor = 0
        self.cursor = self.document.total_chars()
        self._preferred_column = None

    def _replace_selection(self, text: str) -> None:
        selection = self.selection
        if selection is None:
            self.document.insert(self.cursor, text)
            self.cursor += len(text)
        else:
            start, end = selection
            self.document.replace(start, end, text)
            self.cursor = start + len(text)
        self.anchor = self.cursor
        self._preferred_column = None

    def insert_text(self, text: str) -> None:
        if text:
            self._replace_selection(text)

    def backspace(self) -> None:
        selection = self.selection
        if selection is not None:
            start, end = selection
            self.document.delete(start, end)
            self.cursor = start
            self.anchor = start
        elif self.cursor > 0:
            self.document.delete(self.cursor - 1, self.cursor)
            self.cursor -= 1
            self.anchor = self.cursor
        self._preferred_column = None

    def delete_forward(self) -> None:
        selection = self.selection
        if selection is not None:
            start, end = selection
            self.document.delete(start, end)
            self.cursor = start
            self.anchor = start
        else:
            try:
                self.document.read(self.cursor, self.cursor + 1)
            except ValueError:
                return
            self.document.delete(self.cursor, self.cursor + 1)
        self._preferred_column = None

    def undo(self) -> None:
        self.document.undo()
        self.cursor = self._validate_position(self.cursor)
        self.anchor = self.cursor
        self._preferred_column = None

    def redo(self) -> None:
        self.document.redo()
        self.cursor = self._validate_position(self.cursor)
        self.anchor = self.cursor
        self._preferred_column = None
