from pathlib import Path

from uniti.app.editor_state import EditorState
from uniti.core.document import Document


def _open(tmp_path: Path, text: str) -> Document:
    path = tmp_path / "editor.txt"
    path.write_text(text, encoding="utf-8")
    return Document.open(path, encoding="utf-8")


def test_insert_replaces_selection_and_updates_cursor(tmp_path: Path):
    with _open(tmp_path, "abcdef") as document:
        state = EditorState(document)
        state.move_to(2)
        state.move_to(5, selecting=True)
        assert state.selection == (2, 5)
        state.insert_text("XY")
        assert document.read(0, document.total_chars()) == "abXYf"
        assert state.cursor == 4
        assert state.selection is None


def test_unicode_movement_is_character_based(tmp_path: Path):
    with _open(tmp_path, "Aé😀Z") as document:
        state = EditorState(document)
        state.move_right()
        state.move_right()
        state.move_right()
        assert state.cursor == 3
        state.move_left()
        assert state.cursor == 2
        assert document.read(state.cursor, state.cursor + 1) == "😀"


def test_backspace_delete_and_select_all(tmp_path: Path):
    with _open(tmp_path, "abcd") as document:
        state = EditorState(document)
        state.move_to(2)
        state.backspace()
        assert document.read(0, document.total_chars()) == "acd"
        assert state.cursor == 1
        state.delete_forward()
        assert document.read(0, document.total_chars()) == "ad"
        state.select_all()
        assert state.selection == (0, 2)
        state.insert_text("x")
        assert document.read(0, document.total_chars()) == "x"


def test_vertical_navigation_handles_crlf_and_preserves_column(tmp_path: Path):
    with _open(tmp_path, "ab\r\ncdef\nz") as document:
        state = EditorState(document)
        state.move_to(1)
        state.move_down()
        assert state.cursor == 5
        state.move_down()
        assert state.cursor == 10
        state.move_up()
        assert state.cursor == 5
        state.move_home()
        assert state.cursor == 4
        state.move_end()
        assert state.cursor == 8


def test_undo_redo_passthrough_keeps_cursor_valid(tmp_path: Path):
    with _open(tmp_path, "abc") as document:
        state = EditorState(document)
        state.move_to(3)
        state.insert_text("d")
        assert state.cursor == 4
        state.undo()
        assert document.read(0, document.total_chars()) == "abc"
        assert state.cursor == 3
        state.redo()
        assert document.read(0, document.total_chars()) == "abcd"
        assert state.cursor == 3


def test_early_cursor_movement_does_not_measure_entire_large_document(tmp_path: Path):
    path = tmp_path / "large.txt"
    path.write_bytes((b"0123456789\n" * 50_000))
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        state.move_right()
        state.move_down()
        assert state.cursor == 12
        assert not document.offset_mapper.complete


def test_move_end_on_giant_line_avoids_full_line_materialization(tmp_path: Path):
    import time

    path = tmp_path / "giant-line.txt"
    path.write_bytes(b"x" * (16 * 1024 * 1024))
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        started = time.perf_counter()
        state.move_end()
        elapsed = time.perf_counter() - started
        assert state.cursor == 16 * 1024 * 1024
        assert elapsed < 8.0


def test_vertical_movement_uses_line_length_without_reading_whole_line(tmp_path: Path):
    path = tmp_path / "vertical.txt"
    path.write_text("abcdef\nxy\n123456", encoding="utf-8")
    with Document.open(path) as document:
        state = EditorState(document)
        state.move_to(5)
        state.move_down()
        assert state.cursor == document.line_start(1) + 2
        state.move_down()
        assert state.cursor == document.line_start(2) + 5
