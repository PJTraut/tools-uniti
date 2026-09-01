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
        "MatchStore",
        "add_edit_listener",
        "resolve_captures",
        "include_captures=False",
        "streamReplaceCommitted",
        "stream_replace_to_file",
        "probe_replacements",
        "STREAM_REPLACE_THRESHOLD",
    ):
        assert required in source


def test_text_view_paints_compact_match_index_intersections_only():
    source = VIEW.read_text()
    assert "MatchIndex" in source
    assert "intersecting" in source
    assert "set_match_index" in source


def test_main_window_integrates_bottom_find_replace_panel_and_shortcuts():
    source = MAIN.read_text()
    assert "FindReplaceWindow" in source
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
        panel.regex_checkbox.setChecked(True)
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


def test_find_replace_accepts_shared_resource_manager_instead_of_owning_worker_pool():
    source = PANEL.read_text()
    assert "resource_manager" in source
    assert "resource_manager.workers" in source


def test_find_replace_is_modeless_and_keeps_document_enabled(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QDialog

    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "modeless.txt"
    path.write_text("editable", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(path)

    window.show_find()
    app.processEvents()

    find_window = window._find_replace
    assert isinstance(find_window, QDialog)
    assert find_window.isModal() is False
    assert find_window.isVisible() is True
    assert view.isEnabled() is True
    find_window.reject()
    assert find_window.isVisible() is False
    window.close_all_documents(force=True)
    window.close()


def test_literal_and_regex_modes_have_separate_semantics():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    panel.show()
    panel.find_input.set_text("a.c")
    literal = panel.compile_current()
    assert literal.fullmatch("a.c") is not None
    assert literal.fullmatch("A.C") is not None
    assert literal.fullmatch("abc") is None
    panel.case_sensitive_checkbox.setChecked(True)
    case_sensitive = panel.compile_current()
    assert case_sensitive.fullmatch("A.C") is None
    panel.whole_word_checkbox.setChecked(True)
    whole_word = panel.compile_current()
    assert whole_word.search("xa.cy") is None

    panel.regex_checkbox.setChecked(True)
    panel.find_input.set_text("(?i)a.c")
    raw_regex = panel.compile_current()
    assert raw_regex.pattern == "(?i)a.c"
    assert raw_regex.fullmatch("ABC") is not None
    assert panel.case_sensitive_checkbox.isVisible() is False
    assert panel.whole_word_checkbox.isVisible() is False
    panel.shutdown()
    panel.close()
    app.processEvents()


def test_find_replace_report_locations_and_zoom_are_independent(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "report.txt"
    path.write_text("ab ab", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        panel = FindReplacePanel(lambda: view)
        editor_zoom = view.zoom_percent
        panel.set_zoom_percent(140)
        assert panel.zoom_percent == 140
        assert view.zoom_percent == editor_zoom
        panel.set_report_location("Hidden")
        assert panel.report_frame.isVisible() is False
        panel.set_report_location("Bottom")
        assert panel.report_frame.isHidden() is False
        assert panel.report_splitter.orientation() == Qt.Orientation.Vertical
        panel.set_report_location("Right")
        assert panel.report_splitter.orientation() == Qt.Orientation.Horizontal
        panel.shutdown()
        panel.close()
        view.close()


def test_capture_report_excludes_group_zero_and_separates_matches(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "captures.txt"
    path.write_text("ab ab", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        panel = FindReplacePanel(lambda: view)
        panel.regex_checkbox.setChecked(True)
        panel.find_input.set_text("(a)(b)")
        panel.find_all()
        for _ in range(100):
            app.processEvents()
            if panel.result_count == 2 and panel.capture_list.count() >= 5:
                break
        rows = [panel.capture_list.item(i).text() for i in range(panel.capture_list.count())]
        assert rows[:2] == ["1 │ a", "2 │ b"]
        assert rows[2].startswith("─")
        assert rows[3:] == ["1 │ a", "2 │ b"]
        assert all(not row.startswith("0") for row in rows)
        panel.shutdown()
        view.close()
        panel.close()


def test_find_replace_geometry_zoom_and_report_location_persist(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    store = SettingsStore(tmp_path / "settings.json")
    store.save(
        Settings(
            find_replace_zoom_percent=140,
            find_replace_report_location="Right",
            find_replace_geometry=(20, 30, 640, 280),
        )
    )
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(settings_store=store)
    find_window = window._find_replace

    geometry = find_window.geometry()
    assert (geometry.x(), geometry.y(), geometry.width(), geometry.height()) == (
        20,
        30,
        640,
        280,
    )
    assert find_window.zoom_percent == 140
    assert find_window.report_location == "Right"

    find_window.show()
    app.processEvents()
    find_window.move(60, 70)
    find_window.resize(700, 330)
    app.processEvents()
    saved = store.load()
    actual = find_window.geometry()
    assert saved.find_replace_geometry == (
        actual.x(),
        actual.y(),
        actual.width(),
        actual.height(),
    )
    assert saved.find_replace_geometry[2:] == (700, 330)
    find_window.shutdown()
    find_window.close()
    window.close()
