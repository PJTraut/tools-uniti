"""Spelling S5: Check Spelling per project tab (plan 2026-10-13-usfm-spellcheck-plan)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from test_service import _desktop_service, _stop_desktop_service  # noqa: E402
from usfm_project_fixture import ensure_project  # noqa: E402

_GEN = "\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 In the beginning God created.\r\n"
_EXO = "\\id EXO\r\n\\c 1\r\n\\p\r\n\\v 1 These are the names.\r\n"
_LIST = """<SpellingStatus>
  <Status Word="in" State="R"/><Status Word="the" State="R"/><Status Word="god" State="R"/>
  <Status Word="created" State="R"/><Status Word="these" State="R"/><Status Word="are" State="R"/>
  <Status Word="names" State="R"/><Status Word="v" State="R"/><Status Word="c" State="R"/>
  <Status Word="beginning" State="W"><Correction>start</Correction></Status>
</SpellingStatus>"""


@pytest.fixture
def desktop(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)


def _project(folder: Path, name: str, words: str | None = _LIST) -> Path:
    ensure_project(folder, name=name)
    (folder / "01GEN.usfm").write_bytes(_GEN.encode())
    (folder / "02EXO.usfm").write_bytes(_EXO.encode())
    if words is not None:
        (folder / "SpellingStatus.xml").write_text(words, encoding="utf-8")
    return folder


def _usfm_window(service, folder: Path):
    main = service.new_window()
    view = main.open_path(folder / "01GEN.usfm")
    return main.move_to_environment_window(view), view


def _wait(predicate, timeout: float = 8.0) -> None:
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.002)
    raise AssertionError("condition did not become true")


def _flagged(view) -> list[str]:
    cache = view.spelling
    if cache is None:
        return []
    document = view.document
    return [document.read(span.start, span.end) for span in cache.book_spans()]


def test_turning_it_on_underlines_this_tab_and_not_another_projects(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    cars = _project(tmp_path / "cars", "CARS")
    window, niv_gen = _usfm_window(service, niv)
    cars_gen = window.open_path(cars / "01GEN.usfm")

    window._spelling.set_tab(niv_gen, True)
    _wait(lambda: niv_gen.spelling is not None)

    assert _flagged(niv_gen) == ["beginning"]
    assert cars_gen.spelling is None and not cars_gen.check_spelling
    assert niv_gen.check_spelling


def test_the_book_list_and_sync_keep_it_on_for_the_tab(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    window._spelling.set_tab(genesis, True)
    _wait(lambda: genesis.spelling is not None)

    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")
    window._project_tabs.refresh_all()

    assert exodus.check_spelling
    _wait(lambda: exodus.spelling is not None)
    assert _flagged(exodus) == []  # every word of Exodus is listed


def test_a_tab_moved_to_another_window_keeps_it(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    window._spelling.set_tab(genesis, True)
    _wait(lambda: genesis.spelling is not None)

    window.move_tab_to_window(genesis.view_id, None)
    other_window = next(w for _id, w in service.windows.items if w is not window and w.environment_window)
    moved = other_window.views[0]
    other_window._project_tabs.refresh_all()
    _wait(lambda: moved.spelling is not None)

    assert moved.check_spelling and _flagged(moved) == ["beginning"]


def test_merging_into_a_tab_takes_the_receiving_tabs_setting(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    window._spelling.set_tab(genesis, True)
    _wait(lambda: genesis.spelling is not None)
    window.move_tab_to_window(genesis.view_id, None)
    other_window = next(w for _id, w in service.windows.items if w is not window and w.environment_window)
    # Exodus opens in the first window, whose NIV tab is now empty: checking is off there.
    exodus = window.open_path(niv / "02EXO.usfm")
    window._project_tabs.refresh_all()
    assert not exodus.check_spelling

    other_window.open_existing_document(exodus.document)
    other_window._project_tabs.refresh_all()
    joined = other_window.views[-1]

    assert joined.check_spelling  # it took the receiving tab's setting


def test_the_setting_is_saved_with_the_session_and_restored(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    window._spelling.set_tab(genesis, True)

    record = genesis.export_state("doc")
    assert record.extra["check_spelling"] is True

    genesis.check_spelling = False
    genesis.restore_state(record)
    assert genesis.check_spelling
    window._project_tabs.refresh_all()
    _wait(lambda: genesis.spelling is not None)
    off = genesis.export_state("doc")
    window._spelling.set_tab(genesis, False)
    assert "check_spelling" not in genesis.export_state("doc").extra and off.extra["check_spelling"]
    assert genesis.spelling is None


def test_a_project_without_a_list_disables_it_with_the_reason(desktop, tmp_path: Path):
    _app, service = desktop
    plain = _project(tmp_path / "plain", "NIV", words=None)
    window, view = _usfm_window(service, plain)
    window._spelling.refresh()

    action = window._spelling.action
    assert not action.isEnabled()
    assert action.toolTip() == "NIV has no spelling list (SpellingStatus.xml or hyphenatedWords.txt)"
    window._spelling.set_tab(view, True)
    assert view.spelling is None and not view.check_spelling


def test_the_toggle_is_in_the_usfm_menu_and_the_tab_menu(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv", "NIV"))
    window._spelling.refresh()

    assert window._spelling.action in window._environment.menu.actions()
    assert window._spelling.action.isEnabled() and not window._spelling.action.isChecked()
    tab_action = next(a for a in window.tab_menu(view.view_id).actions() if a.text() == "Check Spelling")
    tab_action.trigger()
    _wait(lambda: view.spelling is not None)
    assert window._spelling.action.isChecked() and view.check_spelling


def test_a_list_changed_on_disk_is_read_again_when_the_window_is_activated(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    window._spelling.set_tab(genesis, True)
    _wait(lambda: genesis.spelling is not None)
    assert _flagged(genesis) == ["beginning"]

    (niv / "SpellingStatus.xml").write_text(_LIST.replace('State="W"', 'State="R"'), encoding="utf-8")
    later = time.time() + 5
    os.utime(niv / "SpellingStatus.xml", (later, later))
    window._spelling.window_activated()
    _wait(lambda: _flagged(genesis) == [])

    assert _flagged(genesis) == []


def test_every_view_of_a_document_shares_one_cache(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    window._spelling.set_tab(genesis, True)
    _wait(lambda: genesis.spelling is not None)
    other = service.new_environment_window("usfm")
    second = other.open_existing_document(genesis.document)
    other._project_tabs.refresh_all()
    assert not second.check_spelling and second.spelling is None  # another tab: its own setting

    other._spelling.set_tab(second, True)
    _wait(lambda: second.spelling is not None)

    assert second.spelling is genesis.spelling


def test_standard_and_preview_underline_after_the_toggle(desktop, tmp_path: Path):
    _app, service = desktop
    window, genesis = _usfm_window(service, _project(tmp_path / "niv", "NIV"))
    window.activateWindow()
    window._rich_views.show("sfm.standard")
    window._spelling.set_tab(genesis, True)
    _wait(lambda: genesis.spelling is not None)
    pane = window._rich_views.pane

    _wait(lambda: pane._spelling is genesis.spelling)
    pane._apply_highlights()

    assert [span.spelling.correction for _s, _e, span in pane._spelling_shown] == ["start"]
