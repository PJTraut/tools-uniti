"""The source editor narrowed to a window of lines (the USFM per-chapter
view, plan C2): scrolling, painting, keys and clicks stay in the window."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from uniti.app.editor_state import EditorState  # noqa: E402
from uniti.core.document import Document  # noqa: E402
from uniti.core.environments.sfm.references import chapter_window  # noqa: E402
from uniti.ui.text_view import UNITITextView  # noqa: E402

CHAPTER = 40  # lines per "chapter"
LINES = 120


@pytest.fixture
def view(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    path = tmp_path / "book.txt"
    path.write_text("".join(f"line {number}\n" for number in range(LINES)), encoding="utf-8", newline="")
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.resize(640, 300)
        view.line_window_provider = lambda shown: chapter_window(
            range(0, LINES, CHAPTER), shown.document.line_for_char(shown.state.cursor), shown.document.line_count()
        )
        view.show()
        app.processEvents()
        yield view
        view.close()
        view.dispose()


def _put_caret(view: UNITITextView, line: int, column: int = 0) -> None:
    view.state.move_to(view.document.line_start(line) + column)
    view._state_changed()


def _line(view: UNITITextView) -> int:
    return view.document.line_for_char(view.state.cursor)


def test_the_scroll_range_is_the_window(view):
    _put_caret(view, 50)
    bar = view.verticalScrollBar()
    assert view.line_window() == (40, 79)
    assert bar.minimum() == 40
    assert bar.maximum() == 80 - view._visible_whole_line_capacity()
    bar.setValue(0)
    assert bar.value() == 40


def test_keys_stay_in_the_window(view):
    _put_caret(view, 79, 3)
    QTest.keyClick(view, Qt.Key.Key_Down)
    assert _line(view) == 79
    _put_caret(view, 40, 2)
    QTest.keyClick(view, Qt.Key.Key_Up)
    assert view.state.cursor == view.document.line_start(40)
    QTest.keyClick(view, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    assert view.state.cursor == view.document.line_end(79)
    QTest.keyClick(view, Qt.Key.Key_PageDown)
    assert _line(view) == 79
    QTest.keyClick(view, Qt.Key.Key_A, Qt.KeyboardModifier.ControlModifier)
    assert view.state.selection == (view.document.line_start(40), view.document.line_end(79))


def test_backspace_and_delete_stop_at_the_edges_and_edits_keep_the_caret(view):
    _put_caret(view, 40)
    before = view.document.read(0, view.document.total_chars())
    QTest.keyClick(view, Qt.Key.Key_Backspace)
    view.state.move_to(view.document.line_end(79))
    QTest.keyClick(view, Qt.Key.Key_Delete)
    assert view.document.read(0, view.document.total_chars()) == before

    # Enter at the end of the last line: a new line, still in the window.
    QTest.keyClick(view, Qt.Key.Key_Return)
    assert _line(view) == 80


def test_a_click_below_the_last_line_lands_at_its_end(view):
    _put_caret(view, 79)
    view.verticalScrollBar().setValue(view.verticalScrollBar().maximum())
    QTest.mouseClick(view.viewport(), Qt.MouseButton.LeftButton, pos=QPoint(200, view.viewport().height() - 2))
    assert view.state.cursor == view.document.line_end(79)


def test_a_move_from_elsewhere_shows_the_new_window(view):
    _put_caret(view, 10)
    _put_caret(view, 100)  # as sync or Find would
    assert view.line_window() == (80, 120)  # with the empty line after the last newline
    bar = view.verticalScrollBar()
    assert bar.minimum() == 80 and bar.value() <= 100 < bar.value() + view._visible_line_capacity()


def test_select_all_selects_the_window_and_everything_without_one(view):
    _put_caret(view, 5)
    view.select_all()
    assert view.state.selection == (0, view.document.line_end(39))
    view.line_window_provider = None
    view.refresh_line_window()
    view.select_all()
    assert view.state.selection == (0, view.document.total_chars())
    assert view.verticalScrollBar().minimum() == 0


def test_wrapped_rows_are_limited_to_the_window(view):
    view.set_soft_wrap(True)
    _put_caret(view, 45)
    view._refresh_scrollbars(advance_index=False)
    bar = view.verticalScrollBar()
    index = view._wrapped_row_index()
    assert bar.minimum() == index.row_for_position(40, 0)
    assert bar.maximum() <= index.row_for_position(80, 0)
