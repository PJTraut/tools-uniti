import ast
import importlib.util
import os
from pathlib import Path

import pytest


SOURCE = Path("src/uniti/ui/text_view.py")


def test_text_view_is_custom_qabstractscrollarea_without_qt_document_store():
    assert SOURCE.exists()
    source = SOURCE.read_text()
    assert "QPlainTextEdit" not in source
    assert "QTextDocument" not in source
    tree = ast.parse(source)
    classes = [node for node in tree.body if isinstance(node, ast.ClassDef)]
    target = next(node for node in classes if node.name == "UNITITextView")
    bases = [ast.unparse(base) for base in target.bases]
    assert "QAbstractScrollArea" in bases


def test_core_and_resources_remain_qt_free():
    for root in (Path("src/uniti/core"), Path("src/uniti/resources")):
        for path in root.glob("*.py"):
            source = path.read_text()
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
    path.write_text("one\ntwo\n", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        view = UNITITextView(state)
        view.resize(640, 480)
        view.show()
        app.processEvents()
        assert view.state is state
        view.close()


def test_text_view_pages_horizontally_by_character_window():
    source = SOURCE.read_text()
    assert "def _horizontal_window" in source
    assert "column_start=column_start" in source
    assert "line_window_start = line_start + column_start" in source
    assert "return line_start + column_start + low" in source


def test_text_view_exposes_clipboard_and_ime_contracts_without_qt_document_storage():
    source = SOURCE.read_text()
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
    source = SOURCE.read_text()
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
def test_whitespace_modes_paint_only_their_marker_categories(
    tmp_path: Path,
    monkeypatch,
    mode: str,
    expected: tuple[str, ...],
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / f"markers-{mode}.txt"
    path.write_bytes("a b\tc\u00a0\u200b\r\n".encode("utf-8"))
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        painted: list[str] = []

        def observe(_painter, _kind, label, _x1, _x2, _y):
            painted.append(label)

        monkeypatch.setattr(view, "_paint_whitespace_marker", observe)
        view.set_whitespace_mode(mode)
        view.resize(640, 100)
        view.show()
        app.processEvents()
        painted.clear()
        view.viewport().repaint()
        app.processEvents()

        assert tuple(painted) == expected
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

        def observe(_painter, _kind, label, _x1, _x2, y):
            painted.append((label, y))

        monkeypatch.setattr(view, "_paint_whitespace_marker", observe)
        view.resize(view._gutter_width + view._cell_width * 2 + 10, 120)
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

        def observe(_painter, _kind, label, _x1, _x2, _y):
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

        assert QColor(highlighted_text).name() in selected_pixels
        view.close()
        view.deleteLater()
        app.processEvents()


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
        view.resize(view._gutter_width + view._cell_width * 2 + 10, 100)
        view.set_soft_wrap(True)
        view.set_match_index(MatchIndex((MatchRecord(2, 2),)))
        view.show()
        app.processEvents()
        view.viewport().repaint()
        app.processEvents()

        image = view.viewport().grab().toImage()
        base = QColor("#ffffff")
        first_row_x = view._gutter_width + view._metrics.horizontalAdvance("ab")
        second_row_x = view._gutter_width
        first = image.pixelColor(first_row_x, view._line_height - 2)
        second = image.pixelColor(second_row_x, view._line_height * 2 - 2)

        assert first.name() == base.name()
        assert second.name() != base.name()
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
    path.write_text("one два three\n" + "line\n" * 30, encoding="utf-8")
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
    from PySide6.QtGui import QFontDatabase, QRawFont
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
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
        assert view.font().family().casefold() != "monospace"
        assert QFontDatabase.isFixedPitch(view.font().family())
        raw_font = QRawFont.fromFont(view.font())
        assert raw_font.supportsCharacter(ord("A"))
        assert raw_font.supportsCharacter(ord("Ж"))
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
    path.write_text("line\n" * 100, encoding="utf-8")
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
    path.write_text(first_line + "\nsecond line\n", encoding="utf-8")
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
    path.write_text("alpha bravo\nnext\n", encoding="utf-8")
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
    path.write_text(("0123456789" * 30 + "\n") * 80, encoding="utf-8")
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
    path.write_text("alpha\nbeta\n" + ("line\n" * 40), encoding="utf-8")
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
