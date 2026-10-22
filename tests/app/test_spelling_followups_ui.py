"""Spelling follow-ups in the window: right-click entries, your own list,
suggestions, Next/Previous and the count (plan
2026-10-15-usfm-hyphenation-and-spelling-followups, F1, F2, F4, F5)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

from test_service import _desktop_service, _stop_desktop_service  # noqa: E402
from usfm_project_fixture import ensure_project  # noqa: E402
from uniti.core.environments.sfm.user_words import user_words_for  # noqa: E402
from uniti.core.environments.user_config import set_user_config_root  # noqa: E402

_GEN = (
    "\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 In the begining God created.\r\n"
    "\\v 2 The earth was formles and Zerubbabel came.\r\n\\v 3 God said.\r\n"
)
_LIST = """<SpellingStatus>
  <Status Word="in" State="R"/><Status Word="the" State="R"/><Status Word="god" State="R"/>
  <Status Word="created" State="R"/><Status Word="earth" State="R"/><Status Word="was" State="R"/>
  <Status Word="and" State="R"/><Status Word="came" State="R"/><Status Word="said" State="R"/>
  <Status Word="beginning" State="R"/><Status Word="formless" State="R"/>
  <Status Word="v" State="R"/><Status Word="c" State="R"/>
  <Status Word="came" State="R"/><Status Word="chapter" State="R"/>
</SpellingStatus>"""


@pytest.fixture
def desktop(tmp_path: Path):
    set_user_config_root(tmp_path / "userdata")
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)
    set_user_config_root(None)


def _project(folder: Path, name: str = "NIV") -> Path:
    ensure_project(folder, name=name)
    (folder / "01GEN.usfm").write_bytes(_GEN.encode())
    (folder / "SpellingStatus.xml").write_text(_LIST, encoding="utf-8")
    return folder


def _wait(predicate, timeout: float = 8.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("condition did not become true")


def _checking(service, folder: Path):
    main = service.new_window()
    view = main.open_path(folder / "01GEN.usfm")
    window = main.move_to_environment_window(view)
    window._spelling.set_tab(view, True)
    _wait(lambda: view.spelling is not None)
    return window, view


def _flagged(view) -> list[str]:
    return [view.document.read(span.start, span.end) for span in view.spelling.book_spans()]


def _entries(window, view, word: str, *, editable: bool = True) -> dict[str, object]:
    text = view.document.read(0, view.document.total_chars())
    menu = QMenu()
    window._spelling.add_context_entries(menu, view, text.index(word) + 1, editable=editable)
    return {action.text(): action for action in menu.actions() if action.text()}, menu


def test_a_flagged_word_gets_suggestions_and_list_entries_at_the_top(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _project(tmp_path / "niv"))
    assert _flagged(view) == ["begining", "formles", "Zerubbabel"]

    entries, menu = _entries(window, view, "begining")

    assert list(entries)[:1] == ["Change to “beginning”"]
    assert "Approve “begining”" in entries and "Mark “begining” Wrong" in entries
    assert "Remove “begining” from Your Spelling List" not in entries
    assert menu.actions()[1].isSeparator() or menu.actions()[0].text().startswith("Change")


def test_a_word_that_is_not_flagged_gets_nothing(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _project(tmp_path / "niv"))

    entries, _menu = _entries(window, view, "earth")

    assert entries == {}


def test_a_read_only_pane_offers_only_the_list_entries(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _project(tmp_path / "niv"))

    entries, _menu = _entries(window, view, "begining", editable=False)

    assert not any(text.startswith(("Change to", "Use")) for text in entries)
    assert "Approve “begining”" in entries


def test_approving_a_word_stops_flagging_it_everywhere_and_is_remembered(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _project(tmp_path / "niv"))
    entries, _menu = _entries(window, view, "Zerubbabel")

    entries["Approve “Zerubbabel”"].trigger()

    assert _flagged(view) == ["begining", "formles"]
    assert user_words_for("NIV").is_approved("zerubbabel")
    from uniti.core.environments.sfm.user_words import user_words_path

    assert user_words_path("NIV").is_file()
    again, _menu = _entries(window, view, "Zerubbabel")
    assert again == {}  # no longer flagged: no menu entries for it


def test_marking_a_word_wrong_and_removing_it(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _project(tmp_path / "niv"))
    text = view.document.read(0, view.document.total_chars())
    assert "God" not in _flagged(view)

    user_words_for("NIV").reject("God")
    window._spelling.refresh_project(window._spelling.project_of(view))
    assert _flagged(view).count("God") == 2

    entries, _menu = _entries(window, view, "God")
    assert "Mark “God” Wrong" not in entries and "Remove “God” from Your Spelling List" in entries
    entries["Remove “God” from Your Spelling List"].trigger()
    assert "God" not in _flagged(view) and text


def test_choosing_a_suggestion_replaces_the_word_and_undo_takes_it_back(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _project(tmp_path / "niv"))
    view.document.set_locked(False)
    entries, _menu = _entries(window, view, "begining")

    entries["Change to “beginning”"].trigger()

    assert "In the beginning God" in view.document.read(0, view.document.total_chars())
    assert "begining" not in _flagged(view)
    view.state.undo()
    assert "begining" in view.document.read(0, view.document.total_chars())


def test_a_locked_book_refuses_the_replacement(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _project(tmp_path / "niv"))
    view.document.set_locked(True)
    entries, _menu = _entries(window, view, "begining")

    entries["Change to “beginning”"].trigger()

    assert "begining" in view.document.read(0, view.document.total_chars())
    assert "locked" in window.statusBar().currentMessage()


def test_next_and_previous_issue_walk_the_book_and_wrap(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _project(tmp_path / "niv"))
    selected = lambda: view.document.read(*sorted((view.state.cursor, view.state.anchor)))  # noqa: E731
    view.state.move_to(0)

    window._spelling.next_action.trigger()
    assert selected() == "begining"
    assert window.statusBar().currentMessage() == "Spelling issue 1 of 3: wrong “begining”" or "Spelling issue 1 of 3" in window.statusBar().currentMessage()
    window._spelling.next_action.trigger()
    assert selected() == "formles"
    window._spelling.next_action.trigger()
    window._spelling.next_action.trigger()  # past the last: round to the first
    assert selected() == "begining" and "wrapped" in window.statusBar().currentMessage()
    window._spelling.previous_action.trigger()  # before the first: round to the last
    assert selected() == "Zerubbabel"
    window._spelling.previous_action.trigger()
    assert selected() == "formles"


def test_next_issue_is_off_until_checking_is_on_and_the_summary_counts(desktop, tmp_path: Path):
    _app, service = desktop
    main = service.new_window()
    view = main.open_path(_project(tmp_path / "niv") / "01GEN.usfm")
    window = main.move_to_environment_window(view)
    window._spelling.refresh()
    assert not window._spelling.next_action.isEnabled()

    window._spelling.set_tab(view, True)
    _wait(lambda: view.spelling is not None)
    window._spelling.refresh()

    assert window._spelling.next_action.isEnabled() and window._spelling.previous_action.isEnabled()
    assert window._spelling.summary(view) == "01GEN: 0 wrong, 3 unknown words"
    assert next(a for a in window._environment.menu.actions() if a.text() == "Next Spelling Issue")


def test_the_rich_views_right_click_finds_the_word_under_it(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _project(tmp_path / "niv"))
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    editor = pane.editor
    text = pane.projection.text
    from PySide6.QtGui import QTextCursor

    cursor = QTextCursor(editor.document())
    cursor.setPosition(pane._offsets.to_qt(text.index("begining") + 3))
    point = editor.cursorRect(cursor).center()

    source_offset = pane.source_offset_at(point)
    menu = QMenu()
    window._spelling.add_context_entries(menu, view, source_offset, editable=pane.editable)

    assert [a.text() for a in menu.actions() if a.text()][:1] == ["Change to “beginning”"]


_PAIRS = (
    "\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 The grain field and go at it.\r\n"
)


def _pair_project(folder: Path) -> Path:
    _project(folder)
    (folder / "01GEN.usfm").write_bytes(_PAIRS.encode())
    (folder / "SpellingStatus.xml").write_text(
        _LIST.replace(
            "</SpellingStatus>",
            '<Status Word="grain" State="R"/><Status Word="field" State="R"/>'
            '<Status Word="go" State="R"/><Status Word="at" State="R"/><Status Word="it" State="R"/>'
            '<Status Word="grain field" State="W"/></SpellingStatus>',
        ),
        encoding="utf-8",
    )
    return folder


def test_a_flagged_pair_can_be_approved_and_removed_again(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _pair_project(tmp_path / "niv"))
    assert _flagged(view) == ["grain field"]

    entries, _menu = _entries(window, view, "grain")
    assert "Approve “grain field”" in entries and "Mark “grain field” Wrong" not in entries
    entries["Approve “grain field”"].trigger()

    assert _flagged(view) == []
    assert user_words_for("NIV").is_approved("grain field")


def test_two_selected_words_can_be_marked_wrong_together_and_removed(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _pair_project(tmp_path / "niv"))
    text = view.document.read(0, view.document.total_chars())
    start = text.index("go at")
    view._select_range(start, start + len("go at"))
    menu = QMenu()

    window._spelling.add_context_entries(menu, view, start + 1, editable=True)
    entries = {action.text(): action for action in menu.actions() if action.text()}
    assert "Mark “go at” Wrong Together" in entries
    entries["Mark “go at” Wrong Together"].trigger()

    assert _flagged(view) == ["grain field", "go at"]
    again, _menu = _entries(window, view, "go")
    assert "Remove “go at” from Your Spelling List" in again and not any(t.startswith("Approve") for t in again)
    again["Remove “go at” from Your Spelling List"].trigger()
    assert _flagged(view) == ["grain field"]


def test_one_word_or_three_selected_words_offer_no_pair(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _checking(service, _pair_project(tmp_path / "niv"))
    text = view.document.read(0, view.document.total_chars())
    for selection in ("go", "go at it", "go  at"):
        start = text.index(selection.split()[0])
        view._select_range(start, start + len(selection))
        menu = QMenu()
        window._spelling.add_context_entries(menu, view, start + 1, editable=True)
        assert not [a for a in menu.actions() if "Wrong Together" in a.text()]


def test_next_and_previous_issue_have_rebindable_shortcuts(desktop, tmp_path: Path):
    _app, service = desktop
    window, _view = _checking(service, _project(tmp_path / "niv"))

    assert window._command_actions["spelling.next_issue"] is window._spelling.next_action
    assert window._spelling.next_action.shortcut().toString() != ""
    assert window._spelling.next_action.shortcut() != window._spelling.previous_action.shortcut()


@pytest.mark.parametrize("mode", ["sfm.standard", "sfm.preview"])
def test_two_selected_words_can_be_marked_wrong_together_in_standard_and_preview(desktop, tmp_path: Path, mode: str):
    _app, service = desktop
    window, view = _checking(service, _pair_project(tmp_path / "niv"))
    window._rich_views.show(mode)
    pane = window._rich_views.pane
    text = pane.editor.toPlainText()
    start = pane._offsets.to_qt(text.index("go at"))
    cursor = pane.editor.textCursor()
    cursor.setPosition(start)
    cursor.setPosition(start + len("go at"), cursor.MoveMode.KeepAnchor)
    pane.editor.setTextCursor(cursor)
    pane.context_source_offset = pane.source_offset_at(pane.editor.cursorRect(cursor).center())
    menu = QMenu()

    window._rich_views._context_entries(menu, view, pane)

    entries = {action.text(): action for action in menu.actions() if action.text()}
    assert "Mark “go at” Wrong Together" in entries
    entries["Mark “go at” Wrong Together"].trigger()
    assert user_words_for("NIV").is_rejected("go at")


def test_suggestions_are_ranked_by_use_in_the_book(desktop, tmp_path: Path):
    _app, service = desktop
    folder = _project(tmp_path / "niv")
    (folder / "SpellingStatus.xml").write_text(
        _LIST.replace("</SpellingStatus>", '<Status Word="tea" State="R"/><Status Word="ten" State="R"/></SpellingStatus>'),
        encoding="utf-8",
    )
    (folder / "01GEN.usfm").write_bytes(
        "\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 Ten men had ten sons and teh tea.\r\n".encode()
    )
    window, view = _checking(service, folder)

    entries, _menu = _entries(window, view, "teh")

    assert list(entries)[:2] == ["Change to “ten”", "Change to “tea”"]
