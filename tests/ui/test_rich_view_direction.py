"""The reading direction in the rich views (text direction plan W2, W4, W6)."""

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


# --- Standard's tags in a right-to-left paragraph (W4) ---------------------------

from pathlib import Path  # noqa: E402

from PySide6.QtTest import QTest  # noqa: E402

from usfm_project_fixture import in_project  # noqa: E402
from uniti.app.settings import SettingsStore  # noqa: E402
from uniti.core.environments.sfm.sty import parse_raw_stylesheet  # noqa: E402
from uniti.core.environments.sfm.style_layers import StyleLayer, StyleOrigin  # noqa: E402
from uniti.core.rich_views.source_map import LRI, PDI, RLI  # noqa: E402
from uniti.ui.main_window import UNITIMainWindow  # noqa: E402

TAGGED = "\\p \\v 1 שלום \\nd יהוה\\nd* עולם\n"


def test_tags_read_as_written_from_the_right():
    """`\\p \\v 1` reads from the right, each tag left to right inside."""

    projection = SfmStandardView(lambda: STYLES).project_with(TAGGED, direction="rtl")
    document = _render(projection)
    document.setTextWidth(600)
    document.size()  # lays the document out
    text = projection.text
    block = document.begin()
    layout = block.layout()
    assert layout.lineCount() == 1

    def x(position: int) -> float:
        """Where the glyph of the character at `position` is painted."""

        runs = layout.glyphRuns(position, 1)
        return min(point.x() for run in runs for point in run.positions())

    p, v = text.index("\\p"), text.index("\\v")
    assert x(p) < x(p + 1)  # "\\" left of "p"
    assert x(v) < x(v + 1)
    assert x(p) > x(v)  # the first tag is the rightmost


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


def _standard(window, tmp_path: Path, direction: str = "rtl"):
    path = in_project(tmp_path / "book.usfm")
    path.write_text(TAGGED, encoding="utf-8")
    view = window.open_path(path)
    view.set_text_direction_override(direction)
    window._rich_views.show("sfm.standard")
    return view, window._rich_views.pane


def _source(view) -> str:
    return view.document.read(0, view.document.total_chars())


def _put_caret(pane, position: int) -> None:
    cursor = pane.editor.textCursor()
    cursor.setPosition(position)
    pane.editor.setTextCursor(cursor)


def test_the_arrow_keys_step_past_the_isolates(window, tmp_path: Path):
    _view, pane = _standard(window, tmp_path)
    stops = pane._isolate_stops
    assert stops
    end = len(pane.projection.text)
    _put_caret(pane, 0)
    pane.editor.setFocus()

    visited = [0]
    for _ in range(end + 2):
        QTest.keyClick(pane.editor, Qt.Key.Key_Left)  # logical next in a right-to-left line
        visited.append(pane.editor.textCursor().position())
    forward = sorted(set(visited))
    for _ in range(end + 2):
        QTest.keyClick(pane.editor, Qt.Key.Key_Right)
        visited.append(pane.editor.textCursor().position())

    assert not stops & set(visited)
    assert set(forward) == set(range(end + 1)) - stops  # every other position, in one pass


def test_typing_beside_a_tag_lands_where_it_did_without_isolates(window, tmp_path: Path):
    view, pane = _standard(window, tmp_path)
    text = pane.projection.text
    after_tag = text.index("\\nd ") + len("\\nd ") + 1  # past the PDI
    _put_caret(pane, after_tag)
    assert pane.type_text("א")
    assert "\\nd איהוה\\nd*" in _source(view)

    text = pane.projection.text
    before_closer = text.index("\\nd*") - 1  # before the LRI
    _put_caret(pane, before_closer)
    assert pane.type_text("ב")
    assert "\\nd איהוהב\\nd*" in _source(view)

    # A click can put the caret just inside an isolate: still beside the tag.
    text = pane.projection.text
    inside = text.index("\\nd*") + len("\\nd*")  # before its PDI
    assert text[inside] == PDI
    _put_caret(pane, inside)
    assert pane.type_text("ג")
    assert "\\nd*ג עולם" in _source(view)


def test_backspace_steps_into_the_tag_as_without_isolates(window, tmp_path: Path):
    view, pane = _standard(window, tmp_path)
    text = pane.projection.text
    label_end = text.index("\\nd ") + len("\\nd ")
    _put_caret(pane, label_end + 1)  # past the PDI, at the start of יהוה

    assert pane.delete(backwards=True) is False
    assert _source(view) == TAGGED
    assert pane.editor.textCursor().position() == label_end - 1

    _put_caret(pane, label_end + 2)  # after the י
    assert pane.delete(backwards=True) is True
    assert "\\nd הוה\\nd*" in _source(view)


def test_copy_leaves_the_isolates_out(window, tmp_path: Path):
    _view, pane = _standard(window, tmp_path)
    assert LRI in pane.projection.text
    pane.editor.selectAll()

    copied = pane.editor.createMimeDataFromSelection().text()

    assert LRI not in copied and PDI not in copied
    assert copied == pane.projection.text.replace(LRI, "").replace(PDI, "")


# --- `\Direction` on character styles (W6) ----------------------------------------

LATIN = "\\p سلام \\tl Paul,\\tl* عليكم\n"
TL_RULE = "\\Marker tl\n\\Direction LTR\n"


def _x(document: QTextDocument, position: int) -> float:
    """Where the glyph of the character at `position` is painted."""

    document.setTextWidth(600)
    document.size()  # lays the document out
    layout = document.begin().layout()
    assert layout.lineCount() == 1
    runs = layout.glyphRuns(position, 1)
    return min(point.x() for run in runs for point in run.positions())


@pytest.mark.parametrize("view", [SfmStandardView, SfmPreviewView])
def test_a_latin_span_reads_as_written_in_an_arabic_line(view):
    """`Paul,` keeps its comma on the right; without the isolate the comma
    jumps to the left of the name."""

    rule = StyleLayer("uniti.sty", StyleOrigin.UNITI_PROJECT, parse_raw_stylesheet(TL_RULE))
    isolated = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None, [rule]))
    for styles, comma_on_the_right in ((isolated, True), (STYLES, False)):
        projection = view(lambda styles=styles: styles).project_with(LATIN, direction="rtl")
        document = _render(projection)
        comma = projection.text.index(",")
        assert (_x(document, comma) > _x(document, comma - 1)) is comma_on_the_right
        assert _x(document, comma - 4) < _x(document, comma - 3)  # "P" left of "a"


def _with_rule(window, tmp_path: Path, view_key: str, rule: str = TL_RULE, direction: str = "rtl"):
    path = in_project(tmp_path / "book.usfm")
    (tmp_path / "uniti.sty").write_text(rule, encoding="utf-8")
    path.write_text(LATIN, encoding="utf-8")
    view = window.open_path(path)
    view.set_text_direction_override(direction)
    window._rich_views.show(view_key)
    pane = window._rich_views.pane
    opener = LRI if "LTR" in rule else RLI
    assert f"{opener}Paul,{PDI}" in pane.projection.text
    return view, pane


@pytest.mark.parametrize(("rule", "direction"), [(TL_RULE, "rtl"), (TL_RULE.replace("LTR", "RTL"), "ltr")])
def test_the_arrow_keys_step_past_a_spans_isolates(window, tmp_path: Path, rule: str, direction: str):
    _view, pane = _with_rule(window, tmp_path, "sfm.standard", rule, direction)
    text = pane.projection.text
    stops = pane._isolate_stops
    span_start = text.index("Paul") - 1
    assert {span_start + 1, text.index("Paul,") + len("Paul,")} <= stops
    end = len(text)
    _put_caret(pane, 0)
    pane.editor.setFocus()

    visited = [0]
    for _ in range(end + 2):
        QTest.keyClick(pane.editor, Qt.Key.Key_Left if direction == "rtl" else Qt.Key.Key_Right)
        visited.append(pane.editor.textCursor().position())

    assert not stops & set(visited)
    assert set(visited) == set(range(end + 1)) - stops


def test_typing_beside_a_span_lands_in_it_as_without_isolates(window, tmp_path: Path):
    view, pane = _with_rule(window, tmp_path, "sfm.standard")
    text = pane.projection.text
    _put_caret(pane, text.index(f"{LRI}Paul"))  # past the tag, before the span's LRI
    assert pane.type_text("x")
    assert "\\tl xPaul,\\tl*" in _source(view)

    text = pane.projection.text
    _put_caret(pane, text.index(f"Paul,{PDI}") + len(f"Paul,{PDI}"))  # past the span's PDI
    assert pane.type_text("y")
    assert "\\tl xPaul,y\\tl*" in _source(view)


@pytest.mark.parametrize("view_key", ["sfm.standard", "sfm.preview"])
def test_copy_leaves_a_spans_isolates_out(window, tmp_path: Path, view_key: str):
    _view, pane = _with_rule(window, tmp_path, view_key)
    pane.editor.selectAll()

    copied = pane.editor.createMimeDataFromSelection().text()

    assert not set(copied) & {LRI, RLI, PDI}
    assert "Paul," in copied


# --- The direction in effect, in the status bar (the plan's Risks) ---------------


def _rtl_project_book(folder: Path, name: str = "NAV") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "Settings.xml").write_text(
        f'<ScriptureText><Name>{name}</Name><Naming PrePart="" PostPart=".usfm" BookNameForm="41MAT" />'
        "<LeftToRight>F</LeftToRight></ScriptureText>",
        encoding="utf-8",
    )
    path = folder / "43JHN.usfm"
    path.write_text(TAGGED, encoding="utf-8")
    return path


def _status(window) -> tuple[str, str]:
    label = window._status.direction_label
    return label.text(), label.toolTip()


def test_the_status_bar_shows_the_direction_in_effect(window, tmp_path: Path):
    view = window.open_path(_rtl_project_book(tmp_path / "nav"))

    # Plain Text follows only the tab's choice.
    assert _status(window)[0] == "Auto"
    window.set_editor_text_direction("rtl")
    assert _status(window)[0] == "RTL"
    window.set_editor_text_direction("auto")

    # Standard and Preview take the project's.
    window._rich_views.show("sfm.standard")
    text, tooltip = _status(window)
    assert text == "RTL" and "NAV" in tooltip and "Auto" in tooltip

    # The tab's choice wins, and the status bar says what it overrides.
    window.set_editor_text_direction("ltr")
    text, tooltip = _status(window)
    assert text == "LTR (project RTL)" and "this tab's" in tooltip
    assert window._rich_views.pane.projection.blocks[0].attrs.get("direction") == "ltr"

    window._rich_views.close(view)
    assert _status(window)[0] == "LTR"


def test_the_status_bar_follows_the_current_tab(window, tmp_path: Path):
    hebrew = window.open_path(_rtl_project_book(tmp_path / "nav"))
    window._rich_views.show("sfm.preview")
    assert _status(window)[0] == "RTL"

    plain = tmp_path / "notes.txt"
    plain.write_text("plain\n", encoding="utf-8")
    window.open_path(plain)
    assert _status(window)[0] == "Auto"

    window._tabs.setCurrentWidget(hebrew)
    assert _status(window)[0] == "RTL"

    window.close_all_documents(force=True)
    assert _status(window) == ("—", "")
