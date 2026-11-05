"""Environment Settings… (N31, 2026-11-05) in the live window."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)

from PySide6.QtWidgets import QApplication, QCheckBox, QComboBox, QSpinBox

from uniti.app.settings import SettingsStore
from uniti.core.environments.settings import clear_settings_cache, settings_path
from uniti.ui.main_window import UNITIMainWindow
from uniti.ui.open_mode import OpenMode


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path: Path):
    clear_settings_cache()
    window = UNITIMainWindow(settings_store=SettingsStore(tmp_path / "settings.json"))
    window.resize(1000, 600)
    window.show()
    yield window
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()
    clear_settings_cache()


def _open_markdown(window, tmp_path: Path, name: str = "notes.md", text: str = "# T\n\n- a\n"):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return window.open_path(path, open_mode=OpenMode.HERE)


def test_the_dialog_is_built_from_the_declarations_and_saves_changes(window, tmp_path: Path):
    view = _open_markdown(window, tmp_path)
    dialog = window._environment.show_environment_settings(view)
    assert dialog.windowTitle() == "MD Settings"
    assert isinstance(dialog.editors["flavour"], QComboBox)
    assert isinstance(dialog.editors["blank_lines"], QSpinBox)
    assert isinstance(dialog.editors["align_tables"], QCheckBox)

    bullet = dialog.editors["bullet"]
    bullet.setCurrentIndex(bullet.findData("*"))
    dialog.accept()
    path = settings_path("markdown")
    assert json.loads(path.read_text(encoding="utf-8")) == {"bullet": "*"}

    # Format Document follows it at once.
    window._environment.run_command("format")
    QApplication.processEvents()
    assert view.document.read(0, view.document.total_chars()) == "# T\n\n* a\n"

    dialog = window._environment.show_environment_settings(view)
    assert dialog.editors["bullet"].currentData() == "*"
    dialog.restore_button.click()
    assert dialog.editors["bullet"].currentData() == "-"
    dialog.accept()
    assert json.loads(path.read_text(encoding="utf-8")) == {}


def test_plain_text_says_it_has_no_settings(window, tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_text("x", encoding="utf-8")
    view = window.open_path(path)
    dialog = window._environment.show_environment_settings(view)
    assert dialog.editors == {}


def test_opens_in_preview(window, tmp_path: Path):
    path = settings_path("markdown")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"opens_in": "markdown.rendered"}', encoding="utf-8")
    view = _open_markdown(window, tmp_path)
    assert window._rich_views.key_for(view) == "markdown.rendered"


def test_a_bad_settings_file_is_noted_once(window, tmp_path: Path):
    path = settings_path("markdown")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('{"bullet": "x"}', encoding="utf-8")
    view = _open_markdown(window, tmp_path)
    window._environment._note_settings_problems("markdown")
    assert "MD settings" in window.statusBar().currentMessage()
    assert window._rich_views.key_for(view) is None


def test_markdown_settings_link_to_the_stylesheet_files(window, tmp_path: Path):
    """N36: MD's Environment Settings has a button that opens the CSS layers."""

    view = _open_markdown(window, tmp_path)
    dialog = window._environment.show_environment_settings(view)
    assert dialog.manage_files_button is not None
    dialog.manage_files_button.click()
    assert window._environment.configuration_dialog is not None
    assert window._environment.configuration_dialog.environment_key == "markdown"


def test_plain_text_settings_have_no_stylesheet_button(window, tmp_path: Path):
    path = tmp_path / "a.txt"
    path.write_text("x\n", encoding="utf-8")
    view = window.open_path(path, open_mode=OpenMode.HERE)
    dialog = window._environment.show_environment_settings(view)
    assert dialog.manage_files_button is None
