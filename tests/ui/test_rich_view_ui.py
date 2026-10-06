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


def test_view_as_menu_opens_the_formatted_view(window, tmp_path: Path):
    _open(window, tmp_path, "book.usfm", _USFM)
    actions = window._environment.view_actions
    assert set(actions) == {None, "sfm.standard", "sfm.formatted"}
    assert actions[None].isChecked() is True  # Source only, nothing beside it

    actions["sfm.formatted"].trigger()

    pane = window._rich_views.pane
    assert pane is not None and pane.isVisible()
    assert pane.editor.toPlainText() == "GEN\n1\n1In the beginning God created.\n"
    assert window._environment.view_actions["sfm.formatted"].isChecked() is True
    window._environment.view_actions[None].trigger()
    assert window._rich_views.pane is None


def test_typing_in_the_formatted_view_edits_the_canonical_source(window, tmp_path: Path, app):
    view = _open(window, tmp_path, "book.usfm", _USFM)
    window._rich_views.show("sfm.formatted")
    pane = window._rich_views.pane
    cursor = pane.editor.textCursor()
    cursor.setPosition(pane.editor.toPlainText().index("beginning") + len("beginning"))
    pane.editor.setTextCursor(cursor)
    pane.editor.setFocus()

    QTest.keyClicks(pane.editor, "s")

    assert "\\bd beginnings\\bd*" in _source(view)
    assert pane.editor.toPlainText() == "GEN\n1\n1In the beginnings God created.\n"
    # The Source editor's caret follows the rich caret.
    assert view.state.cursor == _source(view).index("\\bd*")

    QTest.keyClick(pane.editor, Qt.Key.Key_Z, Qt.KeyboardModifier.ControlModifier)
    assert _source(view) == _USFM


def test_backspace_steps_over_protected_markers(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", "\\p one \\zz two")
    window._rich_views.show("sfm.formatted")
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
    window._rich_views.show("sfm.formatted")
    pane = window._rich_views.pane
    cursor = pane.editor.textCursor()
    cursor.setPosition(len("line"))
    pane.editor.setTextCursor(cursor)

    assert pane.enter() is True

    assert _source(view) == "\\q1 line\n\\q1  one"


def test_view_commands_apply_styles_through_the_source(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", "\\p In the beginning")
    window._rich_views.show("sfm.formatted")
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
    window._rich_views.show("sfm.formatted")
    assert usfm.rich_view_key == "sfm.formatted"

    # Plain Text Mode hides the pane but keeps the tab's choice.
    window._environment.set_plain_mode(True)
    assert window._rich_views.pane is None
    assert usfm.rich_view_key == "sfm.formatted"
    window._environment.set_plain_mode(False)
    assert window._rich_views.current_key == "sfm.formatted"

    # Another tab has its own (empty) choice; coming back restores ours.
    other = _open(window, tmp_path, "other.usfm", "\\p second")
    assert window._rich_views.pane is None
    window._rich_views.show("sfm.standard")
    window._select_view(usfm)
    assert window._rich_views.target_view is usfm
    assert window._rich_views.current_key == "sfm.formatted"
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
    window._rich_views.show("sfm.formatted")
    pane = window._rich_views.pane
    assert pane.projection is None
    assert pane.editor.isReadOnly() is True
    assert "too large" in pane.editor.toPlainText()
