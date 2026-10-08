"""Environment windows, the USFM Book/Chapter/Verse selector, and
side-by-side reference sync (ADR-0017, 2026-10-07 field test)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from usfm_project_fixture import ensure_project, in_project  # noqa: E402
from test_service import _desktop_service, _stop_desktop_service  # noqa: E402

from uniti.app.document_groups import DocumentGroup  # noqa: E402
from uniti.app.session_runtime import ENVIRONMENT_WINDOW_EXTRA, environment_window_identity  # noqa: E402

_GEN_A = "\\id GEN A\n\\c 1\n\\p\n\\v 1 Alpha one.\n\\v 2 Alpha two.\n\\c 2\n\\p\n\\v 1 Alpha again.\n"
_GEN_B = "\\id GEN B\n\\c 1\n\\p\n\\v 1 Beta one.\n\n\n\\v 2 Beta two.\n\\c 2\n\\p\n\\v 1 Beta again.\n"
_EXO = "\\id EXO\n\\h Exodus\n\\c 1\n\\p\n\\v 1 Exodus.\n"


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
    path.write_text(text, encoding="utf-8")
    return path


def _group(window, service, view, group_id: str) -> None:
    key = window._environment.environment_key_for(view.document)
    if window._group_by_id(group_id, key) is None:
        window._set_groups(key, window.groups_for(key) + (DocumentGroup(group_id, f"Group {group_id}", "#61afef"),))
    entry = service.documents.entry_for_view(view.view_id)
    window._set_document_group(entry.document_id, group_id)


def test_environment_windows_are_named_per_environment_not_per_group(desktop, tmp_path: Path):
    """Round 3 T3: "USFM A", "USFM B" … hold files of any group."""

    app, service = desktop
    main = service.new_window()
    first = main.open_path(_write(tmp_path / "a", "01GEN.usfm", _GEN_A))
    second = main.open_path(_write(tmp_path / "b", "01GEN.usfm", _GEN_B))
    third = main.open_path(_write(tmp_path / "c", "01GEN.usfm", _GEN_A))
    for view, group in ((first, "A"), (second, "A"), (third, "B")):
        _group(main, service, view, group)
    home = main.view_location(first.view_id)

    usfm_a = main.move_to_environment_window(first)
    assert usfm_a is not main
    assert usfm_a.environment_window == ("usfm", 0)
    assert usfm_a.environment_window_name() == "USFM A"
    assert usfm_a.current_view is first
    assert usfm_a._environment_bar is not None
    assert usfm_a.windowTitle() == "UNITI — USFM A — TST — 01GEN.usfm"
    # The tab's own mode selector moves to the window's toolbar.
    assert usfm_a._rich_views.pane_mode_selector is False

    # Every group goes to the most recent USFM window, and keeps its group.
    assert main.move_to_environment_window(second) is usfm_a
    assert main.move_to_environment_window(third) is usfm_a
    assert service.documents.entry_for_view(third.view_id).group_id == "B"

    # A second window is "USFM B"; a slot can be asked for.
    usfm_b = service.new_environment_window("usfm")
    assert usfm_b.environment_window == ("usfm", 1) and usfm_b.environment_window_name() == "USFM B"
    assert usfm_a.move_to_environment_window(third, slot=1) is usfm_b
    # A book of a project already shown somewhere goes to that window, even
    # when another USFM window is more recent.
    exodus = main.open_path(_write(tmp_path / "a", "02EXO.usfm", _EXO))
    service.windows.activate(usfm_b.window_id, None)
    assert service.environment_windows("usfm")[0] is usfm_b
    assert main.move_to_environment_window(exodus) is usfm_a

    # Dock takes a file back to where it came from.
    service.dock_view(first.view_id)
    assert service.windows.window_for_view(first.view_id) is main
    assert main.view_location(first.view_id).pane_id == home.pane_id


def test_environment_window_survives_session_capture(desktop, tmp_path: Path):
    from uniti.app.session_runtime import capture_service_session

    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    _group(main, service, view, "A")
    window = main.move_to_environment_window(view)

    snapshot = capture_service_session(
        service,
        clean_shutdown=True,
        generation="g1",
        service_id="s1",
        build_identity="test",
        created_at="2026-10-07T00:00:00Z",
        updated_at="2026-10-07T00:00:00Z",
    )
    record = next(item for item in snapshot.manifest.views if item.view_id == view.view_id)
    assert record.extra[ENVIRONMENT_WINDOW_EXTRA] == {"environment": "usfm", "window": 0}
    window_record = next(item for item in snapshot.manifest.windows if item.window_id == window.window_id)
    views = {item.view_id: item for item in snapshot.manifest.views}
    assert environment_window_identity(window_record.root, views) == ("usfm", 0)
    # A record saved before round 3 T3 names a group: the window takes a free slot.
    from dataclasses import replace

    old = {view.view_id: replace(record, extra={ENVIRONMENT_WINDOW_EXTRA: {"environment": "usfm", "group": "A"}})}
    assert environment_window_identity(window_record.root, old) == ("usfm", None)
    main_record = next(item for item in snapshot.manifest.windows if item.window_id == main.window_id)
    assert environment_window_identity(main_record.root, views) is None


def test_book_selector_lists_the_projects_books_on_disk(desktop, tmp_path: Path):
    """The Book list is the project's books, open or not (plan P3)."""

    app, service = desktop
    folder = tmp_path / "proj"
    _write(folder, "41MAT.usfm", "\\id MAT\n\\c 1\n\\p\n\\v 1 Matthew.\n")  # on disk, not open
    exodus = _write(folder, "02EXO.usfm", _EXO)
    genesis = _write(folder, "01GEN.usfm", _GEN_A)
    main = service.new_window()
    view = main.open_path(genesis)
    window = main.move_to_environment_window(view)
    bar = window._environment_bar

    labels = [bar.book.itemText(index) for index in range(bar.book.count())]
    # The book id and its \h line (_GEN_A has no \h: the id alone).
    assert labels == ["GEN", "EXO Exodus", "MAT"]
    assert bar.book.currentIndex() == 0

    opened = bar.open_book(exodus)
    assert opened is window.current_view and opened.document.path == exodus


def test_book_selector_lists_a_projects_books_and_opens_them_into_the_group(desktop, tmp_path: Path):
    from uniti.core.environments.sfm.paratext_project import PARATEXT_BOOKS

    app, service = desktop
    project = tmp_path / "NIV11"
    present = "".join("1" if code in ("GEN", "EXO") else "0" for code in PARATEXT_BOOKS)
    _write(
        project,
        "Settings.xml",
        "<ScriptureText><Name>NIV11</Name><FullName>New International Version</FullName>"
        '<Naming PrePart="" PostPart="NIV11.SFM" BookNameForm="41MAT" />'
        f"<BooksPresent>{present}</BooksPresent></ScriptureText>",
    )
    _write(project, "BookNames.xml", '<BookNames><book code="GEN" short="Genesis" /></BookNames>')
    genesis = _write(project, "01GENNIV11.SFM", _GEN_A)
    exodus = _write(project, "02EXONIV11.SFM", _EXO)
    _write(project, "notes.usfm", "\\id REV\n")  # in the folder but not a project book
    main = service.new_window()
    view = main._usfm_projects.open_project(project)
    window = service.windows.window_for_view(view.view_id)
    bar = window._environment_bar
    window._rich_views.show("sfm.preview", view)

    # The id and the \h line; a book without \h (GEN here) shows its id
    # alone, even though BookNames.xml names it.
    assert [bar.book.itemText(index) for index in range(bar.book.count())] == ["GEN", "EXO Exodus"]
    assert window.windowTitle() == "UNITI — USFM A — NIV11 — 01GENNIV11.SFM"
    assert "NIV11" in bar.project_label.text()
    assert "New International Version" not in bar.project_label.toolTip()  # the short name only

    # Regrouped, the book stays in its window (round 3 T3); a book chosen
    # there opens into this window, in the current book's group.
    _group(window, service, view, "A")
    assert service.windows.window_for_view(view.view_id) is window
    opened = window._environment_bar.open_book(exodus)

    assert opened is window.current_view and opened.document.path == exodus
    assert service.documents.entry_for_view(opened.view_id).group_id == "A"
    # The new book opens in the mode the previous tab was in, as USFM.
    assert window._rich_views.key_for(opened) == "sfm.preview"
    assert window._environment.environment_key_for(opened.document) == "usfm"
    assert genesis.exists()


def test_chapter_and_verse_selectors_navigate_and_follow_the_caret(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(view)
    bar = window._environment_bar
    assert [bar.chapter.itemText(i) for i in range(bar.chapter.count())] == ["1", "2"]

    bar.chapter.setCurrentIndex(1)
    bar._chapter_chosen(1)
    assert view.state.cursor == _GEN_A.index("\\c 2")
    assert [bar.verse.itemText(i) for i in range(bar.verse.count())] == ["1"]

    bar.chapter.setCurrentIndex(0)
    bar._chapter_chosen(0)
    bar.verse.setCurrentIndex(1)
    bar._verse_chosen(1)
    assert view.state.cursor == _GEN_A.index("\\v 2")

    # Moving the caret updates the selectors without navigating.
    view.state.move_to(_GEN_A.index("again"))
    view._state_changed()
    assert (bar.chapter.currentText(), bar.verse.currentText()) == ("2", "1")


def test_mode_buttons_switch_the_tab_in_place(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(view)
    bar = window._environment_bar
    assert list(bar.mode_actions) == [None, "sfm.standard", "sfm.preview"]
    assert bar.mode_actions[None].isChecked()

    bar.mode_actions["sfm.preview"].trigger()
    pane = window._rich_views.pane_for(view)
    assert pane is not None and pane.parent() is view
    assert bar.mode_actions["sfm.preview"].isChecked()
    assert pane.mode.isVisible() is False  # the toolbar holds the switch

    bar.mode_actions[None].trigger()
    assert window._rich_views.pane_for(view) is None
    assert view.rich_view_key is None


def _side_by_side(service, tmp_path: Path, right_group: str = "A"):
    main = service.new_window()
    left = main.open_path(_write(tmp_path / "a", "01GEN.usfm", _GEN_A))
    right_document = main.open_path(_write(tmp_path / "b", "01GEN.usfm", _GEN_B))
    _group(main, service, left, "A")
    _group(main, service, right_document, right_group)
    main._select_view(left)
    clone = main.split_right()
    right_leaf = main.panes.leaf_for_view(clone.view_id)
    entry = service.documents.entry_for_view(right_document.view_id)
    right = main.assign_document_to_pane(entry.document_id, right_leaf.pane_id)
    # Only the second file stays on the right (the split's clone of the left
    # file would itself be a same-group, same-book target).
    main._close_view_id(clone.view_id)
    main._select_view(left)
    return main, left, right


def test_sync_shows_a_matching_tab_in_the_other_split(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    left = main.open_path(_write(tmp_path / "a", "01GEN.usfm", _GEN_A))
    exodus = main.open_path(_write(tmp_path / "b", "02EXO.usfm", _EXO))
    genesis_b = main.open_path(_write(tmp_path / "b", "01GEN.usfm", _GEN_B))
    for view in (left, exodus, genesis_b):
        _group(main, service, view, "A")
    main._select_view(left)
    clone = main.split_right()
    right_leaf = main.panes.leaf_for_view(clone.view_id)
    for view in (exodus, genesis_b):
        entry = service.documents.entry_for_view(view.view_id)
        main.assign_document_to_pane(entry.document_id, right_leaf.pane_id)
    main._close_view_id(clone.view_id)
    exodus_right = main.view_for_id(right_leaf.view_ids[0])
    right_leaf.select_view(exodus_right.view_id)
    main._select_view(left)
    assert right_leaf.active_view.document.path.name == "02EXO.usfm"

    left.state.move_to(_GEN_A.index("Alpha two"))
    left._state_changed()
    assert main._reference_sync.sync_from(left) == 1

    shown = right_leaf.active_view
    assert shown.document.path.name == "01GEN.usfm" and shown.document is genesis_b.document
    assert shown.state.cursor == _GEN_B.index("\\v 2")
    assert main.current_view is left


def test_side_by_side_files_of_one_group_sync_by_reference(desktop, tmp_path: Path):
    app, service = desktop
    main, left, right = _side_by_side(service, tmp_path)
    assert main.current_view is left

    left.state.move_to(_GEN_A.index("Alpha two"))
    left._state_changed()
    moved = main._reference_sync.sync_from(left)

    assert moved == 1
    assert right.state.cursor == _GEN_B.index("\\v 2")
    assert main.current_view is left  # sync never steals the active tab
    # The matched verse is highlighted on both sides.
    assert set(right._line_highlights) == {right.document.line_for_char(_GEN_B.index("\\v 2"))}
    assert set(left._line_highlights) == {left.document.line_for_char(_GEN_A.index("\\v 2"))}

    left.state.move_to(_GEN_A.index("Alpha again"))
    left._state_changed()
    main._reference_sync.sync_from(left)
    assert right.state.cursor == _GEN_B.index("\\v 1 Beta again")


def test_files_of_different_groups_do_not_sync(desktop, tmp_path: Path):
    app, service = desktop
    main, left, right = _side_by_side(service, tmp_path, right_group="B")
    before = right.state.cursor

    left.state.move_to(_GEN_A.index("Alpha two"))
    left._state_changed()

    assert main._reference_sync.sync_from(left) == 0
    assert right.state.cursor == before
    assert not left._line_highlights


def test_sync_can_be_turned_off(desktop, tmp_path: Path):
    app, service = desktop
    main, left, right = _side_by_side(service, tmp_path)
    main._reference_sync.action.setChecked(False)
    before = right.state.cursor

    left.state.move_to(_GEN_A.index("Alpha two"))
    left._state_changed()
    main._reference_sync._sync_now()

    assert right.state.cursor == before


def test_plain_text_files_get_an_environment_window(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "notes.txt", "hello"))
    _group(main, service, view, "A")
    main._select_view(view)
    assert main._environment.move_to_window_action.isEnabled()

    window = main.move_to_environment_window(view)

    assert window.environment_window == ("plain_text", 0)
    assert window.windowTitle() == "UNITI — Plain Text A — notes.txt"
    bar = window._environment_bar
    assert list(bar.mode_actions) == [None]  # no rich views for plain text
    assert bar.book.isHidden() and bar.chapter.isHidden()
    # Already home: the entry is there but has nothing to do.
    assert window._environment.move_to_window_action.isEnabled() is False


def _usfm_window(service, tmp_path: Path):
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    _group(main, service, view, "A")
    return main, main.move_to_environment_window(view)


def test_a_file_opened_in_an_environment_window_lives_there(desktop, tmp_path: Path):
    app, service = desktop
    _main, window = _usfm_window(service, tmp_path)
    asked = []
    window._confirm_environment_pin = lambda path, key: asked.append(path.name) or True

    opened = window.open_path(_write(tmp_path, "02EXO.usfm", _EXO))

    assert asked == []  # .usfm belongs to USFM: no question
    assert window.view_for_id(opened.view_id) is opened
    entry = service.documents.entry_for_view(opened.view_id)
    # Windows don't stand for a group (round 3 T3); a book takes its
    # project's group (T5), and GEN put the project in A.
    assert entry.group_id == "A" and entry.environment_override is None


def test_an_unknown_extension_asks_before_it_is_pinned(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    readme = main.open_path(_write(tmp_path / "docs", "readme.md", "# Notes\n"))
    window = main.move_to_environment_window(readme)
    notes = _write(tmp_path / "docs", "notes.txt", "plain words\n")

    window._confirm_environment_pin = lambda path, key: False
    assert window.open_path(notes) is None
    assert service.documents.find_path(notes) is None

    asked = []
    window._confirm_environment_pin = lambda path, key: asked.append((path.name, key)) or True
    opened = window.open_path(notes)

    assert asked == [("notes.txt", "markdown")]
    assert window.view_for_id(opened.view_id) is opened
    entry = service.documents.entry_for_view(opened.view_id)
    assert entry.environment_override == "markdown"
    assert window._environment.environment_key_for(opened.document) == "markdown"
    assert window._environment.menu.title() == "Markdown"


def test_a_projects_file_of_any_extension_opens_in_usfm_without_a_question(desktop, tmp_path: Path):
    app, service = desktop
    _main, window = _usfm_window(service, tmp_path)
    notes = _write(tmp_path, "notes.txt", "\\p plain words\n")  # tmp_path is the project
    asked = []
    window._confirm_environment_pin = lambda path, key: asked.append(path.name) or True

    opened = window.open_path(notes)

    assert asked == [] and window.view_for_id(opened.view_id) is opened
    assert window._environment.environment_key_for(opened.document) == "usfm"


def test_opening_a_file_open_elsewhere_moves_it_into_the_environment_window(desktop, tmp_path: Path):
    app, service = desktop
    main, window = _usfm_window(service, tmp_path)
    exodus = main.open_path(_write(tmp_path, "02EXO.usfm", _EXO))
    home = main.view_location(exodus.view_id)

    opened = window.open_path(exodus.document.path)

    assert opened is exodus and window.view_for_id(exodus.view_id) is exodus
    assert exodus.dock_return is not None and exodus.dock_return.window_id == home.window_id


def test_assigning_an_environment_moves_the_file_into_its_window(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    ensure_project(tmp_path)  # USFM assumes a project (round 3 T1)
    view = main.open_path(_write(tmp_path, "notes.txt", "\\p words\n"))
    _group(main, service, view, "A")

    main._environment.set_document_environment("usfm", view)

    # Plain Text's group A isn't one of USFM's groups (round 3 T2): the file
    # leaves its group as it changes environment.
    assert service.documents.entry_for_view(view.view_id).group_id is None
    window = service.environment_window_for("usfm", 0)
    assert window is not None and window.view_for_id(view.view_id) is view

    # Re-assigned inside an environment window: it moves to the new one.
    window._environment.set_document_environment("plain_text", view)
    plain = service.environment_window_for("plain_text", 0)
    assert plain is not None and plain.view_for_id(view.view_id) is view


def test_the_reference_selector_sits_right_with_fixed_widths(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "02EXO.usfm", _EXO))
    window = main.move_to_environment_window(view)
    window.resize(1400, 700)
    app.processEvents()
    bar = window._environment_bar
    em = bar.chapter.fontMetrics().horizontalAdvance("M")

    # Display areas of 10 em (Book) and 3 em (Chapter, Verse).
    assert bar.chapter.width() == bar.verse.width()
    assert abs((bar.book.width() - bar.chapter.width()) - (round(10 * em) - round(3 * em))) <= 2
    assert bar.book.currentText() == "EXO Exodus"
    # Right-aligned: the selector ends at the toolbar's right edge, after the mode switch.
    assert bar.width() - bar.verse.geometry().right() < 4 * em
    mode_button = bar.widgetForAction(bar.mode_actions[None])
    assert bar.book.geometry().left() > mode_button.geometry().right() + 10 * em


# --- R4: highlight the verse on a jump ----------------------------------------------


def _lines_of(view, start: int, end: int) -> set[int]:
    document = view.document
    return set(range(document.line_for_char(start), document.line_for_char(end - 1) + 1))


def test_choosing_a_verse_highlights_it_in_every_mode(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(view)
    bar = window._environment_bar
    bar.chapter.setCurrentIndex(0)
    bar._chapter_chosen(0)

    bar.verse.setCurrentIndex(1)
    bar._verse_chosen(1)

    verse_start = _GEN_A.index("\\v 2")
    verse_end = _GEN_A.index("\\c 2")
    assert view.state.cursor == verse_start
    assert set(view._line_highlights) == _lines_of(view, verse_start, verse_end)
    # A rich view opened afterwards shows the same verse highlighted.
    window._rich_views.show("sfm.preview", view)
    assert window._rich_views.pane_for(view)._highlight == (verse_start, verse_end)

    # Leaving the verse clears it.
    view.state.move_to(_GEN_A.index("Alpha again"))
    view._state_changed()
    assert not view._line_highlights
    assert window._rich_views.pane_for(view)._highlight is None


def test_choosing_a_chapter_highlights_its_line(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(view)
    bar = window._environment_bar

    bar.chapter.setCurrentIndex(1)
    bar._chapter_chosen(1)

    chapter = _GEN_A.index("\\c 2")
    assert view.state.cursor == chapter
    assert set(view._line_highlights) == {view.document.line_for_char(chapter)}


def test_go_to_chapter_verse_highlights_the_verse(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))

    assert main._environment.run_command("go_to", "1:2") is True

    verse_start = _GEN_A.index("\\v 2")
    assert view.state.cursor == verse_start
    assert set(view._line_highlights) == _lines_of(view, verse_start, _GEN_A.index("\\c 2"))

    main._environment.run_command("go_to", "2:1")
    assert set(view._line_highlights) == {view.document.line_for_char(_GEN_A.index("\\v 1 Alpha again"))}


def test_a_jump_highlight_survives_side_by_side_sync(desktop, tmp_path: Path):
    app, service = desktop
    main, left, right = _side_by_side(service, tmp_path)

    main._environment.run_command("go_to", "1:2")
    main._reference_sync.sync_from(left)

    assert left._line_highlights  # still highlighted after the sync cleared others
    assert right.state.cursor == _GEN_B.index("\\v 2")
    assert right._line_highlights


# --- R6: "Open in <Environment> / Open as Plain Text" -------------------------------


@pytest.fixture
def answer(monkeypatch):
    """Answer the open dialog with `answer.mode`; records each question."""

    from uniti.ui import open_mode

    class Answer:
        mode = open_mode.OpenMode.ENVIRONMENT
        asked: list[tuple[str, str, int]] = []

    def prompt(parent, path, label, count=1):
        Answer.asked.append((path.name, label, count))
        return Answer.mode

    Answer.asked = []
    monkeypatch.setattr(open_mode, "prompt_open_mode", prompt)
    return Answer


def test_opening_in_the_environment_puts_the_file_in_its_window(desktop, tmp_path: Path, answer):
    app, service = desktop
    main = service.new_window()

    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))

    assert answer.asked == [("01GEN.usfm", "USFM", 1)]
    window = service.windows.window_for_view(view.view_id)
    assert window is not main and window.environment_window == ("usfm", 0)


def test_opening_as_plain_text_has_no_extended_features(desktop, tmp_path: Path, answer):
    from uniti.ui.open_mode import OpenMode

    app, service = desktop
    main = service.new_window()
    answer.mode = OpenMode.PLAIN_TEXT

    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))

    assert service.windows.window_for_view(view.view_id) is main
    assert service.documents.entry_for_view(view.view_id).environment_override == "plain_text"
    assert view.syntax_profile.key == "plain_text"
    assert main._environment.menu.title() == "Plain Text"
    assert main._rich_views.providers_for(view) == ()
    assert main._environment.command_available("go_to", view) is False


def test_cancel_opens_nothing(desktop, tmp_path: Path, answer):
    app, service = desktop
    main = service.new_window()
    answer.mode = None
    path = _write(tmp_path, "01GEN.usfm", _GEN_A)

    assert main.open_path(path) is None
    assert service.documents.find_path(path) is None


def test_no_question_for_plain_text_open_files_or_environment_windows(desktop, tmp_path: Path, answer):
    from uniti.ui.open_mode import OpenMode

    app, service = desktop
    main = service.new_window()
    main.open_path(_write(tmp_path, "notes.txt", "hello"))
    assert answer.asked == []  # plain text: nothing to choose

    answer.mode = OpenMode.HERE
    genesis = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(genesis)
    answer.asked.clear()

    assert main.open_path(genesis.document.path) is genesis  # already open: focused
    window.open_path(_write(tmp_path, "02EXO.usfm", _EXO))  # inside an environment window
    assert answer.asked == []


def test_a_recent_file_opens_in_the_environment_with_its_group(desktop, tmp_path: Path, answer):
    app, service = desktop
    main = service.new_window()
    path = _write(tmp_path, "01GEN.usfm", _GEN_A)
    main._recent_files_store.record_opened(path, group_id="A")

    main._open_recent_file(str(path))

    entry = service.documents.find_path(path)
    window = service.windows.window_for_view(entry.view_ids[0])
    assert window.environment_window == ("usfm", 0) and entry.group_id == "A"


def test_open_folder_by_type_asks_once_for_the_batch(desktop, tmp_path: Path, answer, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QInputDialog

    app, service = desktop
    main = service.new_window()
    folder = tmp_path / "books"
    _write(folder, "01GEN.usfm", _GEN_A)
    _write(folder, "02EXO.usfm", _EXO)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(folder))
    def pick(_parent, _title, _label, items, *args, **kwargs):
        # The only file type, then "No Group".
        return (items[0] if "No Group" not in items else "No Group"), True

    monkeypatch.setattr(QInputDialog, "getItem", pick)

    main.open_folder_by_type()

    assert answer.asked == [("01GEN.usfm", "USFM", 2)]
    window = service.environment_window_for("usfm", 0)
    assert window is not None and len(window.views) == 2


# --- R8: configuration files from an environment window -----------------------------


def test_configuration_files_open_in_an_ordinary_window(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path / "project", "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(view)

    dialog = window._environment.show_configuration_files(view)
    dialog.select_role("Project custom stylesheet")
    opened = dialog.create_selected()

    # Not pinned into the USFM window: a stylesheet is edited as plain text.
    assert service.windows.window_for_view(opened.view_id) is main
    assert opened.document.path == tmp_path / "project" / "custom.sty"
    assert main._environment.environment_key_for(opened.document) == "plain_text"


# --- P4: versification --------------------------------------------------------------


def test_a_texts_versification_can_be_chosen_and_is_saved(desktop, tmp_path: Path):
    from types import SimpleNamespace

    from uniti.app.session_controller import SessionController
    from uniti.app.session_runtime import capture_service_session

    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "19PSA.usfm", "\\id PSA\n\\c 51\n\\p\n\\v 1 Have mercy.\n"))
    environment = main._environment
    actions = environment.versification_actions
    assert actions[None].text() == "Project (English)" and actions[None].isChecked()
    assert {"eng", "org"} <= set(actions)

    actions["org"].trigger()

    entry = service.documents.entry_for_view(view.view_id)
    assert entry.versification == "org"
    assert environment.versification_for(view.document).stem == "org"
    assert environment.versification_actions["org"].isChecked()

    snapshot = capture_service_session(
        service, clean_shutdown=True, generation="g", service_id="s", build_identity="t",
        created_at="2026-10-08T00:00:00Z", updated_at="2026-10-08T00:00:00Z",
    )
    record = next(item for item in snapshot.manifest.documents if item.document_id == entry.document_id)
    assert record.extra["versification"] == "org"
    restored = SimpleNamespace(versification=None, environment_override=None, environment_key="usfm")
    SessionController._restore_entry_environment(restored, record)
    assert restored.versification == "org"


# --- P5: sync across books and versifications ---------------------------------------

_PSA_A = "\\id PSA A\n\\c 51\n\\p\n\\v 1 Have mercy.\n\\v 2 Wash me.\n\\v 3 For I know.\n"
_PSA_B = "\\id PSA B\n\\c 51\n\\d Title\n\\p\n\\v 1 For the director.\n\\v 2 When Nathan.\n\\v 3 Have mercy.\n"


def _two_splits(service, left_path: Path, right_path: Path, group: str = "A"):
    main = service.new_window()
    left = main.open_path(left_path)
    right_document = main.open_path(right_path)
    _group(main, service, left, group)
    _group(main, service, right_document, group)
    main._select_view(left)
    clone = main.split_right()
    leaf = main.panes.leaf_for_view(clone.view_id)
    entry = service.documents.entry_for_view(right_document.view_id)
    right = main.assign_document_to_pane(entry.document_id, leaf.pane_id)
    main._close_view_id(clone.view_id)
    main._select_view(left)
    return main, left, right, leaf


def test_sync_maps_the_reference_into_each_texts_versification(desktop, tmp_path: Path):
    app, service = desktop
    main, left, right, _leaf = _two_splits(
        service, _write(tmp_path / "en", "19PSA.usfm", _PSA_A), _write(tmp_path / "orig", "19PSA.usfm", _PSA_B)
    )
    main._environment.set_versification("org", right)  # numbered like the original text

    left.state.move_to(_PSA_A.index("Have mercy"))
    left._state_changed()
    assert main._reference_sync.sync_from(left) == 1

    # English Ps 51:1 is the original's 51:3.
    assert right.state.cursor == _PSA_B.index("\\v 3")


def _niv_project(folder: Path) -> Path:
    from uniti.core.environments.sfm.paratext_project import PARATEXT_BOOKS

    present = "".join("1" if code in ("GEN", "EXO") else "0" for code in PARATEXT_BOOKS)
    _write(
        folder,
        "Settings.xml",
        "<ScriptureText><Name>NIV</Name>"
        f'<Naming PrePart="" PostPart="NIV.SFM" BookNameForm="41MAT" /><BooksPresent>{present}</BooksPresent>'
        "</ScriptureText>",
    )
    _write(folder, "01GENNIV.SFM", _GEN_B)
    return _write(folder, "02EXONIV.SFM", _EXO)


def test_a_project_split_opens_its_own_book_to_follow(desktop, tmp_path: Path):
    app, service = desktop
    exodus = _niv_project(tmp_path / "NIV")
    main, left, right, leaf = _two_splits(service, _write(tmp_path / "mine", "01GEN.usfm", _GEN_A), exodus)
    main._rich_views.show("sfm.preview", right)

    left.state.move_to(_GEN_A.index("Alpha two"))
    left._state_changed()
    assert main._reference_sync.sync_from(left) == 1

    shown = leaf.active_view
    assert shown.document.path == tmp_path / "NIV" / "01GENNIV.SFM"
    assert shown.state.cursor == _GEN_B.index("\\v 2")
    assert main.current_view is left  # activation stays with the source
    assert service.documents.entry_for_view(shown.view_id).group_id == "A"
    assert main._rich_views.key_for(shown) == "sfm.preview"  # the split's mode carries over
    assert shown.view_id not in main._environment.undefined_dialogs  # no popup from a sync


def test_a_single_file_without_the_book_stays_with_a_notice(desktop, tmp_path: Path):
    app, service = desktop
    main, left, right, leaf = _two_splits(
        service, _write(tmp_path / "a", "01GEN.usfm", _GEN_A), _write(tmp_path / "b", "02EXO.usfm", _EXO)
    )
    before = right.state.cursor

    left.state.move_to(_GEN_A.index("Alpha two"))
    left._state_changed()

    assert main._reference_sync.sync_from(left) == 0
    assert leaf.active_view is right and right.state.cursor == before
    assert main.statusBar().currentMessage().startswith("GEN isn't in 02EXO.usfm")


def test_choosing_a_book_carries_the_groups_splits_along(desktop, tmp_path: Path):
    app, service = desktop
    niv_exodus = _niv_project(tmp_path / "NIV")
    niv_genesis = tmp_path / "NIV" / "01GENNIV.SFM"
    mine = tmp_path / "mine"
    _write(mine, "02EXO.usfm", _EXO)
    main = service.new_window()
    left = main.open_path(_write(mine, "01GEN.usfm", _GEN_A))
    right = main.open_path(niv_genesis)
    for view in (left, right):
        _group(main, service, view, "A")
    window = main.move_to_environment_window(left)
    main.move_to_environment_window(right)
    window._select_view(left)
    clone = window.split_right()
    right_leaf = window.panes.leaf_for_view(clone.view_id)
    entry = service.documents.entry_for_view(right.view_id)
    window.assign_document_to_pane(entry.document_id, right_leaf.pane_id)
    window._close_view_id(clone.view_id)
    window._select_view(left)
    assert right_leaf.active_view.document.path == niv_genesis

    window._environment_bar.open_book(mine / "02EXO.usfm")

    assert window.current_view.document.path == mine / "02EXO.usfm"
    # The project text follows to its own EXO, in its split.
    assert right_leaf.active_view.document.path == niv_exodus


def test_sync_falls_back_to_the_same_reference_when_the_text_lacks_the_mapped_verse(desktop, tmp_path: Path):
    """The target says it is numbered like the original text, but its text
    is numbered like English: Mal 4:1 (Original 3:19) isn't there, 4:1 is."""

    malachi = "\\id MAL {}\n\\c 3\n\\p\n" + "".join(f"\\v {v} V{v}.\n" for v in range(1, 19)) + "\\c 4\n\\p\n\\v 1 Surely the day.\n"
    main, left, right, _leaf = _two_splits(
        service=desktop[1],
        left_path=_write(tmp_path / "a", "39MAL.usfm", malachi.format("A")),
        right_path=_write(tmp_path / "b", "39MAL.usfm", malachi.format("B")),
    )
    main._environment.set_versification("org", right)
    text = malachi.format("A")

    left.state.move_to(text.index("Surely"))
    left._state_changed()
    assert main._reference_sync.sync_from(left) == 1
    assert right.state.cursor == malachi.format("B").index("\\v 1 Surely")


# --- the toolbar's Group dropdown ---------------------------------------------------


def _choose_group(bar, text: str) -> None:
    index = bar.group.findText(text)
    assert index >= 0, text
    bar.group.setCurrentIndex(index)
    bar._group_chosen(index)


def test_the_group_dropdown_shows_the_current_files_group(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(view)
    bar = window._environment_bar

    items = [bar.group.itemText(i) for i in range(bar.group.count()) if bar.group.itemText(i)]
    assert items == ["Ungrouped", "A", "B", "C", "New Group…", "Manage Groups…"]
    assert bar.group.currentText() == "Ungrouped"


def test_choosing_a_group_sets_the_current_files_group_only(desktop, tmp_path: Path):
    """Round 3 T3: the dropdown is the current file's group; nothing moves."""

    app, service = desktop
    main = service.new_window()
    left = main.open_path(_write(tmp_path / "a", "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(left)
    right = window.open_path(_write(tmp_path / "b", "01GEN.usfm", _GEN_B))
    window._select_view(left)

    _choose_group(window._environment_bar, "A")

    assert window.environment_window == ("usfm", 0)
    assert service.documents.entry_for_view(left.view_id).group_id == "A"
    assert service.documents.entry_for_view(right.view_id).group_id is None
    assert all(service.windows.window_for_view(v.view_id) is window for v in (left, right))
    assert window._environment_bar.group.currentText() == "A"
    window._select_view(right)
    assert window._environment_bar.group.currentText() == "Ungrouped"
    assert window.windowTitle().startswith("UNITI — USFM A")


def test_new_group_from_the_dropdown(desktop, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(view)
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Translators", True))

    _choose_group(window._environment_bar, "New Group…")

    group_id = service.documents.entry_for_view(view.view_id).group_id
    assert window._group_by_id(group_id, "usfm").name == "Translators"
    assert window._environment_bar.group.currentText() == "Translators"


# --- Round 3 T3: window names ---------------------------------------------------------


def test_a_window_can_be_renamed_and_keeps_its_name(desktop, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    app, service = desktop
    main = service.new_window()
    view = main.open_path(_write(tmp_path, "01GEN.usfm", _GEN_A))
    window = main.move_to_environment_window(view)
    window._environment.refresh()
    assert window._environment.rename_window_action is not None
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Compare", True))

    window._environment.rename_window_action.trigger()

    assert window.environment_window_name() == "USFM Compare"
    assert window._environment_bar.title.text() == "USFM Compare"
    assert window.windowTitle().startswith("UNITI — USFM Compare — TST")
    # The name belongs to the slot: saved with the environment's settings.
    saved = tmp_path / "Environments" / "USFM" / "windows.json"
    assert saved.is_file() and "Compare" in saved.read_text(encoding="utf-8")
    # A second window is still "USFM B"; Plain Text windows have their own names.
    assert service.new_environment_window("usfm").environment_window_name() == "USFM B"
    assert service.new_environment_window("plain_text").environment_window_name() == "Plain Text A"
    # Names stay different.
    from PySide6.QtWidgets import QMessageBox

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args, **kwargs: warnings.append(args[2]))
    assert window.rename_environment_window("B") is False
    assert warnings == ["Window names must be different"]


def test_a_closed_windows_slot_is_reused(desktop, tmp_path: Path):
    app, service = desktop
    first = service.new_environment_window("usfm")
    second = service.new_environment_window("usfm")
    assert (first.environment_window, second.environment_window) == (("usfm", 0), ("usfm", 1))

    first.close()
    app.processEvents()

    assert service.new_environment_window("usfm").environment_window == ("usfm", 0)


# --- Round 3 T1: USFM assumes a Paratext project -------------------------------------


def _loose(folder: Path, name: str, text: str) -> Path:
    """A USFM file outside any project (no Settings.xml)."""

    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def test_a_usfm_file_outside_a_project_opens_as_plain_text(desktop, tmp_path: Path, answer):
    app, service = desktop
    main = service.new_window()

    view = main.open_path(_loose(tmp_path / "loose", "01GEN.usfm", _GEN_A))

    assert answer.asked == []  # no "Open in USFM Environment?" question
    assert service.windows.window_for_view(view.view_id) is main
    assert main._environment.environment_key_for(view.document) == "plain_text"
    assert main._environment.menu.title() == "Plain Text"
    assert main._rich_views.providers_for(view) == ()
    assert main.statusBar().currentMessage() == "01GEN.usfm isn't in a Paratext project: opened as plain text"
    assert service.environment_window_for("usfm", None) is None

    # A project book still opens in USFM.
    book = main.open_path(_write(tmp_path / "proj", "01GEN.usfm", _GEN_A))
    assert answer.asked == [("01GEN.usfm", "USFM", 1)]
    assert service.windows.window_for_view(book.view_id).environment_window[0] == "usfm"


def test_a_usfm_window_opens_a_file_outside_a_project_as_plain_text_elsewhere(desktop, tmp_path: Path):
    app, service = desktop
    main, window = _usfm_window(service, tmp_path / "proj")
    asked = []
    window._confirm_environment_pin = lambda path, key: asked.append(path.name) or True

    opened = window.open_path(_loose(tmp_path / "loose", "02EXO.usfm", _EXO))

    assert asked == []
    home = service.windows.window_for_view(opened.view_id)
    assert home is not window and home.environment_window is None
    assert home._environment.environment_key_for(opened.document) == "plain_text"


def test_usfm_is_not_offered_for_a_file_outside_a_project(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_loose(tmp_path / "loose", "notes.txt", "\\p words\n"))
    environment = main._environment
    environment.refresh()

    action = environment.document_environment_actions["usfm"]
    assert not action.isEnabled() and action.text() == "USFM (needs a Paratext project)"

    environment.set_document_environment("usfm", view)

    assert environment.environment_key_for(view.document) == "plain_text"
    assert service.documents.entry_for_view(view.view_id).environment_override is None
    assert service.windows.window_for_view(view.view_id) is main
    assert main.statusBar().currentMessage() == "notes.txt isn't in a Paratext project, so it can't be USFM"


def test_a_restored_usfm_pin_outside_a_project_is_plain_text(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    view = main.open_path(_loose(tmp_path / "loose", "notes.txt", "\\p words\n"))
    entry = service.documents.entry_for_view(view.view_id)
    entry.environment_override = "usfm"  # as a session saved before T1 restores it

    assert main._environment.environment_key_for(view.document) == "plain_text"


def test_open_folder_by_type_opens_files_outside_a_project_as_plain_text(desktop, tmp_path: Path, answer, monkeypatch):
    from PySide6.QtWidgets import QFileDialog, QInputDialog

    app, service = desktop
    main = service.new_window()
    folder = tmp_path / "loose"
    _loose(folder, "01GEN.usfm", _GEN_A)
    _loose(folder, "02EXO.usfm", _EXO)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *args, **kwargs: str(folder))
    monkeypatch.setattr(
        QInputDialog, "getItem", lambda _p, _t, _l, items, *a, **k: (items[0] if "No Group" not in items else "No Group", True)
    )

    main.open_folder_by_type()

    assert answer.asked == []
    assert len(main.views) == 2
    assert all(main._environment.environment_key_for(view.document) == "plain_text" for view in main.views)
    assert main.statusBar().currentMessage() == "2 files aren't in a Paratext project: opened as plain text"
