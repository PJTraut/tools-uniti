import importlib.util
import os
from pathlib import Path

import pytest


REGEX_INPUT = Path("src/uniti/ui/regex_input.py")
PANEL = Path("src/uniti/ui/find_replace.py")
VIEW = Path("src/uniti/ui/text_view.py")
MAIN = Path("src/uniti/ui/main_window.py")


def test_regex_inputs_use_syntax_highlighting_and_lexers():
    assert REGEX_INPUT.exists()
    source = REGEX_INPUT.read_text()
    assert "QSyntaxHighlighter" in source
    assert "tokenize_pattern" in source
    assert "tokenize_replacement" in source
    assert "RegexInput" in source
    assert "ReplacementInput" in source


def test_find_replace_panel_has_worker_cancellation_navigation_and_capture_ui():
    assert PANEL.exists()
    source = PANEL.read_text()
    for required in (
        "PriorityWorkerPool",
        "CancellationToken",
        "Find All",
        "Previous",
        "Next",
        "Replace All",
        "Cancel",
        "capture",
        "MatchIndex",
    ):
        assert required in source


def test_text_view_paints_compact_match_index_intersections_only():
    source = VIEW.read_text()
    assert "MatchIndex" in source
    assert "intersecting" in source
    assert "set_match_index" in source


def test_main_window_integrates_bottom_find_replace_panel_and_shortcuts():
    source = MAIN.read_text()
    assert "FindReplacePanel" in source
    assert "QKeySequence.StandardKey.Find" in source
    assert "show_find" in source
    assert "show_replace" in source


def test_find_replace_offscreen_smoke_when_pyside6_available(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "find.txt"
    path.write_text("one 123 two 456", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        panel = FindReplacePanel(lambda: view)
        panel.find_input.set_text(r"\d+")
        panel.find_all()
        for _ in range(100):
            app.processEvents()
            if panel.result_count == 2:
                break
        assert panel.result_count == 2
        panel.shutdown()
        view.close()
        panel.close()
