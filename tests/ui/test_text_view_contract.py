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
