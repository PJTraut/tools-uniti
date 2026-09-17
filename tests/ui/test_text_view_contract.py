import ast
import importlib.util
import os
from pathlib import Path

import pytest


SOURCE = Path("src/uniti/ui/text_view.py")


def test_text_view_is_custom_qabstractscrollarea_without_qt_document_store():
    assert SOURCE.exists()
    source = SOURCE.read_text(encoding="utf-8")
    assert "QPlainTextEdit" not in source
    assert "QTextDocument" not in source
    assert "_fixed_pitch_font" not in source
    assert "resolve_editor_font" in source
    tree = ast.parse(source)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    target = next(node for node in classes if node.name == "UNITITextView")
    bases = [ast.unparse(base) for base in target.bases]
    assert "QAbstractScrollArea" in bases


def test_core_and_resources_remain_qt_free():
    for root in (Path("src/uniti/core"), Path("src/uniti/resources")):
        for path in root.glob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "PySide6" not in source
            assert "PyQt" not in source


def test_text_view_offscreen_smoke_when_pyside6_is_available(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "view.txt"
    path.write_text("one\ntwo\n", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(640, 480)
        view.show()
        app.processEvents()
        assert view.state is state
        view.close()


def test_scrolling_to_the_end_fully_reveals_the_last_line(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "view.txt"
    path.write_text(
        "\n".join(f"line {i}" for i in range(40)), encoding="utf-8", newline=""
    )
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        try:
            # A height deliberately not a whole multiple of the row height —
            # a scroll maximum padded for a partial extra row leaves the
            # true last line straddling the viewport's bottom edge (BF-025).
            view.resize(320, view._line_height * 10 + view._line_height // 2)
            view.show()
            app.processEvents()

            scrollbar = view.verticalScrollBar()
            scrollbar.setValue(scrollbar.maximum())
            app.processEvents()

            first_line = scrollbar.value()
            known_lines = document.document_line_index.indexed_line_count
            assert document.document_line_index.complete
            last_row = known_lines - 1 - first_line
            assert (last_row + 1) * view._line_height <= view.viewport().height()
        finally:
            view.close()


def test_set_tab_width_changes_visible_tab_stop_width(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "tabs.txt"
    path.write_text("\tX", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        try:
            view.resize(640, 200)
            assert view._tab_width_chars == 4

            view.set_tab_width(2)
            narrow = view._shape("\tX").width

            view.set_tab_width(8)
            wide = view._shape("\tX").width

            assert wide > narrow
        finally:
            view.close()


def test_text_view_pages_horizontally_by_character_window():
    source = SOURCE.read_text(encoding="utf-8")
    assert "def _horizontal_window" in source
    assert "column_start=column_start" in source
    assert "line_window_start = line_start + column_start" in source
    assert "shaped.cp_for_x" in source


def test_text_view_exposes_clipboard_and_ime_contracts_without_qt_document_storage():
    source = SOURCE.read_text(encoding="utf-8")
    for required in (
        "copy_selection",
        "cut_selection",
        "paste_clipboard",
        "inputMethodEvent",
        "inputMethodQuery",
        "QGuiApplication.clipboard",
        "commitString",
        "preeditString",
    ):
        assert required in source
    assert "QTextDocument" not in source
    assert "QPlainTextEdit" not in source


def test_text_view_paints_invalid_byte_annotations_distinctly():
    source = SOURCE.read_text(encoding="utf-8")
    assert "read_line_window_annotated" in source
    assert "invalid_bytes" in source
    assert "_paint_invalid_byte_annotations" in source


@pytest.mark.parametrize(
    ("mode", "expected"),
    (
        ("off", ()),
        ("eol", ("CRLF",)),
        ("spaces_tabs", ("SPACE", "TAB")),
        ("invisible_unicode", ("NBSP", "ZWSP")),
        ("all", ("SPACE", "TAB", "NBSP", "ZWSP", "CRLF")),
    ),
)
@pytest.mark.parametrize("inspecting", [False, True])
def test_whitespace_modes_paint_only_their_marker_categories(
    tmp_path: Path,
    monkeypatch,
    mode: str,
    expected: tuple[str, ...],
    inspecting: bool,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / f"markers-{mode}.txt"
    path.write_bytes("a b\tc\u00a0\u200b\r\n".encode("utf-8"))
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        painted: list[str] = []

        def observe(_painter, _kind, label, _x1, _x2, _y, **_kwargs):
            painted.append(label)

        monkeypatch.setattr(view, "_paint_whitespace_marker", observe)
        view.set_whitespace_mode(mode)
        view.resize(640, 100)
        view.show()
        app.processEvents()
        if inspecting:
            app.sendEvent(view, QKeyEvent(
                QEvent.Type.KeyPress, Qt.Key.Key_Alt,
                Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier,
            ))
        painted.clear()
        view.viewport().repaint()
        app.processEvents()

        assert tuple(painted) == expected
        app.sendEvent(app, QEvent(QEvent.Type.ApplicationDeactivate))
        view.close()


def test_whitespace_off_has_no_marker_pixels_and_spaces_mode_uses_theme_token(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace

    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView
    from uniti.ui.theme import active_theme

    path = tmp_path / "marker-pixels.txt"
    path.write_text("a b", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    marker = QColor("#ff00ff")
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.set_theme_tokens(
            replace(active_theme(app).editor, space_marker=marker)
        )
        view.resize(320, 80)
        view.show()
        view.set_whitespace_mode("spaces_tabs")
        app.processEvents()
        visible = view.viewport().grab().toImage()
        assert any(
            visible.pixelColor(x, y) == marker
            for x in range(visible.width())
            for y in range(visible.height())
        )

        view.set_whitespace_mode("off")
        view.viewport().repaint()
        app.processEvents()
        hidden = view.viewport().grab().toImage()
        assert all(
            hidden.pixelColor(x, y) != marker
            for x in range(hidden.width())
            for y in range(hidden.height())
        )
        view.close()


def test_wrapped_eol_marker_is_painted_only_on_final_visual_row(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "wrapped-eol.txt"
    path.write_bytes(b"abcdef\r\n")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        painted: list[tuple[str, int]] = []

        def observe(_painter, _kind, label, _x1, _x2, y, **_kwargs):
            painted.append((label, y))

        monkeypatch.setattr(view, "_paint_whitespace_marker", observe)
        view.resize(
            view._gutter_width + view._cell_width * 2 + 10 + view._canvas_inset * 2,
            120 + view._canvas_inset * 2,
        )
        view.set_soft_wrap(True)
        view.set_whitespace_mode("eol")
        view.show()
        app.processEvents()
        painted.clear()
        view.viewport().repaint()
        app.processEvents()

        assert len(painted) == 1
        assert painted[0][0] == "CRLF"
        assert painted[0][1] >= view._line_height * 2
        view.close()


def test_end_of_text_marker_stays_clear_of_text_regardless_of_direction(
    tmp_path: Path,
):
    """A fixed rightward nudge (the EOL/overflow marker's old behavior)
    only lands in empty margin for LTR, where reading order and
    increasing screen x agree. For RTL, reading continues to the *left*
    of the text's end -- the same rightward nudge draws the marker glyph
    back on top of the text instead of past its edge. Confirmed directly:
    a 36-character Arabic line's EOL marker fully overlapped the line's
    own rendered text before this fix (bounding boxes (102, 286) and
    (106, 288) -- effectively the same span)."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "direction-neutral.txt"
    path.write_text("x", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        left = 100
        for rtl in (False, True):
            for glyph in ("␊", "␍", "␍␊"):
                x = view._end_of_text_marker_x(left, glyph, rtl=rtl)
                width = view._metrics.horizontalAdvance(glyph)
                if rtl:
                    # The whole glyph must sit at or before `left`,
                    # entirely in the margin beyond the RTL text's own
                    # (leftward) end -- not spilling back over `left`
                    # into the text itself.
                    assert x + width <= left
                else:
                    # The glyph must start at or after `left`, in the
                    # margin beyond the LTR text's own (rightward) end.
                    assert x >= left
        view.close()
        app.processEvents()


def test_rtl_eol_marker_is_positioned_clear_of_the_arabic_text(
    tmp_path: Path, monkeypatch
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "rtl-eol.txt"
    arabic = "مرحبا بكم جميعا في هذا اليوم الجميل"
    path.write_text(arabic + "\n", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        painted: list[tuple[str, float, bool]] = []

        def observe(_painter, kind, label, x1, _x2, _y, *, rtl=False):
            if kind == "eol":
                painted.append((label, x1, rtl))

        view.resize(300, 100)
        view.set_soft_wrap(False)
        view.set_whitespace_mode("eol")
        view.show()
        app.processEvents()
        monkeypatch.setattr(view, "_paint_whitespace_marker", observe)
        view.viewport().repaint()
        app.processEvents()

        assert len(painted) == 1
        label, x1, rtl = painted[0]
        assert label == "LF"
        assert rtl is True
        resolved = view._end_of_text_marker_x(int(round(x1)), "␊", rtl=True)
        width = view._metrics.horizontalAdvance("␊")
        # The glyph must be drawn entirely to the left of the text's own
        # end position (`x1`), not overlapping it.
        assert resolved + width <= int(round(x1))
        view.close()


def test_whitespace_marker_frame_budget_reserves_one_overflow_aggregate(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import MAX_WHITESPACE_MARKERS_PER_FRAME, UNITITextView

    path = tmp_path / "dense-markers.txt"
    path.write_text(" " * 6000, encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        painted: list[str] = []

        def observe(_painter, _kind, label, _x1, _x2, _y, **_kwargs):
            painted.append(label)

        monkeypatch.setattr(view, "_paint_whitespace_marker", observe)
        view.set_zoom_percent(50)
        view.resize(40_000, 60)
        view.set_whitespace_mode("spaces_tabs")
        view.show()
        app.processEvents()
        painted.clear()
        view.viewport().repaint()
        app.processEvents()

        assert len(painted) <= MAX_WHITESPACE_MARKERS_PER_FRAME == 4096
        aggregates = [label for label in painted if label.startswith("+")]
        assert len(aggregates) == 1
        assert int(aggregates[0][1:]) > 0
        view.close()


@pytest.mark.parametrize(
    ("base", "text", "highlight", "highlighted_text"),
    (
        ("#ffffff", "#111827", "#2563eb", "#ffffff"),
        ("#0d1117", "#f0f4f8", "#58a6ff", "#06121f"),
    ),
)
def test_selected_text_uses_highlighted_text_palette_role(
    tmp_path: Path,
    base: str,
    text: str,
    highlight: str,
    highlighted_text: str,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace

    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "selected.txt"
    path.write_text("MMMM", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document, cursor=4, anchor=0))
        palette = QPalette(view.palette())
        palette.setColor(QPalette.ColorRole.Base, QColor(base))
        palette.setColor(QPalette.ColorRole.Text, QColor(text))
        palette.setColor(QPalette.ColorRole.Highlight, QColor(highlight))
        palette.setColor(
            QPalette.ColorRole.HighlightedText,
            QColor(highlighted_text),
        )
        view.setPalette(palette)
        view.set_theme_tokens(
            replace(
                view.theme_tokens,
                base=QColor(base),
                text=QColor(text),
                selection=QColor(highlight),
                selected_text=QColor(highlighted_text),
            )
        )
        view.resize(320, 100)
        view.show()
        app.processEvents()
        view.viewport().repaint()
        app.processEvents()

        image = view.viewport().grab().toImage()
        x1 = view._gutter_width
        x2 = x1 + view._metrics.horizontalAdvance("MMMM")
        selected_pixels = {
            image.pixelColor(x, y).name()
            for x in range(x1, x2)
            for y in range(view._line_height)
        }

        background = QColor(highlight)
        expected = QColor(highlighted_text)
        ordinary = QColor(text)
        foreground_pixels = [
            QColor(pixel)
            for pixel in selected_pixels
            if pixel != background.name()
        ]

        def distance(left: QColor, right: QColor) -> int:
            return sum(
                (first - second) ** 2
                for first, second in zip(left.getRgb()[:3], right.getRgb()[:3])
            )

        assert foreground_pixels
        assert min(distance(pixel, expected) for pixel in foreground_pixels) < min(
            distance(pixel, ordinary) for pixel in foreground_pixels
        )
        view.close()
        view.deleteLater()
        app.processEvents()


def test_syntax_profile_paints_a_token_in_its_category_color(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.core.syntax_profiles import profile_for_extension
    from uniti.ui.syntax_theme import syntax_category_palette
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "sample.json"
    text = '{"key": 1}'
    path.write_text(text, encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        try:
            view.set_syntax_profile(profile_for_extension("json"))
            view.resize(320, 100)
            view.show()
            app.processEvents()
            view.viewport().repaint()
            app.processEvents()

            image = view.viewport().grab().toImage()
            # `"key"` spans text[1:6]; sample across its rendered width.
            x_start = view._gutter_width + view._metrics.horizontalAdvance(text[:1])
            x_end = view._gutter_width + view._metrics.horizontalAdvance(text[:6])
            y = view._line_height // 2

            expected_color = syntax_category_palette(view.theme_tokens.base)["string"]
            text_color = view.theme_tokens.text

            def distance(left: QColor, right: QColor) -> int:
                return sum(
                    (a - b) ** 2 for a, b in zip(left.getRgb()[:3], right.getRgb()[:3])
                )

            closest = min(
                (image.pixelColor(x, y) for x in range(x_start, x_end)),
                key=lambda color: distance(color, expected_color),
            )
            assert distance(closest, expected_color) < distance(closest, text_color)
        finally:
            view.close()


def test_plain_text_syntax_profile_leaves_rendering_unaffected(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "sample.txt"
    text = '{"key": 1}'
    path.write_text(text, encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        try:
            view.resize(320, 100)
            view.show()
            app.processEvents()
            view.viewport().repaint()
            app.processEvents()
            before = view.viewport().grab().toImage()

            from uniti.core.syntax_profiles import PLAIN_TEXT

            assert view.syntax_profile is PLAIN_TEXT
            view.viewport().repaint()
            app.processEvents()
            after = view.viewport().grab().toImage()
            assert before == after
        finally:
            view.close()


def test_syntax_highlighting_never_changes_document_content(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.core.syntax_profiles import profile_for_extension
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "sample.xml"
    text = '<a b="c">text</a>'
    path.write_text(text, encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        try:
            view.set_syntax_profile(profile_for_extension("xml"))
            view.resize(320, 100)
            view.show()
            app.processEvents()
            view.viewport().repaint()
            app.processEvents()
            assert document.read(0, document.total_chars()) == text
            assert not document.modified
        finally:
            view.close()


def test_zero_width_marker_row_ownership_is_unambiguous():
    from uniti.ui.text_view import _zero_width_visible

    assert not _zero_width_visible(2, 0, 2, owns_end=False)
    assert _zero_width_visible(2, 2, 4, owns_end=True)
    assert _zero_width_visible(4, 2, 4, owns_end=True)
    assert not _zero_width_visible(4, 2, 4, owns_end=False)


def test_wrapped_zero_width_marker_is_painted_on_only_its_owning_row(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace

    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.regex.results import MatchIndex, MatchRecord
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "zero-width-wrap.txt"
    path.write_text("abcd", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        palette = view.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#204060"))
        view.setPalette(palette)
        match = QColor("#204060")
        match.setAlpha(120)
        view.set_theme_tokens(
            replace(
                view.theme_tokens,
                base=QColor("#ffffff"),
                match=match,
            )
        )
        view.resize(
            view._gutter_width + view._cell_width * 2 + 10 + view._canvas_inset * 2,
            100 + view._canvas_inset * 2,
        )
        view.set_soft_wrap(True)
        view.set_match_index(MatchIndex((MatchRecord(2, 2),)))
        view.show()
        app.processEvents()
        view.viewport().repaint()
        app.processEvents()

        image = view.viewport().grab().toImage()
        base = QColor("#ffffff")
        tint = view.theme_tokens.current_line
        alpha = tint.alphaF()
        current_line_over_base = QColor(
            round(tint.red() * alpha + base.red() * (1 - alpha)),
            round(tint.green() * alpha + base.green() * (1 - alpha)),
            round(tint.blue() * alpha + base.blue() * (1 - alpha)),
        )
        first_row_x = view._gutter_width + view._metrics.horizontalAdvance("ab")
        second_row_x = view._gutter_width
        first = image.pixelColor(first_row_x, view._line_height - 2)
        second = image.pixelColor(second_row_x, view._line_height * 2 - 2)

        # Both wrapped rows belong to the same logical (cursor) line, so the
        # otherwise-unmarked first row now carries the BF-060 current-line
        # tint rather than the raw base color.
        assert first.name() == current_line_over_base.name()
        assert second.name() != base.name()
        assert second.name() != current_line_over_base.name()
        view.close()


def test_text_view_keys_dispatch_word_document_and_page_navigation(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "navigation.txt"
    path.write_text(
        "one два three\n" + "line\n" * 30,
        encoding="utf-8",
        newline="",
    )
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document, cursor=13, anchor=13)
        view = UNITITextView(state)
        view.resize(320, 120)
        view.show()
        view.setFocus()
        app.processEvents()

        QTest.keyClick(view, Qt.Key.Key_Left, Qt.KeyboardModifier.ControlModifier)
        assert state.cursor == 8
        QTest.keyClick(view, Qt.Key.Key_End, Qt.KeyboardModifier.ControlModifier)
        assert state.cursor == document.total_chars()
        QTest.keyClick(view, Qt.Key.Key_Home, Qt.KeyboardModifier.ControlModifier)
        assert state.cursor == 0
        QTest.keyClick(view, Qt.Key.Key_PageDown)
        assert document.line_for_char(state.cursor) > 0
        QTest.keyClick(
            view,
            Qt.Key.Key_End,
            Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier,
        )
        assert state.selection == (state.anchor, document.total_chars())
        view.close()


def test_text_view_zoom_changes_metrics_without_changing_document_text(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFontDatabase, QFontMetrics
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.font_policy import resolve_editor_font
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "zoom.txt"
    path.write_text("Western Привет", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        original_text = document.read(0, document.total_chars())
        original_height = view.fontMetrics().height()

        view.set_zoom_percent(130)

        assert view.zoom_percent == 130
        assert view.fontMetrics().height() > original_height
        assert document.read(0, document.total_chars()) == original_text
        assert view.font().family() == resolve_editor_font().resolved_family
        assert view.font().family().casefold() != "monospace"
        assert QFontDatabase.isFixedPitch(view.font().family())
        metrics = QFontMetrics(view.font())
        assert metrics.inFontUcs4(ord("A"))
        assert metrics.inFontUcs4(ord("Ж"))
        view.reset_zoom()
        assert view.zoom_percent == 100
        view.close()
        app.processEvents()


def test_text_view_zoom_is_clamped_to_supported_range(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "zoom-range.txt"
    path.write_text("text", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.set_zoom_percent(999)
        assert view.zoom_percent == 300
        view.set_zoom_percent(1)
        assert view.zoom_percent == 50
        view.close()
        app.processEvents()


def test_font_weight_steps_independently_of_zoom_and_clamps_at_the_edges(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "weight.txt"
    path.write_text("text", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        assert view.font_weight == 400
        assert view.font().weight() == 400

        view.set_zoom_percent(150)
        view.increase_font_weight()
        assert view.font_weight == 500
        # Changing weight must not undo the zoom, and vice versa — both are
        # rebuilt from the same base font on every change (BF-067).
        assert view.zoom_percent == 150
        assert view.font().weight() == 500

        view.set_zoom_percent(80)
        assert view.font_weight == 500
        assert view.font().weight() == 500

        for _ in range(10):
            view.increase_font_weight()
        assert view.font_weight == 900
        for _ in range(10):
            view.decrease_font_weight()
        assert view.font_weight == 100

        view.reset_font_weight()
        assert view.font_weight == 400
        assert view.zoom_percent == 80

        view.set_font_weight(560)
        assert view.font_weight == 600
        view.close()
        app.processEvents()


def test_font_weight_round_trips_through_export_and_restore_state(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "weight-state.txt"
    path.write_text("text", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        original = UNITITextView(EditorState(document), view_id="weight-view")
        original.set_font_weight(700)
        record = original.export_state("doc-weight")
        assert record.font_weight == 700

        restored = UNITITextView(EditorState(document), view_id="weight-view")
        restored.restore_state(record)
        assert restored.font_weight == 700
        assert restored.font().weight() == 700

        original.close()
        restored.close()
        app.processEvents()


def test_primary_modifier_wheel_changes_editor_zoom_instead_of_scrolling(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "wheel-zoom.txt"
    path.write_text("line\n" * 100, encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.resize(320, 120)
        view.show()
        app.processEvents()
        initial_scroll = view.verticalScrollBar().value()
        event = QWheelEvent(
            QPointF(10, 10),
            QPointF(10, 10),
            QPoint(),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )

        QApplication.sendEvent(view.viewport(), event)

        assert view.zoom_percent == 110
        assert view.verticalScrollBar().value() == initial_scroll
        view.close()


def test_multi_click_selects_word_visual_line_and_logical_line(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "multi-click.txt"
    first_line = "alpha bravo charlie delta echo foxtrot"
    path.write_text(
        first_line + "\nsecond line\n",
        encoding="utf-8",
        newline="",
    )
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(220, 120)
        view.set_soft_wrap(True)
        view.show()
        app.processEvents()
        x = view._gutter_width + view.fontMetrics().horizontalAdvance("alpha br")
        y = view._line_height // 2

        view._select_click_unit(x, y, 2)
        assert state.selected_text() == "bravo"

        word_right_edge = (
            view._gutter_width
            + view.fontMetrics().horizontalAdvance("alpha bravo")
            - 1
        )
        view._select_click_unit(word_right_edge, y, 2)
        assert state.selected_text() == "bravo"

        first_visual_row = view._wrapped_row_index().row(0)
        view._select_click_unit(x, y, 3)
        assert state.selection == (
            first_visual_row.column_start,
            first_visual_row.column_start + first_visual_row.length,
        )

        view._select_click_unit(x, y, 4)
        assert state.selection == (document.line_start(0), document.line_start(1))
        assert state.selected_text() == first_line + "\n"
        view.close()
        app.processEvents()


def test_native_click_sequence_promotes_word_line_and_line_break_selection(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "native-multi-click.txt"
    path.write_text("alpha bravo\nnext\n", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(320, 120)
        view.show()
        app.processEvents()
        point = QPointF(
            view._gutter_width + view.fontMetrics().horizontalAdvance("alpha br"),
            view._line_height // 2,
        )

        def mouse_event(event_type):
            return QMouseEvent(
                event_type,
                point,
                point,
                Qt.MouseButton.LeftButton,
                Qt.MouseButton.LeftButton,
                Qt.KeyboardModifier.NoModifier,
            )

        view.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress))
        view.mouseDoubleClickEvent(mouse_event(QEvent.Type.MouseButtonDblClick))
        assert state.selected_text() == "bravo"
        view.mousePressEvent(mouse_event(QEvent.Type.MouseButtonPress))
        assert state.selected_text() == "alpha bravo"
        view.mouseDoubleClickEvent(mouse_event(QEvent.Type.MouseButtonDblClick))
        assert state.selected_text() == "alpha bravo\n"
        view.close()
        app.processEvents()


def test_soft_wrap_progressively_indexes_visual_rows_without_changing_text(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "wrapped-giant-line.txt"
    path.write_bytes(b"x" * (2 * 1024 * 1024))
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.resize(240, 100)
        view.show()
        app.processEvents()

        view.set_soft_wrap(True)
        app.processEvents()

        assert view.soft_wrap is True
        assert view.horizontalScrollBar().maximum() == 0
        assert view.verticalScrollBar().maximum() > 0
        assert document.read(0, 8) == "xxxxxxxx"
        first_maximum = view.verticalScrollBar().maximum()
        view.verticalScrollBar().setValue(first_maximum)
        app.processEvents()
        assert view.verticalScrollBar().maximum() > first_maximum
        view.set_soft_wrap(False)
        assert view.soft_wrap is False
        view.close()


def test_view_state_round_trips_selection_scroll_wrap_row_and_zoom(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState, EditorStateSnapshot
    from uniti.app.session import DockReturnRecord
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "view-state.txt"
    path.write_text(
        ("0123456789" * 30 + "\n") * 80,
        encoding="utf-8",
        newline="",
    )
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        original = UNITITextView(EditorState(document), view_id="view-a")
        original.resize(220, 90)
        original.show()
        app.processEvents()
        original.state.restore_state(EditorStateSnapshot(35, 5, 12))
        original.set_zoom_percent(130)
        anchor = DockReturnRecord("window-a", "pane-left", 2)
        original.set_dock_return(anchor)
        original.horizontalScrollBar().setValue(48)
        original.verticalScrollBar().setValue(7)
        nonwrapped = original.export_state("doc-a")

        restored = UNITITextView(EditorState(document), view_id="view-a")
        restored.resize(220, 90)
        restored.show()
        app.processEvents()
        restored.restore_state(nonwrapped)

        assert restored.export_state("doc-a") == nonwrapped
        assert restored.dock_return == anchor

        original.set_soft_wrap(True)
        original._wrapped_row_index().ensure_row(20)
        original._refresh_scrollbars(advance_index=False)
        original.verticalScrollBar().setValue(9)
        wrapped = original.export_state("doc-a")
        restored.restore_state(wrapped)

        assert restored.soft_wrap is True
        assert restored.verticalScrollBar().value() == 9
        assert restored.export_state("doc-a").wrap_viewport_row == 9
        original.dispose()
        restored.dispose()
        original.close()
        restored.close()


def test_view_restore_clamps_state_invalidated_by_a_shorter_document(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.app.session import ViewRecord
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "short-view-state.txt"
    path.write_text("abc", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document), view_id="view-a")
        view.resize(220, 90)
        view.show()
        app.processEvents()
        record = ViewRecord(
            "view-a",
            "doc-a",
            100,
            90,
            8,
            50,
            40,
            30,
            False,
            120,
        )

        view.restore_state(record)

        assert view.state.cursor == 3
        assert view.state.anchor == 3
        assert view.verticalScrollBar().value() == 0
        assert view.horizontalScrollBar().value() == 0
        view.dispose()
        view.close()


def test_two_views_share_text_history_but_keep_independent_positions(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.regex.results import MatchIndex, MatchRecord
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "shared-view.txt"
    path.write_text(
        "alpha\nbeta\n" + ("line\n" * 40),
        encoding="utf-8",
        newline="",
    )
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        left = UNITITextView(EditorState(document), view_id="left")
        right = UNITITextView(EditorState(document), view_id="right")
        for view in (left, right):
            view.resize(240, 70)
            view.show()
        app.processEvents()
        left.state.move_to(2)
        right.state.move_to(8)
        right.verticalScrollBar().setValue(1)
        right.set_match_index(MatchIndex((MatchRecord(0, 5),)))
        sibling_refreshes: list[bool] = []
        right.stateChanged.connect(lambda: sibling_refreshes.append(True))

        left.state.insert_text("X")
        left._state_changed()
        app.processEvents()

        assert document.read(0, 12) == "alXpha\nbeta\n"
        assert right.state.cursor == 8
        assert right.verticalScrollBar().value() == 1
        assert len(right._match_index) == 0
        assert sibling_refreshes
        assert document.can_undo is True
        left.dispose()
        right.dispose()
        left.close()
        right.close()


def test_disposed_view_ignores_late_document_revision_callbacks(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.regex.results import MatchIndex, MatchRecord
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "disposed-view.txt"
    path.write_text("abc", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document), view_id="view-a")
        view.set_match_index(MatchIndex((MatchRecord(0, 1),)))
        view.dispose()

        document.insert(0, "X")
        app.processEvents()

        assert len(view._match_index) == 1
        view.close()


def test_view_focus_publishes_its_stable_identifier(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QEvent
    from PySide6.QtGui import QFocusEvent
    from PySide6.QtTest import QSignalSpy
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "focused-view.txt"
    path.write_text("abc", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document), view_id="stable-view")
        focused = QSignalSpy(view.viewFocused)

        view.focusInEvent(QFocusEvent(QEvent.Type.FocusIn))

        assert focused.count() == 1
        assert focused.at(0) == ["stable-view"]
        view.dispose()
        view.close()
        app.processEvents()


@pytest.mark.parametrize("zoom", [50, 100, 200, 300])
def test_gutter_ink_is_smaller_with_text_baselines_and_six_digit_hit_testing(
    tmp_path, monkeypatch, zoom,
):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFont, QFontMetrics, QPainter
    from PySide6.QtWidgets import QApplication
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    import uniti.ui.text_view as text_view

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "six-digit.txt"
    path.write_bytes(b"123456\n" * 100_020)
    painted = []

    class ObservedPainter(QPainter):
        def drawText(self, *args):
            if len(args) == 3 and isinstance(args[2], str) and args[2].strip().isdigit():
                painted.append((args, QFont(self.font())))
            return super().drawText(*args)

    monkeypatch.setattr(text_view, "QPainter", ObservedPainter)
    with Document.open(path, encoding="utf-8") as document:
        view = text_view.UNITITextView(EditorState(document))
        view.set_zoom_percent(zoom)
        view.resize(640, 140)
        document.line_count()
        view._refresh_scrollbars(advance_index=False)
        view.show()
        view.verticalScrollBar().setValue(99_999)
        app.processEvents()
        painted.clear()
        view.viewport().repaint()
        numbers = [(args, font) for args, font in painted if args[0] < view._gutter_width]
        assert numbers
        (x, baseline, label), font = numbers[0]
        assert label.strip() == "100000"
        assert font.pointSizeF() == pytest.approx(view.font().pointSizeF() * 0.8)
        assert baseline == view._row_ascent
        ink = QFontMetrics(font).tightBoundingRect(label.strip())
        ordinary_ink = QFontMetrics(view.font()).tightBoundingRect(label.strip())
        # At small sizes, font hinting can round both glyph heights to the
        # same pixel count; the six-digit ink must still be strictly narrower.
        assert 0 < ink.height() <= ordinary_ink.height()
        assert 0 < ink.width() < ordinary_ink.width()
        assert x >= 4
        assert x + QFontMetrics(font).horizontalAdvance(label) <= view._gutter_width - 4
        assert view._gutter_width >= 48
        assert view._gutter_width == max(48, QFontMetrics(font).horizontalAdvance("100021") + 12)
        assert [args[1] for args, _ in numbers[:2]] == [baseline, baseline + view._line_height]
        assert view.verticalScrollBar().singleStep() == 1
        assert view.horizontalScrollBar().singleStep() == view._cell_width
        view._select_click_unit(view._gutter_width + view._cell_width * 2, view._line_height // 2, 2)
        assert view.state.selected_text() == "123456"
        view.verticalScrollBar().setValue(100_000)
        assert view._char_for_point(view._gutter_width, view._line_height // 2) == document.line_start(100_000)
        view.dispose()
        view.close()
        app.processEvents()


@pytest.mark.parametrize("zoom", [50, 100, 200, 300])
def test_small_gutter_font_does_not_leak_into_wrapped_text_or_markers(tmp_path, monkeypatch, zoom):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QFont, QPainter
    from PySide6.QtWidgets import QApplication
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    import uniti.ui.text_view as text_view

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "gutter-wrap.txt"
    path.write_bytes(b"abcdef\nghijkl\n")
    numbers, content_fonts, marker_fonts = [], [], []

    class ObservedPainter(QPainter):
        def drawText(self, *args):
            if len(args) == 3 and isinstance(args[2], str) and args[2].strip().isdigit():
                numbers.append((args, QFont(self.font())))
            return super().drawText(*args)

    monkeypatch.setattr(text_view, "QPainter", ObservedPainter)
    with Document.open(path, encoding="utf-8") as document:
        view = text_view.UNITITextView(EditorState(document))
        view.set_zoom_percent(zoom)
        view.resize(
            view._gutter_width + view._cell_width * 2 + 10 + view._canvas_inset * 2,
            view._line_height * 9 + view._canvas_inset * 2,
        )
        view.set_soft_wrap(True)
        view.set_whitespace_mode("eol")
        original_text = view._paint_line_text
        original_marker = view._paint_whitespace_marker

        def observe_text(painter, *args, **kwargs):
            content_fonts.append(QFont(painter.font()))
            return original_text(painter, *args, **kwargs)

        def observe_marker(painter, *args, **kwargs):
            marker_fonts.append(QFont(painter.font()))
            return original_marker(painter, *args, **kwargs)

        monkeypatch.setattr(view, "_paint_line_text", observe_text)
        monkeypatch.setattr(view, "_paint_whitespace_marker", observe_marker)
        view.show()
        app.processEvents()
        numbers.clear()
        content_fonts.clear()
        marker_fonts.clear()
        view.viewport().repaint()
        assert [args[2].strip() for args, _ in numbers] == ["1", "2", "3"]
        assert all(font.pointSizeF() == pytest.approx(view.font().pointSizeF() * 0.8) for _, font in numbers)
        assert len(content_fonts) > len(numbers)
        assert content_fonts and marker_fonts
        assert all(font == view.font() for font in content_fonts + marker_fonts)
        assert numbers[1][0][1] - numbers[0][0][1] >= 3 * view._line_height
        view.dispose()
        view.close()
        app.processEvents()


def test_restored_deep_wrapped_row_has_six_digit_gutter_before_first_paint(
    tmp_path, monkeypatch,
):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace
    from PySide6.QtGui import QPainter
    from PySide6.QtWidgets import QApplication
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    import uniti.ui.text_view as text_view

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "deep-wrapped.txt"
    path.write_bytes(b"x\n" * 99_999 + b"abcdefghijklmnopqrstuvwxyz\n" * 20)
    numbers = []

    class ObservedPainter(QPainter):
        def drawText(self, *args):
            if len(args) == 3 and isinstance(args[2], str) and args[2].isdigit():
                numbers.append(args)
            return super().drawText(*args)

    monkeypatch.setattr(text_view, "QPainter", ObservedPainter)
    with Document.open(path, encoding="utf-8") as document:
        view = text_view.UNITITextView(EditorState(document))
        view.resize(360, 180)
        view.set_zoom_percent(300)
        view.set_soft_wrap(True)
        view.show()
        app.processEvents()
        initial_width = view._gutter_width
        initial_columns = view._wrap_columns()
        assert document.document_line_index.indexed_line_count < 100_000
        record = replace(view.export_state("deep"), wrap_viewport_row=99_999)

        view.restore_state(record)

        # Cold shaped lookup advances within its per-request work budget.
        # The first actual target paint still needs the final gutter and wrap width.
        for _ in range(500):
            index = view._prepare_wrapped_rows(99_999, view._visible_line_capacity())
            if index.known_count > 100_010:
                break
        assert view._gutter_width > initial_width
        assert view._gutter_width >= view._gutter_metrics.horizontalAdvance("100000") + 12
        assert view._wrap_columns() < initial_columns
        index = view._wrapped_row_index()
        assert index.columns == view._wrap_columns()
        assert index.known_count > 99_999
        row = index.row(99_999)
        assert row.line == 99_999
        assert row.length == view._wrap_columns()
        numbers.clear()
        view.viewport().repaint()
        assert numbers[0][2] == "100000"
        assert numbers[0][0] >= 4
        assert view._char_for_point(view._gutter_width, view._line_height // 2) == document.line_start(99_999)
        view.dispose()
        view.close()
        app.processEvents()


def test_direction_override_fixes_a_predominantly_rtl_line_starting_with_western_text(
    tmp_path: Path,
):
    """A predominantly-Arabic line that happens to *start* with Western
    text (e.g. a verse reference) is misjudged left-to-right by Auto's
    first-strong-character rule alone -- confirmed directly:
    `is_rtl_paragraph` returns False for this exact line. The "primary
    direction" override lets a user correct this per-view when Auto gets
    it wrong."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.bidi import is_rtl_paragraph
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "mixed-start.txt"
    text = "John 3:16 قال يسوع من آمن به"
    path.write_text(text, encoding="utf-8", newline="")
    assert is_rtl_paragraph(text) is False  # confirms the real Auto gap

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(600, 120)
        view.set_soft_wrap(False)
        view.show()
        app.processEvents()

        from PySide6.QtCore import Qt as _Qt

        assert view.text_direction_override == "auto"
        # Auto misjudges this line LTR, exactly matching `is_rtl_paragraph`
        # above -- the same rule the renderer itself uses.
        assert view._direction_for_window(text, 0) == _Qt.LayoutDirection.LeftToRight

        view.set_text_direction_override("rtl")
        assert view.text_direction_override == "rtl"
        assert view._direction_for_window(text, 0) == _Qt.LayoutDirection.RightToLeft

        # The override changes real hit-testing, not just the reported
        # direction: clicking at the same point now resolves differently.
        far_right = view._gutter_width + view._wrap_width() - 1
        y = view._line_height // 2
        rtl_offset = view._char_for_point(far_right, y)

        view.set_text_direction_override("auto")
        assert view.text_direction_override == "auto"
        assert view._direction_for_window(text, 0) == _Qt.LayoutDirection.LeftToRight
        auto_offset = view._char_for_point(far_right, y)
        assert rtl_offset != auto_offset

        view.close()
        app.processEvents()


def test_direction_override_rejects_unknown_values(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "direction-validation.txt"
    path.write_text("alpha", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        with pytest.raises(ValueError):
            view.set_text_direction_override("sideways")
        assert view.text_direction_override == "auto"
        view.close()
        app.processEvents()


def test_direction_override_round_trips_through_view_state(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "direction-persist.txt"
    path.write_text("alpha", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        source = UNITITextView(EditorState(document))
        source.set_text_direction_override("rtl")
        record = source.export_state("doc-1")
        assert record.extra["text_direction_override"] == "rtl"

        restored = UNITITextView(EditorState(document), view_id=record.view_id)
        restored.restore_state(record)
        assert restored.text_direction_override == "rtl"

        # The default (Auto) is never written -- an unmodified view's
        # saved record carries no extra key for it at all.
        source.set_text_direction_override("auto")
        assert "text_direction_override" not in source.export_state("doc-1").extra

        source.close()
        restored.close()
        app.processEvents()


@pytest.mark.parametrize("zoom", [50, 100, 200, 300])
def test_canvas_inset_scales_with_zoom_and_keeps_hit_testing_correct(
    tmp_path: Path, zoom: int
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "canvas-inset.txt"
    path.write_text("alpha bravo\nnext line\n", encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.set_zoom_percent(zoom)
        view.resize(320, 160)
        view.show()
        app.processEvents()

        inset = view._canvas_inset
        assert inset == max(1, round(view._cell_width * 0.25))
        assert inset >= 1

        outer = view.rect()
        inner = view.viewport().geometry()
        assert inner.left() == outer.left() + inset
        assert inner.top() == outer.top() + inset
        assert inner.width() == outer.width() - 2 * inset
        assert inner.height() == outer.height() - 2 * inset

        # Hit-testing uses viewport-local coordinates and is unaffected by
        # the frame inset: a click still resolves to the same word.
        x = view._gutter_width + view.fontMetrics().horizontalAdvance("alpha br")
        y = view._line_height // 2
        view._select_click_unit(x, y, 2)
        assert view.state.selected_text() == "bravo"

        # No content is clipped by the inset: every painted row still fits
        # inside the (smaller) viewport rect.
        painter_target = view.viewport().rect()
        assert painter_target.width() > 0 and painter_target.height() > 0
        view.viewport().repaint()

        view.close()
        app.processEvents()


def test_rtl_line_hit_testing_maps_visual_left_to_logical_end(tmp_path: Path):
    """BF-064: a pure-RTL logical line must render with logical position 0
    (the start of reading order) at the visual right edge, and later
    logical positions further left — the opposite of an LTR line."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "rtl.txt"
    arabic = "مرحبا بك"  # "مرحبا بك"
    path.write_text(arabic, encoding="utf-8", newline="")

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(600, 120)
        view.set_soft_wrap(False)
        view.show()
        app.processEvents()

        # The row is now right-anchored within the available text area
        # (see `ShapedWindow`'s `align_width_px`), so "near the right edge"
        # means near the right edge of that area, not an arbitrary point.
        far_right = view._gutter_width + view._wrap_width() - 1
        left_edge_offset = view._char_for_point(view._gutter_width + 1, view._line_height // 2)
        right_edge_offset = view._char_for_point(far_right, view._line_height // 2)

        # Clicking near the left edge must land near the *end* of the
        # line's reading order; clicking near the right edge must land
        # near its *start* — inverted from an LTR line.
        assert left_edge_offset > len(arabic) // 2
        assert right_edge_offset <= 1

        view.close()
        app.processEvents()


def test_ltr_line_hit_testing_is_unaffected_by_rtl_support(tmp_path: Path):
    """Guards against a direction-detection regression breaking the
    overwhelmingly common LTR case."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "ltr.txt"
    path.write_text("hello world", encoding="utf-8", newline="")

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(600, 120)
        view.set_soft_wrap(False)
        view.show()
        app.processEvents()

        left_edge_offset = view._char_for_point(view._gutter_width + 1, view._line_height // 2)
        right_edge_offset = view._char_for_point(view._gutter_width + 400, view._line_height // 2)

        assert left_edge_offset <= 1
        assert right_edge_offset >= len("hello world") - 1

        view.close()
        app.processEvents()


def test_line_direction_is_detected_once_and_reused_for_mid_line_windows(tmp_path: Path):
    """BF-064: a window starting mid-line (e.g. a wrapped continuation row)
    must reuse the paragraph's own detected direction rather than
    misjudging one from its own possibly-unrepresentative fragment."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "mixed.txt"
    # An RTL paragraph whose tail is a pure-Latin fragment: if direction
    # were (mis)detected fresh from just that tail, it would read LTR.
    arabic = "مرحبا "
    text = arabic + "hello world"
    path.write_text(text, encoding="utf-8", newline="")

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(600, 120)
        view.show()
        app.processEvents()

        line_start = document.line_start(0)
        whole_line_direction = view._direction_for_window(text, line_start)
        assert whole_line_direction == Qt.LayoutDirection.RightToLeft

        tail_start = line_start + len(arabic)
        tail_text = "hello world"
        reused_direction = view._direction_for_window(tail_text, tail_start)
        assert reused_direction == Qt.LayoutDirection.RightToLeft

        view.close()
        app.processEvents()


def test_line_direction_cache_is_cleared_on_edit(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "changing.txt"
    arabic = "مرحبا"
    path.write_text(arabic, encoding="utf-8", newline="")

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(600, 120)
        view.show()
        app.processEvents()

        assert view._direction_for_window(arabic, 0) == Qt.LayoutDirection.RightToLeft
        assert 0 in view._line_directions

        document.replace(0, len(arabic), "hello")
        app.processEvents()

        assert view._line_directions == {}
        assert view._direction_for_window("hello", 0) == Qt.LayoutDirection.LeftToRight

        view.close()
        app.processEvents()


def test_arrow_keys_move_visually_on_an_rtl_line(tmp_path: Path):
    """BF-064: real Right/Left arrow key presses on an RTL line must move
    the cursor toward the visual edge they're labeled for, not always
    logically forward/backward."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "arrow-rtl.txt"
    arabic = "مرحبا"  # 5 characters
    path.write_text(arabic, encoding="utf-8", newline="")

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(600, 120)
        view.show()
        view.setFocus()
        app.processEvents()

        state.move_to(3)

        QTest.keyClick(view, Qt.Key.Key_Right)
        assert state.cursor == 2

        QTest.keyClick(view, Qt.Key.Key_Left)
        assert state.cursor == 3

        view.close()
        app.processEvents()


def test_visual_right_moves_forward_inside_an_embedded_ltr_run(tmp_path: Path):
    """BF-064: fixes the embedding-level caret-affinity gap characterized
    at the `EditorState` level by
    `test_visual_movement_known_limitation_uses_paragraph_direction_not_local_run`
    (`tests/app/test_editor_state.py`) — that test's own paragraph-level
    heuristic gets this wrong (moves backward) because it has no layout
    access. Through the real view, a Right-arrow keypress with the cursor
    inside an embedded left-to-right run ("hello") within a right-to-left
    paragraph must move forward (matching the local run's own direction),
    using the cursor line's actual shaped pixel positions rather than
    just the paragraph's overall direction."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "arrow-embedded-run.txt"
    arabic_prefix = "مرحبا "
    text = arabic_prefix + "hello"
    path.write_text(text, encoding="utf-8", newline="")
    inside_hello = len(arabic_prefix) + 2

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document, cursor=inside_hello, anchor=inside_hello)
        view = UNITITextView(state)
        view.resize(600, 120)
        view.show()
        view.setFocus()
        app.processEvents()

        QTest.keyClick(view, Qt.Key.Key_Right)
        assert state.cursor == inside_hello + 1

        QTest.keyClick(view, Qt.Key.Key_Left)
        assert state.cursor == inside_hello

        view.close()
        app.processEvents()


def test_visual_movement_at_a_line_boundary_still_falls_back_to_paragraph_direction(
    tmp_path: Path,
):
    """The embedding-level fix (`_move_visual_char`) deliberately only
    resolves direction using an in-line neighbor; at a line's own
    start/end there is none, so it falls back to the existing
    paragraph-level heuristic — which already correctly crosses to the
    adjacent logical line. Locks in that this bounded fallback still
    works, not just the in-line case."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "arrow-line-boundary.txt"
    arabic = "مرحبا"
    text = arabic + "\nsecond"
    path.write_text(text, encoding="utf-8", newline="")

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document, cursor=0, anchor=0)
        view = UNITITextView(state)
        view.resize(600, 120)
        view.show()
        view.setFocus()
        app.processEvents()

        # Logical position 0 is the RTL line's own visual *right* edge, so
        # visual-right there has nowhere further right to go (correctly a
        # no-op — not exercised further here). Visual-*left* at the same
        # position has no in-line neighbor either, but the paragraph
        # fallback still resolves it (RTL: visual-left is logically
        # forward) and must move, not silently no-op.
        QTest.keyClick(view, Qt.Key.Key_Left)
        assert state.cursor == 1

        # From the RTL line's own end, visual-left (still logically
        # forward for RTL) must cross the line break into "second".
        state.move_to(len(arabic))
        QTest.keyClick(view, Qt.Key.Key_Left)
        assert state.cursor == len(arabic) + 1

        view.close()
        app.processEvents()


def test_arrow_keys_move_logically_on_an_ltr_line(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "arrow-ltr.txt"
    path.write_text("hello", encoding="utf-8", newline="")

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(600, 120)
        view.show()
        view.setFocus()
        app.processEvents()

        state.move_to(2)

        QTest.keyClick(view, Qt.Key.Key_Right)
        assert state.cursor == 3

        QTest.keyClick(view, Qt.Key.Key_Left)
        assert state.cursor == 2

        view.close()
        app.processEvents()


def test_span_rect_normalizes_reversed_x_coordinates():
    """BF-064: `_span_rect` must produce a correct-width, correctly-placed
    rect regardless of whether x1 < x2 (LTR ordering) or x1 > x2 (RTL
    ordering, since `x_for_cp` decreases with logical position there)."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.text_view import UNITITextView

    QApplication.instance() or QApplication([])

    ltr_rect = UNITITextView._span_rect(10.0, 40.0, y=5, height=20)
    assert (ltr_rect.left(), ltr_rect.top(), ltr_rect.width(), ltr_rect.height()) == (
        10,
        5,
        30,
        20,
    )

    rtl_rect = UNITITextView._span_rect(40.0, 10.0, y=5, height=20)
    assert (rtl_rect.left(), rtl_rect.top(), rtl_rect.width(), rtl_rect.height()) == (
        10,
        5,
        30,
        20,
    )


def test_selection_into_an_embedded_run_does_not_overcover_the_unselected_remainder(
    tmp_path: Path,
):
    """BF-064: a highlighted span that ends partway *into* an embedded
    direction run must not paint the unselected rest of that run.
    `_span_rect`'s single bounding box (`min(x1, x2)` to `max(x1, x2)`)
    is correct for a span entirely within one direction, but for a span
    that starts in the LTR paragraph and ends partway into an embedded
    RTL run, the bounding box between the two endpoints' x-coordinates
    sweeps across the *unselected* remainder of that run too — confirmed
    directly below by computing what the old single-box approach would
    have produced and showing it wrongly covers that remainder, while
    `_span_rects` (backed by `ShapedWindow.run_spans`, i.e. Qt's own
    glyph-run geometry) correctly excludes it."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    text = "AB مرحبا CD"
    path = tmp_path / "embedded-run-selection.txt"
    path.write_text(text, encoding="utf-8", newline="")

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        shaped = view._shape(text)

        # Select "B مر" (indices 1..5) — only the first two Arabic letters
        # of "مرحبا"; "حبا" (indices 5..8) must stay unhighlighted.
        a, b = 1, 5
        unselected_midpoint = sum(shaped.run_spans(5, 8)[0]) / 2

        old_x1, old_x2 = shaped.x_for_cp(a), shaped.x_for_cp(b)
        old_box = view._span_rect(old_x1, old_x2, 0, view._line_height)
        assert old_box.left() <= unselected_midpoint <= old_box.right(), (
            "fixture assumption failed: the old bounding box was expected "
            "to (incorrectly) cover the unselected remainder"
        )

        rects = view._span_rects(shaped, 0, a, b, 0, view._line_height)
        assert len(rects) >= 2
        assert not any(
            rect.left() <= unselected_midpoint <= rect.right() for rect in rects
        )
        view.close()
        app.processEvents()


def test_rtl_selection_paints_a_full_width_highlight_not_a_hairline(tmp_path: Path):
    """BF-064: before this fix, selecting an entire pure-RTL line painted a
    1-pixel-wide highlight at the wrong edge instead of covering the span —
    `x_for_cp` decreases with logical position on an RTL line, so the old
    unconditional `x2 - x1` width went negative and got clamped to 1."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "rtl-selection.txt"
    arabic = "مرحبا بك"  # "مرحبا بك"
    path.write_text(arabic, encoding="utf-8", newline="")

    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(400, 120)
        view.set_soft_wrap(False)
        view.show()
        app.processEvents()

        state.move_to(0)
        state.move_to(len(arabic), selecting=True)
        app.processEvents()

        pixmap = QPixmap(view.viewport().size())
        view.viewport().render(pixmap)
        image = pixmap.toImage()

        selection_color = view._theme_tokens.selection

        y = view._line_height // 2
        highlighted_x = [
            x
            for x in range(view.viewport().width())
            if image.pixelColor(x, y) == selection_color
        ]
        assert highlighted_x, "expected some highlighted pixels on the selection row"
        span = max(highlighted_x) - min(highlighted_x)
        # A hairline (the pre-fix bug) is 0-1px wide; a real selection over
        # a 7-character Arabic line at this font size spans many pixels.
        assert span > 10

        view.close()
        app.processEvents()


def test_whitespace_marker_glyph_draws_at_the_visual_left_regardless_of_x_order(
    tmp_path: Path,
):
    """BF-064: tab/EOL/overflow marker glyphs are drawn starting at
    `min(x1, x2)` — the span's actual visual left edge — rather than always
    `x1`, which is the character's *logical* start and sits at the visual
    *right* edge of its span on a right-to-left line."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QPainter, QPixmap
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView
    from uniti.ui.whitespace import WhitespaceKind

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "marker-order.txt"
    path.write_text("a\tb", encoding="utf-8")
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.resize(300, 80)
        view.show()
        app.processEvents()

        def ink_bounds(x1: float, x2: float) -> tuple[int, int]:
            pixmap = QPixmap(200, 40)
            pixmap.fill(view._theme_tokens.base)
            painter = QPainter(pixmap)
            view._paint_whitespace_marker(painter, WhitespaceKind.TAB, "TAB", x1, x2, 0.0)
            painter.end()
            image = pixmap.toImage()
            ink_x = [
                x
                for x in range(image.width())
                for y in range(image.height())
                if image.pixelColor(x, y) != view._theme_tokens.base
            ]
            return min(ink_x), max(ink_x)

        ltr_min, ltr_max = ink_bounds(20.0, 40.0)
        rtl_min, rtl_max = ink_bounds(40.0, 20.0)

        # The glyph must land in the same place whichever order the span's
        # two edges were passed in.
        assert (ltr_min, ltr_max) == (rtl_min, rtl_max)
        assert ltr_min >= 20

        view.close()
        app.processEvents()


def test_typing_into_an_rtl_line_advances_the_caret_visually(tmp_path: Path):
    """BF-064: found while finishing the RTL work — Qt anchors a QTextLine
    flush-*left* within its line width by default, regardless of paragraph
    direction (direction only reorders glyphs inside the box). For a
    right-to-left line growing at its logical end (ordinary typing, or IME
    composition), the box just widens rightward from that fixed left
    anchor, so the caret — which sits at the logical end — never visually
    moved. Reproduced directly: typing five Arabic characters left the
    caret frozen at the exact same pixel every time, in both wrapped and
    non-wrapped mode, before this test's fix (`ShapedWindow`'s
    `align_width_px` / right-alignment)."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    arabic = "مرحبا"
    app = QApplication.instance() or QApplication([])
    for soft_wrap in (True, False):
        path = tmp_path / f"typing-rtl-{soft_wrap}.txt"
        path.write_text("", encoding="utf-8")
        with Document.open(path, encoding="utf-8") as document:
            view = UNITITextView(EditorState(document))
            view.resize(400, 100)
            view.set_soft_wrap(soft_wrap)
            view.show()
            app.processEvents()

            positions = []
            for character in arabic:
                view.state.insert_text(character)
                app.processEvents()
                positions.append(view._cursor_rectangle().x())

            # Each new character must move the caret — no two consecutive
            # positions equal, which is what the freeze bug produced.
            assert len(set(positions)) == len(positions), (
                soft_wrap,
                positions,
            )
            # Arabic joining forms can *shrink* a previous letter's glyph
            # once a new letter is appended after it — e.g. "ب" loses its
            # isolated/final terminal tail and takes a narrower medial form
            # when "ا" joins after it (confirmed directly: the real bundled
            # Noto Naskh Arabic font shapes "مرحب" at 55.9px natural width
            # but "مرحبا" at only 49.3px). That is genuine contextual
            # reshaping from the real Arabic font now bundled (BF-066), not
            # a caret bug, so individual steps are not required to be
            # strictly monotonic — only that the caret is never frozen
            # (checked above) and ends up net further left than it started.
            assert positions[-1] < positions[0], (soft_wrap, positions)

            view.close()
            app.processEvents()


def test_caret_moves_leftward_across_an_rtl_horizontal_scroll_checkpoint(
    tmp_path: Path,
):
    """BF-064's documented remaining gap: a non-wrapped right-to-left line
    long enough to need more than one 8,192-code-point horizontal-scroll
    checkpoint window did not scroll/position correctly across that
    boundary. Reconfirmed directly before this fix: a 12,000-character
    Arabic line's caret at position 9,000 (past the first checkpoint)
    landed at x≈ 39,375, moving further *right* the deeper into the
    line, when it should move left off a right anchor (see the RTL/bidi
    plan's "Not yet done" note). Reproduced here with real cursor moves
    spanning both checkpoints; confirmed to fail against the pre-fix code
    before being accepted."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    app = QApplication.instance() or QApplication([])
    # 12,000 Arabic characters as one logical line -- long enough to need
    # a second 8,192-code-point horizontal-scroll checkpoint window.
    arabic_line = "مرحبا" * 2400
    assert len(arabic_line) == 12_000
    path = tmp_path / "long-rtl-line.txt"
    path.write_text(arabic_line, encoding="utf-8", newline="")

    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(400, 100)
        view.set_soft_wrap(False)
        view.show()
        app.processEvents()

        positions = []
        for target in (0, 100, 4000, 8000, 8200, 9000, 11_999):
            state.move_to(target)
            view._state_changed()
            app.processEvents()
            positions.append(view._cursor_rectangle().x())

        # Deeper reading-order positions must move the caret further left
        # (or hold at the same on-screen edge), never further right --
        # the pre-fix bug's exact signature.
        for earlier, later in zip(positions, positions[1:]):
            assert later <= earlier + 1.0, positions

        # The line only has 12,000 characters, all read by position
        # 11,999 -- the caret must actually have moved net leftward
        # across the whole traversal, not merely failed to regress.
        assert positions[-1] < positions[0], positions

        view.close()
        app.processEvents()


def test_hit_testing_stays_correct_past_an_rtl_horizontal_scroll_checkpoint(
    tmp_path: Path,
):
    """Companion to the caret-position regression above: clicking inside
    the *second* checkpoint window of a long RTL line must resolve to a
    character actually within that window, not silently misplace the hit
    onto the first checkpoint's (wrongly reused) coordinate space."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    app = QApplication.instance() or QApplication([])
    arabic_line = "مرحبا" * 2400
    path = tmp_path / "long-rtl-line-hit.txt"
    path.write_text(arabic_line, encoding="utf-8", newline="")

    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(400, 100)
        view.set_soft_wrap(False)
        view.show()
        app.processEvents()

        # Scroll deep enough that the visible window is entirely within
        # the second checkpoint (past code point 8,192).
        state.move_to(9_000)
        view._state_changed()
        app.processEvents()

        far_right = view._gutter_width + view._wrap_width() - 1
        offset = view._char_for_point(far_right, view._line_height // 2)

        # The resolved offset must land within the checkpoint actually
        # being displayed (near the deep scroll target), not snap back to
        # the very start of the line -- which is what reusing the first
        # checkpoint's coordinate space for the second one would produce.
        assert offset > 8_192, offset

        view.close()
        app.processEvents()


def test_typing_into_an_ltr_line_still_advances_the_caret_forward(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    app = QApplication.instance() or QApplication([])
    for soft_wrap in (True, False):
        path = tmp_path / f"typing-ltr-{soft_wrap}.txt"
        path.write_text("", encoding="utf-8")
        with Document.open(path, encoding="utf-8") as document:
            view = UNITITextView(EditorState(document))
            view.resize(400, 100)
            view.set_soft_wrap(soft_wrap)
            view.show()
            app.processEvents()

            positions = []
            for character in "hello":
                view.state.insert_text(character)
                app.processEvents()
                positions.append(view._cursor_rectangle().x())

            assert all(
                later > earlier for earlier, later in zip(positions, positions[1:])
            ), (soft_wrap, positions)

            view.close()
            app.processEvents()


def test_current_line_tint_paints_gutter_and_full_text_line_only_for_cursor_line(
    tmp_path: Path,
):
    """BF-060: a slight tint highlights the current line's gutter number and
    the full width of its text, but not other lines."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "current-line.txt"
    path.write_text("first\nsecond\nthird\n", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        state.move_to(document.line_start(1))
        view = UNITITextView(state)
        view.resize(400, 200)
        view.show()
        app.processEvents()
        view.viewport().repaint()
        app.processEvents()

        image = view.viewport().grab().toImage()
        base = view.theme_tokens.base

        cursor_line_gutter = image.pixelColor(4, view._line_height + 2)
        other_line_gutter = image.pixelColor(4, 2)
        cursor_line_far_right_text = image.pixelColor(
            view.viewport().width() - 4, view._line_height + 2
        )
        other_line_far_right_text = image.pixelColor(
            view.viewport().width() - 4, 2
        )

        assert cursor_line_gutter.name() != other_line_gutter.name()
        assert cursor_line_far_right_text.name() != other_line_far_right_text.name()
        assert other_line_far_right_text.name() == base.name()
        view.close()
