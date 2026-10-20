"""The reading direction in the rich views (text direction plan W2)."""

from __future__ import annotations

import importlib.util
import os
from types import SimpleNamespace

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QFont, QPalette, QTextDocument  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from uniti.core.document import Document  # noqa: E402
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers  # noqa: E402
from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline  # noqa: E402
from uniti.core.environments.sfm.views import SfmPreviewView, SfmStandardView  # noqa: E402
from uniti.ui.rich_view import PROJECTIONS, RichPalette, block_format, render_projection  # noqa: E402
from uniti.ui.rich_view_controller import RichViewController  # noqa: E402

_APP = QApplication.instance() or QApplication([])
STYLES = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))
HEBREW = (
    "\\id JHN\n\\c 1\n\\p\n\\v 1 שלום עולם\n\\q1 Paul שלום עולם\n\\qr \\v 2 שלום\n\\s1 12\n\\p\nשלום\n"
)
AUTO = Qt.LayoutDirection.LayoutDirectionAuto


def _render(projection) -> QTextDocument:
    document = QTextDocument()
    render_projection(document, projection, QFont(), RichPalette.from_widget_palette(QPalette()))
    return document


def _directions(document: QTextDocument) -> list[Qt.LayoutDirection]:
    result = []
    block = document.begin()
    while block.isValid():
        result.append(block.blockFormat().layoutDirection())
        block = block.next()
    return result


def test_block_format_sets_the_layout_direction():
    assert block_format({"direction": "rtl"}).layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert block_format({"direction": "ltr"}).layoutDirection() == Qt.LayoutDirection.LeftToRight
    assert block_format({"align": "start"}).layoutDirection() == AUTO
    assert block_format({"direction": "up"}).layoutDirection() == AUTO


@pytest.mark.parametrize("view", [SfmStandardView, SfmPreviewView])
def test_every_paragraph_takes_the_direction_whatever_it_starts_with(view):
    """A tag-led, a Latin-led and a digit-only paragraph, and the chapter
    heading: Qt's first-strong guess is bypassed."""

    projection = view(lambda: STYLES).project_with(HEBREW, direction="rtl")
    document = _render(projection)

    directions = _directions(document)
    assert len(directions) > 3
    assert set(directions) == {Qt.LayoutDirection.RightToLeft}
    assert all(block.textDirection() == Qt.LayoutDirection.RightToLeft for block in _blocks(document))


def test_without_a_direction_nothing_is_set():
    projection = SfmStandardView(lambda: STYLES).project(HEBREW)

    assert set(_directions(_render(projection))) == {AUTO}


def _blocks(document: QTextDocument):
    block = document.begin()
    while block.isValid():
        yield block
        block = block.next()


def test_the_cache_keeps_a_projection_per_direction(tmp_path):
    path = tmp_path / "a.usfm"
    path.write_text(HEBREW, encoding="utf-8")
    document = Document.open(path)
    view = SfmPreviewView(lambda: STYLES)

    plain = PROJECTIONS.project(document, view, lambda: HEBREW)
    rtl = PROJECTIONS.project(document, view, lambda: HEBREW, None, None, "rtl")
    ltr = PROJECTIONS.project(document, view, lambda: HEBREW, None, None, "ltr")

    assert rtl is not plain and ltr is not rtl
    assert PROJECTIONS.project(document, view, lambda: HEBREW, None, None, "rtl") is rtl
    assert PROJECTIONS.project(document, view, lambda: HEBREW) is plain
    document.close()


def _view(folder, choice: str = "auto"):
    return SimpleNamespace(text_direction_override=choice, document=SimpleNamespace(path=folder / "41MAT.SFM"))


def _project(folder, flag: str | None) -> None:
    flag_xml = "" if flag is None else f"<LeftToRight>{flag}</LeftToRight>"
    (folder / "Settings.xml").write_text(f"<ScriptureText><Name>P</Name>{flag_xml}</ScriptureText>", encoding="utf-8")


def test_the_views_choice_beats_the_project_which_beats_the_text(tmp_path):
    direction_for = RichViewController.direction_for
    _project(tmp_path, "F")

    assert direction_for(_view(tmp_path)) == "rtl"
    assert direction_for(_view(tmp_path, "ltr")) == "ltr"
    assert direction_for(_view(tmp_path, "rtl")) == "rtl"

    other = tmp_path / "other"
    other.mkdir()
    _project(other, "T")
    assert direction_for(_view(other)) == "ltr"
    assert direction_for(_view(other, "rtl")) == "rtl"


def test_no_project_or_no_setting_leaves_the_direction_to_the_text(tmp_path):
    direction_for = RichViewController.direction_for
    assert direction_for(None) is None
    assert direction_for(_view(tmp_path)) is None  # not a project

    unset = tmp_path / "unset"
    unset.mkdir()
    _project(unset, None)
    assert direction_for(_view(unset)) is None
    assert direction_for(_view(unset, "rtl")) == "rtl"
