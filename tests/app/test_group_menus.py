"""Document Group on every right-click menu (2026-10-08)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from usfm_project_fixture import in_project  # noqa: E402
from test_service import _desktop_service, _stop_desktop_service  # noqa: E402

from uniti.app.document_groups import DocumentGroup  # noqa: E402

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


def _group_submenu(menu):
    return next(
        action.menu()
        for action in menu.actions()
        if action.menu() and action.text().startswith(("Document Group", "Project Group"))
    )


def test_the_editor_right_click_menu_assigns_the_group(desktop, tmp_path: Path):
    app, service = desktop
    window = service.new_window()
    view = _open(window, tmp_path / "GEN.usfm")

    submenu = _group_submenu(window._editor_context_menu(view))

    assert _texts(submenu) == ["No Group", "A", "B", "C", "New Group…", "Manage Groups…"]
    assert next(a for a in submenu.actions() if a.text() == "No Group").isChecked()
    next(a for a in submenu.actions() if a.text() == "B").trigger()

    assert service.documents.entry_for_view(view.view_id).group_id == "B"
    # A USFM book's group is its project's (round 3 T5).
    assert _group_submenu(window._editor_context_menu(view)).title() == "Project Group (B)"
    leaf = window.panes.leaf_for_view(view.view_id)
    assert not leaf.tabs.tabIcon(leaf.index_of(view.view_id)).isNull()  # the tab's swatch


def test_standard_and_preview_right_click_menus_assign_the_group_too(desktop, tmp_path: Path):
    app, service = desktop
    window = service.new_window()
    view = _open(window, tmp_path / "GEN.usfm")
    window._rich_views.show("sfm.preview", view)

    menu = window._rich_views.pane_for(view).editor.context_menu()

    assert _texts(menu)[:3] == ["Cut", "Copy", "Paste"]
    submenu = _group_submenu(menu)
    next(a for a in submenu.actions() if a.text() == "A").trigger()
    assert service.documents.entry_for_view(view.view_id).group_id == "A"


def test_new_group_creates_assigns_and_reaches_every_window(desktop, tmp_path: Path, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    app, service = desktop
    first = service.new_window()
    second = service.new_window()
    view = _open(first, tmp_path / "GEN.usfm")
    other = _open(second, tmp_path / "EXO.usfm", _USFM.replace("GEN", "EXO"))
    monkeypatch.setattr(QInputDialog, "getText", lambda *args, **kwargs: ("Translators", True))

    next(a for a in _group_submenu(first._editor_context_menu(view)).actions() if a.text() == "New Group…").trigger()

    entry = service.documents.entry_for_view(view.view_id)
    group = first._group_by_id(entry.group_id, "usfm")
    assert group is not None and group.name == "Translators"
    # Saved with USFM's own groups (round 3 T2), not Plain Text's.
    assert [g.name for g in first._environment_groups.store("usfm").load()][-1] == "Translators"
    assert "Translators" not in [g.name for g in first.groups_for("plain_text")]
    # The other window knows the new group straight away.
    assert second._group_by_id(group.id, "usfm") is not None
    assert "Translators" in _texts(_group_submenu(second._editor_context_menu(other)))


def test_regrouping_a_file_in_an_environment_window_keeps_it_there(desktop, tmp_path: Path):
    """Round 3 T3: groups don't move files between windows."""

    app, service = desktop
    main = service.new_window()
    view = _open(main, tmp_path / "GEN.usfm")
    main._set_document_group(service.documents.entry_for_view(view.view_id).document_id, "A")
    window = main.move_to_environment_window(view)
    assert window.environment_window == ("usfm", 0)

    next(a for a in _group_submenu(window._editor_context_menu(view)).actions() if a.text() == "B").trigger()

    assert service.windows.window_for_view(view.view_id) is window
    assert service.documents.entry_for_view(view.view_id).group_id == "B"
    assert window._environment_bar.group.text() == "B"
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

    assert "Work" in _texts(_group_submenu(window._editor_context_menu(notes)))
    assert "Work" not in _texts(_group_submenu(window._editor_context_menu(book)))

    # The same id in two environments is two groups: renaming USFM's A
    # leaves Plain Text's A alone.
    usfm = window.groups_for("usfm")
    window._groups_and_recent_files._publish_groups("usfm", (DocumentGroup("A", "Bibles", usfm[0].color),) + usfm[1:])
    for view, group_id in ((book, "A"), (notes, "A")):
        window._set_document_group(service.documents.entry_for_view(view.view_id).document_id, group_id)
    assert _group_submenu(window._editor_context_menu(book)).title() == "Project Group (Bibles)"
    assert _group_submenu(window._editor_context_menu(notes)).title() == "Document Group (A)"


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


def test_manage_groups_renames_an_environments_windows(desktop, tmp_path: Path, monkeypatch):
    """Round 3 T3, D4: window names are edited next to the groups."""

    app, service = desktop
    main = service.new_window()
    book = _open(main, tmp_path / "proj" / "GEN.usfm")
    window = main.move_to_environment_window(book)
    seen = {}

    class FakeEditor:
        def __init__(self, groups, parent=None, *, environments=None, environment=None, window_names=None) -> None:
            seen["names"] = window_names

        def exec(self) -> bool:
            return True

        def groups_by_environment(self):
            return {}

        def window_names_by_environment(self):
            return {"usfm": ["Draft", "Compare", "C"]}

    monkeypatch.setattr("uniti.ui.document_group_editor.DocumentGroupEditor", FakeEditor)

    window.show_document_group_editor()

    assert seen["names"]["usfm"] == ["1", "2", "3"]
    assert window.environment_window_name() == "SFM-Draft"
    assert window.windowTitle().startswith("UNITI — SFM-Draft")
    assert service.new_environment_window("usfm").environment_window_name() == "SFM-Compare"
