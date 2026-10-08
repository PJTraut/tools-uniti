"""The undefined-markup popup (round 2, R7; D4)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from usfm_project_fixture import in_project  # noqa: E402
from uniti.app.settings import SettingsStore  # noqa: E402
from uniti.core.environments import user_config  # noqa: E402
from uniti.core.environments.sfm.paratext_project import PARATEXT_BOOKS  # noqa: E402
from uniti.ui.main_window import UNITIMainWindow  # noqa: E402

_UNDEFINED = "\\id GEN\n\\c 1\n\\p\n\\v 1 A \\zfoo word\\zfoo* here.\n\\esb\n\\p B\n\\esbe\n"
_DEFINED = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning.\n"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path: Path):
    window = UNITIMainWindow(settings_store=SettingsStore(tmp_path / "settings" / "settings.json"))
    window.resize(1000, 600)
    window.show()
    yield window
    for dialog in window._environment.undefined_dialogs.values():
        dialog.close()
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()
    user_config.set_user_config_root(None)


def _open(window, path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    in_project(path).write_text(text, encoding="utf-8")
    return window.open_path(path)


def test_opening_a_file_with_undefined_markers_pops_up_the_report(window, tmp_path: Path):
    view = _open(window, tmp_path / "GEN.usfm", _UNDEFINED)

    dialog = window._environment.undefined_dialogs[view.view_id]
    assert dialog.isVisible()
    assert dialog.windowTitle() == "Undefined Markers — GEN.usfm"
    rows = [dialog.tree.topLevelItem(i) for i in range(dialog.tree.topLevelItemCount())]
    assert [(row.text(0), row.text(1)) for row in rows] == [("\\zfoo", "1"), ("\\esb", "1"), ("\\esbe", "1")]
    assert rows[0].child(0).text(0) == "GEN 1:1, line 4"
    assert "3 markers in GEN.usfm are not defined" in dialog.intro.text()


def test_a_fully_defined_file_opens_quietly(window, tmp_path: Path):
    view = _open(window, tmp_path / "GEN.usfm", _DEFINED)
    assert view.view_id not in window._environment.undefined_dialogs


def test_the_report_can_be_copied_and_saved(window, tmp_path: Path, app):
    view = _open(window, tmp_path / "GEN.usfm", _UNDEFINED)
    dialog = window._environment.undefined_dialogs[view.view_id]

    copied = dialog.copy_report()
    assert app.clipboard().text() == copied
    assert copied.startswith("Undefined markers in GEN.usfm\n")
    saved = dialog.save_report(tmp_path / "report.txt")
    assert saved.read_text(encoding="utf-8") == copied


def test_activating_a_use_jumps_to_it(window, tmp_path: Path):
    view = _open(window, tmp_path / "GEN.usfm", _UNDEFINED)
    dialog = window._environment.undefined_dialogs[view.view_id]
    esb = dialog.tree.topLevelItem(1)

    dialog._activated(esb.child(0), 0)

    assert view.state.cursor == _UNDEFINED.index("\\esb")


def test_adding_definitions_to_custom_sty_then_saving_defines_them(window, tmp_path: Path, app):
    # USFM assumes a project (round 3 T1), so definitions go to its custom.sty.
    view = _open(window, tmp_path / "project" / "GEN.usfm", _UNDEFINED)
    dialog = window._environment.undefined_dialogs[view.view_id]
    assert dialog.target_path() == tmp_path / "project" / "custom.sty"

    rules = dialog.add_definitions()

    text = rules.document.read(0, rules.document.total_chars())
    assert "Paratext, PTXprint and UNITI all read this file" in text
    assert "\\Marker zfoo\n\\Endmarker zfoo*\n" in text and "\\Marker esbe\n" in text
    window.save_current()
    app.processEvents()

    assert dialog.result.markers == ()
    assert "Every marker in GEN.usfm is defined." == dialog.intro.text()


def test_a_project_file_is_defined_in_the_projects_custom_sty(window, tmp_path: Path):
    project = tmp_path / "NIV"
    project.mkdir()
    present = "".join("1" if code == "GEN" else "0" for code in PARATEXT_BOOKS)
    (project / "Settings.xml").write_text(
        "<ScriptureText><Name>NIV</Name>"
        f'<Naming PrePart="" PostPart="NIV.usfm" BookNameForm="41MAT" /><BooksPresent>{present}</BooksPresent>'
        "</ScriptureText>",
        encoding="utf-8",
    )
    view = _open(window, project / "01GENNIV.usfm", _UNDEFINED)
    dialog = window._environment.undefined_dialogs[view.view_id]
    assert dialog.target_path() == project / "custom.sty"

    opened = dialog.edit_stylesheet()

    assert opened.document.path == project / "custom.sty"
    assert "Paratext, PTXprint and UNITI all read this file" in opened.document.read(0, opened.document.total_chars())
