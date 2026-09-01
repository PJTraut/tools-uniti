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
