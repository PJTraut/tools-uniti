"""Projects belong to groups; groups bind projects across windows (field
test round 3, T5)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from usfm_project_fixture import ensure_project  # noqa: E402
from test_service import _desktop_service, _stop_desktop_service  # noqa: E402

from uniti.app.editor_state import EditorStateSnapshot  # noqa: E402

_GEN = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning.\n\\v 2 Formless.\n\\v 3 Light.\n"
_EXO = "\\id EXO\n\\c 1\n\\p\n\\v 1 These are the names.\n"


@pytest.fixture
def desktop(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)


def _project(folder: Path, name: str) -> Path:
    ensure_project(folder, name=name)
    (folder / "01GEN.usfm").write_text(_GEN, encoding="utf-8")
    (folder / "02EXO.usfm").write_text(_EXO, encoding="utf-8")
    return folder


def _group(window, service, view, group_id: str | None) -> None:
    window._set_document_group(service.documents.entry_for_view(view.view_id).document_id, group_id)


def _caret_at(view, text: str, marker: str) -> None:
    offset = text.index(marker)
    view.state.restore_state(EditorStateSnapshot(offset, offset, None))
    view._state_changed()


def test_a_projects_group_is_every_one_of_its_books(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    main = service.new_window()
    genesis = main.open_path(niv / "01GEN.usfm")
    window = main.move_to_environment_window(genesis)
    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")

    _group(window, service, exodus, "B")

    for view in (genesis, exodus):
        assert service.documents.entry_for_view(view.view_id).group_id == "B"
    saved = json.loads((tmp_path / "Environments" / "USFM" / "projects.json").read_text(encoding="utf-8"))
    assert saved == {"schema": 1, "projects": {str(niv.resolve()): "B"}}
    # The tab carries the group's colour.
    leaf = window._panes.leaf_for_view(exodus.view_id)
    assert leaf.tabBar().tab_tint(exodus.view_id) == window._group_by_id("B", "usfm").color

    # A book opened later, anywhere, takes the project's group.
    window.close_all_documents(force=True)
    again = main.open_path(niv / "02EXO.usfm")
    assert service.documents.entry_for_view(again.view_id).group_id == "B"


def test_a_project_opens_in_its_group(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    main = service.new_window()
    main._project_groups.set("usfm", niv, "C")

    view = main._usfm_projects.open_project(niv)

    assert service.documents.entry_for_view(view.view_id).group_id == "C"


def _two_windows(service, tmp_path: Path):
    """NIV in USFM A, CARS in USFM B, both in group A."""

    niv = _project(tmp_path / "niv", "NIV")
    cars = _project(tmp_path / "cars", "CARS")
    main = service.new_window()
    left = main.open_path(niv / "01GEN.usfm")
    window_a = main.move_to_environment_window(left)
    right = main.open_path(cars / "01GEN.usfm")
    window_b = service.new_environment_window("usfm")
    main.move_to_environment_window(right, slot=1)
    for window, view in ((window_a, left), (window_b, right)):
        _group(window, service, view, "A")
    return niv, cars, window_a, window_b, left, right


def test_a_group_syncs_its_projects_across_windows(desktop, tmp_path: Path):
    app, service = desktop
    niv, cars, window_a, window_b, left, right = _two_windows(service, tmp_path)
    assert service.windows.window_for_view(right.view_id) is window_b

    _caret_at(left, _GEN, "\\v 2")
    moved = window_a._reference_sync.sync_from(left)

    assert moved == 1
    assert right.state.cursor == _GEN.index("\\v 2")
    # The sync in A doesn't start one back from B.
    assert window_b._reference_sync._timer.isActive() is False


def test_sync_changes_a_tabs_book_without_asking_and_keeps_its_edits(desktop, tmp_path: Path, monkeypatch):
    from uniti.ui import book_lock

    app, service = desktop
    niv, cars, window_a, window_b, left, right = _two_windows(service, tmp_path)
    exodus = window_b._environment_bar.open_book(cars / "02EXO.usfm")
    exodus.document.insert(exodus.document.total_chars(), "\\v 2 Edited.\n")
    monkeypatch.setattr(book_lock, "ask_save_or_discard", lambda *args, **kwargs: pytest.fail("sync must not ask (D2)"))

    _caret_at(left, _GEN, "\\v 3")
    window_a._reference_sync.sync_from(left)

    shown = window_b.current_view
    assert shown is right and shown.state.cursor == _GEN.index("\\v 3")  # CARS's tab is at GEN again
    assert exodus.document.modified  # still open, still unsaved
    assert window_b.view_for_id(exodus.view_id) is exodus


def test_ungrouped_projects_dont_sync(desktop, tmp_path: Path):
    app, service = desktop
    niv, cars, window_a, window_b, left, right = _two_windows(service, tmp_path)
    _group(window_b, service, right, None)

    _caret_at(left, _GEN, "\\v 2")

    assert window_a._reference_sync.sync_from(left) == 0
    assert right.state.cursor != _GEN.index("\\v 2")


def test_sync_changes_the_shown_projects_book_not_another_projects_tab(desktop, tmp_path: Path):
    """When another project's tab in the target split has the book, sync
    still changes the book in the shown project's tab (2026-10-13 spec check)."""

    from PySide6.QtCore import Qt

    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    esv = _project(tmp_path / "esv", "ESV")
    cars = _project(tmp_path / "cars", "CARS")
    main = service.new_window()
    source = main.open_path(cars / "01GEN.usfm")
    window = main.move_to_environment_window(source)
    window._panes.split_view(source.view_id, Qt.Orientation.Horizontal)
    esv_genesis = window.open_path(esv / "01GEN.usfm")
    niv_exodus = window.open_path(niv / "02EXO.usfm")
    leaf = window._panes.leaf_for_view(niv_exodus.view_id)
    assert window._panes.leaf_for_view(esv_genesis.view_id) is leaf
    assert window._panes.leaf_for_view(source.view_id) is not leaf
    for view in (source, esv_genesis, niv_exodus):
        _group(window, service, view, "A")
    window._select_view(niv_exodus)
    window._select_view(source)

    _caret_at(source, _GEN, "\\v 2")
    window._reference_sync.sync_from(source)

    shown = leaf.active_view
    assert shown is not esv_genesis
    assert shown.document.path == niv / "01GEN.usfm"
    assert shown.state.cursor == _GEN.index("\\v 2")
