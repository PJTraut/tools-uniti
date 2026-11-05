"""Group menus: the tab's menu and Ctrl+Alt+0…9 set a file's group; the
text's right-click menu no longer does (field test 2026-11-05, N30)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from test_service import _desktop_service, _stop_desktop_service
from usfm_project_fixture import in_project

from uniti.app.document_groups import DocumentGroup

_USFM = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning.\n"


@pytest.fixture
def desktop(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)


def _open(window, path: Path, text: str = _USFM):
    path.parent.mkdir(parents=True, exist_ok=True)
    in_project(path).write_text(text, encoding="utf-8")
    return window.open_path(path)


def _texts(menu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def _has_group_submenu(menu) -> bool:
    return any(action.menu() and "Group" in action.text() for action in menu.actions())


def _pick(menu, text: str) -> None:
    next(action for action in menu.actions() if action.text() == text).trigger()


def test_the_editor_right_click_menu_has_no_group(desktop, tmp_path: Path):
    """Field test 2026-11-05 (N30): the group is set from the tab, the
    toolbar's [group] button or Ctrl+Alt+0…9, not the text's menu."""

    app, service = desktop
    window = service.new_window()
    view = _open(window, tmp_path / "GEN.usfm")

    assert not _has_group_submenu(window._editor_context_menu(view))


def test_standard_and_preview_right_click_menus_have_no_group(desktop, tmp_path: Path):
    app, service = desktop
    window = service.new_window()
    view = _open(window, tmp_path / "GEN.usfm")
    for mode in ("sfm.standard", "sfm.preview"):
        window._rich_views.show(mode, view)
        menu = window._rich_views.pane_for(view).editor.context_menu()
        assert _texts(menu)[:3] == ["Cut", "Copy", "Paste"]
        assert not _has_group_submenu(menu)


def test_the_tab_menu_assigns_the_group(desktop, tmp_path: Path):
    app, service = desktop
    window = service.new_window()
    view = _open(window, tmp_path / "GEN.usfm")

    menu = window.tab_menu(view.view_id)

    assert _texts(menu)[:5] == ["No Group", "A", "B", "C", "New Group…"]
    assert _texts(menu)[-1] == "Manage Groups…"
    assert next(a for a in menu.actions() if a.text() == "No Group").isChecked()
    _pick(menu, "B")
    assert service.documents.entry_for_view(view.view_id).group_id == "B"
    leaf = window.panes.leaf_for_view(view.view_id)
    assert leaf.tabBar().tab_tint(view.view_id) == window._group_by_id("B", "usfm").color  # N29


def test_new_group_creates_assigns_and_reaches_every_window(desktop, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    app, service = desktop
    first = service.new_window()
    second = service.new_window()
    view = _open(first, tmp_path / "GEN.usfm")
    other = _open(second, tmp_path / "EXO.usfm", _USFM.replace("GEN", "EXO"))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Translators", True))

    _pick(first.tab_menu(view.view_id), "New Group…")

    entry = service.documents.entry_for_view(view.view_id)
    group = first._group_by_id(entry.group_id, "usfm")
    assert group is not None and group.name == "Translators"
    # Saved with USFM's own groups (round 3 T2), not Plain Text's.
    assert [g.name for g in first._environment_groups.store("usfm").load()][-1] == "Translators"
    assert "Translators" not in [g.name for g in first.groups_for("plain_text")]
    # The other window knows the new group straight away.
    assert second._group_by_id(group.id, "usfm") is not None
    assert "Translators" in _texts(second.tab_menu(other.view_id))


def test_regrouping_a_file_in_an_environment_window_keeps_it_there(desktop, tmp_path: Path):
    """Round 3 T3: groups don't move files between windows."""

    app, service = desktop
    main = service.new_window()
    view = _open(main, tmp_path / "GEN.usfm")
    main._set_document_group(service.documents.entry_for_view(view.view_id).document_id, "A")
    window = main.move_to_environment_window(view)
    assert window.environment_window == ("usfm", 0)

    menu = window.tab_menu(view.view_id)
    _pick(next(a.menu() for a in menu.actions() if a.text() == "Group"), "B")

    assert service.windows.window_for_view(view.view_id) is window
    assert service.documents.entry_for_view(view.view_id).group_id == "B"
    assert window._environment_bar.group.text() == "[B]"
    # Dock still goes back to where the file came from.
    service.dock_view(view.view_id)
    assert service.windows.window_for_view(view.view_id) is main


def test_each_file_offers_its_own_environments_groups(desktop, tmp_path: Path, monkeypatch):
    """Round 3 T2: groups belong to an environment."""

    app, service = desktop
    window = service.new_window()
    book = _open(window, tmp_path / "proj" / "GEN.usfm")
    notes = _open(window, tmp_path / "notes" / "todo.txt", "plain words\n")
    window._groups_and_recent_files._publish_groups(
        "plain_text", window.groups_for("plain_text") + (DocumentGroup("work", "Work", "#123456"),)
    )

    assert "Work" in _texts(window.tab_menu(notes.view_id))
    assert "Work" not in _texts(window.tab_menu(book.view_id))

    # The same id in two environments is two groups: renaming USFM's A
    # leaves Plain Text's A alone.
    usfm = window.groups_for("usfm")
    window._groups_and_recent_files._publish_groups("usfm", (DocumentGroup("A", "Bibles", usfm[0].color),) + usfm[1:])
    for view, group_id in ((book, "A"), (notes, "A")):
        window._set_document_group(service.documents.entry_for_view(view.view_id).document_id, group_id)
    assert "Bibles" in _texts(window.tab_menu(book.view_id))
    assert "Bibles" not in _texts(window.tab_menu(notes.view_id))


def test_ctrl_alt_digits_set_the_group_in_an_ordinary_window(desktop, tmp_path: Path):
    """N30: Ctrl+Alt+0…9 work in every window, using the current file's
    environment's groups."""

    app, service = desktop
    window = service.new_window()
    assert window.environment_window is None
    keys = [action.shortcut().toString() for action in window.group_shortcut_actions]
    assert keys == [f"Ctrl+Alt+{n}" for n in range(10)]
    notes = _open(window, tmp_path / "notes" / "todo.txt", "plain words\n")
    window._select_view(notes)
    entry = service.documents.entry_for_view(notes.view_id)

    window.group_shortcut_actions[2].trigger()
    assert entry.group_id == window.groups_for("plain_text")[1].id
    window.group_shortcut_actions[0].trigger()
    assert entry.group_id is None
    # A position past the last group does nothing.
    assert not window.choose_group_by_position(9)
    assert entry.group_id is None


def test_manage_groups_starts_at_the_files_environment(desktop, tmp_path: Path, monkeypatch):
    app, service = desktop
    window = service.new_window()
    book = _open(window, tmp_path / "proj" / "GEN.usfm")
    window._select_view(book)
    seen = {}

    class FakeEditor:
        def __init__(self, groups, parent=None, *, environments=None, environment=None, **_kwargs) -> None:
            seen["environment"] = environment
            seen["labels"] = [label for _key, label, _groups in environments]

        def exec(self) -> bool:
            return True

        def groups_by_environment(self):
            return {"usfm": (DocumentGroup("A", "Only", "#e06c75"),)}

    monkeypatch.setattr("uniti.ui.document_group_editor.DocumentGroupEditor", FakeEditor)
    entry = service.documents.entry_for_view(book.view_id)
    window._set_document_group(entry.document_id, "B")

    window.show_document_group_editor()

    assert seen["environment"] == "usfm" and "Plain Text" in seen["labels"] and "USFM" in seen["labels"]
    assert [group.name for group in window.groups_for("usfm")] == ["Only"]
    assert entry.group_id is None  # its group B was removed
    assert [group.id for group in window.groups_for("plain_text")] == ["A", "B", "C"]
