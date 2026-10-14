"""Footnote category filter, the window (plan 2026-10-14-footnote-category-filter)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from test_service import _desktop_service, _stop_desktop_service  # noqa: E402
from usfm_project_fixture import ensure_project  # noqa: E402

_GEN = (
    "\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 Alpha\\f + \\cat aa bb\\cat* \\ft first note\\f* beta"
    "\\f + \\ft plain note\\f* gamma\\f + \\cat cc\\cat* \\ft third note\\f* end.\r\n"
)
_EXO = "\\id EXO\r\n\\c 1\r\n\\p\r\n\\v 1 One\\f + \\cat aa\\cat* \\ft exo note\\f* two.\r\n"


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
    (folder / "01GEN.usfm").write_bytes(_GEN.encode())
    (folder / "02EXO.usfm").write_bytes(_EXO.encode())
    return folder


def _usfm_window(service, folder: Path):
    main = service.new_window()
    view = main.open_path(folder / "01GEN.usfm")
    return main.move_to_environment_window(view), view


def _entries(menu) -> dict[str, bool]:
    menu.aboutToShow.emit()
    return {action.text(): action.isChecked() for action in menu.actions() if action.isCheckable()}


def _preview(window):
    window._rich_views.show("sfm.preview")
    return window._rich_views.pane


def test_the_menu_lists_every_category_and_none_all_checked(desktop, tmp_path: Path):
    _app, service = desktop
    window, _view = _usfm_window(service, _project(tmp_path / "niv", "NIV"))

    assert window._note_categories.menu in [a.menu() for a in window._environment.menu.actions()]
    assert _entries(window._note_categories.menu) == {"aa": True, "bb": True, "cc": True, "None": True}


def test_unchecking_a_category_removes_its_notes_from_preview_only(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv", "NIV"))
    pane = _preview(window)
    assert len(pane.note_sections) == 1 and "first note" in pane.note_sections[0].editor.toPlainText()

    window._note_categories.set_shown(view, "aa", False)
    window._note_categories.set_shown(view, "bb", False)

    sections = pane.note_sections[0].editor.toPlainText()
    assert "first note" not in sections and "plain note" in sections and "third note" in sections
    assert _entries(window._note_categories.menu) == {"aa": False, "bb": False, "cc": True, "None": True}

    window._rich_views.show("sfm.standard")  # Standard keeps every note, in the text
    assert "first note" in window._rich_views.pane.editor.toPlainText()


def test_none_and_show_all(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv", "NIV"))
    pane = _preview(window)

    window._note_categories.set_shown(view, "", False)
    assert "plain note" not in pane.note_sections[0].editor.toPlainText()

    window._note_categories.menu.aboutToShow.emit()
    show_all = next(a for a in window._note_categories.menu.actions() if a.text() == "Show All")
    assert show_all.isEnabled()
    show_all.trigger()
    assert "plain note" in pane.note_sections[0].editor.toPlainText()
    window._note_categories.set_shown(view, "", False)
    window._project_tabs.set_note_filter(view, frozenset())
    assert "plain note" in pane.note_sections[0].editor.toPlainText()


def test_it_is_per_project_tab(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    cars = _project(tmp_path / "cars", "CARS")
    window, niv_gen = _usfm_window(service, niv)
    cars_gen = window.open_path(cars / "01GEN.usfm")

    window._note_categories.set_shown(niv_gen, "aa", False)

    assert niv_gen.hidden_note_categories == {"aa"}
    assert cars_gen.hidden_note_categories == frozenset()


def test_a_book_opened_into_the_tab_takes_the_filter_and_the_session_keeps_it(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    window._note_categories.set_shown(genesis, "aa", False)

    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")
    window._project_tabs.refresh_all()
    assert exodus.hidden_note_categories == {"aa"}

    record = genesis.export_state("doc")
    assert record.extra["hidden_note_categories"] == ["aa"]
    genesis.hidden_note_categories = frozenset()
    genesis.restore_state(record)
    assert genesis.hidden_note_categories == {"aa"}
    window._project_tabs.refresh_all()
    pane = _preview(window)
    assert pane._hidden_categories == {"aa"}


def test_a_filtered_projection_is_cached_beside_the_full_one(desktop, tmp_path: Path):
    from uniti.ui.rich_view import PROJECTIONS

    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv", "NIV"))
    pane = _preview(window)
    full = pane.projection
    window._note_categories.set_shown(view, "aa", False)
    filtered = pane.projection
    assert filtered is not full

    window._project_tabs.set_note_filter(view, frozenset())
    assert pane.projection is full  # back to the cached one: no new projection
    window._project_tabs.set_note_filter(view, frozenset({"aa"}))
    assert pane.projection is filtered


def test_the_tab_menu_has_the_submenu(desktop, tmp_path: Path):
    from PySide6.QtWidgets import QMenu

    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv", "NIV"))
    tab_menu = window.tab_menu(view.view_id)
    submenu = next(a.menu() for a in tab_menu.actions() if a.text() == "Footnote Categories")
    assert isinstance(submenu, QMenu)
    assert _entries(submenu) == {"aa": True, "bb": True, "cc": True, "None": True}
