"""Hyphenate Preview per project tab (plan 2026-10-15-usfm-hyphenation-and-spelling-followups, H3)."""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from test_service import _desktop_service, _stop_desktop_service  # noqa: E402
from usfm_project_fixture import ensure_project  # noqa: E402

SHY = "­"
_GEN = "\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 We understand completely.\r\n"
_EXO = "\\id EXO\r\n\\c 1\r\n\\p\r\n\\v 1 They understand it.\r\n"
_LIST = (
    "﻿#Hyphenated Word List v2.0\r\n"
    'HardHyphen = "-"\r\nSoftHyphen = "="\r\n'
    "un=der=stand\r\ncom=plete=ly\r\n"
)


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
        (folder / "hyphenatedWords.txt").write_bytes(words.encode("utf-8"))
    return folder


def _usfm_window(service, folder: Path):
    main = service.new_window()
    view = main.open_path(folder / "01GEN.usfm")
    return main.move_to_environment_window(view), view


def _preview_text(window) -> str:
    window._rich_views.show("sfm.preview")
    return window._rich_views.pane.projection.text


def test_it_is_off_by_default_and_turning_it_on_hyphenates_preview(desktop, tmp_path: Path):
    _app, service = desktop
    window, genesis = _usfm_window(service, _project(tmp_path / "niv", "NIV"))
    assert SHY not in _preview_text(window)

    window._hyphenation.set_tab(genesis, True)

    assert genesis.hyphenate_preview
    text = window._rich_views.pane.projection.text
    assert f"un{SHY}der{SHY}stand" in text and f"com{SHY}plete{SHY}ly" in text
    window._hyphenation.set_tab(genesis, False)
    assert SHY not in window._rich_views.pane.projection.text


def test_it_is_per_project_tab(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    cars = _project(tmp_path / "cars", "CARS")
    window, niv_gen = _usfm_window(service, niv)
    cars_gen = window.open_path(cars / "01GEN.usfm")
    window._hyphenation.set_tab(niv_gen, True)

    assert niv_gen.hyphenate_preview and not cars_gen.hyphenate_preview


def test_a_book_opened_into_the_tab_takes_it_and_the_session_keeps_it(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    window._hyphenation.set_tab(genesis, True)

    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")
    window._project_tabs.refresh_all()
    assert exodus.hyphenate_preview  # the tab keeps it as the book changes

    record = exodus.export_state("doc")
    assert record.extra["hyphenate_preview"] is True
    exodus.hyphenate_preview = False
    exodus.restore_state(record)
    assert exodus.hyphenate_preview
    window._hyphenation.set_tab(exodus, False)
    assert "hyphenate_preview" not in exodus.export_state("doc").extra


def test_a_project_without_a_list_disables_it_with_the_reason(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "plain", "NIV", words=None))
    window._hyphenation.refresh()

    action = window._hyphenation.action
    assert not action.isEnabled()
    assert action.toolTip() == "NIV has no hyphenation list (hyphenatedWords.txt)"
    window._hyphenation.set_tab(view, True)
    assert not view.hyphenate_preview


def test_the_toggle_is_in_the_usfm_menu_and_the_tab_menu(desktop, tmp_path: Path):
    _app, service = desktop
    window, view = _usfm_window(service, _project(tmp_path / "niv", "NIV"))
    window._hyphenation.refresh()

    assert window._hyphenation.action in window._environment.menu.actions()
    assert window._hyphenation.action.isEnabled() and not window._hyphenation.action.isChecked()
    next(a for a in window.tab_menu(view.view_id).actions() if a.text() == "Hyphenate Preview").trigger()
    assert view.hyphenate_preview and window._hyphenation.action.isChecked()


def test_a_list_changed_on_disk_is_read_again_when_the_window_is_activated(desktop, tmp_path: Path):
    _app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    window._hyphenation.set_tab(genesis, True)
    assert f"un{SHY}der" in _preview_text(window)

    path = niv / "hyphenatedWords.txt"
    path.write_bytes(_LIST.replace("un=der=stand", "under=stand").encode("utf-8"))
    later = time.time() + 5
    os.utime(path, (later, later))
    window._hyphenation.window_activated()

    text = window._rich_views.pane.projection.text
    assert f"under{SHY}stand" in text and f"un{SHY}der" not in text


def test_copying_from_preview_leaves_the_soft_hyphens_out(desktop, tmp_path: Path):
    _app, service = desktop
    window, genesis = _usfm_window(service, _project(tmp_path / "niv", "NIV"))
    window._hyphenation.set_tab(genesis, True)
    _preview_text(window)
    editor = window._rich_views.pane.editor
    editor.selectAll()

    copied = editor.createMimeDataFromSelection().text()

    assert "understand completely" in copied and SHY not in copied


def test_the_notes_frame_hyphenates_too_and_copying_from_it_leaves_the_soft_hyphens_out(desktop, tmp_path: Path):
    _app, service = desktop
    folder = _project(tmp_path / "niv", "NIV")
    (folder / "01GEN.usfm").write_bytes(
        "\\id GEN\r\n\\c 1\r\n\\p\r\n\\v 1 We understand it.\\f + \\ft A note on completely.\\f*\r\n".encode()
    )
    window, genesis = _usfm_window(service, folder)
    window._hyphenation.set_tab(genesis, True)
    _preview_text(window)
    (section,) = window._rich_views.pane.note_sections

    assert f"com{SHY}plete{SHY}ly" in section.editor.toPlainText()
    section.editor.selectAll()
    copied = section.editor.createMimeDataFromSelection().text()

    assert "A note on completely." in copied and SHY not in copied
    window._hyphenation.set_tab(genesis, False)
    assert SHY not in window._rich_views.pane.note_sections[0].editor.toPlainText()
