"""Progressive logical line indexing for the edited UNITI document."""

from __future__ import annotations

from array import array
from bisect import bisect_right

from .pieces import PieceTable


class DocumentLineIndex:
    """Index edited-document line starts as 64-bit Unicode character offsets."""

    def __init__(self, piece_table: PieceTable, *, chunk_chars: int = 65_536) -> None:
        if chunk_chars <= 0:
            raise ValueError("chunk_chars must be positive")
        self._piece_table = piece_table
        self._chunk_chars = chunk_chars
        self._starts = array("Q", [0])
        self._indexed_char_end = 0
        self._complete = False
        self._pending_cr_end: int | None = None

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def indexed_char_end(self) -> int:
        return self._indexed_char_end

    @property
    def indexed_line_count(self) -> int:
        return len(self._starts)

    def _append_start(self, char_offset: int) -> None:
        if self._starts[-1] != char_offset:
            self._starts.append(char_offset)

    def _consume(self, start: int, text: str) -> None:
        for index, char in enumerate(text):
            char_end = start + index + 1
            if self._pending_cr_end is not None:
                if char == "\n":
                    self._append_start(char_end)
                    self._pending_cr_end = None
                    continue
                self._append_start(self._pending_cr_end)
                self._pending_cr_end = None

            if char == "\r":
                self._pending_cr_end = char_end
            elif char == "\n":
                self._append_start(char_end)

    def _finish(self) -> None:
        if self._pending_cr_end is not None:
            self._append_start(self._pending_cr_end)
            self._pending_cr_end = None
        self._complete = True

    def _advance(self) -> None:
        if self._complete:
            return
        iterator = self._piece_table.iter_text(
            self._indexed_char_end,
            chunk_chars=self._chunk_chars,
        )
        try:
            start, text = next(iterator)
        except StopIteration:
            self._finish()
            return
        if start != self._indexed_char_end:
            raise RuntimeError("piece-table iterator returned a discontinuous range")
        self._consume(start, text)
        self._indexed_char_end = start + len(text)
        if len(text) < self._chunk_chars:
            self._finish()

    def ensure_char(self, char_offset: int) -> None:
        if char_offset < 0:
            raise ValueError("character offset must be non-negative")
        while char_offset > self._indexed_char_end and not self._complete:
            self._advance()
        if (
            char_offset == self._indexed_char_end
            and self._pending_cr_end == char_offset
            and not self._complete
        ):
            self._advance()
        if char_offset > self._indexed_char_end:
            raise ValueError("character offset is beyond end of document")

    def ensure_line(self, line_index: int) -> None:
        if line_index < 0:
            raise ValueError("line index must be non-negative")
        while line_index >= len(self._starts) and not self._complete:
            self._advance()
        if line_index >= len(self._starts):
            raise ValueError("line index is beyond end of document")

    def line_start(self, line_index: int) -> int:
        self.ensure_line(line_index)
        return int(self._starts[line_index])

    def line_for_char(self, char_offset: int) -> int:
        self.ensure_char(char_offset)
        return bisect_right(self._starts, char_offset) - 1

    def total_lines(self) -> int:
        while not self._complete:
            self._advance()
        return len(self._starts)

    def invalidate_from_char(self, char_offset: int) -> None:
        if char_offset < 0:
            raise ValueError("character offset must be non-negative")
        if char_offset > self._indexed_char_end:
            return
        if (
            char_offset == self._indexed_char_end
            and self._pending_cr_end is None
            and not self._complete
        ):
            return
        line_index = bisect_right(self._starts, char_offset) - 1
        restart = int(self._starts[line_index])
        self._starts = array("Q", self._starts[: line_index + 1])
        self._indexed_char_end = restart
        self._pending_cr_end = None
        self._complete = False
