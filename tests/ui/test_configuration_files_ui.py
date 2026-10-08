"""Configuration Files…: open, create, copy, and reload on save (round 2, R8)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from uniti.app.settings import SettingsStore  # noqa: E402
from uniti.core.environments import user_config  # noqa: E402
from uniti.ui.main_window import UNITIMainWindow  # noqa: E402

_USFM = "\\id GEN\n\\c 1\n\\p\n\\v 1 The \\nd Lord\\nd* spoke.\n"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path: Path):
    window = UNITIMainWindow(settings_store=SettingsStore(tmp_path / "settings" / "settings.json"))
    window.resize(1000, 600)
    window.show()
    yield window
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()
    user_config.set_user_config_root(None)


def _open(window, path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return window.open_path(path)


def _nd_attrs(pane) -> dict[str, str]:
    start = pane.projection.text.index("Lord")
    merged: dict[str, str] = {}
    for span in pane.projection.spans:
        if span.marker == "nd" and span.view_start <= start < span.view_end and "marker_token" not in span.attrs:
            merged.update(span.attrs)
    return merged


def test_the_user_folder_lives_next_to_the_settings(window, tmp_path: Path):
    assert user_config.user_config_root() == tmp_path / "settings"


def test_creating_and_saving_your_rules_updates_preview(window, tmp_path: Path, app):
    book = _open(window, tmp_path / "project" / "GEN.usfm", _USFM)
    window._rich_views.show("sfm.preview", book)
    assert _nd_attrs(window._rich_views.pane_for(book)) == {"smallcaps": "yes"}  # built-in rule

    dialog = window._environment.show_configuration_files(book)
    dialog.select_role("Your rules (every USFM file)")
    assert dialog.create_button.isEnabled() and not dialog.open_button.isEnabled()
    rules = dialog.create_selected()

    path = tmp_path / "settings" / "Environments" / "USFM" / "uniti.sty"
    assert rules is window.current_view and rules.document.path == path
    assert path.read_text(encoding="utf-8").startswith("# uniti.sty - your own rules")
    assert rules.syntax_profile.key == "plain_text"  # a .sty file opens as plain text, not USFM

    rules.document.replace(0, rules.document.total_chars(), "\\Marker nd\n\\Underline\n\\SmallCaps -\n")
    window.save_current()
    window._select_view(book)
    app.processEvents()

    assert _nd_attrs(window._rich_views.pane_for(book)) == {"underline": "yes"}
    dialog.refresh()
    dialog.select_role("Your rules (every USFM file)")
    assert dialog.open_button.isEnabled() and not dialog.create_button.isEnabled()


def test_a_built_in_file_opens_as_a_copy_to_read(window, tmp_path: Path):
    book = _open(window, tmp_path / "GEN.usfm", _USFM)
    dialog = window._environment.show_configuration_files(book)
    dialog.select_role("Official USFM stylesheet")
    assert dialog.copy_button.isEnabled() and not dialog.create_button.isEnabled()

    copy = dialog.open_selected()

    assert copy.document.path == tmp_path / "settings" / "Environments" / "USFM" / "Reference" / "usfm.sty"
    assert "\\Marker nd" in copy.document.read(0, copy.document.total_chars())


def test_creating_the_project_custom_stylesheet(window, tmp_path: Path):
    book = _open(window, tmp_path / "project" / "GEN.usfm", _USFM)
    dialog = window._environment.show_configuration_files(book)
    dialog.select_role("Project custom stylesheet")

    created = dialog.create_selected()

    assert created.document.path == tmp_path / "project" / "custom.sty"
    assert "Paratext, PTXprint and UNITI all read this file" in created.document.read(0, created.document.total_chars())


def test_every_environment_lists_its_folder_and_documentation(window, tmp_path: Path):
    view = _open(window, tmp_path / "data.json", '{"a": 1}')
    dialog = window._environment.show_configuration_files(view)
    assert [row.role for row in dialog.rows] == ["Your JSON configuration folder"]
    assert dialog.windowTitle() == "JSON Configuration Files"
    assert dialog.docs_button.isEnabled()
