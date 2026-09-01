"""Progressive visual-row index for soft-wrapped UNITI document lines."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WrappedRow:
    line: int
    column_start: int
    length: int


class WrappedRowIndex:
    """Map visual rows lazily without constructing a whole-document layout."""

    def __init__(self, document, columns: int) -> None:
        if columns <= 0:
            raise ValueError("columns must be positive")
        self._document = document
        self.columns = columns
        self._rows: list[WrappedRow] = []
        self._next_line = 0
        self._next_column = 0
        self._complete = False

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def known_count(self) -> int:
        return len(self._rows)

    def _append_next(self) -> None:
        while not self._complete:
            try:
                self._document.line_start(self._next_line)
            except ValueError:
                self._complete = True
                return
            text = self._document.read_line_window(
                self._next_line,
                column_start=self._next_column,
                max_chars=self.columns,
            )
            if text:
                self._rows.append(
                    WrappedRow(self._next_line, self._next_column, len(text))
                )
                if len(text) < self.columns:
                    self._next_line += 1
                    self._next_column = 0
                else:
                    self._next_column += len(text)
                return
            if self._next_column == 0:
                self._rows.append(WrappedRow(self._next_line, 0, 0))
                self._next_line += 1
                return
            self._next_line += 1
            self._next_column = 0

    def ensure_row(self, row_index: int) -> None:
        if row_index < 0:
            raise ValueError("row_index must be non-negative")
        while row_index >= len(self._rows) and not self._complete:
            self._append_next()

    def row(self, row_index: int) -> WrappedRow:
        self.ensure_row(row_index)
        if row_index >= len(self._rows):
            raise ValueError("visual row is beyond end of document")
        return self._rows[row_index]

    def row_for_position(self, line: int, column: int) -> int:
        if line < 0 or column < 0:
            raise ValueError("line and column must be non-negative")
        row_index = 0
        while True:
            self.ensure_row(row_index)
            if row_index >= len(self._rows):
                raise ValueError("position is beyond end of document")
            row = self._rows[row_index]
            if row.line == line:
                row_end = row.column_start + row.length
                if row.length == 0 or column < row_end:
                    return row_index
                if column == row_end:
                    if row.length < self.columns:
                        return row_index
                    self.ensure_row(row_index + 1)
                    if (
                        row_index + 1 >= len(self._rows)
                        or self._rows[row_index + 1].line != line
                    ):
                        return row_index
            elif row.line > line:
                raise ValueError("position is beyond logical line end")
            row_index += 1
