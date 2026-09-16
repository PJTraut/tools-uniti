from pathlib import Path

import pytest

from uniti.app.editor_state import EditorState, EditorStateSnapshot
from uniti.core.document import Document


def _open(tmp_path: Path, text: str) -> Document:
    path = tmp_path / "editor.txt"
    path.write_text(text, encoding="utf-8", newline="")
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
    path.write_text("abcdef\nxy\n123456", encoding="utf-8", newline="")
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


def test_editor_state_snapshot_exports_the_vertical_preferred_column(
    tmp_path: Path,
):
    with _open(tmp_path, "abcd\nx\nwxyz") as document:
        state = EditorState(document)
        state.move_to(3)
        state.move_down()

        assert state.export_state() == EditorStateSnapshot(6, 6, 3)


def test_editor_state_restore_clamps_positions_to_the_exact_document(
    tmp_path: Path,
):
    with _open(tmp_path, "abc") as document:
        state = EditorState(document)

        state.restore_state(EditorStateSnapshot(20, 2, 7))

        assert state.cursor == 3
        assert state.anchor == 2
        assert state.export_state().preferred_column == 7


def test_editor_state_snapshot_rejects_a_negative_preferred_column():
    with pytest.raises(ValueError, match="preferred column"):
        EditorStateSnapshot(0, 0, -1)


def test_editor_state_restore_breaks_typing_coalescing(tmp_path: Path):
    with _open(tmp_path, "") as document:
        state = EditorState(document)
        state.insert_text("a")

        state.restore_state(state.export_state())
        state.insert_text("b")
        state.undo()

        assert document.read(0, document.total_chars()) == "a"


def test_visual_left_right_move_logically_forward_on_an_rtl_line(tmp_path: Path):
    """BF-064: on a right-to-left line, the physical Left/Right arrow keys
    must move toward the visual edge they're labeled for, which is the
    opposite logical direction from a left-to-right line."""

    # Logical position 0 sits at the *visual right* edge of an RTL line
    # (reading starts there); higher logical positions sit further left.
    arabic = "مرحبا"  # "مرحبا", 5 characters
    with _open(tmp_path, arabic) as document:
        state = EditorState(document, cursor=3, anchor=3)

        # Visual-right moves toward smaller logical positions (toward the
        # line's start) — the mirror of an LTR line, where visual-right
        # moves toward *larger* logical positions.
        state.move_visual_right()
        assert state.cursor == 2
        state.move_visual_right()
        assert state.cursor == 1

        # Visual-left then moves back the other way (logically forward).
        state.move_visual_left()
        assert state.cursor == 2


def test_visual_left_right_match_plain_left_right_on_an_ltr_line(tmp_path: Path):
    with _open(tmp_path, "hello") as document:
        state = EditorState(document, cursor=2, anchor=2)

        state.move_visual_right()
        assert state.cursor == 3
        state.move_visual_left()
        assert state.cursor == 2
        state.move_visual_left()
        assert state.cursor == 1


def test_visual_movement_extends_selection_when_selecting(tmp_path: Path):
    arabic = "مرحبا"
    with _open(tmp_path, arabic) as document:
        state = EditorState(document, cursor=2, anchor=2)
        # Visual-right on this RTL line moves the cursor logically backward.
        state.move_visual_right(selecting=True)
        assert state.selection == (1, 2)
        assert state.cursor == 1


def test_visual_word_movement_is_direction_aware_on_an_rtl_line(tmp_path: Path):
    arabic_words = "مرحبا بك"  # two words, 8 characters total
    with _open(tmp_path, arabic_words) as document:
        state = EditorState(document, cursor=len(arabic_words), anchor=len(arabic_words))

        # Visual-word-right on an RTL line moves toward the line's start —
        # logically backward, matching ordinary (logical) word-left.
        state.move_visual_word_right()
        backward_cursor = state.cursor
        assert 0 < backward_cursor < len(arabic_words)

        # Visual-word-left then moves the other way, back to the end.
        state.move_visual_word_left()
        assert state.cursor == len(arabic_words)

    with _open(tmp_path, arabic_words) as document:
        reference_state = EditorState(
            document, cursor=len(arabic_words), anchor=len(arabic_words)
        )
        reference_state.move_word_left()
        assert reference_state.cursor == backward_cursor


def test_visual_word_movement_matches_plain_word_movement_on_an_ltr_line(
    tmp_path: Path,
):
    with _open(tmp_path, "one two three") as document:
        state = EditorState(document, cursor=0, anchor=0)
        state.move_visual_word_right()
        assert state.cursor == 4
        state.move_visual_word_right()
        assert state.cursor == 8
        state.move_visual_word_left()
        assert state.cursor == 4


def test_visual_movement_known_limitation_uses_paragraph_direction_not_local_run(
    tmp_path: Path,
):
    """Characterizes a known, deliberately scoped limitation of the
    Qt-free `EditorState` API specifically: with no layout access here,
    visual movement can only use the cursor's *paragraph* direction, not
    the bidi embedding level at its exact position. Inside an embedded
    left-to-right run within a right-to-left paragraph, this means
    visual-right still moves logically *backward* (matching the
    paragraph) rather than forward (matching the local run).

    The real editing path no longer has this limitation:
    `UNITITextView._move_visual_char` (BF-064) uses the cursor line's
    actual shaped pixel positions to resolve this correctly for arbitrary
    embedding depth — see
    `test_visual_right_moves_forward_inside_an_embedded_ltr_run` in
    `tests/ui/test_text_view_contract.py`. This test still locks in the
    Qt-free fallback's own behavior (used at a line's own start/end and
    for lines too long to shape, where the view falls back to exactly
    this method) so a future change to *it* is a deliberate, visible
    decision, not a silent regression in either direction."""

    arabic_prefix = "مرحبا "  # "مرحبا " — RTL paragraph start
    text = arabic_prefix + "hello"
    with _open(tmp_path, text) as document:
        inside_hello = len(arabic_prefix) + 2  # cursor inside the embedded "hello"
        state = EditorState(document, cursor=inside_hello, anchor=inside_hello)

        state.move_visual_right()

        # Known-limited: moves backward (paragraph is RTL), not forward
        # (which the local "hello" run's own direction would suggest).
        assert state.cursor == inside_hello - 1
