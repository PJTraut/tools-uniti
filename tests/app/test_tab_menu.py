"""The tab's menu in an environment window: Group, Split and Window
(field test round 3, T6)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from usfm_project_fixture import ensure_project  # noqa: E402
from test_service import _desktop_service, _stop_desktop_service  # noqa: E402

from PySide6.QtCore import Qt  # noqa: E402

from uniti.ui.grouped_tabs import visible_tab_texts  # noqa: E402

_GEN = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning.\n"
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


def _texts(menu) -> list[str]:
    return [action.text() for action in menu.actions() if not action.isSeparator()]


def _submenu(menu, title: str):
    return next(action.menu() for action in menu.actions() if action.menu() is not None and action.text() == title)


def _action(menu, text: str):
    return next(action for action in menu.actions() if action.text() == text)


def _window_with_two_projects(service, tmp_path: Path):
    """USFM A with an NIV tab (GEN and EXO) and a CARS tab (GEN)."""

    niv = _project(tmp_path / "niv", "NIV")
    cars = _project(tmp_path / "cars", "CARS")
    main = service.new_window()
    genesis = main.open_path(niv / "01GEN.usfm")
    window = main.move_to_environment_window(genesis)
    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")
    other = window.open_path(cars / "01GEN.usfm")
    return window, genesis, exodus, other


def test_the_tab_menu_has_group_split_and_window(desktop, tmp_path: Path):
    app, service = desktop
    window, genesis, exodus, other = _window_with_two_projects(service, tmp_path)

    menu = window.tab_menu(exodus.view_id)

    assert _texts(menu) == ["Group", "Split", "Window"]
    assert _texts(_submenu(menu, "Group"))[0] == "No Group"
    split = _submenu(menu, "Split")
    assert _texts(split) == ["Move to New Split Right", "Move to New Split Down", "Unsplit"]
    assert not _action(split, "Unsplit").isEnabled()  # one split only
    assert _texts(_submenu(menu, "Window")) == ["Move to New Window", "Dock"]
    # GEN came here from the main window, so the tab can dock back.
    assert _action(_submenu(menu, "Window"), "Dock").isEnabled()


def test_an_ordinary_windows_tab_menu_is_its_group(desktop, tmp_path: Path):
    app, service = desktop
    main = service.new_window()
    (tmp_path / "notes.txt").write_text("hello", encoding="utf-8")
    view = main.open_path(tmp_path / "notes.txt")

    assert _texts(main.tab_menu(view.view_id))[0] == "No Group"


def test_a_tab_moves_with_all_its_books_to_a_new_split(desktop, tmp_path: Path):
    app, service = desktop
    window, genesis, exodus, other = _window_with_two_projects(service, tmp_path)
    first = window._panes.leaf_for_view(other.view_id)

    _action(_submenu(window.tab_menu(exodus.view_id), "Split"), "Move to New Split Right").trigger()

    leaf = window._panes.leaf_for_view(exodus.view_id)
    assert leaf is not first and window._panes.leaf_count == 2
    assert window._panes.leaf_for_view(genesis.view_id) is leaf  # the hidden book came too
    assert visible_tab_texts(leaf) == ["NIV"] and visible_tab_texts(first) == ["CARS"]
    assert window.current_view is exodus

    # Back with Move to Split 1, and the emptied split closes.
    _action(_submenu(window.tab_menu(exodus.view_id), "Split"), "Move to Split 1").trigger()
    assert window._panes.leaf_count == 1
    assert visible_tab_texts(first) == ["CARS", "NIV"]


def test_unsplit_merges_a_split_into_its_neighbour(desktop, tmp_path: Path):
    app, service = desktop
    window, genesis, exodus, other = _window_with_two_projects(service, tmp_path)
    window.move_tab_to_new_split(other.view_id, Qt.Orientation.Vertical)
    assert window._panes.leaf_count == 2

    _action(_submenu(window.tab_menu(other.view_id), "Split"), "Unsplit").trigger()

    assert window._panes.leaf_count == 1
    leaf = window._panes.leaf_for_view(other.view_id)
    assert set(leaf.view_ids) == {genesis.view_id, exodus.view_id, other.view_id}
    assert visible_tab_texts(leaf) == ["NIV", "CARS"]


def test_an_environment_window_has_at_most_four_splits(desktop, tmp_path: Path):
    app, service = desktop
    window, genesis, exodus, other = _window_with_two_projects(service, tmp_path)
    for _ in range(3):
        assert window.split_right() is not None
    assert window._panes.leaf_count == 4

    assert window.split_right() is None
    assert window._panes.leaf_count == 4
    assert window.statusBar().currentMessage() == "An environment window has at most 4 splits"
    split = _submenu(window.tab_menu(other.view_id), "Split")
    assert not _action(split, "Move to New Split Right").isEnabled()
    assert [text for text in _texts(split) if text.startswith("Move to Split")] == [
        "Move to Split 2", "Move to Split 3", "Move to Split 4"
    ]


def test_a_tab_moves_between_windows_and_docks_back(desktop, tmp_path: Path):
    app, service = desktop
    window, genesis, exodus, other = _window_with_two_projects(service, tmp_path)

    _action(_submenu(window.tab_menu(exodus.view_id), "Window"), "Move to New Window").trigger()

    usfm_b = service.windows.window_for_view(exodus.view_id)
    assert usfm_b is not window and usfm_b.environment_window_name() == "USFM B"
    assert service.windows.window_for_view(genesis.view_id) is usfm_b
    assert visible_tab_texts(usfm_b._panes.leaf_for_view(exodus.view_id)) == ["NIV"]
    assert usfm_b.current_view is exodus

    # From USFM B, the menu offers USFM A; moving there again merges with
    # whatever tab of the project is there (here: none, so its own tab).
    window_menu = _submenu(usfm_b.tab_menu(exodus.view_id), "Window")
    assert "Move to USFM A" in _texts(window_menu)
    assert _action(window_menu, "Dock").isEnabled()

    _action(window_menu, "Dock").trigger()
    assert service.windows.window_for_view(exodus.view_id) is window
    assert service.windows.window_for_view(genesis.view_id) is window


def test_moving_a_tab_into_a_window_with_its_project_merges_the_books(desktop, tmp_path: Path):
    app, service = desktop
    window, genesis, exodus, other = _window_with_two_projects(service, tmp_path)
    usfm_b = service.new_environment_window("usfm")
    niv = tmp_path / "niv"
    # A second NIV book view in USFM B: open a third book there.
    (niv / "03LEV.usfm").write_text("\\id LEV\n\\c 1\n\\p\n\\v 1 Leviticus.\n", encoding="utf-8")
    leviticus = usfm_b.open_path(niv / "03LEV.usfm")
    assert service.windows.window_for_view(leviticus.view_id) is usfm_b

    usfm_b.move_tab_to_window(leviticus.view_id, window.environment_window[1])

    leaf = window._panes.leaf_for_view(leviticus.view_id)
    assert leaf is window._panes.leaf_for_view(genesis.view_id)
    assert visible_tab_texts(leaf) == ["NIV", "CARS"]  # one NIV tab, now with LEV
    assert window.current_view is leviticus
