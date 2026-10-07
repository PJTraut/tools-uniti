"""Open USFM Project… and Recent Projects (plan P2, ADR-0018)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from test_service import _desktop_service, _stop_desktop_service  # noqa: E402

from uniti.app.recent_projects import MAX_RECENT_PROJECTS, RecentProject, RecentProjectsStore  # noqa: E402
from uniti.core.environments.sfm.paratext_project import PARATEXT_BOOKS  # noqa: E402


def _project(folder: Path, name: str = "NIV11", books: tuple[str, ...] = ("GEN", "EXO")) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    present = "".join("1" if code in books else "0" for code in PARATEXT_BOOKS)
    (folder / "Settings.xml").write_text(
        f"<ScriptureText><Name>{name}</Name><Encoding>65001</Encoding><Versification>4</Versification>"
        f'<Naming PrePart="" PostPart="{name}.SFM" BookNameForm="41MAT" />'
        f"<BooksPresent>{present}</BooksPresent></ScriptureText>",
        encoding="utf-8",
    )
    numbers = {"GEN": "01", "EXO": "02"}
    for code in books:
        (folder / f"{numbers[code]}{code}{name}.SFM").write_text(
            f"\\id {code}\n\\c 1\n\\p\n\\v 1 One.\n\\v 2 Two.\n\\c 2\n\\p\n\\v 1 Again.\n", encoding="utf-8"
        )
    return folder


@pytest.fixture
def desktop(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)


def _no_prompt(window) -> None:
    def refuse(path, key):  # pragma: no cover - failing is the assertion
        raise AssertionError(f"unexpected 'Open as' prompt for {path}")

    window._confirm_environment_pin = refuse


# --- store -----------------------------------------------------------------------


def test_recent_projects_store_records_merges_and_bounds(tmp_path: Path):
    store = RecentProjectsStore(tmp_path / "recent-projects.json")
    assert store.load() == ()

    store.record_opened("/p/a", "A", group_id="A", book="GEN")
    store.record_opened("/p/b", "B")
    store.update("/p/a", reference="3:16")
    entry = store.record_opened("/p/a", "A2")  # fields left out are kept

    assert entry == RecentProject("/p/a", "A2", "A", "GEN", "3:16")
    assert [item.folder for item in store.load()] == ["/p/a", "/p/b"]

    for index in range(MAX_RECENT_PROJECTS + 5):
        store.record_opened(f"/p/{index}", str(index))
    assert len(store.load()) == MAX_RECENT_PROJECTS

    store.clear()
    assert store.load() == ()


def test_a_damaged_recent_projects_file_reads_as_empty(tmp_path: Path):
    path = tmp_path / "recent-projects.json"
    for text in ("{", '{"schema": 2, "projects": []}', '{"schema": 1, "projects": [{"folder": 1}]}'):
        path.write_text(text, encoding="utf-8")
        assert RecentProjectsStore(path).load() == ()


# --- opening ------------------------------------------------------------------------


def test_open_project_opens_its_first_book_in_the_usfm_window(desktop, tmp_path: Path):
    app, service = desktop
    folder = _project(tmp_path / "NIV11")
    main = service.new_window()
    _no_prompt(main)

    view = main._usfm_projects.open_project(folder)

    window = service.windows.window_for_view(view.view_id)
    assert window.environment_window == ("usfm", None)
    assert view.document.path.name == "01GENNIV11.SFM"
    # .SFM isn't assigned to USFM, but a project's books are USFM: pinned, no prompt.
    assert window._environment.environment_key_for(view.document) == "usfm"
    recent = main._usfm_projects.store.load()
    assert [(entry.name, entry.book) for entry in recent] == [("NIV11", "GEN")]


def test_reopening_a_project_returns_to_where_it_was_left(desktop, tmp_path: Path):
    app, service = desktop
    folder = _project(tmp_path / "NIV11")
    main = service.new_window()
    view = main._usfm_projects.open_project(folder)
    window = service.windows.window_for_view(view.view_id)
    exodus = window._environment_bar.open_book(folder / "02EXONIV11.SFM")
    text = exodus.document.read(0, exodus.document.total_chars())
    exodus.state.move_to(text.index("Again"))
    exodus._state_changed()
    window._usfm_projects._save_position()

    entry = main._usfm_projects.store.find(folder)
    assert (entry.book, entry.reference) == ("EXO", "2:1")

    for _window_id, open_window in service.windows.items:
        open_window.close_all_documents(force=True)
    reopened = main._usfm_projects.open_project(folder)

    assert reopened.document.path.name == "02EXONIV11.SFM"
    assert reopened.state.cursor == text.index("\\v 1 Again")


def test_a_project_opens_in_its_remembered_group(desktop, tmp_path: Path):
    app, service = desktop
    folder = _project(tmp_path / "NIV11")
    main = service.new_window()
    main._usfm_projects.store.record_opened(folder, "NIV11", group_id="B")

    view = main._usfm_projects.open_project(folder)

    assert service.windows.window_for_view(view.view_id).environment_window == ("usfm", "B")
    assert service.documents.entry_for_view(view.view_id).group_id == "B"


def test_a_folder_without_settings_xml_is_refused(desktop, tmp_path: Path, monkeypatch):
    from uniti.ui import usfm_projects

    app, service = desktop
    main = service.new_window()
    warnings = []
    monkeypatch.setattr(usfm_projects.QMessageBox, "warning", lambda *args: warnings.append(args[2]))

    assert main._usfm_projects.open_project(tmp_path) is None
    assert "isn't a Paratext project" in warnings[0]
    assert main._usfm_projects.store.load() == ()


def test_opening_a_project_book_as_a_file_records_the_project(desktop, tmp_path: Path):
    app, service = desktop
    folder = _project(tmp_path / "NIV11")
    main = service.new_window()

    main.open_path(folder / "02EXONIV11.SFM")

    entry = main._usfm_projects.store.find(folder)
    assert entry is not None and (entry.name, entry.book) == ("NIV11", "EXO")


def test_recent_projects_menu_lists_and_clears(desktop, tmp_path: Path):
    app, service = desktop
    folder = _project(tmp_path / "NIV11")
    main = service.new_window()
    store = main._usfm_projects.store
    store.record_opened(tmp_path / "gone", "OLD")
    store.record_opened(folder, "NIV11")

    main._usfm_projects.populate_menu()
    actions = [action for action in main._usfm_projects.menu.actions() if not action.isSeparator()]

    assert [(action.text(), action.isEnabled()) for action in actions] == [
        ("NIV11", True),
        ("OLD (unavailable)", False),
        ("Clear Recent Projects", True),
    ]
    actions[0].trigger()
    assert service.documents.find_path(folder / "01GENNIV11.SFM") is not None
    actions[-1].trigger()
    assert store.load() == ()
