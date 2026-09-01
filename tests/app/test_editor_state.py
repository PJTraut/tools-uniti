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


def test_insert_newline_uses_crlf_source_policy(tmp_path: Path):
    path = tmp_path / "crlf.txt"
    path.write_bytes(b"a\r\nb\r\n")
    document = Document.open(path)
    try:
        state = EditorState(document)
        state.move_to(1)
        state.insert_newline()
        assert document.read(0, 4) == "a\r\n\r"
        assert document.insertion_eol == "CRLF"
    finally:
        document.close()


def test_insert_newline_uses_cr_source_policy(tmp_path: Path):
    path = tmp_path / "cr.txt"
    path.write_bytes(b"a\rb\r")
    document = Document.open(path)
    try:
        state = EditorState(document)
        state.move_to(1)
        state.insert_newline()
        assert document.read(0, 3) == "a\r\r"
        assert document.insertion_eol == "CR"
    finally:
        document.close()


def test_insert_newline_uses_dominant_mixed_source_policy(tmp_path: Path):
    path = tmp_path / "mixed.txt"
    path.write_bytes(b"a\r\nb\r\nc\nd\r\n")
    document = Document.open(path)
    try:
        state = EditorState(document)
        state.move_to(1)
        state.insert_newline()
        assert document.insertion_eol == "CRLF"
        assert document.read(0, 3) == "a\r\n"
    finally:
        document.close()


def test_explicit_insertion_eol_is_independent_of_output_conversion(tmp_path: Path):
    path = tmp_path / "policy.txt"
    path.write_bytes(b"a\r\nb\r\n")
    document = Document.open(path)
    try:
        document.set_output_eol("LF")
        document.set_insertion_eol("CR")
        state = EditorState(document)
        state.move_to(1)
        state.insert_newline()
        assert document.output_eol == "LF"
        assert document.insertion_eol == "CR"
        assert document.read(0, 3) == "a\r\r"
    finally:
        document.close()


def test_clipboard_state_copy_cut_and_paste_use_document_mutations(tmp_path: Path):
    with _open(tmp_path, "abcédef") as document:
        state = EditorState(document)
        state.move_to(3)
        state.move_to(5, selecting=True)
        assert state.selected_text() == "éd"
        assert state.cut_selection() == "éd"
        assert document.read(0, document.total_chars()) == "abcef"
        state.paste_text("漢字")
        assert document.read(0, document.total_chars()) == "abc漢字ef"


def test_ime_surrounding_text_is_bounded_and_uses_relative_cursor_anchor(tmp_path: Path):
    with _open(tmp_path, "0123456789") as document:
        state = EditorState(document)
        state.move_to(3)
        state.move_to(5, selecting=True)
        text, cursor, anchor = state.ime_surrounding_text(radius=3)
        assert text == "234567"
        assert cursor == 3
        assert anchor == 1


def test_word_navigation_handles_western_and_cyrillic_words(tmp_path: Path):
    with _open(tmp_path, "one два three") as document:
        state = EditorState(document, cursor=13, anchor=13)

        state.move_word_left()
        assert state.cursor == 8
        state.move_word_left(selecting=True)
        assert state.selection == (4, 8)
        state.move_word_right()
        assert state.cursor == 8


def test_document_and_page_navigation_extend_selection(tmp_path: Path):
    with _open(tmp_path, "zero\none\ntwo\nthree\nfour") as document:
        state = EditorState(document)

        state.move_page(3)
        assert state.cursor == document.line_start(3)
        state.move_document_end(selecting=True)
        assert state.selection == (document.line_start(3), document.total_chars())
        state.move_document_start()
        assert state.cursor == 0
        assert state.selection is None


def test_adjacent_typing_is_one_undo_step(tmp_path: Path):
    with _open(tmp_path, "") as document:
        state = EditorState(document)

        for character in "word":
            state.insert_text(character)
        state.undo()

        assert document.read(0, document.total_chars()) == ""
        assert document.can_undo is False


def test_cursor_movement_breaks_typing_undo_coalescing(tmp_path: Path):
    with _open(tmp_path, "") as document:
        state = EditorState(document)
        state.insert_text("a")
        state.insert_text("b")
        state.move_left()
        state.move_right()
        state.insert_text("c")

        state.undo()
        assert document.read(0, document.total_chars()) == "ab"
        state.undo()

        assert document.read(0, document.total_chars()) == ""


def test_save_breaks_typing_undo_coalescing(tmp_path: Path):
    with _open(tmp_path, "") as document:
        state = EditorState(document)
        state.insert_text("a")
        state.insert_text("b")
        document.save()
        state.insert_text("c")
        state.insert_text("d")

        state.undo()

        assert document.read(0, document.total_chars()) == "ab"
        assert document.modified is False


def test_repeated_backspace_is_one_undo_step(tmp_path: Path):
    with _open(tmp_path, "abcd") as document:
        state = EditorState(document, cursor=4, anchor=4)

        state.backspace()
        state.backspace()
        assert document.read(0, document.total_chars()) == "ab"
        state.undo()

        assert document.read(0, document.total_chars()) == "abcd"


def test_repeated_forward_delete_is_one_undo_step(tmp_path: Path):
    with _open(tmp_path, "abcd") as document:
        state = EditorState(document)

        state.delete_forward()
        state.delete_forward()
        assert document.read(0, document.total_chars()) == "cd"
        state.undo()

        assert document.read(0, document.total_chars()) == "abcd"
