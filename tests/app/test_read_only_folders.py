"""Read-only folders (field test round 3, T7)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from usfm_project_fixture import ensure_project  # noqa: E402
from test_service import _desktop_service, _stop_desktop_service  # noqa: E402

from uniti.app.read_only import is_read_only_path, with_folder  # noqa: E402
from uniti.core.document import DocumentReadOnlyError  # noqa: E402

_GEN = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning.\n"


@pytest.fixture
def desktop(tmp_path: Path):
    app, service, _recovery = _desktop_service(tmp_path)
    yield app, service
    for _window_id, window in service.windows.items:
        window.close_all_documents(force=True)
        window.close()
    app.processEvents()
    _stop_desktop_service(app, service)


def _project(folder: Path) -> Path:
    ensure_project(folder, name="NIV")
    (folder / "01GEN.usfm").write_text(_GEN, encoding="utf-8")
    return folder


def test_paths_in_or_below_a_folder_are_read_only(tmp_path: Path):
    folders = with_folder((), tmp_path / "projects", True)

    assert is_read_only_path(tmp_path / "projects" / "NIV" / "01GEN.usfm", folders)
    assert is_read_only_path(tmp_path / "projects", folders)
    assert not is_read_only_path(tmp_path / "projects-old" / "x.usfm", folders)
    assert with_folder(folders, tmp_path / "projects", False) == ()


def test_a_file_in_a_read_only_folder_cant_be_changed_or_saved(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "Paratext" / "NIV")
    main = service.new_window()
    main.set_read_only_folders([str(tmp_path / "Paratext")])
    assert main._settings_store.load().read_only_folders == (str(tmp_path / "Paratext"),)

    view = main.open_path(niv / "01GEN.usfm")

    assert view.document.read_only and view.read_only
    with pytest.raises(DocumentReadOnlyError):
        view.document.insert(0, "x")
    assert main.save_current() is None
    assert main.statusBar().currentMessage().startswith("01GEN.usfm is in a read-only folder")
    assert main.windowTitle().endswith("01GEN.usfm (read-only)")
    leaf = main._panes.leaf_for_view(view.view_id)
    assert leaf.tabText(leaf.index_of(view.view_id)).startswith("🔒 ")
    # Standard can't edit it either.
    main._rich_views.show("sfm.standard", view)
    assert main._rich_views.pane_for(view).editable is False
    assert (niv / "01GEN.usfm").read_text(encoding="utf-8") == _GEN


def test_turning_a_projects_folder_read_only_from_its_tab(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "niv")
    main = service.new_window()
    view = main.open_path(niv / "01GEN.usfm")
    window = main.move_to_environment_window(view)
    view.document.insert(0, "\\rem mine\n")  # editable for now

    read_only = next(action for action in window.tab_menu(view.view_id).actions() if action.text() == "Read Only")
    read_only.trigger()

    assert view.document.read_only and view.read_only
    assert window.read_only_folders() == (str(niv.resolve()),)
    assert window._project_tabs.label(view).startswith("🔒 NIV")
    # The unsaved edit is kept, and Save As elsewhere is the way out.
    assert view.document.modified
    window.set_folder_read_only(niv, False)
    assert not view.document.read_only


def test_replace_leaves_a_read_only_file_alone(desktop, tmp_path: Path):
    app, service = desktop
    niv = _project(tmp_path / "Paratext" / "NIV")
    main = service.new_window()
    view = main.open_path(niv / "01GEN.usfm")
    main.set_read_only_folders([str(tmp_path / "Paratext")])
    find = main._find_replace

    assert find._safe_operation_error(DocumentReadOnlyError("x")) == "the file is read-only"
    assert view.document.read_only
    with pytest.raises(DocumentReadOnlyError):
        view.document.replace_many([(0, 3, "XYZ")])
    assert view.document.read(0, 3) == "\\id"


def test_definitions_for_a_read_only_project_go_to_your_rules(desktop, tmp_path: Path):
    from uniti.ui.undefined_markup_dialog import UndefinedMarkupDialog

    app, service = desktop
    niv = _project(tmp_path / "Paratext" / "NIV")
    (niv / "01GEN.usfm").write_text(_GEN + "\\zfoo custom\n", encoding="utf-8")
    main = service.new_window()
    main.set_read_only_folders([str(tmp_path / "Paratext")])

    view = main.open_path(niv / "01GEN.usfm")

    dialog = main._environment.undefined_dialogs[view.view_id]
    assert isinstance(dialog, UndefinedMarkupDialog)
    assert dialog.target_path() == tmp_path / "Environments" / "USFM" / "uniti.sty"
