from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from uniti.app.settings import SettingsStore  # noqa: E402
from uniti.ui.main_window import UNITIMainWindow  # noqa: E402

_USFM = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the \\bd beginning\\bd* God created.\n"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path: Path):
    window = UNITIMainWindow(settings_store=SettingsStore(tmp_path / "settings.json"))
    window.resize(1000, 600)
    window.show()
    yield window
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def _open(window, tmp_path: Path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return window.open_path(path)


def _source(view) -> str:
    return view.document.read(0, view.document.total_chars())


def test_view_as_menu_opens_the_preview(window, tmp_path: Path):
    _open(window, tmp_path, "book.usfm", _USFM)
    actions = window._environment.view_actions
    assert set(actions) == {None, "sfm.standard", "sfm.preview"}
    assert actions[None].isChecked() is True  # Plain Text: the Source editor only

    actions["sfm.preview"].trigger()

    pane = window._rich_views.pane
    assert pane is not None and pane.isVisible()
    assert pane.editor.toPlainText() == "1\n1In the beginning God created.\n"
    assert window._environment.view_actions["sfm.preview"].isChecked() is True
    window._environment.view_actions[None].trigger()
    assert window._rich_views.pane is None


def test_typing_in_the_standard_view_edits_the_canonical_source(window, tmp_path: Path, app):
    view = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    cursor = pane.editor.textCursor()
    cursor.setPosition(pane.editor.toPlainText().index("beginning") + len("beginning"))
    pane.editor.setTextCursor(cursor)
    pane.editor.setFocus()

    QTest.keyClicks(pane.editor, "s")

    assert "\\bd beginnings\\bd*" in _source(view)
    assert pane.editor.toPlainText() == "\\id GEN\n\\c 1\n\\p \\v 1 In the \\bd beginnings\\bd* God created.\n"
    # The Source editor's caret follows the rich caret.
    assert view.state.cursor == _source(view).index("\\bd*")

    QTest.keyClick(pane.editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert _source(view) == _USFM


def test_backspace_steps_over_protected_markers(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", "\\p one \\zz two")
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    text = pane.editor.toPlainText()
    position = text.index("\\zz") + len("\\zz")
    cursor = pane.editor.textCursor()
    cursor.setPosition(position)
    pane.editor.setTextCursor(cursor)

    assert pane.delete(backwards=True) is False

    assert _source(view) == "\\p one \\zz two"
    assert pane.editor.textCursor().position() == position - 1
    assert pane.last_message


def test_enter_starts_a_new_paragraph_of_the_same_kind(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", "\\q1 line one")
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    cursor = pane.editor.textCursor()
    cursor.setPosition(pane.editor.toPlainText().index("line") + len("line"))
    pane.editor.setTextCursor(cursor)

    assert pane.enter() is True

    assert _source(view) == "\\q1 line\n\\q1  one"


def test_view_commands_apply_styles_through_the_source(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", "\\p In the beginning")
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    text = pane.editor.toPlainText()
    cursor = pane.editor.textCursor()
    cursor.setPosition(text.index("beginning"))
    cursor.setPosition(text.index("beginning") + 9, cursor.MoveMode.KeepAnchor)
    pane.editor.setTextCursor(cursor)

    assert pane.run_view_command("bold") is True
    assert _source(view) == "\\p In the \\bd beginning\\bd*"

    assert pane.run_view_command("remove_style") is True
    assert _source(view) == "\\p In the beginning"
    assert pane.run_view_command("paragraph_style", "q2") is True
    assert _source(view) == "\\q2 In the beginning"


def test_source_edits_and_caret_flow_into_the_rich_view(window, tmp_path: Path, app):
    view = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    view.document.insert(view.document.total_chars(), "\\v 2 More.\n")
    view._state_changed()
    app.processEvents()
    assert pane.editor.toPlainText().endswith("\\v 2 More.\n")

    view.state.move_to(_source(view).index("God"))
    view._state_changed()
    assert pane.editor.textCursor().position() == pane.editor.toPlainText().index("God")


def test_rich_view_choice_is_per_tab(window, tmp_path: Path, app):
    usfm = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.preview")
    assert usfm.rich_view_key == "sfm.preview"

    # Plain Text Mode hides the pane but keeps the tab's choice.
    window._environment.set_plain_mode(True)
    assert window._rich_views.pane is None
    assert usfm.rich_view_key == "sfm.preview"
    window._environment.set_plain_mode(False)
    assert window._rich_views.current_key == "sfm.preview"

    # Another tab has its own (empty) choice; coming back restores ours.
    other = _open(window, tmp_path, "other.usfm", "\\p second")
    assert window._rich_views.pane is None
    window._rich_views.show("sfm.standard")
    window._select_view(usfm)
    assert window._rich_views.target_view is usfm
    assert window._rich_views.current_key == "sfm.preview"
    window._select_view(other)
    assert window._rich_views.current_key == "sfm.standard"

    _open(window, tmp_path, "notes.txt", "hello")
    assert window._rich_views.pane is None

    # Source Only forgets the choice.
    window._select_view(usfm)
    window._environment.view_actions[None].trigger()
    assert usfm.rich_view_key is None
    window._select_view(other)
    window._select_view(usfm)
    assert window._rich_views.pane is None


def test_rich_view_choice_is_saved_with_the_view(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", _USFM)
    assert "rich_view" not in view.export_state("doc").extra
    window._rich_views.show("sfm.standard")
    record = view.export_state("doc")
    assert record.extra["rich_view"] == "sfm.standard"

    from uniti.app.editor_state import EditorState
    from uniti.ui.text_view import UNITITextView

    restored = UNITITextView(EditorState(view.document), view_id=record.view_id)
    restored.restore_state(record)
    assert restored.rich_view_key == "sfm.standard"
    restored.close()


def test_markdown_rendered_view_is_editable(window, tmp_path: Path):
    view = _open(window, tmp_path, "notes.md", "# Title\nSome **bold** text\n")
    assert set(window._environment.view_actions) == {None, "markdown.rendered"}
    window._environment.view_actions["markdown.rendered"].trigger()
    pane = window._rich_views.pane
    assert pane.editor.toPlainText() == "Title\nSome bold text\n"
    cursor = pane.editor.textCursor()
    cursor.setPosition(pane.editor.toPlainText().index("bold") + 4)
    pane.editor.setTextCursor(cursor)

    assert pane.type_text("er") is True

    assert _source(view) == "# Title\nSome **bolder** text\n"


def test_large_documents_refuse_a_rich_view(window, tmp_path: Path):
    _open(window, tmp_path, "big.usfm", "\\p " + "x" * (1 << 20))
    window._rich_views.show("sfm.preview")
    pane = window._rich_views.pane
    assert pane.projection is None
    assert pane.editor.isReadOnly() is True
    assert "too large" in pane.editor.toPlainText()


def test_standard_view_refuses_edits_while_the_source_is_saving(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    cursor = pane.editor.textCursor()
    cursor.setPosition(pane.editor.toPlainText().index("beginning") + len("beginning"))
    pane.editor.setTextCursor(cursor)
    view.setEnabled(False)  # as during a save

    QTest.keyClicks(pane.editor, "s")

    assert _source(view) == _USFM
    assert view.document.modified is False
    view.setEnabled(True)
    QTest.keyClicks(pane.editor, "s")
    assert "\\bd beginnings\\bd*" in _source(view)


def test_opening_a_rich_view_keeps_an_open_markdown_preview_closable(window, tmp_path: Path, app):
    _open(window, tmp_path, "notes.md", "# Hello\n")
    window.toggle_markdown_preview()
    assert window._markdown_preview is not None
    _open(window, tmp_path, "book.usfm", _USFM)

    window._environment.view_actions["sfm.preview"].trigger()

    assert window._rich_views.pane is not None
    assert window._markdown_preview_action.isEnabled() is True
    window._environment.view_actions[None].trigger()
    assert window._markdown_preview_action.isEnabled() is True


def _select_in_source(view, start: int, end: int) -> None:
    from uniti.app.editor_state import EditorStateSnapshot

    view.state.restore_state(EditorStateSnapshot(end, start, None))
    view._state_changed()


def _rich_selection(pane) -> str:
    # Qt positions count UTF-16 units; selectedText() needs no conversion.
    return pane.editor.textCursor().selectedText()


@pytest.mark.parametrize("key", ["sfm.standard", "sfm.preview"])
def test_crlf_document_keeps_formatting_and_selection_on_the_right_text(window, tmp_path: Path, app, key):
    path = tmp_path / "book.usfm"
    path.write_bytes(_USFM.replace("\n", "\r\n").encode("utf-8"))
    view = window.open_path(path)
    window._rich_views.show(key)
    pane = window._rich_views.pane
    assert pane.editor.toPlainText() == pane.projection.text

    source = _source(view)
    start = source.index("created")
    _select_in_source(view, start, start + len("created"))
    app.processEvents()

    assert _rich_selection(pane) == "created"
    # The bold span still lands on "beginning", not a few characters off.
    cursor = pane.editor.textCursor()
    cursor.setPosition(pane.editor.toPlainText().index("beginning") + 1)
    assert cursor.charFormat().fontWeight() == 700


def test_typing_into_a_crlf_document_keeps_crlf(window, tmp_path: Path):
    path = tmp_path / "book.usfm"
    path.write_bytes(b"\\q1 line one\r\n")
    view = window.open_path(path)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    cursor = pane.editor.textCursor()
    cursor.setPosition(pane.editor.toPlainText().index("line") + len("line"))
    pane.editor.setTextCursor(cursor)

    assert pane.enter() is True

    assert _source(view) == "\\q1 line\r\n\\q1  one\r\n"


def test_characters_outside_the_bmp_do_not_shift_the_rich_caret(window, tmp_path: Path, app):
    view = _open(window, tmp_path, "book.usfm", "\\p \U0001F600\U0001F600 In the beginning\n")
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    start = _source(view).index("beginning")
    _select_in_source(view, start, start + len("beginning"))
    app.processEvents()

    assert _rich_selection(pane) == "beginning"


def test_preview_is_read_only(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.preview")
    pane = window._rich_views.pane
    cursor = pane.editor.textCursor()
    cursor.setPosition(pane.editor.toPlainText().index("God"))
    pane.editor.setTextCursor(cursor)

    QTest.keyClicks(pane.editor, "x")
    pane.delete(backwards=True)

    assert _source(view) == _USFM
    assert pane.editor.isReadOnly() is True
    assert "read-only" in (pane.last_message or "")
    assert pane.commands == ()


def test_standard_tags_share_one_size_smaller_than_body_text(window, tmp_path: Path):
    _open(window, tmp_path, "book.usfm", "\\mt1 Title\n\\p \\v 1 Body \\wj red\\wj*\n")
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    text = pane.editor.toPlainText()

    def size_at(fragment: str) -> float:
        cursor = pane.editor.textCursor()
        cursor.setPosition(text.index(fragment) + 1)
        return cursor.charFormat().fontPointSize() or pane.editor.font().pointSizeF()

    tag_sizes = {size_at(tag) for tag in ("\\mt1", "\\p", "\\v", "\\wj ", "\\wj*")}
    assert len(tag_sizes) == 1
    assert tag_sizes.pop() < size_at("Body") < size_at("Title")


def test_rich_view_follows_source_zoom_and_theme(window, tmp_path: Path, app):
    from PySide6.QtCore import QPoint, QPointF
    from PySide6.QtGui import QPalette, QWheelEvent

    view = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    before = pane.editor.font().pointSizeF()
    assert pane.editor.palette().color(QPalette.ColorRole.Base) == view.theme_tokens.base

    view.zoom_in()
    assert pane.editor.font().pointSizeF() > before

    zoom = view.zoom_percent
    wheel = QWheelEvent(
        QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase, False,
    )
    QApplication.sendEvent(pane.editor.viewport(), wheel)
    assert view.zoom_percent > zoom


def test_mode_switcher_offers_plain_text(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    labels = [pane.mode.itemText(index) for index in range(pane.mode.count())]
    assert labels == ["Plain Text", "Standard", "Preview"]

    pane.mode.activated.emit(0)

    assert window._rich_views.pane is None and view.rich_view_key is None


def test_rich_view_is_shown_in_place_of_the_source_editor(window, tmp_path: Path, app):
    """ADR-0017: Plain Text / Standard / Preview are modes of one tab, not a
    second pane beside it."""

    view = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.preview")
    pane = window._rich_views.pane

    assert pane.parent() is view
    assert pane.geometry() == view.rect()
    assert window._central_splitter.count() == 1  # no side pane
    assert view.focusProxy() is pane.editor
    window.resize(700, 500)
    app.processEvents()
    assert pane.geometry() == view.rect()

    # The tab still holds the Source editor, and Plain Text removes the pane.
    assert window.current_view is view
    window._environment.view_actions[None].trigger()
    assert window._rich_views.pane is None and view.focusProxy() is None


def test_split_tabs_each_keep_their_own_in_place_mode(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", _USFM)
    other = _open(window, tmp_path, "other.usfm", _USFM)
    window._rich_views.show("sfm.preview", view)
    window._rich_views.show("sfm.standard", other)

    assert window._rich_views.key_for(view) == "sfm.preview"
    assert window._rich_views.key_for(other) == "sfm.standard"
    assert window._rich_views.pane_for(view) is not window._rich_views.pane_for(other)


def test_edit_menu_cannot_paste_into_the_read_only_preview(window, tmp_path: Path, app):
    view = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.preview")
    app.clipboard().setText("pasted")

    window.paste_current()
    window.cut_current()

    assert _source(view) == _USFM
    assert "read-only" in (window._rich_views.pane.last_message or "")


_NOTES = (
    "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning\\f + \\fr 1:1 \\ft Or: at first\\f* God"
    "\\x - \\xo 1:1 \\xt Jn 1:1\\x* created.\n"
)


def test_preview_stacks_notes_per_class_below_the_text(window, tmp_path: Path, app):
    view = _open(window, tmp_path, "book.usfm", _NOTES)
    window._rich_views.show("sfm.preview")
    pane = window._rich_views.pane

    assert pane.editor.toPlainText() == "1\n1In the beginninga God created.\n"
    assert [section.title.text() for section in pane.note_sections] == ["Footnotes", "Cross References"]
    assert [section.editor.toPlainText() for section in pane.note_sections] == ["a 1:1 Or: at first", "1:1 Jn 1:1"]
    assert pane.body.count() == 3  # text, then one section per class

    # A click in a note moves the caret to that note's source.
    footnotes = pane.note_sections[0]
    cursor = footnotes.editor.textCursor()
    cursor.setPosition(footnotes.editor.toPlainText().index("first"))
    footnotes.editor.setTextCursor(cursor)
    assert view.state.cursor == _NOTES.index("first")

    # The caret on a caller highlights its note.
    text = pane.editor.toPlainText()
    cursor = pane.editor.textCursor()
    cursor.setPosition(text.index("a God") + 1)
    pane.editor.setTextCursor(cursor)
    assert len(footnotes.editor.extraSelections()) == 1
    assert pane.note_sections[1].editor.extraSelections() == []


def test_standard_keeps_notes_inline(window, tmp_path: Path):
    _open(window, tmp_path, "book.usfm", _NOTES)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    assert pane.note_sections == []
    assert "\\ft Or: at first" in pane.editor.toPlainText()


@pytest.mark.parametrize("key", ["sfm.standard", "sfm.preview"])
def test_regex_search_always_matches_the_underlying_plain_text(window, tmp_path: Path, app, key):
    """ADR-0017 decision 8: Find/Replace runs on the source, whatever the
    tab shows — `\\v` markers match even where Preview hides them."""

    import time

    from uniti.ui.find_replace import FindReplacePanel

    source = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning\n\\v 2 God created.\n"
    view = _open(window, tmp_path, "book.usfm", source)
    window._rich_views.show(key)
    pane = window._rich_views.pane
    panel = FindReplacePanel(lambda: window.current_view)
    try:
        panel.regex_checkbox.setChecked(True)
        panel.find_input.set_text(r"\\v (\d+)")
        deadline = time.perf_counter() + 5
        while panel.compile_current() is None and time.perf_counter() < deadline:
            app.processEvents()
        panel.find_all()
        while (panel.busy or panel.result_count != 2) and time.perf_counter() < deadline:
            app.processEvents()
        assert panel.result_count == 2

        # Matches are spans of the source, the \v marker included.
        for marker in ("\\v 1", "\\v 2"):
            app.processEvents()
            start = source.index(marker)
            assert sorted((view.state.cursor, view.state.anchor)) == [start, start + len(marker)]
            # The rich view mirrors that source selection (the verse number).
            assert marker[-1] in pane.editor.textCursor().selectedText()
            panel.next_match()
    finally:
        panel.shutdown()
        panel.close()
