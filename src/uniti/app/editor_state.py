"""Qt-independent cursor, selection, and editing state."""

from __future__ import annotations

from dataclasses import dataclass

from uniti.core.bidi import is_rtl_paragraph
from uniti.core.document import Document
from uniti.core.unicode_hex import LOOKBACK_WINDOW, hex_notation, hex_run_before_cursor
from uniti.app.graphemes import neighbor_boundary, deletion_span

# BF-064: bounded enough to reliably reach a paragraph's first strong
# character (see `uniti.core.bidi`) without reading an entire huge line
# just to decide arrow-key direction.
_DIRECTION_PROBE_CHARS = 256


@dataclass(frozen=True, slots=True)
class EditorStateSnapshot:
    cursor: int
    anchor: int
    preferred_column: int | None

    def __post_init__(self) -> None:
        if type(self.cursor) is not int or type(self.anchor) is not int:
            raise TypeError("cursor and anchor must be integers")
        if self.preferred_column is not None and (
            type(self.preferred_column) is not int or self.preferred_column < 0
        ):
            raise ValueError("preferred column must be a non-negative integer or None")


@dataclass(slots=True)
class EditorState:
    document: Document
    cursor: int = 0
    anchor: int = 0
    _preferred_column: int | None = None

    def export_state(self) -> EditorStateSnapshot:
        return EditorStateSnapshot(
            self.cursor,
            self.anchor,
            self._preferred_column,
        )

    def restore_state(self, snapshot: EditorStateSnapshot) -> None:
        if not isinstance(snapshot, EditorStateSnapshot):
            raise TypeError("snapshot must be an EditorStateSnapshot")
        total = self.document.total_chars()
        self.cursor = max(0, min(total, snapshot.cursor))
        self.anchor = max(0, min(total, snapshot.anchor))
        self._preferred_column = snapshot.preferred_column
        self.document.break_history_coalescing()

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

    def _set_cursor(
        self, offset: int, *, selecting: bool, vertical: bool = False
    ) -> None:
        self.document.break_history_coalescing()
        offset = self._validate_position(offset)
        if not selecting:
            self.anchor = offset
        self.cursor = offset
        if not vertical:
            self._preferred_column = None

    def move_to(self, offset: int, *, selecting: bool = False) -> None:
        self._set_cursor(offset, selecting=selecting)

    def move_left(self, *, selecting: bool = False) -> None:
        result = neighbor_boundary(self.document, self.cursor, -1)
        if result.complete:
            self._set_cursor(result.position, selecting=selecting)

    def move_right(self, *, selecting: bool = False) -> None:
        result = neighbor_boundary(self.document, self.cursor, 1)
        if result.complete:
            self._set_cursor(result.position, selecting=selecting)

    @staticmethod
    def _is_word_character(character: str) -> bool:
        return character == "_" or character.isalnum()

    def _character_before(self, offset: int) -> str | None:
        if offset <= 0:
            return None
        return self.document.read(offset - 1, offset)

    def _character_at(self, offset: int) -> str | None:
        try:
            return self.document.read(offset, offset + 1)
        except ValueError:
            return None

    def move_word_left(self, *, selecting: bool = False) -> None:
        target = self.cursor
        while target > 0:
            character = self._character_before(target)
            if character is not None and self._is_word_character(character):
                break
            target -= 1
        while target > 0:
            character = self._character_before(target)
            if character is None or not self._is_word_character(character):
                break
            target -= 1
        result = neighbor_boundary(self.document, target, 1, inclusive=True)
        if result.complete:
            self._set_cursor(result.position, selecting=selecting)

    def move_word_right(self, *, selecting: bool = False) -> None:
        target = self.cursor
        character = self._character_at(target)
        while character is not None and self._is_word_character(character):
            target += 1
            character = self._character_at(target)
        while character is not None and not self._is_word_character(character):
            target += 1
            character = self._character_at(target)
        result = neighbor_boundary(self.document, target, 1, inclusive=True)
        if result.complete:
            self._set_cursor(result.position, selecting=selecting)

    def _cursor_line_is_rtl(self, *, direction_override: bool | None = None) -> bool:
        """BF-064: whether the cursor's logical line reads right-to-left,
        by the same paragraph-level (first-strong-character) rule used to
        render it — see `uniti.core.bidi.is_rtl_paragraph`.

        This is deliberately paragraph-level, not per-character bidi
        embedding level: within a predominantly-RTL line's embedded
        left-to-right run (e.g. an English term inside Arabic text), arrow
        keys will use the paragraph's direction rather than that run's own
        — a known, documented limitation. Full embedding-level-aware caret
        affinity is a materially larger, separately-scoped effort (the
        "caret affinity" problem flagged in BF-043/BF-064's plan).

        `direction_override`, when not None, bypasses detection entirely —
        the "primary direction" switch: the first-strong-character rule
        alone misjudges a predominantly-RTL paragraph that happens to
        *start* with a Western character (a verse number's LTR text, an
        abbreviation), classifying the whole line LTR. The caller (the
        view, which owns the per-view override) is responsible for
        passing it; this class stays Qt-free and has no view of its own.
        """

        if direction_override is not None:
            return direction_override
        line = self.document.line_for_char(self.cursor)
        line_start = self.document.line_start(line)
        line_end = self.document.line_end(line)
        probe_end = min(line_start + _DIRECTION_PROBE_CHARS, line_end)
        text = self.document.read(line_start, probe_end) if probe_end > line_start else ""
        return is_rtl_paragraph(text)

    def move_visual_left(
        self, *, selecting: bool = False, direction_override: bool | None = None
    ) -> None:
        """Move toward the visual left edge — logically backward in a
        left-to-right line, logically forward in a right-to-left one."""

        if self._cursor_line_is_rtl(direction_override=direction_override):
            self.move_right(selecting=selecting)
        else:
            self.move_left(selecting=selecting)

    def move_visual_right(
        self, *, selecting: bool = False, direction_override: bool | None = None
    ) -> None:
        """Move toward the visual right edge — the mirror of `move_visual_left`."""

        if self._cursor_line_is_rtl(direction_override=direction_override):
            self.move_left(selecting=selecting)
        else:
            self.move_right(selecting=selecting)

    def move_visual_word_left(
        self, *, selecting: bool = False, direction_override: bool | None = None
    ) -> None:
        """Word-wise counterpart to `move_visual_left` (Ctrl/Cmd+Left)."""

        if self._cursor_line_is_rtl(direction_override=direction_override):
            self.move_word_right(selecting=selecting)
        else:
            self.move_word_left(selecting=selecting)

    def move_visual_word_right(
        self, *, selecting: bool = False, direction_override: bool | None = None
    ) -> None:
        """Word-wise counterpart to `move_visual_right` (Ctrl/Cmd+Right)."""

        if self._cursor_line_is_rtl(direction_override=direction_override):
            self.move_word_left(selecting=selecting)
        else:
            self.move_word_right(selecting=selecting)

    def _column(self) -> int:
        line = self.document.line_for_char(self.cursor)
        start = self.document.line_start(line)
        end = self.document.line_end(line)
        return min(self.cursor - start, end - start)

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
            end = self.document.line_end(target_line)
        except ValueError:
            return
        target = start + min(self._preferred_column, end - start)
        result = neighbor_boundary(self.document, target, 1, inclusive=True)
        if result.complete:
            self._set_cursor(result.position, selecting=selecting, vertical=True)

    def move_up(self, *, selecting: bool = False) -> None:
        self._move_vertical(-1, selecting=selecting)

    def move_down(self, *, selecting: bool = False) -> None:
        self._move_vertical(1, selecting=selecting)

    def move_page(self, line_delta: int, *, selecting: bool = False) -> None:
        if line_delta == 0:
            return
        direction = 1 if line_delta > 0 else -1
        for _ in range(abs(line_delta)):
            previous = self.cursor
            self._move_vertical(direction, selecting=selecting)
            if self.cursor == previous:
                break

    def move_document_start(self, *, selecting: bool = False) -> None:
        self._set_cursor(0, selecting=selecting)

    def move_document_end(self, *, selecting: bool = False) -> None:
        self._set_cursor(self.document.total_chars(), selecting=selecting)

    def move_home(self, *, selecting: bool = False) -> None:
        line = self.document.line_for_char(self.cursor)
        self._set_cursor(self.document.line_start(line), selecting=selecting)

    def move_end(self, *, selecting: bool = False) -> None:
        line = self.document.line_for_char(self.cursor)
        self._set_cursor(self.document.line_end(line), selecting=selecting)

    def select_all(self) -> None:
        self.document.break_history_coalescing()
        self.anchor = 0
        self.cursor = self.document.total_chars()
        self._preferred_column = None

    def _replace_selection(self, text: str, *, coalesce: str | None = None) -> None:
        selection = self.selection
        if selection is None:
            self.document.insert(self.cursor, text, coalesce=coalesce)
            self.cursor += len(text)
        else:
            start, end = selection
            self.document.replace(start, end, text)
            self.cursor = start + len(text)
        self.anchor = self.cursor
        self._preferred_column = None

    def insert_text(self, text: str) -> None:
        if text:
            coalesce = (
                "typing"
                if self.selection is None
                and len(text) == 1
                and text not in {"\t", "\r", "\n"}
                else None
            )
            self._replace_selection(text, coalesce=coalesce)

    def selected_text(self) -> str:
        selection = self.selection
        if selection is None:
            return ""
        start, end = selection
        return self.document.read(start, end)

    def cut_selection(self) -> str:
        text = self.selected_text()
        if text:
            self._replace_selection("")
        return text

    def paste_text(self, text: str) -> None:
        if text:
            self._replace_selection(text)

    def ime_surrounding_text(self, *, radius: int = 2048) -> tuple[str, int, int]:
        if radius <= 0:
            raise ValueError("radius must be positive")
        start = max(0, self.cursor - radius)
        before = self.document.read(start, self.cursor)
        after = ""
        iterator = self.document.iter_text(self.cursor, chunk_chars=radius)
        try:
            _, after = next(iterator)
        except StopIteration:
            pass
        after = after[:radius]
        text = before + after
        cursor_relative = len(before)
        anchor_relative = self.anchor - start
        if anchor_relative < 0 or anchor_relative > len(text):
            anchor_relative = cursor_relative
        return text, cursor_relative, anchor_relative

    def insert_newline(self) -> None:
        eol = self.document.insertion_eol
        self._replace_selection({"LF": "\n", "CRLF": "\r\n", "CR": "\r"}[eol])

    def backspace(self) -> None:
        selection = self.selection
        if selection is not None:
            start, end = selection
            self.document.delete(start, end)
            self.cursor = start
            self.anchor = start
        elif self.cursor > 0:
            span = deletion_span(self.document, self.cursor, -1)
            if span is None:
                return
            self.document.delete(*span, coalesce="backspace")
            self.cursor = span[0]
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
            span = deletion_span(self.document, self.cursor, 1)
            if span is None or span[0] == span[1]:
                return
            self.document.delete(*span, coalesce="delete_forward")
            self.cursor = self.anchor = span[0]
        self._preferred_column = None

    def toggle_unicode_hex(self) -> bool:
        """BF-053: convert a hex codepoint run just before the cursor into
        its character (mirrors Microsoft Word's Alt+X), or reverse a single
        character back into `U+XXXX` hex notation when no valid hex run
        precedes the cursor. A no-op (returns False) with an active
        selection, at the document start, or when the preceding text is an
        out-of-range/surrogate hex value. Always one undoable edit."""

        if self.selection is not None or self.cursor == 0:
            return False
        window_start = max(0, self.cursor - LOOKBACK_WINDOW)
        text_before = self.document.read(window_start, self.cursor)
        match = hex_run_before_cursor(text_before)
        if match is not None:
            run_length, code_point = match
            replacement = chr(code_point)
            start = self.cursor - run_length
        else:
            replacement = hex_notation(self.document.read(self.cursor - 1, self.cursor))
            start = self.cursor - 1
        self.document.replace(start, self.cursor, replacement)
        self.cursor = start + len(replacement)
        self.anchor = self.cursor
        self._preferred_column = None
        return True

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
