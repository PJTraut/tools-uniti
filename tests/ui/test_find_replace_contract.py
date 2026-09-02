import importlib.util
import os
import threading
import time
from pathlib import Path

import pytest


REGEX_INPUT = Path("src/uniti/ui/regex_input.py")
PANEL = Path("src/uniti/ui/find_replace.py")
VIEW = Path("src/uniti/ui/text_view.py")
MAIN = Path("src/uniti/ui/main_window.py")


def _wait_until(app, predicate, timeout: float = 5.0):
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.001)
    raise AssertionError("condition did not become true before timeout")


def _make_panel(tmp_path: Path, text: str):
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "analysis.txt"
    path.write_text(text, encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    document = Document.open(path, encoding="utf-8")
    view = UNITITextView(EditorState(document))
    panel = FindReplacePanel(lambda: view)
    return app, document, view, panel


def _close_panel(app, document, view, panel):
    panel.shutdown()
    panel.close()
    view.close()
    document.close()
    app.processEvents()


def _colors_at_token_starts(editor, analysis, *, group_number: int) -> set[str]:
    formats = editor.document().firstBlock().layout().formats()
    colors: set[str] = set()
    for token in analysis.tokens:
        if token.group_number != group_number or token.color_key is None:
            continue
        for item in formats:
            if item.start <= token.start < item.start + item.length:
                colors.add(item.format.foreground().color().name())
    return colors


def _contrast_ratio(first, second) -> float:
    def luminance(color):
        channels = []
        for value in color.getRgbF()[:3]:
            channels.append(
                value / 12.92
                if value <= 0.04045
                else ((value + 0.055) / 1.055) ** 2.4
            )
        return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]

    high, low = sorted((luminance(first), luminance(second)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def test_regex_inputs_render_supplied_immutable_analysis():
    assert REGEX_INPUT.exists()
    source = REGEX_INPUT.read_text()
    assert "QSyntaxHighlighter" in source
    assert "set_analysis" in source
    assert "tokenize_pattern" not in source
    assert "tokenize_replacement" not in source
    assert "RegexInput" in source
    assert "ReplacementInput" in source


def test_find_replace_panel_has_worker_cancellation_navigation_and_capture_ui():
    assert PANEL.exists()
    source = PANEL.read_text()
    for required in (
        "TaskSpec",
        "TaskKind",
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
        "collect_replacements",
        "ReplacementPlan",
        "apply_replacement_plan",
        ".snapshot()",
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
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text(r"\d+")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        for _ in range(100):
            app.processEvents()
            if panel.result_count == 2:
                break
        assert panel.result_count == 2
        panel.shutdown()
        view.close()
        panel.close()


def test_find_all_renders_every_visible_match_with_clear_contrast(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QPalette
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "highlight-all.txt"
    text = "one gap one gap one"
    path.write_text(text, encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        palette = view.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#ffffff"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#204060"))
        view.setPalette(palette)
        view.resize(700, 180)
        view.show()

        panel = FindReplacePanel(lambda: view)
        panel.find_input.set_text("one")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        for _ in range(200):
            app.processEvents()
            if not panel.busy:
                break
        view.viewport().repaint()
        app.processEvents()

        assert panel.result_count == 3
        image = view.viewport().grab().toImage()
        base = QColor("#ffffff")
        y = view._line_height - 2

        def contrast_from_base(column: int) -> int:
            x = (
                view._gutter_width
                + view._metrics.horizontalAdvance(text[:column])
                + view._metrics.horizontalAdvance("one") // 2
            )
            color = image.pixelColor(x, y)
            return sum(
                abs(actual - expected)
                for actual, expected in zip(color.getRgb()[:3], base.getRgb()[:3])
            )

        contrasts = [contrast_from_base(column) for column in (0, 8, 16)]
        assert all(contrast >= 200 for contrast in contrasts), contrasts

        panel.shutdown()
        panel.close()
        view.close()


def test_find_replace_uses_shared_resource_task_coordinator():
    source = PANEL.read_text()
    assert "resource_manager" in source
    assert "_resource_manager.tasks.submit" in source


def test_regex_analysis_is_debounced_serialized_and_stale_safe(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import uniti.ui.find_replace as find_replace

    calls: list[str] = []
    real = find_replace.analyze_pattern

    def observed(expression, generation, **options):
        calls.append(expression)
        if expression == "slow":
            time.sleep(0.05)
        return real(expression, generation, **options)

    monkeypatch.setattr(find_replace, "analyze_pattern", observed)
    app, document, view, panel = _make_panel(tmp_path, "abc")
    try:
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text("slow")
        panel.find_input.set_text("(fast)")
        assert panel.status_label.text() == "checking pattern…"
        assert not panel.find_all_button.isEnabled()
        _wait_until(app, lambda: panel.compile_current() is not None)
        assert panel._pattern_analysis.expression == "(fast)"
        assert panel._pattern_analysis.generation == panel._pattern_generation
        assert calls[-1] == "(fast)"
        assert panel.find_all_button.isEnabled()
    finally:
        _close_panel(app, document, view, panel)


def test_invalid_and_over_limit_patterns_expose_exact_nonmodal_states(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from uniti.regex.analysis import AnalysisState

    app, document, view, panel = _make_panel(tmp_path, "abc")
    try:
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text("(")
        _wait_until(
            app,
            lambda: panel._pattern_analysis.state is AnalysisState.INVALID,
        )
        assert "column" in panel.status_label.text()
        assert not panel.replace_all_button.isEnabled()
        panel.find_input.set_text("x" * 65_537)
        _wait_until(
            app,
            lambda: panel._pattern_analysis.state is AnalysisState.OVER_LIMIT,
        )
        assert "65,536" in panel.status_label.text()
        assert panel.find_input.text().endswith("x")
    finally:
        _close_panel(app, document, view, panel)


def test_pattern_and_replacement_formats_share_group_color(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "word-42")
    try:
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text(r"(?P<word>\w+)-(\d+)\1")
        panel.replace_input.set_text(r"\g<word>:\2")
        _wait_until(app, lambda: panel.compile_current() is not None)
        app.processEvents()
        pattern_colors = _colors_at_token_starts(
            panel.find_input,
            panel._pattern_analysis,
            group_number=1,
        )
        replacement_colors = _colors_at_token_starts(
            panel.replace_input,
            panel._replacement_analysis,
            group_number=1,
        )
        assert len(pattern_colors) == 1
        assert replacement_colors == pattern_colors
        assert len(panel.find_input.highlighter.group_palette) >= 8
    finally:
        _close_panel(app, document, view, panel)


def test_invalid_diagnostic_has_wave_underline_and_accessible_text(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QTextCharFormat

    from uniti.regex.analysis import AnalysisState

    app, document, view, panel = _make_panel(tmp_path, "abc")
    try:
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text("(")
        _wait_until(
            app,
            lambda: panel._pattern_analysis.state is AnalysisState.INVALID,
        )
        formats = panel.find_input.document().firstBlock().layout().formats()
        assert any(
            item.format.underlineStyle()
            == QTextCharFormat.UnderlineStyle.WaveUnderline
            for item in formats
        )
        assert panel.status_label.text() in panel.find_input.accessibleDescription()
    finally:
        _close_panel(app, document, view, panel)


def test_palette_change_rebuilds_group_formats_with_accessible_contrast(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QColor, QPalette

    app, document, view, panel = _make_panel(tmp_path, "a")
    try:
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text("(a)")
        _wait_until(app, lambda: panel.compile_current() is not None)
        before = panel.find_input.highlighter.group_palette[0]
        palette = panel.find_input.palette()
        palette.setColor(QPalette.ColorRole.Base, QColor("#101216"))
        palette.setColor(QPalette.ColorRole.Text, QColor("#f5f5f5"))
        panel.find_input.setPalette(palette)
        app.processEvents()

        after = panel.find_input.highlighter.group_palette[0]
        base = panel.find_input.palette().color(QPalette.ColorRole.Base)
        assert after.name() != before.name()
        assert all(
            _contrast_ratio(color, base) >= 4.5
            for color in panel.find_input.highlighter.group_palette
        )
    finally:
        _close_panel(app, document, view, panel)


def test_zero_width_navigation_wraps_by_result_index_without_selection(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "aa")
    try:
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text(r"(?=a)")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: panel.result_count == 2 and not panel.busy)
        assert (panel._current_index, view.state.cursor, view.state.selection) == (
            0,
            0,
            None,
        )
        panel.next_match()
        assert (panel._current_index, view.state.cursor, view.state.selection) == (
            1,
            1,
            None,
        )
        panel.next_match()
        assert panel._current_index == 0
        panel.previous_match()
        assert panel._current_index == 1
    finally:
        _close_panel(app, document, view, panel)


def test_single_zero_width_result_wraps_to_itself(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "aa")
    try:
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text(r"^")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: panel.result_count == 1 and not panel.busy)
        panel.next_match()
        panel.previous_match()

        assert panel._current_index == 0
        assert view.state.selection is None
        assert panel.status_label.text() == "match 1/1"
    finally:
        _close_panel(app, document, view, panel)


def test_single_zero_width_replace_inserts_once_and_invalidates_results(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "a")
    try:
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text(r"(?=a)")
        panel.replace_input.set_text("X")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: panel.result_count == 1 and not panel.busy)
        panel.replace_current()
        _wait_until(app, lambda: not panel.busy)

        assert document.read(0, document.total_chars()) == "Xa"
        assert panel.result_count == 0
        assert view.state.cursor == 1
        assert view.state.selection is None
        assert panel.status_label.text() == "1 replaced"
    finally:
        _close_panel(app, document, view, panel)


def test_replace_current_captures_widget_text_before_worker_starts():
    source = PANEL.read_text()
    method = source[source.index("    def replace_current(") : source.index("    def replace_all(")]

    capture = method.index("replacement_text = self._replacement_expression()")
    worker = method.index("        def work(")
    assert capture < worker
    assert "self._replacement_expression()" not in method[worker:]


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


def test_find_job_keeps_editor_enabled_and_edit_cancels_stale_snapshot(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui import find_replace
    from uniti.ui.main_window import UNITIMainWindow

    real_search = find_replace.search_document
    started = threading.Event()
    release = threading.Event()

    def delayed_search(*args, **kwargs):
        started.set()
        release.wait(5.0)
        yield from real_search(*args, **kwargs)

    monkeypatch.setattr(find_replace, "search_document", delayed_search)
    path = tmp_path / "editable-search.txt"
    path.write_text("one two one", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    try:
        view = window.open_path(path)
        panel = window._find_replace
        panel.find_input.set_text("one")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()

        _wait_until(app, started.is_set)
        assert view.isEnabled()
        view.document.insert(0, "edited ")
        view._state_changed()
        release.set()
        deadline = time.perf_counter() + 5.0
        while panel.busy and time.perf_counter() < deadline:
            app.processEvents()
            time.sleep(0.001)

        assert not panel.busy
        assert panel.result_count == 0
        assert panel.status_label.text() in {"cancelled", "text changed — search again"}
    finally:
        release.set()
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


def test_literal_and_regex_modes_have_separate_semantics():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    panel.show()
    assert panel.search_mode_combo.currentText() == "Literal"
    assert panel.case_sensitive_checkbox.isVisible() is True
    assert panel.whole_word_checkbox.isVisible() is True
    panel.find_input.set_text("a.c")
    _wait_until(app, lambda: panel.compile_current() is not None)
    literal = panel.compile_current()
    assert literal.fullmatch("a.c") is not None
    assert literal.fullmatch("A.C") is not None
    assert literal.fullmatch("abc") is None
    panel.case_sensitive_checkbox.setChecked(True)
    _wait_until(app, lambda: panel.compile_current() is not None)
    case_sensitive = panel.compile_current()
    assert case_sensitive.fullmatch("A.C") is None
    panel.whole_word_checkbox.setChecked(True)
    _wait_until(app, lambda: panel.compile_current() is not None)
    whole_word = panel.compile_current()
    assert whole_word.search("xa.cy") is None

    panel.search_mode_combo.setCurrentText("Regex")
    panel.find_input.set_text("(?i)a.c")
    _wait_until(app, lambda: panel.compile_current() is not None)
    raw_regex = panel.compile_current()
    assert raw_regex.pattern == "(?i)a.c"
    assert raw_regex.fullmatch("ABC") is not None
    assert panel.case_sensitive_checkbox.isVisible() is False
    assert panel.whole_word_checkbox.isVisible() is False
    panel.shutdown()
    panel.close()
    app.processEvents()


def test_find_replace_window_and_capture_pane_are_resizable_and_collapsible():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    panel.show()
    panel.set_report_location("Bottom")
    panel.resize(860, 520)
    panel.report_splitter.setSizes((220, 260))
    app.processEvents()

    assert panel.isSizeGripEnabled() is True
    assert (panel.width(), panel.height()) == (860, 520)
    assert panel.capture_list.maximumHeight() > 1_000_000
    assert panel.report_splitter.sizes()[1] > 82

    panel.report_splitter.setSizes((480, 0))
    app.processEvents()
    assert panel.report_splitter.sizes()[1] == 0
    panel.shutdown()
    panel.close()


def test_find_replace_inputs_split_height_above_bottom_control_stack():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    panel.set_report_location("Hidden")
    panel.resize(720, 600)
    panel.show()
    app.processEvents()

    controls = panel.report_splitter.widget(0)
    assert panel.find_input.height() > 100
    assert abs(panel.find_input.height() - panel.replace_input.height()) <= 2
    assert panel.batch_actions_widget.height() <= (
        panel.batch_actions_widget.sizeHint().height() + 2
    )
    assert panel.match_actions_widget.height() <= (
        panel.match_actions_widget.sizeHint().height() + 2
    )
    cancel_bottom = panel.cancel_button.mapTo(
        controls,
        panel.cancel_button.rect().bottomLeft(),
    ).y()
    assert cancel_bottom >= controls.height() - 6

    panel.shutdown()
    panel.close()


def test_find_replace_actions_are_grouped_by_operation_scope():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)

    def button_labels(widget):
        layout = widget.layout()
        return [
            layout.itemAt(index).widget().text()
            for index in range(layout.count())
            if layout.itemAt(index).widget() is not None
        ]

    assert button_labels(panel.batch_actions_widget) == [
        "Find All",
        "Replace All",
    ]
    assert button_labels(panel.match_actions_widget) == [
        "Previous",
        "Next",
        "Replace",
    ]
    panel.shutdown()
    panel.close()


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
        original_font_size = panel.find_input.font().pointSizeF()
        original_minimum_height = panel.find_input.minimumHeight()
        panel.set_zoom_percent(140)
        assert panel.zoom_percent == 140
        assert panel.find_input.font().pointSizeF() > original_font_size
        assert panel.find_input.minimumHeight() > original_minimum_height
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


def test_primary_modifier_wheel_zooms_focused_find_replace_only(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "find-wheel-zoom.txt"
    path.write_text("text", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        panel = FindReplacePanel(lambda: view)
        panel.show()
        panel.find_input.setFocus()
        app.processEvents()
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

        QApplication.sendEvent(panel.find_input.viewport(), event)

        assert panel.zoom_percent == 110
        assert view.zoom_percent == 100
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
        panel.search_mode_combo.setCurrentText("Regex")
        panel.find_input.set_text("(a)(b)")
        _wait_until(app, lambda: panel.compile_current() is not None)
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
