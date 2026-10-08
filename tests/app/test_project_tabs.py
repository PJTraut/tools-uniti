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


def test_a_projects_books_share_one_tab_titled_with_its_short_name(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)

    exodus = window.open_path(niv / "02EXO.usfm")

    leaf = _leaf(window, exodus)
    assert leaf is _leaf(window, genesis) and len(leaf.view_ids) == 2  # both books open
    assert visible_tab_texts(leaf) == ["NIV"]  # one tab, the short name
    assert window.current_view is exodus
    assert leaf.tabToolTip(leaf.index_of(exodus.view_id)) == f"EXO\n{niv / '02EXO.usfm'}"
    assert window.windowTitle().startswith("UNITI — USFM A — NIV")

    # Another project is another tab.
    cars = _project(tmp_path / "cars", "CARS")
    window.open_path(cars / "01GEN.usfm")
    assert visible_tab_texts(leaf) == ["NIV", "CARS"]


def test_changing_the_book_changes_it_in_the_tab_and_keeps_each_books_state(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    bar = window._environment_bar
    from uniti.app.editor_state import EditorStateSnapshot

    caret = _GEN.index("\\v 2")
    genesis.state.restore_state(EditorStateSnapshot(caret, caret, None))
    genesis._state_changed()

    exodus = bar.open_book(niv / "02EXO.usfm")

    leaf = _leaf(window, genesis)
    assert window.current_view is exodus and _leaf(window, exodus) is leaf
    assert visible_tab_texts(leaf) == ["NIV"]
    assert not leaf.tabBar().isTabVisible(leaf.index_of(genesis.view_id))
    # Back again: the same view, caret where it was, still one tab.
    assert bar.open_book(niv / "01GEN.usfm") is genesis
    assert genesis.state.cursor == caret
    assert visible_tab_texts(leaf) == ["NIV"]
    # The tab stays where the project's tab was.
    assert leaf.index_of(genesis.view_id) == 0


def test_unsaved_changes_ask_before_the_book_changes(desktop, tmp_path: Path, monkeypatch):
    from uniti.ui import project_tabs

    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    bar = window._environment_bar
    asked = []
    answer = {"save": False}
    monkeypatch.setattr(
        project_tabs,
        "ask_save_before_switch",
        lambda parent, view, name: asked.append((view.document.path.name, name)) or answer["save"],
    )
    genesis.document.insert(genesis.document.total_chars(), "\\v 3 Added.\n")

    # No: the book keeps its changes, open but hidden, and is marked.
    exodus = bar.open_book(niv / "02EXO.usfm")
    assert asked == [("01GEN.usfm", "NIV")]
    assert window.current_view is exodus
    assert genesis.document.modified and genesis.document.can_undo
    assert service.documents.find_path(niv / "01GEN.usfm") is not None
    labels = [bar.book.itemText(i) for i in range(bar.book.count())]
    assert "GEN Genesis •" in labels
    assert visible_tab_texts(_leaf(window, exodus)) == ["NIV*"]  # unsaved work in the tab

    # Yes: saved, then changed.
    assert bar.open_book(niv / "01GEN.usfm") is genesis  # exodus is clean: no question
    assert len(asked) == 1
    answer["save"] = True
    bar.open_book(niv / "02EXO.usfm")
    assert asked[-1] == ("01GEN.usfm", "NIV")
    assert not genesis.document.modified
    assert "Added." in (niv / "01GEN.usfm").read_text(encoding="utf-8")
    assert visible_tab_texts(_leaf(window, exodus)) == ["NIV"]


def test_closing_a_project_tab_closes_all_its_books(desktop, tmp_path: Path, monkeypatch):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    cars = _project(tmp_path / "cars", "CARS")
    window, genesis = _usfm_window(service, niv)
    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")
    other = window.open_path(cars / "01GEN.usfm")
    genesis.document.insert(0, "\\rem edited\n")
    asked = []
    monkeypatch.setattr(
        window, "_confirm_close", lambda view: (asked.append(view.document.path.name) if view.document.modified else None) or True
    )
    leaf = _leaf(window, exodus)

    assert window._close_tab_request(exodus.view_id) is True

    assert asked == ["01GEN.usfm"]  # each modified book asks
    assert leaf.view_ids == (other.view_id,)
    assert visible_tab_texts(leaf) == ["CARS"]


def test_a_cancelled_close_keeps_the_tab(desktop, tmp_path: Path, monkeypatch):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    window, genesis = _usfm_window(service, niv)
    exodus = window._environment_bar.open_book(niv / "02EXO.usfm")
    exodus.document.insert(0, "\\rem edited\n")
    monkeypatch.setattr(window, "_confirm_close", lambda view: not view.document.modified)

    assert window.close_current() is False

    assert set(_leaf(window, exodus).view_ids) == {exodus.view_id}  # GEN closed, EXO kept


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
    # Both books are saved, the current one first: restored, it's the tab's book.
    assert record.root.view_ids == (exodus.view_id, genesis.view_id)


def test_ordinary_windows_keep_a_tab_per_file(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv", "NIV")
    main = service.new_window()
    main.open_path(niv / "01GEN.usfm")
    view = main.open_path(niv / "02EXO.usfm")

    assert main._project_tabs.active is False
    assert visible_tab_texts(_leaf(main, view)) == ["01GEN.usfm", "02EXO.usfm"]
