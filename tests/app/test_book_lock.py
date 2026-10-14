"""USFM book lock (plan 2026-10-14-usfm-book-lock-plan, L1-L5)."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from test_service import _desktop_service, _stop_desktop_service  # noqa: E402
from usfm_project_fixture import ensure_project  # noqa: E402

pytestmark = pytest.mark.book_lock

_GEN = "\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 In the beginning.\r\n"
_EXO = "\\id EXO\r\n\\c 1\r\n\\p\r\n\\v 1 These are the names.\r\n"


@pytest.fixture
def desktop(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)


def test_save_without_changes_writes_nothing(desktop, tmp_path: Path):
    _app, service = desktop
    main = service.new_window()
    path = tmp_path / "note.txt"
    path.write_bytes(b"one\r\ntwo\r\n")
    os.utime(path, (1_000_000_000, 1_000_000_000))
    view = main.open_path(path)

    assert main.save_current() is None
    assert main.start_save_current() is None

    assert main.statusBar().currentMessage() == "note.txt has no changes: nothing saved"
    assert path.read_bytes() == b"one\r\ntwo\r\n"
    assert path.stat().st_mtime == 1_000_000_000
    assert not view.document.modified


def test_save_after_only_a_line_ending_change_still_writes(desktop, tmp_path: Path):
    from uniti.core.text_format import EOLPolicy, OutputFormat

    _app, service = desktop
    main = service.new_window()
    path = tmp_path / "note.txt"
    path.write_bytes(b"one\r\ntwo\r\n")
    view = main.open_path(path)
    document = view.document
    document.set_output_format(OutputFormat(encoding=document.output_format.encoding, eol=EOLPolicy.LF))
    assert document.modified

    assert main.save_current() == path
    assert path.read_bytes() == b"one\ntwo\n"


def _project(folder: Path, name: str = "NIV", gen: bytes | None = None) -> Path:
    ensure_project(folder, name=name)
    if gen is not None and b"\xe9" in gen:
        # A project that declares Windows-1252 opens its books in it.
        (folder / "Settings.xml").write_text(
            f"<ScriptureText><Name>{name}</Name><Encoding>1252</Encoding>"
            '<Naming PrePart="" PostPart=".usfm" BookNameForm="41MAT" /></ScriptureText>',
            encoding="utf-8",
        )
    (folder / "01GEN.usfm").write_bytes(_GEN.encode("utf-8") if gen is None else gen)
    (folder / "02EXO.usfm").write_bytes(_EXO.encode("utf-8"))
    return folder


def _usfm_window(service, folder: Path):
    main = service.new_window()
    view = main.open_path(folder / "01GEN.usfm")
    return main.move_to_environment_window(view), view


def _answers(monkeypatch, **answers):
    """Replace the lock's questions; each records its calls."""

    from uniti.ui import book_lock

    asked: dict[str, list] = {name: [] for name in answers}
    for name, answer in answers.items():

        def ask(*args, _name=name, _answer=answer, **kwargs):
            asked[_name].append(args[1:])
            return _answer

        monkeypatch.setattr(book_lock, name, ask)
    return asked


def test_a_book_opens_locked_in_the_usfm_window(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv")
    window, view = _usfm_window(service, niv)

    assert view.document.locked and view.read_only
    assert window.windowTitle().endswith("01GEN.usfm (locked)")
    leaf = window._panes.leaf_for_view(view.view_id)
    assert leaf.tabText(leaf.index_of(view.view_id)).startswith("🔒 NIV")
    window._rich_views.show("sfm.standard", view)
    assert window._rich_views.pane_for(view).editable is False


def test_typing_in_a_locked_book_says_it_is_locked(desktop, tmp_path: Path):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from PySide6.QtCore import QEvent

    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv"))

    view.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_A, Qt.KeyboardModifier.NoModifier, "a"))

    assert not view.document.modified
    assert window.statusBar().currentMessage() == (
        "GEN (NIV) is locked: right-click the Book list › Unlock to edit"
    )
    window.undo_current()
    assert not view.document.modified


def test_every_open_path_locks_the_book_and_reopening_locks_it_again(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)

    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")
    assert exodus.document.locked

    genesis.document.set_locked(False)
    window._close_service_view(genesis, force=True)
    again = window._environment_bar.open_book(niv / "01GEN.usfm")
    assert again.document.locked


def test_a_second_view_shares_the_lock_and_refreshes_when_it_changes(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv")
    window, view = _usfm_window(service, niv)
    other = service.new_environment_window("usfm")
    second = other.open_existing_document(view.document)

    assert second.document is view.document and second.read_only

    view.document.set_locked(False)

    assert not view.read_only and not second.read_only
    assert "(locked)" not in window.windowTitle()
    leaf = other._panes.leaf_for_view(second.view_id)
    assert not leaf.tabText(leaf.index_of(second.view_id)).startswith("🔒")


def test_plain_text_never_locks_a_book(desktop, tmp_path: Path):
    from uniti.ui.open_mode import OpenMode

    _app, service = desktop
    niv = _project(tmp_path / "niv")
    main = service.new_window()

    view = main.open_path(niv / "01GEN.usfm", open_mode=OpenMode.PLAIN_TEXT)

    assert not view.document.locked and not view.read_only


def test_a_modified_plain_text_book_stays_unlocked_when_it_becomes_usfm(desktop, tmp_path: Path):
    from uniti.ui.open_mode import OpenMode

    _app, service = desktop
    niv = _project(tmp_path / "niv")
    main = service.new_window()
    view = main.open_path(niv / "01GEN.usfm", open_mode=OpenMode.PLAIN_TEXT)
    view.document.insert(0, "\\rem x\r\n")

    main._environment.set_document_environment("usfm", view, move=False)

    assert not view.document.locked
    assert main.statusBar().currentMessage() == "01GEN.usfm has unsaved changes: it stays unlocked"


def test_a_plain_text_book_that_becomes_usfm_is_locked(desktop, tmp_path: Path):
    from uniti.ui.open_mode import OpenMode

    _app, service = desktop
    niv = _project(tmp_path / "niv")
    main = service.new_window()
    view = main.open_path(niv / "01GEN.usfm", open_mode=OpenMode.PLAIN_TEXT)

    main._environment.set_document_environment("usfm", view, move=False)

    assert view.document.locked


def test_save_on_a_locked_book_unlocks_and_saves_or_cancels(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    niv = _project(tmp_path / "niv")
    window, view = _usfm_window(service, niv)
    document = view.document
    document.set_locked(False)
    document.insert(0, "\\rem a\r\n")
    document.set_locked(True)
    path = niv / "01GEN.usfm"
    before = path.read_bytes()

    asked = _answers(monkeypatch, ask_unlock_and_save=False)
    assert window.save_current() is None
    assert asked["ask_unlock_and_save"] == [("GEN (NIV)",)]
    assert path.read_bytes() == before and document.locked

    _answers(monkeypatch, ask_unlock_and_save=True)
    assert window.save_current() == path
    assert path.read_bytes().startswith(b"\\rem a\r\n") and not document.locked and not document.modified


def test_the_close_prompt_for_a_locked_book_offers_unlock_and_save(desktop, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    _app, service = desktop
    niv = _project(tmp_path / "niv")
    window, view = _usfm_window(service, niv)
    document = view.document
    document.set_locked(False)
    document.insert(0, "\\rem a\r\n")
    document.set_locked(True)
    seen = []

    def fake_exec(box):
        seen.append(box.button(QMessageBox.StandardButton.Save).text())
        box.setProperty("answered", True)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda box: box.button(QMessageBox.StandardButton.Save))

    assert window._confirm_close(view)

    assert seen == ["Unlock and Save"]
    assert not document.modified and (niv / "01GEN.usfm").read_bytes().startswith(b"\\rem a")


def test_a_changed_book_leaving_its_tab_asks_save_or_discard(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    niv = _project(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    bar = window._environment_bar
    genesis.document.set_locked(False)
    genesis.document.insert(0, "\\rem a\r\n")
    path = niv / "01GEN.usfm"

    # Cancel: stays.
    asked = _answers(monkeypatch, ask_save_or_discard=None)
    assert bar.open_book(niv / "02EXO.usfm") is None
    assert window.current_view is genesis and genesis.document.modified
    assert asked["ask_save_or_discard"] == [("GEN (NIV)",)]

    # Discard: the book closes unsaved, and reopening reads the file.
    _answers(monkeypatch, ask_save_or_discard=False)
    exodus = bar.open_book(niv / "02EXO.usfm")
    assert window.current_view is exodus
    assert service.documents.find_path(path) is None
    assert path.read_bytes() == _GEN.encode()
    again = bar.open_book(path)
    assert again.document.read(0, 4) == "\\id " and not again.document.can_undo and again.document.locked


def test_save_leaving_the_tab_saves_a_locked_book(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    niv = _project(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    genesis.document.set_locked(False)
    genesis.document.insert(0, "\\rem a\r\n")
    genesis.document.set_locked(True)
    asked = _answers(monkeypatch, ask_save_or_discard=True)

    window._environment_bar.open_book(niv / "02EXO.usfm")

    assert asked["ask_save_or_discard"] == [("GEN (NIV)",)]
    assert (niv / "01GEN.usfm").read_bytes().startswith(b"\\rem a\r\n")
    assert not genesis.document.modified


def test_no_prompt_while_another_view_still_shows_the_book(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    niv = _project(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    other = service.new_environment_window("usfm")
    other.open_existing_document(genesis.document)
    genesis.document.set_locked(False)
    genesis.document.insert(0, "\\rem a\r\n")
    asked = _answers(monkeypatch, ask_save_or_discard=False)

    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")

    assert exodus is not None and asked["ask_save_or_discard"] == []
    assert genesis.document.modified


@pytest.mark.parametrize(
    ("content", "found"),
    [
        (b"\\id GEN\n\\c 1\n", "LF"),
        (b"\\id GEN\r\n\\c 1\n", "mixed"),
        (b"\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 Le caf\xe9, la cr\xe8me br\xfbl\xe9e et le th\xe9 \xe0 la fran\xe7aise.\r\n", "Windows-1252"),
    ],
)
def test_a_book_that_isnt_utf8_crlf_asks_update_and_stays_locked(desktop, tmp_path: Path, monkeypatch, content, found):
    app, service = desktop
    niv = _project(tmp_path / "niv", gen=content)
    path = niv / "01GEN.usfm"
    asked = _answers(monkeypatch, ask_update_or_close=True)
    main = service.new_window()

    view = main.open_path(path)
    app.processEvents()

    assert asked["ask_update_or_close"] == [("GEN (NIV)", found)]
    document = view.document
    assert document.locked and document.modified
    text = document.read(0, document.total_chars())
    assert "\n" not in text.replace("\r\n", "")
    assert document.output_format.encoding.codec == "utf-8"
    assert path.read_bytes() == content  # nothing written
    # Undo takes the conversion back (unlocked to do it: Undo is refused while locked).
    if found == "Windows-1252":
        assert not document.can_undo  # only the encoding changes: no text to take back
    else:
        document.set_locked(False)
        document.undo()
        assert document.read(0, document.total_chars()).count("\r") == content.count(b"\r")


def test_closing_a_book_that_isnt_utf8_crlf_writes_nothing(desktop, tmp_path: Path, monkeypatch):
    app, service = desktop
    niv = _project(tmp_path / "niv", gen=b"\\id GEN\n\\c 1\n")
    path = niv / "01GEN.usfm"
    _answers(monkeypatch, ask_update_or_close=False)
    main = service.new_window()

    main.open_path(path)
    app.processEvents()

    entry = service.documents.find_path(path)
    assert entry is None or not entry.view_ids  # closed
    assert path.read_bytes() == b"\\id GEN\n\\c 1\n"


def test_a_utf8_crlf_book_isnt_asked_about(desktop, tmp_path: Path, monkeypatch):
    app, service = desktop
    niv = _project(tmp_path / "niv")
    asked = _answers(monkeypatch, ask_update_or_close=True)

    service.new_window().open_path(niv / "01GEN.usfm")
    app.processEvents()

    assert asked["ask_update_or_close"] == []


def test_line_endings_and_encoding_are_off_while_a_book_is_locked(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv"))
    format_menu = next(action.menu() for action in window.menuBar().actions() if action.text() == "F&ormat")

    format_menu.aboutToShow.emit()
    assert not any(action.isEnabled() for action in format_menu.actions() if not action.isSeparator())
    window.set_output_eol("LF")
    assert view.document.output_eol != "LF"

    view.document.set_locked(False)
    format_menu.aboutToShow.emit()
    assert all(action.isEnabled() for action in format_menu.actions())


def test_replace_in_a_locked_book_asks_skip_or_unlock_and_replace(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv"))
    find = window._find_replace

    asked = _answers(monkeypatch, ask_unlock_and_replace=False)
    assert find._unlock_to_replace(view.document) is False
    assert view.document.locked and asked["ask_unlock_and_replace"] == [("GEN (NIV)",)]
    assert find._unlock_to_replace(view.document) is False  # the next Replace asks again
    assert len(asked["ask_unlock_and_replace"]) == 2

    _answers(monkeypatch, ask_unlock_and_replace=True)
    assert find._unlock_to_replace(view.document) is True
    assert not view.document.locked


def test_a_restored_or_adopted_book_with_no_view_yet_is_locked_when_its_view_is_added(desktop, tmp_path: Path):
    from uniti.core.document import Document

    # Session restore adopts the document into the registry first, then adds its view.
    _app, service = desktop
    niv = _project(tmp_path / "niv")
    main = service.new_window()
    document = Document.open(niv / "01GEN.usfm")
    service.documents.adopt(document, environment_key="usfm")

    view = main.open_existing_document(document)

    assert view.document.locked and view.read_only


# --- L3: Unlock Book / Lock Book ---------------------------------------------


def _menu_actions(menu) -> list:
    actions = []
    for action in menu.actions():
        actions.append(action)
        if action.menu() is not None:
            actions.extend(_menu_actions(action.menu()))
    return actions


def _lock_action(menu, text):
    return next((action for action in _menu_actions(menu) if action.text() == text), None)


def test_the_toolbar_button_unlocks_and_locks_the_shown_book(desktop, tmp_path: Path):
    from PySide6.QtWidgets import QToolButton

    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv"))
    button = window._environment_bar.lock_toggle

    action = window._book_lock.action
    assert isinstance(button, QToolButton) and button.text() == "🔒" and action.text() == "Unlock Book"
    assert button.isEnabled()
    button.click()
    assert not view.document.locked and not view.read_only and action.text() == "Lock Book"
    window._rich_views.show("sfm.standard", view)
    assert window._rich_views.pane_for(view).editable is True  # Standard edits after unlocking

    view.document.insert(0, "\\rem edited\r\n")
    button.click()  # locking with unsaved changes is allowed
    assert view.document.locked and view.document.modified and action.text() == "Unlock Book"
    assert window._rich_views.pane_for(view).editable is False


def test_the_usfm_menu_the_tab_menu_and_the_text_menu_have_it(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv"))

    usfm_menu = window._environment.menu
    assert window._book_lock.action in usfm_menu.actions()

    tab_menu = window.tab_menu(view.view_id)
    tab_action = _lock_action(tab_menu, "Unlock Book")
    assert tab_action is not None and tab_action is not window._book_lock.action
    tab_action.trigger()
    assert not view.document.locked

    text_menu = window._editor_context_menu(view)
    text_action = _lock_action(text_menu, "Lock Book")
    assert text_action is not None
    text_action.trigger()
    assert view.document.locked


def test_the_book_lists_right_click_menu_has_it(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv"))

    menu = window._environment_bar.book.lock_menu()

    assert [action.text() for action in menu.actions()] == ["Unlock Book"]
    menu.actions()[0].trigger()
    assert not view.document.locked


def test_a_book_in_a_read_only_folder_cant_be_unlocked(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "Paratext" / "niv")
    window, view = _usfm_window(service, niv)
    window.set_read_only_folders([str(tmp_path / "Paratext")])

    action = window._book_lock.action
    assert not action.isEnabled() and "read-only folder" in action.toolTip()
    assert str(tmp_path / "Paratext") in action.toolTip()
    assert window._book_lock.toggle(view) is True or view.document.read_only
    assert not _lock_action(window.tab_menu(view.view_id), "Unlock Book").isEnabled()


def test_a_plain_text_view_has_no_lock_to_change(desktop, tmp_path: Path):
    from uniti.ui.open_mode import OpenMode

    _app, service = desktop
    main = service.new_window()
    view = main.open_path(_project(tmp_path / "niv") / "01GEN.usfm", open_mode=OpenMode.PLAIN_TEXT)

    assert not main._book_lock.applies_to(view)
    assert _lock_action(main._editor_context_menu(view), "Unlock Book") is None


def test_saving_after_locking_again_asks_to_unlock(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    niv = _project(tmp_path / "niv")
    window, view = _usfm_window(service, niv)
    window._book_lock.toggle(view)
    view.document.insert(0, "\\rem a\r\n")
    window._book_lock.toggle(view)
    asked = _answers(monkeypatch, ask_unlock_and_save=True)

    assert window.save_current() == niv / "01GEN.usfm"

    assert asked["ask_unlock_and_save"] == [("GEN (NIV)",)] and not view.document.locked


# --- L4: the opt-in list and the project as the group ------------------------

_LEV = "\\id LEV\r\n\\c 1\r\n\\p\r\n\\v 1 And the LORD called.\r\n"
_NUM = "\\id NUM\r\n\\c 1\r\n\\p\r\n\\v 1 Count them.\r\n"


def _project_of_four(folder: Path) -> Path:
    _project(folder)
    (folder / "03LEV.usfm").write_bytes(_LEV.encode())
    (folder / "04NUM.usfm").write_bytes(_NUM.encode())
    return folder


def _replace_all(service, find, replace, scope):
    from uniti.ui.find_replace import ReplaceScope

    panel = service.find_replace
    panel.regex_checkbox.setChecked(True)
    panel.find_input.set_text(find)
    panel.replace_input.set_text(replace)
    _wait(service, lambda: panel.compile_current() is not None and panel._replacement_is_current())
    panel.replace_scope_combo.setCurrentIndex(panel.replace_scope_combo.findData(scope))
    panel.replace_all()
    _wait(service, lambda: not panel.busy and panel.status_label.text() not in ("", "Planning replacements"))
    return panel


def _wait(service, predicate, timeout: float = 8.0):
    import time

    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("condition did not become true")


def test_in_usfm_the_group_is_the_whole_project_opened_or_not(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)

    documents = service._documents_in_same_group(genesis.document)

    assert [Path(document.path).name for document in documents] == ["01GEN.usfm", "02EXO.usfm", "03LEV.usfm", "04NUM.usfm"]
    assert documents[0] is genesis.document
    assert len(service._transient_documents) == 3  # opened only to be searched
    for document in service._transient_documents:
        service.release_group_document(document)
    assert service._transient_documents == []


def test_replace_all_in_the_group_lists_files_with_matches_and_changes_only_ticked_ones(
    desktop, tmp_path: Path, monkeypatch
):
    from uniti.ui import replace_files
    from uniti.ui.find_replace import ReplaceScope

    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    window.activateWindow()
    seen = []

    def choose(parent, rows):
        seen.append(rows)
        return {2}  # only LEV, which isn't open

    monkeypatch.setattr(replace_files, "choose", choose)

    panel = _replace_all(service, "beginning|names|LORD", "X", ReplaceScope.CURRENT_GROUP)

    (rows,) = seen
    assert [(row.name, row.count, row.locked) for row in rows] == [
        ("GEN (NIV)", 1, True),
        ("EXO (NIV)", 1, False),
        ("LEV (NIV)", 1, False),
    ]
    # Unticked books are unchanged and never written; NUM has no match so isn't listed.
    assert (niv / "01GEN.usfm").read_bytes() == _GEN.encode()
    assert (niv / "02EXO.usfm").read_bytes() == _EXO.encode()
    assert (niv / "03LEV.usfm").read_bytes() == _LEV.encode()
    assert (niv / "04NUM.usfm").read_bytes() == _NUM.encode()
    assert not genesis.document.modified
    assert panel.status_label.text().startswith("1 replaced across 1 document(s)")
    # The ticked book that wasn't open stays open in the project tab: changed, unsaved.
    lev = service.documents.find_path(niv / "03LEV.usfm")
    assert lev is not None and lev.view_ids and lev.document.modified
    assert "And the X called." in lev.document.read(0, lev.document.total_chars())
    # Books that weren't chosen and weren't open are closed again.
    assert service.documents.find_path(niv / "04NUM.usfm") is None
    assert service.documents.find_path(niv / "02EXO.usfm") is None
    assert service._transient_documents == []
    assert window.current_view is genesis  # the user's book keeps focus


def test_ticked_locked_books_are_unlocked_and_left_unsaved(desktop, tmp_path: Path, monkeypatch):
    from uniti.ui import replace_files
    from uniti.ui.find_replace import ReplaceScope

    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    window.activateWindow()
    monkeypatch.setattr(replace_files, "choose", lambda parent, rows: {0})

    panel = _replace_all(service, "beginning|names|LORD", "X", ReplaceScope.CURRENT_GROUP)

    assert genesis.document.locked is False and genesis.document.modified
    assert "In the X." in genesis.document.read(0, genesis.document.total_chars())
    assert (niv / "01GEN.usfm").read_bytes() == _GEN.encode()
    assert panel.status_label.text().endswith("; 1 unlocked")


def test_cancelling_the_list_changes_nothing(desktop, tmp_path: Path, monkeypatch):
    from uniti.ui import replace_files
    from uniti.ui.find_replace import ReplaceScope

    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    window.activateWindow()
    monkeypatch.setattr(replace_files, "choose", lambda parent, rows: None)

    panel = _replace_all(service, "beginning|names|LORD", "X", ReplaceScope.CURRENT_GROUP)

    assert panel.status_label.text() == "cancelled: no file changed"
    assert genesis.document.locked and not genesis.document.modified
    assert service.documents.find_path(niv / "03LEV.usfm") is None
    assert service._transient_documents == []


def test_read_only_folder_files_are_listed_but_never_changed(desktop, tmp_path: Path, monkeypatch):
    from uniti.ui import replace_files
    from uniti.ui.find_replace import ReplaceScope

    _app, service = desktop
    niv = _project_of_four(tmp_path / "Paratext" / "niv")
    window, genesis = _usfm_window(service, niv)
    window.activateWindow()
    window.set_read_only_folders([str(tmp_path / "Paratext")])
    seen = []
    monkeypatch.setattr(replace_files, "choose", lambda parent, rows: seen.append(rows) or set(range(len(rows))))

    panel = _replace_all(service, "beginning|names|LORD", "X", ReplaceScope.CURRENT_GROUP)

    assert seen and all(row.read_only for row in seen[0])
    assert panel.status_label.text().startswith("0 replaced across 0 document(s)")
    assert (niv / "01GEN.usfm").read_bytes() == _GEN.encode()


def test_the_dialog_lists_all_unticked_and_names_the_locked_books(desktop, tmp_path: Path):
    from PySide6.QtCore import Qt

    from uniti.ui.replace_files import FileRow, ReplaceFilesDialog

    _app, _service = desktop
    dialog = ReplaceFilesDialog(
        [FileRow("GEN (NIV)", "/p", 3, locked=True), FileRow("EXO (NIV)", "/p", 1), FileRow("x.txt", "/q", 2, read_only=True)]
    )

    assert dialog.chosen() == set() and not dialog.replace_button.isEnabled()
    assert dialog.tree.topLevelItem(0).text(0) == "🔒 GEN (NIV)"
    assert not dialog.tree.topLevelItem(2).flags() & Qt.ItemFlag.ItemIsEnabled
    dialog.tree.topLevelItem(0).setCheckState(0, Qt.CheckState.Checked)
    assert dialog.chosen() == {0} and dialog.replace_button.isEnabled()
    assert dialog.note.text() == "1 locked book will be unlocked"


def test_replace_all_in_all_open_documents_lists_every_environment(desktop, tmp_path: Path, monkeypatch):
    from uniti.ui import replace_files
    from uniti.ui.find_replace import ReplaceScope

    _app, service = desktop
    niv = _project(tmp_path / "niv")
    main = service.new_window()
    main.activateWindow()
    plain = tmp_path / "notes.txt"
    plain.write_bytes(b"the end\r\n")
    main.open_path(plain)
    book = main.open_path(niv / "01GEN.usfm")
    seen = []
    monkeypatch.setattr(replace_files, "choose", lambda parent, rows: seen.append(rows) or {0})

    _replace_all(service, "the", "THE", ReplaceScope.ALL_OPEN_DOCUMENTS)

    names = sorted(row.name for row in seen[0])
    assert names == ["GEN (NIV)", "notes.txt"]
    assert plain.read_bytes() == b"the end\r\n"


# --- L5: stepping through the project's books ---------------------------------


def _step_panel(service, window, find: str = "LORD|beginning"):
    from uniti.ui.find_replace import ReplaceScope

    window.activateWindow()
    panel = service.find_replace
    panel.regex_checkbox.setChecked(True)
    panel.find_input.set_text(find)
    panel.replace_input.set_text("X")
    _wait(service, lambda: panel.compile_current() is not None and panel._replacement_is_current())
    panel.replace_scope_combo.setCurrentIndex(panel.replace_scope_combo.findData(ReplaceScope.CURRENT_GROUP))
    return panel


def _settle(service, panel):
    _wait(service, lambda: not panel.busy)
    from PySide6.QtWidgets import QApplication

    QApplication.instance().processEvents()


def _caret_after(view, text: str) -> None:
    content = view.document.read(0, view.document.total_chars())
    view.state.move_to(content.index(text) + len(text))
    view._state_changed()


def test_find_next_steps_into_a_book_that_was_not_open_and_passes_over_one_without_a_match(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    panel = _step_panel(service, window)
    _caret_after(genesis, "beginning")

    panel.next_match()
    _settle(service, panel)

    shown = window.current_view
    assert Path(shown.document.path).name == "03LEV.usfm"  # EXO has no match: passed over
    assert shown.document.read(*shown.state.selection) == "LORD" if shown.state.selection else False
    assert service.documents.find_path(niv / "02EXO.usfm") is None  # searched, never opened
    assert service._transient_documents == []


def test_find_next_within_a_book_stays_in_it(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    panel = _step_panel(service, window, find="n")  # several matches in GEN
    genesis.state.move_to(0)

    panel.next_match()
    _settle(service, panel)

    assert window.current_view is genesis and genesis.state.selection is not None


def test_leaving_a_changed_book_by_stepping_asks_and_discard_drops_its_changes(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    genesis.document.set_locked(False)
    genesis.document.insert(genesis.document.total_chars(), "\\rem edit\r\n")
    panel = _step_panel(service, window)
    _caret_after(genesis, "beginning")
    asked = _answers(monkeypatch, ask_save_or_discard=False)

    panel.next_match()
    _settle(service, panel)

    assert asked["ask_save_or_discard"] == [("GEN (NIV)",)]
    assert Path(window.current_view.document.path).name == "03LEV.usfm"
    assert service.documents.find_path(niv / "01GEN.usfm") is None  # discarded: closed, unwritten
    assert (niv / "01GEN.usfm").read_bytes() == _GEN.encode()


def test_cancelling_the_save_or_discard_question_stays_in_the_book(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    genesis.document.set_locked(False)
    genesis.document.insert(genesis.document.total_chars(), "\\rem edit\r\n")
    panel = _step_panel(service, window)
    _caret_after(genesis, "beginning")
    _answers(monkeypatch, ask_save_or_discard=None)

    panel.next_match()
    _settle(service, panel)

    assert window.current_view is genesis and genesis.document.modified


def test_replace_in_a_locked_book_reached_by_stepping_asks_skip_or_unlock(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    panel = _step_panel(service, window)
    _caret_after(genesis, "beginning")
    panel.next_match()
    _settle(service, panel)
    lev = window.current_view
    assert Path(lev.document.path).name == "03LEV.usfm" and lev.document.locked
    asked = _answers(monkeypatch, ask_unlock_and_replace=True)

    panel.replace_current()
    _wait(service, lambda: not panel.busy and panel.status_label.text() == "1 replaced")

    assert asked["ask_unlock_and_replace"] == [("LEV (NIV)",)]
    assert "And the X called." in lev.document.read(0, lev.document.total_chars())
    assert not lev.document.locked


def test_wrapping_past_the_last_book_asks(desktop, tmp_path: Path, monkeypatch):
    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    panel = _step_panel(service, window)
    _caret_after(genesis, "beginning")
    panel.next_match()
    _settle(service, panel)
    lev = window.current_view
    _caret_after(lev, "LORD")

    asked = _answers(monkeypatch, ask_wrap_project=False)
    panel.next_match()
    _settle(service, panel)
    assert asked["ask_wrap_project"] == [()] or len(asked["ask_wrap_project"]) == 1
    assert window.current_view is lev  # declined: stays

    _answers(monkeypatch, ask_wrap_project=True)
    panel.next_match()
    _settle(service, panel)
    assert Path(window.current_view.document.path).name == "01GEN.usfm"


def test_the_only_book_with_a_match_wraps_in_place(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    panel = _step_panel(service, window, find="beginning")
    _caret_after(genesis, "beginning")

    panel.next_match()
    _settle(service, panel)

    assert window.current_view is genesis
    assert genesis.document.read(*genesis.state.selection) == "beginning"


def test_other_scopes_dont_step(desktop, tmp_path: Path):
    from uniti.ui.find_replace import ReplaceScope

    _app, service = desktop
    niv = _project_of_four(tmp_path / "niv")
    window, genesis = _usfm_window(service, niv)
    panel = _step_panel(service, window)
    panel.replace_scope_combo.setCurrentIndex(panel.replace_scope_combo.findData(ReplaceScope.WHOLE_DOCUMENT))
    _caret_after(genesis, "beginning")

    panel.next_match()
    _settle(service, panel)

    assert window.current_view is genesis
