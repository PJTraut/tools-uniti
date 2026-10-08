"""Environment windows, the USFM Book/Chapter/Verse selector, and
side-by-side reference sync (ADR-0017, 2026-10-07 field test)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

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
    path = folder / name
    path.write_text(text, encoding="utf-8")
    return path


def _group(window, service, view, group_id: str) -> None:
    if window._group_by_id(group_id) is None:
        window._groups = window._groups + (DocumentGroup(group_id, f"Group {group_id}", "#61afef"),)
    entry = service.documents.entry_for_view(view.view_id)
    window._set_document_group(entry.document_id, group_id)


def test_move_to_environment_window_groups_files_by_environment_and_group(desktop, tmp_path: Path):
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
    assert usfm_a.environment_window == ("usfm", "A")
    assert usfm_a.current_view is first
    assert usfm_a._environment_bar is not None
    assert usfm_a.windowTitle() == "UNITI — USFM — A — 01GEN.usfm"
    # The tab's own mode selector moves to the window's toolbar.
    assert usfm_a._rich_views.pane_mode_selector is False

    assert main.move_to_environment_window(second) is usfm_a  # same group: same window
    usfm_b = main.move_to_environment_window(third)
    assert usfm_b not in (main, usfm_a) and usfm_b.environment_window == ("usfm", "B")

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
    assert record.extra[ENVIRONMENT_WINDOW_EXTRA] == {"environment": "usfm", "group": "A"}
    window_record = next(item for item in snapshot.manifest.windows if item.window_id == window.window_id)
    views = {item.view_id: item for item in snapshot.manifest.views}
    assert environment_window_identity(window_record.root, views) == ("usfm", "A")
    main_record = next(item for item in snapshot.manifest.windows if item.window_id == main.window_id)
    assert environment_window_identity(main_record.root, views) is None


def test_book_selector_lists_the_groups_open_single_files(desktop, tmp_path: Path):
    """Outside a Paratext project the Book list is the group's open files,
    never a scan of the folder (plan P3)."""

    app, service = desktop
    folder = tmp_path / "loose"
    _write(folder, "41MAT.usfm", "\\id MAT\n\\c 1\n\\p\n\\v 1 Matthew.\n")  # on disk, not open
    exodus = _write(folder, "02EXO.usfm", _EXO)
    genesis = _write(folder, "01GEN.usfm", _GEN_A)
    other = _write(tmp_path / "elsewhere", "02EXO.usfm", _EXO)
    main = service.new_window()
    view = main.open_path(genesis)
    for path, group in ((exodus, "A"), (other, "B")):
        _group(main, service, main.open_path(path), group)
    _group(main, service, view, "A")
    window = main.move_to_environment_window(view)
    bar = window._environment_bar

    labels = [bar.book.itemText(index) for index in range(bar.book.count())]
    # The book id and its \h line (_GEN_A has no \h: the id alone).
    assert labels == ["GEN", "EXO Exodus"]
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

    # \h wins; BookNames.xml names a book without one (GEN here).
    assert [bar.book.itemText(index) for index in range(bar.book.count())] == ["GEN Genesis", "EXO Exodus"]
    assert window.windowTitle() == "UNITI — USFM — Ungrouped — NIV11 — 01GENNIV11.SFM"
    assert "NIV11" in bar.title.text()

    _group(window, service, view, "A")
    window.set_environment_window("usfm", "A")
    opened = bar.open_book(exodus) if window._environment_bar is bar else window._environment_bar.open_book(exodus)

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

    assert window.environment_window == ("plain_text", "A")
    assert window.windowTitle() == "UNITI — Plain Text — A — notes.txt"
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
    assert entry.group_id == "A" and entry.environment_override is None


def test_an_unknown_extension_asks_before_it_is_pinned(desktop, tmp_path: Path):
    app, service = desktop
    _main, window = _usfm_window(service, tmp_path)
    notes = _write(tmp_path, "notes.txt", "\\p plain words\n")

    window._confirm_environment_pin = lambda path, key: False
    assert window.open_path(notes) is None
    assert service.documents.find_path(notes) is None

    asked = []
    window._confirm_environment_pin = lambda path, key: asked.append((path.name, key)) or True
    opened = window.open_path(notes)

    assert asked == [("notes.txt", "usfm")]
    assert window.view_for_id(opened.view_id) is opened
    entry = service.documents.entry_for_view(opened.view_id)
    assert entry.environment_override == "usfm"
    assert window._environment.environment_key_for(opened.document) == "usfm"
    assert window._environment.menu.title() == "USFM"


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
    view = main.open_path(_write(tmp_path, "notes.txt", "\\p words\n"))
    _group(main, service, view, "A")

    main._environment.set_document_environment("usfm", view)

    window = service.environment_window_for("usfm", "A")
    assert window is not None and window.view_for_id(view.view_id) is view

    # Re-assigned inside an environment window: it moves to the new one.
    window._environment.set_document_environment("plain_text", view)
    plain = service.environment_window_for("plain_text", "A")
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
