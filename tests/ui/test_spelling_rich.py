"""Spelling S4: Standard and Preview underline only what's on screen
(plan 2026-10-13-usfm-spellcheck-plan)."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QTextCharFormat  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from usfm_project_fixture import in_project  # noqa: E402
from uniti.app.settings import SettingsStore  # noqa: E402
from uniti.core.environments.sfm.spellcheck import CheckContext, SpellingCache  # noqa: E402
from uniti.core.environments.sfm.spelling import SpellingList, SpellingStatusData  # noqa: E402
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers  # noqa: E402
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline  # noqa: E402
from uniti.ui.main_window import UNITIMainWindow  # noqa: E402

_USFM = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning God created.\n"
_WITH_NOTE = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning God created.\\f + \\fr 1.1 \\ft zzfootnote\\f*\n"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path: Path):
    window = UNITIMainWindow(settings_store=SettingsStore(tmp_path / "settings.json"))
    window.resize(1000, 600)
    window.show()
    yield window
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def _open(window, tmp_path: Path, text: str):
    path = in_project(tmp_path / "book.usfm")
    path.write_text(text, encoding="utf-8", newline="")
    return window.open_path(path)


def _cache(document, known=("in", "the", "god", "created", "v", "c")) -> SpellingCache:
    data = SpellingStatusData()
    data.states.update({word: "R" for word in known})
    data.states["beginning"] = "W"
    styles = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))
    return SpellingCache(document, CheckContext(SpellingList(data, None), styles, "NIV"))


def _underlined(pane) -> list[str]:
    text = pane.editor.toPlainText()
    found = []
    for selection in pane.editor.extraSelections():
        if selection.format.underlineStyle() == QTextCharFormat.UnderlineStyle.SpellCheckUnderline:
            found.append(selection.cursor.selectedText())
    return found


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("sfm.standard", ["beginning", "zzfootnote"]), ("sfm.preview", ["beginning"])],
)
def test_a_wrong_word_is_underlined_and_preview_leaves_a_notes_text_to_its_frame(window, tmp_path: Path, app, mode, expected):
    view = _open(window, tmp_path, _WITH_NOTE)
    window._rich_views.show(mode)
    pane = window._rich_views.pane
    pane.set_spelling(_cache(view.document))
    app.processEvents()

    # Standard shows a note where it is, so its words are underlined there;
    # Preview moves it to the notes frame, which isn't underlined.
    assert _underlined(pane) == expected


def test_turning_it_off_clears_the_underlines_without_rendering_again(window, tmp_path: Path, app):
    view = _open(window, tmp_path, _USFM)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    pane.set_spelling(_cache(view.document))
    renders = []
    original = pane.refresh
    pane.refresh = lambda *args, **kwargs: renders.append(1) or original(*args, **kwargs)

    pane.set_spelling(None)
    assert _underlined(pane) == []
    pane.set_spelling(_cache(view.document))

    assert _underlined(pane) == ["beginning"] and renders == []


def test_an_edit_in_standard_updates_the_underline(window, tmp_path: Path, app):
    view = _open(window, tmp_path, _USFM)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    cache = _cache(view.document)
    pane.set_spelling(cache)
    assert _underlined(pane) == ["beginning"]

    index = view.document.read(0, view.document.total_chars()).index("God")
    view.document.insert(index, "qqq ")
    pane.refresh()
    app.processEvents()

    assert sorted(_underlined(pane)) == ["beginning", "qqq"]


def _long_book(chapters: int = 40) -> str:
    lines = ["\\id GEN"]
    for chapter in range(1, chapters + 1):
        lines += [f"\\c {chapter}", "\\p"]
        lines += [f"\\v {verse} In the beginning God created zzword{chapter}x{verse}." for verse in range(1, 9)]
    return "\n".join(lines) + "\n"


def test_only_the_words_on_screen_are_underlined_and_scrolling_updates_them(window, tmp_path: Path, app):
    view = _open(window, tmp_path, _long_book())
    window._rich_views.show("sfm.preview")
    pane = window._rich_views.pane
    pane.set_spelling(_cache(view.document, known=("in", "the", "god", "created", "beginning", "v", "c")))
    app.processEvents()
    first = [start for start, _end, _span in pane._spelling_shown]
    total_flagged = len(pane._book_spans())

    assert 0 < len(first) < total_flagged / 2  # far fewer than the book holds
    assert min(first) < 100  # from the top of the book

    bar = pane.editor.verticalScrollBar()
    bar.setValue(bar.maximum())
    app.processEvents()
    later = [start for start, _end, _span in pane._spelling_shown]

    assert later and len(later) < total_flagged / 2
    assert min(later) > max(first) and max(later) > len(pane.projection.text) - 200  # the end of the book


def test_a_frozen_window_underlines_nothing_until_it_is_live(window, tmp_path: Path, app):
    view = _open(window, tmp_path, _USFM)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    pane.is_live = lambda: False
    pane.set_spelling(_cache(view.document))
    assert _underlined(pane) == []

    pane.is_live = lambda: True
    pane.set_spelling(_cache(view.document))
    assert _underlined(pane) == ["beginning"]


def test_the_tooltip_in_a_rich_view(window, tmp_path: Path, app, monkeypatch):
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QToolTip

    view = _open(window, tmp_path, _USFM)
    window._rich_views.show("sfm.standard")
    pane = window._rich_views.pane
    pane.set_spelling(_cache(view.document))
    start, end, span = pane._spelling_shown[0]
    shown = []
    monkeypatch.setattr(QToolTip, "showText", lambda pos, text, *args: shown.append(text))
    rect = pane.editor.cursorRect(pane.editor.textCursor())
    # Point at the word's first characters.
    from PySide6.QtGui import QTextCursor

    cursor = QTextCursor(pane.editor.document())
    cursor.setPosition(pane._offsets.to_qt(start) + 1)
    point = pane.editor.cursorRect(cursor).center()

    pane.show_spelling_tooltip(QHelpEvent(QEvent.Type.ToolTip, point, pane.editor.mapToGlobal(point)))

    assert shown == ["Paratext marks this wrong"] and rect is not None
