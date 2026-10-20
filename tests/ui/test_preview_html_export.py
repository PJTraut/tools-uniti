"""Export Preview as HTML from the window (text direction plan W8)."""

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
from uniti.core.environments.sfm.stylesheet_support import EXPORT_PREVIEW_HTML_FEATURE  # noqa: E402
from uniti.ui.main_window import UNITIMainWindow  # noqa: E402

BOOK = (
    "\\id JHN\n\\c 1\n\\p\n\\v 1 שלום\\f + \\cat People\\cat* \\ft hidden\\f* עולם\\f + \\ft shown\\f*\n"
    "\\c 2\n\\p\n\\v 1 second chapter\n"
)


@pytest.fixture
def window(tmp_path: Path):
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=SettingsStore(tmp_path / "settings.json"))
    window.resize(1000, 600)
    window.show()
    yield window
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def _open_book(window, tmp_path: Path):
    folder = tmp_path / "ARB"
    folder.mkdir()
    (folder / "Settings.xml").write_text(
        "<ScriptureText><Name>ARB</Name><FullName>Arabic Test</FullName><LanguageIsoCode>ar:::</LanguageIsoCode>"
        "<LeftToRight>F</LeftToRight><DefaultFont>Adobe Arabic</DefaultFont>"
        '<Naming PrePart="" PostPart=".usfm" BookNameForm="41MAT" /></ScriptureText>',
        encoding="utf-8",
    )
    path = folder / "43JHN.usfm"
    path.write_text(BOOK, encoding="utf-8")
    return window.open_path(path)


def test_the_command_is_in_the_usfm_menu_and_on_previews_menu(window, tmp_path: Path):
    view = _open_book(window, tmp_path)
    action = window._preview_export.action

    assert window._environment.offers_host_feature(view, EXPORT_PREVIEW_HTML_FEATURE)
    assert action.isEnabled()
    window._rich_views.show("sfm.preview")
    menu = window._rich_views.pane.editor.context_menu()
    assert action in menu.actions()
    window._rich_views.show("sfm.standard")
    assert action not in window._rich_views.pane.editor.context_menu().actions()


def test_it_exports_the_whole_book_with_the_tabs_preview_settings(window, tmp_path: Path):
    view = _open_book(window, tmp_path)
    view.hidden_note_categories = frozenset({"People"})
    window._chapter_view.set_enabled(True)  # Show One Chapter doesn't narrow the export
    target = tmp_path / "out" / "43JHN.html"
    target.parent.mkdir()

    assert window._preview_export.export(view, path=target)

    page = target.read_text(encoding="utf-8")
    assert '<html lang="ar" dir="rtl">' in page
    assert '"Adobe Arabic", serif' in page
    assert "<title>43JHN — Arabic Test</title>" in page
    assert "second chapter" in page  # chapter 2 too
    assert "shown" in page and "hidden" not in page
    assert "\\v" not in page  # Preview, not Standard


def test_a_plain_text_tab_has_no_export(window, tmp_path: Path):
    path = tmp_path / "notes.txt"
    path.write_text("text", encoding="utf-8")
    view = window.open_path(path)

    assert window._preview_export.html_for(view) is None
    assert window._preview_export.export(view, path=tmp_path / "x.html") is False
    assert not (tmp_path / "x.html").exists()
