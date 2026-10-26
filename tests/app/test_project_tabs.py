"""One tab per project in a USFM window (field test round 3, T4)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from usfm_project_fixture import ensure_project  # noqa: E402
from test_service import _desktop_service, _stop_desktop_service  # noqa: E402

from uniti.ui.grouped_tabs import visible_tab_texts  # noqa: E402

_GEN = "\\id GEN\n\\h Genesis\n\\c 1\n\\p\n\\v 1 In the beginning.\n\\v 2 Formless.\n"
_EXO = "\\id EXO\n\\h Exodus\n\\c 1\n\\p\n\\v 1 These are the names.\n"


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


def _usfm_window(service, folder: Path):
    main = service.new_window()
    view = main.open_path(folder / "01GEN.usfm")
    return main.move_to_environment_window(view), view


def _leaf(window, view):
    return window._panes.leaf_for_view(view.view_id)


def test_a_project_has_one_open_book_in_a_tab_titled_with_its_short_name(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)

    exodus = window.open_path(niv / "02EXO.usfm")

    leaf = _leaf(window, exodus)
    assert leaf.view_ids == (exodus.view_id,)  # one open book: GEN closed, not hidden
    assert not service.documents.find_path(niv / "01GEN.usfm").view_ids
    assert visible_tab_texts(leaf) == ["NIV"]  # one tab, the short name
    assert window.current_view is exodus
    assert leaf.tabToolTip(leaf.index_of(exodus.view_id)) == f"EXO\n{niv / '02EXO.usfm'}"
    assert window.windowTitle().startswith("UNITI — SFM-1 — NIV")

    # Another project is another tab, with its own open book.
    cars = _project(tmp_path / "cars", "CARS")
    window.open_path(cars / "01GEN.usfm")
    assert visible_tab_texts(leaf) == ["NIV", "CARS"]
    assert len(leaf.view_ids) == 2


def test_changing_the_book_replaces_it_in_the_tab(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    bar = window._environment_bar

    exodus = bar.open_book(niv / "02EXO.usfm")

    leaf = _leaf(window, exodus)
    assert window.current_view is exodus
    assert leaf.view_ids == (exodus.view_id,)
    assert visible_tab_texts(leaf) == ["NIV"]
    # Back again: GEN opens afresh, in the tab's place.
    again = bar.open_book(niv / "01GEN.usfm")
    assert again is not genesis and leaf.view_ids == (again.view_id,)
    assert visible_tab_texts(leaf) == ["NIV"]
    assert leaf.index_of(again.view_id) == 0


@pytest.mark.book_lock
def test_a_changed_book_asks_before_the_next_replaces_it_and_stays_when_cancelled(desktop, tmp_path: Path, monkeypatch):
    from uniti.ui import book_lock

    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    genesis = window.current_view
    genesis.document.set_locked(False)
    genesis.document.insert(0, "\\rem edited\n")
    monkeypatch.setattr(book_lock, "ask_save_or_discard", lambda *args, **kwargs: None)

    genesis = window.current_view
    assert window.open_path(niv / "02EXO.usfm") is not None  # File > Open of another book

    leaf = _leaf(window, genesis)
    assert genesis.view_id in leaf.view_ids  # cancelled: it stays, hidden
    monkeypatch.setattr(book_lock, "ask_save_or_discard", lambda *args, **kwargs: False)
    window._environment_bar.keep_one_book(window.current_view)
    assert genesis.view_id not in leaf.view_ids  # Discard closes it
    assert service.documents.find_path(niv / "01GEN.usfm") is None


def test_closing_a_project_tab_closes_its_book(desktop, tmp_path: Path, monkeypatch):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    cars = _project(tmp_path / "cars", "CARS")
    window, genesis = _usfm_window(service, niv)
    other = window.open_path(cars / "01GEN.usfm")
    genesis.document.insert(0, "\\rem edited\n")
    asked = []
    monkeypatch.setattr(
        window, "_confirm_close", lambda view: (asked.append(view.document.path.name) if view.document.modified else None) or True
    )
    leaf = _leaf(window, genesis)

    assert window._close_tab_request(genesis.view_id) is True

    assert asked == ["01GEN.usfm"]  # a modified book asks
    assert leaf.view_ids == (other.view_id,)
    assert visible_tab_texts(leaf) == ["CARS"]


def test_a_cancelled_close_keeps_the_tab(desktop, tmp_path: Path, monkeypatch):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    genesis.document.insert(0, "\\rem edited\n")
    monkeypatch.setattr(window, "_confirm_close", lambda view: not view.document.modified)

    assert window.close_current() is False

    assert set(_leaf(window, genesis).view_ids) == {genesis.view_id}


def test_project_tabs_survive_a_session_capture(desktop, tmp_path: Path):
    from uniti.app.session_runtime import capture_service_session

    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")

    snapshot = capture_service_session(
        service, clean_shutdown=True, generation="g", service_id="s", build_identity="t",
        created_at="2026-10-08T00:00:00Z", updated_at="2026-10-08T00:00:00Z",
    )

    record = next(item for item in snapshot.manifest.windows if item.window_id == window.window_id)
    # One open book per project: just the current one.
    assert record.root.view_ids == (exodus.view_id,)


def test_ordinary_windows_keep_a_tab_per_file(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    main = service.new_window()
    main.open_path(niv / "01GEN.usfm")
    view = main.open_path(niv / "02EXO.usfm")

    assert main._project_tabs.active is False
    assert visible_tab_texts(_leaf(main, view)) == ["01GEN.usfm", "02EXO.usfm"]


def test_the_same_book_can_be_open_in_two_windows(desktop, tmp_path: Path):
    """Two windows' tabs of one project can show the same book: choosing it
    in one window, or opening it there, doesn't take it out of the other
    (2026-10-13 spec check)."""

    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window_a, genesis_a = _usfm_window(service, niv)
    window_b = service.new_environment_window("usfm")

    genesis_b = window_b.open_path(niv / "01GEN.usfm")

    assert window_a.view_for_id(genesis_a.view_id) is genesis_a  # still in A
    assert genesis_b is not genesis_a and genesis_b.document is genesis_a.document
    exodus_b = window_b._environment_bar.open_book(niv / "02EXO.usfm")
    assert window_a.view_for_id(genesis_a.view_id) is genesis_a  # B's change leaves A's book
    assert window_b.view_for_id(genesis_b.view_id) is None  # B's own view of it closed
    assert service.documents.find_path(niv / "01GEN.usfm") is not None  # A still shows it
    assert visible_tab_texts(_leaf(window_a, genesis_a)) == ["NIV"]
    assert visible_tab_texts(_leaf(window_b, exodus_b)) == ["NIV"]
    # Opening it again in B shows a view of it there.
    again = window_b.open_path(niv / "01GEN.usfm")
    assert again.document is genesis_a.document and _leaf(window_b, again).view_ids == (again.view_id,)


def test_a_restored_tab_with_several_books_keeps_the_shown_one_and_any_with_changes(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    bar = window._environment_bar
    genesis = window.current_view
    bar._keeping = True  # as an old session had it: several books in one tab
    try:
        exodus = window.open_path(niv / "02EXO.usfm")
    finally:
        bar._keeping = False
    leaf = _leaf(window, genesis)
    assert set(leaf.view_ids) == {genesis.view_id, exodus.view_id}
    genesis.document.insert(0, "\\rem edited\n")

    bar.settle_restored_books()
    assert set(leaf.view_ids) == {genesis.view_id, exodus.view_id}  # GEN has changes: kept

    genesis.document.undo()
    bar.settle_restored_books()
    assert leaf.view_ids == (exodus.view_id,)  # the shown book stays
