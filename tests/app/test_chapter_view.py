"""Show One Chapter: the USFM per-chapter view, per environment window
(plan 2026-10-09, C4)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402

from usfm_project_fixture import in_project  # noqa: E402
from test_service import _desktop_service, _stop_desktop_service  # noqa: E402

from uniti.app.document_groups import DocumentGroup  # noqa: E402

# Lines: 0-2 the header, \c 1 on line 3, \c 2 on 7, \c 3 on 11, and an
# empty line 15 after the last line break.
_MARK = (
    "\\id MRK A\n\\h Mark\n\\mt1 Mark\n"
    "\\c 1\n\\p\n\\v 1 One one\\f + \\fr 1:1 \\ft Note one.\\f*\n\\v 2 One two.\n"
    "\\c 2\n\\p\n\\v 1 Two one\\f + \\fr 2:1 \\ft Note two.\\f*\n\\v 2 Two two.\n"
    "\\c 3\n\\p\n\\v 1 Three one.\n\\v 2 Three two.\n"
)
CHAPTER_1, CHAPTER_2, CHAPTER_3 = (0, 6), (7, 10), (11, 15)


@pytest.fixture
def desktop(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)


def _write(folder: Path, name: str, text: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = in_project(folder / name)
    path.write_text(text, encoding="utf-8", newline="\n")  # offsets below count LF, also on Windows
    return path


def _usfm_window(desktop, tmp_path: Path, folder: str = "a"):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path / folder, "41MRK.usfm", _MARK))
    window = main.move_to_environment_window(view)
    window.resize(1000, 600)
    window.show()
    app.processEvents()
    return window, view


def _caret(view, text: str, source: str = _MARK) -> None:
    """A move from outside the view, as the selector, sync and Find make."""

    view.state.move_to(source.index(text))
    view._state_changed()


def _shown_text(editor) -> str:
    document = editor.document()
    block, shown = document.begin(), []
    while block.isValid():
        if block.isVisible():
            shown.append(block.text())
        block = block.next()
    return "\n".join(shown)


def test_show_one_chapter_narrows_the_text_to_the_carets_chapter(desktop, tmp_path: Path):
    window, view = _usfm_window(desktop, tmp_path)
    toggle = window._chapter_view.action
    assert not toggle.isChecked() and view.line_window() is None
    # The toolbar's "Chapter" (beside the Chapter selector) is the toggle.
    button = window._environment_bar.chapter_toggle
    assert button.defaultAction() is toggle and button.text() == "Chapter"

    _caret(view, "Two two")
    toggle.trigger()

    assert view.line_window() == CHAPTER_2
    assert view.verticalScrollBar().minimum() == CHAPTER_2[0]
    _caret(view, "Mark")  # the header goes with chapter 1
    assert view.line_window() == CHAPTER_1

    toggle.trigger()
    assert view.line_window() is None and view.verticalScrollBar().minimum() == 0


def test_the_selector_go_to_and_find_change_the_chapter_and_keys_do_not(desktop, tmp_path: Path):
    window, view = _usfm_window(desktop, tmp_path)
    window._chapter_view.set_enabled(True)
    bar = window._environment_bar

    bar.chapter.setCurrentIndex(2)
    bar._chapter_chosen(2)
    assert view.line_window() == CHAPTER_3

    assert window._environment.run_command("go_to", "2:2") is True
    assert view.line_window() == CHAPTER_2

    # Arrow keys stop at the chapter's last line.
    QTest.keyClick(view, Qt.Key.Key_Down)
    QTest.keyClick(view, Qt.Key.Key_Down)
    assert view.line_window() == CHAPTER_2
    assert view.document.line_for_char(view.state.cursor) == CHAPTER_2[1]

    _caret(view, "One two")  # Find's next match (`find_replace._navigate_to`)
    assert view.line_window() == CHAPTER_1


def test_sync_moves_the_other_split_to_its_chapter(desktop, tmp_path: Path):
    window, left = _usfm_window(desktop, tmp_path)
    right = window.open_path(_write(tmp_path / "b", "41MRK.usfm", _MARK.replace("MRK A", "MRK B")))
    for view in (left, right):
        if window._group_by_id("A", "usfm") is None:
            window._set_groups("usfm", window.groups_for("usfm") + (DocumentGroup("A", "Group A", "#61afef"),))
        window._set_document_group(window._service.documents.entry_for_view(view.view_id).document_id, "A")
    window._select_view(left)
    clone = window.split_right()
    leaf = window.panes.leaf_for_view(clone.view_id)
    right = window.assign_document_to_pane(window._service.documents.entry_for_view(right.view_id).document_id, leaf.pane_id)
    window._close_view_id(clone.view_id)
    window._select_view(left)
    window._chapter_view.set_enabled(True)

    _caret(left, "Three two")
    assert window._reference_sync.sync_from(left) == 1

    assert right.line_window() == CHAPTER_3
    assert right.state.cursor == _MARK.index("\\v 2 Three")


def test_preview_shows_only_the_chapters_text_and_notes(desktop, tmp_path: Path):
    window, view = _usfm_window(desktop, tmp_path)
    window._chapter_view.set_enabled(True)
    _caret(view, "Two one")
    window._rich_views.show("sfm.preview", view)
    pane = window._rich_views.pane_for(view)
    assert pane.projection is not None

    shown = _shown_text(pane.editor)
    assert "Two one" in shown and "One one" not in shown and "Three one" not in shown
    notes = "\n".join(_shown_text(section.editor) for section in pane.note_sections if section.isVisibleTo(pane))
    assert "Note two." in notes and "Note one." not in notes

    window._environment_bar._chapter_chosen(2)
    shown = _shown_text(pane.editor)
    assert "Three one" in shown and "Two one" not in shown
    assert not any(section.isVisibleTo(pane) for section in pane.note_sections)  # chapter 3 has no notes

    window._chapter_view.set_enabled(False)
    assert "One one" in _shown_text(pane.editor) and "Three one" in _shown_text(pane.editor)


def test_standard_keeps_the_caret_and_edits_in_the_chapter(desktop, tmp_path: Path):
    window, view = _usfm_window(desktop, tmp_path)
    window._chapter_view.set_enabled(True)
    _caret(view, "Two two")
    window._rich_views.show("sfm.standard", view)
    pane = window._rich_views.pane_for(view)
    before = view.document.read(0, view.document.total_chars())

    # Ctrl+End and Select All stop at the chapter's end.
    QTest.keyClick(pane.editor, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
    assert view.line_window() == CHAPTER_2
    assert pane.editor.textCursor().position() == pane._window_positions[1]
    pane.editor.selectAll()
    assert pane.editor.textCursor().selectedText().endswith("Two two.")
    assert "Three" not in pane.editor.textCursor().selectedText()

    # Delete at the end and Backspace at the start don't join chapters.
    cursor = pane.editor.textCursor()
    cursor.setPosition(pane._window_positions[1])
    pane.editor.setTextCursor(cursor)
    assert pane.delete(backwards=False) is False
    cursor.setPosition(pane._window_positions[0])
    pane.editor.setTextCursor(cursor)
    assert pane.delete(backwards=True) is False
    assert view.document.read(0, view.document.total_chars()) == before


def test_a_tab_opened_as_plain_text_is_not_narrowed(desktop, tmp_path: Path):
    window, view = _usfm_window(desktop, tmp_path)
    window._chapter_view.set_enabled(True)
    _caret(view, "Two two")
    assert view.line_window() == CHAPTER_2

    window._environment.set_plain_mode(True, view)

    assert view.line_window() is None


def test_show_one_chapter_is_saved_with_the_window(desktop, tmp_path: Path):
    from uniti.app.session_runtime import (
        ENVIRONMENT_WINDOW_EXTRA,
        capture_service_session,
        environment_window_shows_one_chapter,
    )

    window, view = _usfm_window(desktop, tmp_path)
    service = desktop[1]

    def captured():
        snapshot = capture_service_session(
            service,
            clean_shutdown=True,
            generation="g1",
            service_id="s1",
            build_identity="test",
            created_at="2026-10-09T00:00:00Z",
            updated_at="2026-10-09T00:00:00Z",
        )
        record = next(item for item in snapshot.manifest.windows if item.window_id == window.window_id)
        views = {item.view_id: item for item in snapshot.manifest.views}
        return views[view.view_id].extra[ENVIRONMENT_WINDOW_EXTRA], environment_window_shows_one_chapter(record.root, views)

    assert captured() == ({"environment": "usfm", "window": 0}, False)
    window._chapter_view.set_enabled(True)
    assert captured() == ({"environment": "usfm", "window": 0, "chapter": True}, True)
