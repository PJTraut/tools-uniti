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
