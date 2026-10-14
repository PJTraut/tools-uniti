"""Spelling S3: the wavy underline in Plain Text (plan 2026-10-13-usfm-spellcheck-plan)."""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from uniti.app.editor_state import EditorState  # noqa: E402
from uniti.core.document import Document  # noqa: E402
from uniti.core.environments.sfm.spellcheck import CheckContext, SpellingCache  # noqa: E402
from uniti.core.environments.sfm.spelling import SpellingList, SpellingStatusData  # noqa: E402
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers  # noqa: E402
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline  # noqa: E402
from uniti.ui.text_view import UNITITextView  # noqa: E402

_BOOK = "\\id GEN\n\\p\n\\v 1 fine bad zzzz fine\n\\v 2 fine fine\n"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _cache(document: Document, *, project: str = "NIV") -> SpellingCache:
    data = SpellingStatusData()
    data.states.update({"fine": "R", "bad": "W", "v": "R"})
    data.corrections["bad"] = "good"
    styles = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))
    return SpellingCache(document, CheckContext(SpellingList(data, None), styles, project))


def _view(tmp_path: Path, text: str = _BOOK):
    path = tmp_path / "01GEN.usfm"
    path.write_text(text, encoding="utf-8", newline="")
    document = Document.open(path, encoding="utf-8")
    view = UNITITextView(EditorState(document))
    view.resize(700, 300)
    view.show()
    return document, view


def _count(view, color) -> int:
    image = view.grab().toImage()
    target = color.rgb()
    return sum(1 for x in range(image.width()) for y in range(image.height()) if image.pixel(x, y) == target)


def test_flagged_words_are_underlined_in_their_colour_and_nothing_else_is(tmp_path: Path, app):
    document, view = _view(tmp_path)
    tokens = view._theme_tokens
    assert _count(view, tokens.spelling_wrong) == 0

    view.set_spelling(_cache(document))
    app.processEvents()

    assert _count(view, tokens.spelling_wrong) > 0  # "bad"
    assert _count(view, tokens.spelling_unknown) > 0  # "zzzz"
    view.set_spelling(None)
    assert _count(view, tokens.spelling_wrong) == 0 and _count(view, tokens.spelling_unknown) == 0
    document.close()


def test_the_cache_after_an_edit_checks_only_the_changed_lines(tmp_path: Path, app):
    document, view = _view(tmp_path)
    cache = _cache(document)
    view.set_spelling(cache)
    view.grab()
    checked = cache.checked

    view.grab()
    assert cache.checked == checked  # a repaint costs no checking

    document.insert(document.line_start(3), "qqq ")
    view.grab()
    assert cache.checked == checked + 1  # only the edited line
    assert [s.start for s in view.spelling_spans(3)] == [0]
    document.close()


def test_changing_the_word_list_updates_the_underlines(tmp_path: Path, app):
    document, view = _view(tmp_path)
    cache = _cache(document)
    view.set_spelling(cache)
    assert len(view.spelling_spans(2)) == 2

    data = SpellingStatusData()
    data.states.update({"fine": "R", "bad": "R", "zzzz": "R", "v": "R"})
    cache.set_context(CheckContext(SpellingList(data, None), cache.context._styles, "NIV"))

    assert view.spelling_spans(2) == ()
    document.close()


def test_the_tooltip_says_what_is_wrong(tmp_path: Path, app, monkeypatch):
    from PySide6.QtCore import QEvent, QPoint
    from PySide6.QtGui import QHelpEvent
    from PySide6.QtWidgets import QToolTip

    document, view = _view(tmp_path)
    view.set_spelling(_cache(document))
    shown = []
    monkeypatch.setattr(QToolTip, "showText", lambda pos, text, *args: shown.append(text))
    monkeypatch.setattr(view, "_char_for_point", lambda x, y: document.line_start(2) + _BOOK.split("\n")[2].index("bad") + 1)

    view.viewportEvent(QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), QPoint(5, 5)))
    monkeypatch.setattr(view, "_char_for_point", lambda x, y: document.line_start(2) + _BOOK.split("\n")[2].index("zzzz"))
    view.viewportEvent(QHelpEvent(QEvent.Type.ToolTip, QPoint(5, 5), QPoint(5, 5)))

    assert shown == ["Paratext marks this wrong: use good", "Not in NIV's spelling list"]
    document.close()


def test_a_wrapped_and_scrolled_view_still_underlines(tmp_path: Path, app):
    text = "\\id GEN\n\\p\n" + "\\v 1 " + "fine " * 80 + "zzzz " + "fine " * 20 + "\n"
    document, view = _view(tmp_path, text)
    view.set_soft_wrap(True)
    view.set_spelling(_cache(document))
    view.resize(300, 400)
    app.processEvents()

    assert _count(view, view._theme_tokens.spelling_unknown) > 0
    document.close()


def test_spelling_theme_roles_exist_in_every_theme_and_pass_contrast(app):
    from uniti.app.theme_profiles import packaged_profiles
    from uniti.ui.theme import THEME_CONTRASTS, THEME_MODES, build_theme, contrast_feedback

    for profile in packaged_profiles():
        assert {"editor.spelling_wrong", "editor.spelling_unknown"} <= set(profile.colors)
    for mode in THEME_MODES:
        for contrast in THEME_CONTRASTS:
            spec = build_theme(app.palette(), mode, contrast)
            rows = {label: (ratio, need) for label, ratio, need in contrast_feedback(spec)}
            for label in ("Spelling wrong", "Spelling unknown"):
                ratio, need = rows[label]
                assert ratio >= need, (mode, contrast, label, ratio)
