"""Bounded progressive visual-row indexing for soft-wrapped text."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WrappedRow:
    line: int
    column_start: int
    length: int


@dataclass(frozen=True, slots=True)
class WrapCheckpoint:
    line: int
    row: int


@dataclass(frozen=True, slots=True)
class WrappedRowBlock:
    block_index: int
    first_row: int
    rows: tuple[WrappedRow, ...]


class WrappedRowIndex:
    """Map visual rows lazily while retaining only a few row-detail blocks."""

    def __init__(
        self,
        document,
        columns: int,
        *,
        row_block_size: int = 512,
        max_blocks: int = 4,
        checkpoint_lines: int = 256,
        row_provider=None,
    ) -> None:
        if columns <= 0:
            raise ValueError("columns must be positive")
        if row_block_size <= 0:
            raise ValueError("row_block_size must be positive")
        if max_blocks <= 0:
            raise ValueError("max_blocks must be positive")
        if checkpoint_lines <= 0:
            raise ValueError("checkpoint_lines must be positive")
        self._document = document
        self._row_provider = row_provider
        self._block_positions = {0: (0, 0)}
        self._rebuild_resume = {}
        self.columns = columns
        self._row_block_size = row_block_size
        self._max_blocks = max_blocks
        self._checkpoint_lines = checkpoint_lines
        self._blocks: OrderedDict[int, WrappedRowBlock] = OrderedDict()
        self._checkpoints: list[WrapCheckpoint] = [WrapCheckpoint(0, 0)]
        self._next_line = 0
        self._next_column = 0
        self._known_count = 0
        self._complete = False

    @property
    def complete(self) -> bool:
        return self._complete

    @property
    def known_count(self) -> int:
        return self._known_count

    @property
    def resident_row_count(self) -> int:
        return sum(len(block.rows) for block in self._blocks.values())

    @property
    def checkpoints(self) -> tuple[WrapCheckpoint, ...]:
        return tuple(self._checkpoints)

    def _store_row(self, row_index: int, row: WrappedRow) -> None:
        block_index = row_index // self._row_block_size
        first_row = block_index * self._row_block_size
        block = self._blocks.pop(block_index, None)
        rows = [] if block is None else list(block.rows)
        local = row_index - first_row
        if local == len(rows):
            rows.append(row)
        elif local < len(rows):
            rows[local] = row
        else:
            raise RuntimeError("wrapped row block was built discontinuously")
        self._blocks[block_index] = WrappedRowBlock(
            block_index,
            first_row,
            tuple(rows),
        )
        while len(self._blocks) > self._max_blocks:
            self._blocks.popitem(last=False)

    def _cached_row(self, row_index: int) -> WrappedRow | None:
        block_index = row_index // self._row_block_size
        block = self._blocks.get(block_index)
        if block is None:
            return None
        local = row_index - block.first_row
        if local >= len(block.rows):
            return None
        self._blocks.move_to_end(block_index)
        return block.rows[local]

    def _remember_checkpoint(self, line: int, row: int) -> None:
        if line % self._checkpoint_lines:
            return
        checkpoint = WrapCheckpoint(line, row)
        if checkpoint != self._checkpoints[-1]:
            self._checkpoints.append(checkpoint)

    def _next_row(self) -> WrappedRow | None:
        while not self._complete:
            try:
                self._document.line_start(self._next_line)
            except ValueError:
                self._complete = True
                return None
            if self._next_column == 0:
                self._remember_checkpoint(self._next_line, self._known_count)
            if self._row_provider is not None:
                length, final = self._row_provider(self._next_line, self._next_column)
                if length or self._next_column == 0:
                    row = WrappedRow(self._next_line, self._next_column, length)
                    if final:
                        self._next_line += 1
                        self._next_column = 0
                    else:
                        self._next_column += length
                    return row
                self._next_line += 1
                self._next_column = 0
                continue
            text = self._document.read_line_window(
                self._next_line,
                column_start=self._next_column,
                max_chars=self.columns,
            )
            if text:
                row = WrappedRow(self._next_line, self._next_column, len(text))
                if len(text) < self.columns:
                    self._next_line += 1
                    self._next_column = 0
                else:
                    self._next_column += len(text)
                return row
            if self._next_column == 0:
                row = WrappedRow(self._next_line, 0, 0)
                self._next_line += 1
                return row
            self._next_line += 1
            self._next_column = 0
        return None

    def _append_next(self) -> None:
        if self._known_count % self._row_block_size == 0:
            self._block_positions[self._known_count // self._row_block_size] = (
                self._next_line,
                self._next_column,
            )
        row = self._next_row()
        if row is None:
            return
        self._store_row(self._known_count, row)
        self._known_count += 1

    def _rebuild_block(self, block_index: int) -> None:
        first = block_index * self._row_block_size
        stop = min(self._known_count, first + self._row_block_size)
        line, column = self._block_positions.get(block_index, (0, 0))
        row_index = first if block_index in self._block_positions else 0
        existing = self._blocks.get(block_index)
        rows = list(existing.rows) if existing is not None else []
        if rows and block_index in self._rebuild_resume:
            line, column, row_index = self._rebuild_resume[block_index]
        else:
            rows = []
        while row_index < stop:
            try:
                self._document.line_start(line)
            except ValueError:
                break
            if self._row_provider is not None:
                try:
                    length, final = self._row_provider(line, column)
                except ValueError:
                    break
                row = WrappedRow(line, column, length)
                if final:
                    line += 1
                    column = 0
                else:
                    column += length
            else:
                text = self._document.read_line_window(
                    line,
                    column_start=column,
                    max_chars=self.columns,
                )
                if text:
                    row = WrappedRow(line, column, len(text))
                    if len(text) < self.columns:
                        line += 1
                        column = 0
                    else:
                        column += len(text)
                elif column == 0:
                    row = WrappedRow(line, 0, 0)
                    line += 1
                else:
                    line += 1
                    column = 0
                    continue
            if row_index >= first:
                rows.append(row)
            row_index += 1
        self._rebuild_resume[block_index] = (line, column, row_index)
        self._blocks[block_index] = WrappedRowBlock(block_index, first, tuple(rows))
        self._blocks.move_to_end(block_index)
        while len(self._blocks) > self._max_blocks:
            self._blocks.popitem(last=False)

    def ensure_row(self, row_index: int) -> None:
        if row_index < 0:
            raise ValueError("row_index must be non-negative")
        if self._row_provider is not None:
            self._row_provider.read_chars = 0
        work = 0
        while row_index >= self._known_count and not self._complete:
            if self._row_provider is not None and work >= 512:
                break
            try:
                self._append_next()
            except ValueError:
                break
            work += 1
        if row_index < self._known_count and self._cached_row(row_index) is None:
            try:
                self._rebuild_block(row_index // self._row_block_size)
            except ValueError:
                pass

    def row(self, row_index: int) -> WrappedRow:
        self.ensure_row(row_index)
        result = self._cached_row(row_index)
        if result is None:
            raise ValueError("visual row is beyond end of document")
        return result

    def _line_row_count(self, line: int) -> int:
        start = self._document.line_start(line)
        end = self._document.line_end(line)
        length = max(0, end - start)
        return max(1, (length + self.columns - 1) // self.columns)

    def _row_start_for_line(self, line: int) -> int:
        checkpoint = self._checkpoints[0]
        for candidate in self._checkpoints:
            if candidate.line > line:
                break
            checkpoint = candidate
        row = checkpoint.row
        for current in range(checkpoint.line, line):
            row += self._line_row_count(current)
        return row

    def row_for_position(self, line: int, column: int) -> int:
        if line < 0 or column < 0:
            raise ValueError("line and column must be non-negative")
        if self._row_provider is not None:
            target = (line, column)
            if (self._next_line, self._next_column) <= target and not self._complete:
                self.ensure_row(self._known_count + 511)
            if (self._next_line, self._next_column) <= target and not self._complete:
                raise ValueError("shaped position pending")
            candidates = [
                (block, position)
                for block, position in self._block_positions.items()
                if position <= target
            ]
            block = candidates[-1][0] if candidates else 0
            first = block * self._row_block_size
            self.ensure_row(
                min(self._known_count - 1, first + self._row_block_size - 1)
            )
            last = None
            for row_index in range(
                first, min(self._known_count, first + self._row_block_size)
            ):
                row = self._cached_row(row_index)
                if row is None:
                    raise ValueError("shaped position pending")
                if (row.line, row.column_start) > target:
                    break
                last = row_index
            if last is None:
                raise ValueError("position beyond document")
            return last
        start = self._document.line_start(line)
        if column == 0:
            local_row = 0
        else:
            probe = self._document.read_line_window(
                line,
                column_start=column,
                max_chars=1,
            )
            if probe:
                local_row = column // self.columns
            else:
                end = self._document.line_end(line)
                length = max(0, end - start)
                if column > length:
                    raise ValueError("position is beyond logical line end")
                local_row = min(
                    column // self.columns,
                    max(0, self._line_row_count(line) - 1),
                )
        return self._row_start_for_line(line) + local_row
