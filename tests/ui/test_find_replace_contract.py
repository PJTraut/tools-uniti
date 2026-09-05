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
SHORTCUT_POLICY = Path("src/uniti/ui/shortcut_policy.py")


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
    from PySide6.QtCore import QCoreApplication, QEvent

    panel.shutdown()
    if panel._owns_resources:
        panel._resource_manager.workers.shutdown(wait=True, cancel_pending=True)
    panel.close()
    view.close()
    panel.deleteLater()
    view.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    document.close()
    app.processEvents()


def _run_regex_search(app, panel, pattern: str, *, expected: int):
    panel.regex_checkbox.setChecked(True)
    panel.find_input.set_text(pattern)
    _wait_until(app, lambda: panel.compile_current() is not None)
    panel.find_all()
    _wait_until(app, lambda: panel.result_count == expected and not panel.busy)


class _ObservedSnapshot:
    def __init__(self, inner) -> None:
        self._inner = inner
        self.closed = False

    def read(self, start: int, end: int) -> str:
        return self._inner.read(start, end)

    def total_chars(self) -> int:
        return self._inner.total_chars()

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


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
        "resolve_capture_report",
        "CaptureReportModel",
        "include_captures=False",
        "collect_replacements",
        "ReplacementPlan",
        "apply_replacement_plan",
        ".snapshot()",
    ):
        assert required in source
    assert "QListWidget" not in source
    assert "resolve_captures" not in source


def test_capture_report_model_formats_rows_and_accessible_text():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt

    from uniti.regex.captures import (
        CaptureGroupRow,
        CaptureMatchReport,
        CapturePreview,
        CaptureReport,
        CaptureReportRequest,
    )
    from uniti.regex.results import MatchRecord
    from uniti.ui.capture_report import CaptureReportModel

    request = CaptureReportRequest(
        pattern_generation=7,
        pattern_text="pattern",
        document_key="doc",
        revision=3,
        store_id="store",
        requested_index=0,
        match_count=2,
        matches=((0, MatchRecord(0, 3)), (1, MatchRecord(4, 7))),
    )
    report = CaptureReport(
        request=request,
        matches=(
            CaptureMatchReport(
                index=0,
                total=2,
                groups=(
                    CaptureGroupRow(
                        1,
                        "letter",
                        "value",
                        3,
                        (
                            CapturePreview(0, 1, "a", False),
                            CapturePreview(1, 2, "a", False),
                            CapturePreview(2, 3, "a", False),
                        ),
                    ),
                    CaptureGroupRow(
                        2,
                        "empty",
                        "empty",
                        1,
                        (CapturePreview(3, 3, "", True),),
                    ),
                    CaptureGroupRow(3, "missing", "not_matched", 0, ()),
                    CaptureGroupRow(
                        4,
                        "mixed",
                        "value",
                        2,
                        (
                            CapturePreview(0, 1, "a", False),
                            CapturePreview(1, 1, "", True),
                        ),
                    ),
                ),
            ),
            CaptureMatchReport(
                index=1,
                total=2,
                groups=(),
                unavailable_reason="capture details unavailable",
            ),
        ),
        payload_bytes=1024,
    )
    model = CaptureReportModel()

    model.set_loading()
    assert model.rows() == ("loading captures…",)
    assert model.current_index is None
    model.set_report(report)

    assert model.rows() == (
        "Match 1 of 2",
        "1 letter │ a | a | a (3 occurrences)",
        "2 empty │ empty at 3",
        "3 missing │ not matched",
        "4 mixed │ a | empty at 1 (2 occurrences)",
        "─────────────────",
        "Match 2 of 2",
        "capture details unavailable",
    )
    assert model.current_index == 0
    index = model.index(1, 0)
    assert model.data(index, Qt.ItemDataRole.DisplayRole) == model.rows()[1]
    assert model.data(index, Qt.ItemDataRole.AccessibleTextRole) == model.rows()[1]
    model.clear()
    assert model.rows() == ()
    assert model.current_index is None


def test_text_view_paints_compact_match_index_intersections_only():
    source = VIEW.read_text()
    assert "MatchIndex" in source
    assert "intersecting" in source
    assert "set_match_index" in source


def test_main_window_integrates_bottom_find_replace_panel_and_shortcuts():
    source = MAIN.read_text()
    shortcut_source = SHORTCUT_POLICY.read_text()
    assert "FindReplaceWindow" in source
    assert "build_shortcut_policy" in source
    assert "standard.Find" in shortcut_source
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
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: panel.result_count == 2)
        assert panel.result_count == 2
        panel.shutdown()
        view.close()
        panel.close()


def test_find_replace_state_round_trip_preserves_complete_panel_state(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QTextCursor
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.resources import ResourceManager, TaskKind
    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.text_view import UNITITextView

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "round-trip.txt"
    path.write_text("alpha alpha", encoding="utf-8")
    document = Document.open(path)
    view = UNITITextView(EditorState(document))
    resources = ResourceManager(max_workers=2)
    seen_kinds: list[TaskKind] = []
    def observe_tasks() -> None:
        seen_kinds.extend(
            task.spec.kind for task in resources.tasks.snapshot().tasks
        )

    resources.tasks.add_listener(observe_tasks)
    panel = FindReplacePanel(lambda: view, resource_manager=resources)
    restored = FindReplacePanel(lambda: view, resource_manager=resources)
    try:
        panel.show()
        panel.setGeometry(23, 31, 760, 410)
        panel.find_input.setFocus()
        QTest.keyClicks(panel.find_input, "alpha+")
        assert panel.find_input.undo_input()
        find_cursor = panel.find_input.textCursor()
        find_cursor.setPosition(1)
        find_cursor.setPosition(4, QTextCursor.MoveMode.KeepAnchor)
        panel.find_input.setTextCursor(find_cursor)
        panel.replace_input.setFocus()
        QTest.keyClicks(panel.replace_input, r"beta\\1")
        assert panel.replace_input.undo_input()
        panel.regex_checkbox.setChecked(True)
        panel.case_sensitive_checkbox.setChecked(True)
        panel.whole_word_checkbox.setChecked(True)
        panel.set_zoom_percent(140)
        panel.set_report_location("Hidden")
        app.processEvents()
        expected = panel.export_state("view-target")
        revision = document.revision

        restored.restore_state(expected)
        assert restored._analysis_timer.isActive()
        _wait_until(app, lambda: restored.compile_current() is not None)

        assert restored.export_state("view-target") == expected
        assert restored.result_count == 0
        assert document.revision == revision
        assert restored._analysis_timer.interval() == 150
        assert TaskKind.REGEX_ANALYSIS in seen_kinds
        assert TaskKind.SEARCH not in seen_kinds
        assert TaskKind.REPLACE not in seen_kinds
    finally:
        resources.tasks.remove_listener(observe_tasks)
        for item in (panel, restored):
            item.shutdown()
            item.close()
        resources.shutdown()
        view.close()
        document.close()
        app.processEvents()


def test_find_replace_is_bottom_only_dock_widget_and_attach_detach_preserves_state():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QDockWidget, QMainWindow

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    host = QMainWindow()
    panel = FindReplacePanel(lambda: None)
    placements: list[str] = []
    panel.placementChanged.connect(placements.append)
    try:
        assert isinstance(panel, QDockWidget)
        assert panel.allowedAreas() == Qt.DockWidgetArea.BottomDockWidgetArea
        assert panel.widget() is not None
        assert panel.widget().isAncestorOf(panel.find_input)
        assert panel.widget().isAncestorOf(panel.replace_input)
        assert panel.placement == "detached"

        panel.find_input.set_text("needle")
        panel.replace_input.set_text("replacement")
        panel.regex_checkbox.setChecked(True)
        panel.set_zoom_percent(130)
        panel.set_report_location("Hidden")
        expected_find = panel.find_input.export_history()
        expected_replace = panel.replace_input.export_history()

        panel.attach_to(host)
        app.processEvents()

        assert panel.placement == "attached"
        assert panel.isFloating() is False
        assert host.dockWidgetArea(panel) == Qt.DockWidgetArea.BottomDockWidgetArea

        panel.detach()
        app.processEvents()

        assert panel.placement == "detached"
        assert panel.isFloating() is True
        assert panel.find_input.export_history() == expected_find
        assert panel.replace_input.export_history() == expected_replace
        assert panel.regex_checkbox.isChecked() is True
        assert panel.zoom_percent == 130
        assert panel.report_location == "Hidden"
        assert placements == ["attached", "detached"]
    finally:
        panel.shutdown()
        panel.close()
        host.close()
        app.processEvents()


def test_find_replace_persists_placement_and_only_tracks_detached_geometry():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace

    from PySide6.QtWidgets import QApplication, QMainWindow

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    host = QMainWindow()
    panel = FindReplacePanel(lambda: None)
    restored = FindReplacePanel(lambda: None)
    geometry_events: list[tuple[int, int, int, int]] = []
    panel.geometryChanged.connect(geometry_events.append)
    try:
        panel.setGeometry(23, 31, 760, 410)
        panel.show()
        app.processEvents()
        detached = panel.export_state("view-target")
        assert detached.placement == "detached"
        assert detached.geometry == (23, 31, 760, 410)
        assert geometry_events

        panel.attach_to(host)
        app.processEvents()
        attached_event_count = len(geometry_events)
        panel.resize(900, 220)
        app.processEvents()
        attached = panel.export_state("view-target")

        assert attached.placement == "attached"
        assert attached.geometry == detached.geometry
        assert len(geometry_events) == attached_event_count

        restored.restore_state(replace(attached, visible=False))
        assert restored.placement == "attached"
        assert restored.export_state("view-target").placement == "attached"
        assert restored.export_state("view-target").geometry == detached.geometry
    finally:
        for item in (panel, restored):
            item.shutdown()
            item.close()
        host.close()
        app.processEvents()


def test_find_replace_export_prunes_oldest_field_history_with_notice():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.session import (
        MAX_FIND_REPLACE_DECODED_BYTES,
        InputHistoryRecord,
        InputStateRecord,
        estimate_input_history_bytes,
    )
    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    current = InputStateRecord("needle", 6, 6)
    undo = tuple(
        InputStateRecord(str(index) + ("x" * 99_999), 0, 0)
        for index in range(45)
    )
    history = InputHistoryRecord(
        current,
        undo,
        (),
        estimate_input_history_bytes(current, undo, ()),
    )
    try:
        panel.find_input.restore_history(history)

        exported = panel.export_state(None)

        assert exported.find.current == current
        assert len(exported.find.undo) < len(undo)
        assert (
            exported.find.decoded_bytes + exported.replace.decoded_bytes
            <= MAX_FIND_REPLACE_DECODED_BYTES
        )
        assert any(
            notice.reason == "field_history_byte_limit"
            and notice.dropped_count > 0
            and notice.dropped_bytes > 0
            for notice in exported.find.notices
        )
    finally:
        panel.shutdown()
        panel.close()
        app.processEvents()


def test_find_all_renders_every_visible_match_with_clear_contrast(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace

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
        match = QColor("#204060")
        match.setAlpha(120)
        view.set_theme_tokens(
            replace(
                view.theme_tokens,
                base=QColor("#ffffff"),
                match=match,
            )
        )
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
        panel.regex_checkbox.setChecked(True)
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
        panel.regex_checkbox.setChecked(True)
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
        panel.regex_checkbox.setChecked(True)
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
        panel.regex_checkbox.setChecked(True)
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
        panel.regex_checkbox.setChecked(True)
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


def test_navigation_buttons_are_ready_before_find_all(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "one two one")
    try:
        panel.find_input.set_text("one")
        _wait_until(app, lambda: panel.compile_current() is not None)

        assert panel.result_count == 0
        assert panel.previous_button.isEnabled()
        assert panel.next_button.isEnabled()
    finally:
        _close_panel(app, document, view, panel)


def test_target_change_clears_document_results_but_retains_panel_state(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    app, document, view, panel = _make_panel(tmp_path, "one two one")
    second_path = tmp_path / "second.txt"
    second_path.write_text("second", encoding="utf-8")
    second_document = Document.open(second_path)
    second_view = UNITITextView(EditorState(second_document))
    try:
        panel.find_input.set_text("one")
        panel.replace_input.set_text("replacement")
        panel.case_sensitive_checkbox.setChecked(True)
        panel.set_zoom_percent(130)
        panel.set_report_location("Hidden")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 2)
        before = panel.export_state("view-one")

        panel.set_view_provider(lambda: second_view)
        assert panel.result_count == 2

        panel.target_changed()

        assert panel.result_count == 0
        assert panel.export_state("view-two") == replace(
            before,
            last_target_view_id="view-two",
        )
    finally:
        second_view.close()
        second_document.close()
        _close_panel(app, document, view, panel)


@pytest.mark.parametrize(
    ("method_name", "expected_selection"),
    (
        ("next_match", (18, 21)),
        ("previous_match", (8, 11)),
    ),
)
def test_navigation_before_find_all_starts_from_cursor(
    tmp_path: Path,
    method_name: str,
    expected_selection: tuple[int, int],
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(
        tmp_path,
        "one two one three one",
    )
    try:
        view.state.move_to(12)
        view._state_changed()
        panel.find_input.set_text("one")
        _wait_until(app, lambda: panel.compile_current() is not None)

        getattr(panel, method_name)()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 3)

        assert view.state.selection == expected_selection
    finally:
        _close_panel(app, document, view, panel)


def test_navigation_uses_moved_cursor_when_results_are_current(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "one x one x one")
    try:
        panel.find_input.set_text("one")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 3)
        assert view.state.selection == (0, 3)

        view.state.move_to(10)
        view._state_changed()
        panel.next_match()

        assert view.state.selection == (12, 15)
        assert panel._current_index == 2
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
        panel.regex_checkbox.setChecked(True)
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
        panel.regex_checkbox.setChecked(True)
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
        panel.regex_checkbox.setChecked(True)
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
    from PySide6.QtWidgets import QApplication, QDockWidget

    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "modeless.txt"
    path.write_text("editable", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(path)

    window.show_find()
    app.processEvents()

    find_window = window._find_replace
    assert isinstance(find_window, QDockWidget)
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
    assert panel.regex_checkbox.isChecked() is False
    assert panel.case_sensitive_checkbox.isVisible() is True
    assert panel.whole_word_checkbox.isVisible() is True
    assert panel.case_sensitive_checkbox.isEnabled() is True
    assert panel.whole_word_checkbox.isEnabled() is True
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

    panel.regex_checkbox.setChecked(True)
    panel.find_input.set_text("(?i)a.c")
    _wait_until(app, lambda: panel.compile_current() is not None)
    raw_regex = panel.compile_current()
    assert raw_regex.pattern == "(?i)a.c"
    assert raw_regex.fullmatch("ABC") is not None
    assert panel.case_sensitive_checkbox.isVisible() is True
    assert panel.whole_word_checkbox.isVisible() is True
    assert panel.case_sensitive_checkbox.isEnabled() is False
    assert panel.whole_word_checkbox.isEnabled() is False
    assert panel.case_sensitive_checkbox.isChecked() is True
    assert panel.whole_word_checkbox.isChecked() is True
    panel.regex_checkbox.setChecked(False)
    assert panel.case_sensitive_checkbox.isEnabled() is True
    assert panel.whole_word_checkbox.isEnabled() is True
    assert panel.case_sensitive_checkbox.isChecked() is True
    assert panel.whole_word_checkbox.isChecked() is True
    panel.shutdown()
    panel.close()
    app.processEvents()


def test_find_replace_window_and_right_report_are_resizable_and_toggleable():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    panel.show()
    panel.resize(860, 520)
    panel.report_splitter.setSizes((500, 340))
    app.processEvents()

    assert (panel.width(), panel.height()) == (860, 520)
    assert panel.capture_view.maximumHeight() > 1_000_000
    assert panel.report_splitter.sizes()[1] > 82
    panel.report_toggle_button.click()
    assert panel.report_location == "Hidden"
    assert panel.report_frame.isHidden() is True
    panel.report_toggle_button.click()
    assert panel.report_location == "Right"
    assert panel.report_splitter.sizes()[1] > 82
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
    assert panel.actions_widget.height() <= (
        panel.actions_widget.sizeHint().height() + 2
    )
    cancel_bottom = panel.cancel_button.mapTo(
        controls,
        panel.cancel_button.rect().bottomLeft(),
    ).y()
    assert cancel_bottom >= controls.height() - 6

    panel.shutdown()
    panel.close()


def test_find_replace_actions_are_compact_accessible_and_on_one_line():
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

    assert button_labels(panel.actions_widget) == ["F+", "R+", "<<", ">>", "R"]
    expected_names = {
        panel.find_all_button: "Find All",
        panel.replace_all_button: "Replace All",
        panel.previous_button: "Previous Match",
        panel.next_button: "Next Match",
        panel.replace_button: "Replace Current Match",
    }
    for button, name in expected_names.items():
        assert button.accessibleName() == name
        assert button.toolTip() == name
        assert button.width() <= 48
    panel.shutdown()
    panel.close()


def test_find_replace_report_is_always_right_docked_and_zoom_is_independent(
    tmp_path: Path,
):
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
        assert panel.report_location == "Right"
        assert panel.report_toggle_button.text() == "║"
        assert panel.report_splitter.orientation() == Qt.Orientation.Horizontal
        panel.set_report_location("Hidden")
        assert panel.report_frame.isVisible() is False
        assert panel.report_toggle_button.text() == ">"
        panel.set_report_location("Bottom")
        assert panel.report_frame.isHidden() is False
        assert panel.report_location == "Right"
        assert panel.report_toggle_button.text() == "║"
        assert panel.report_splitter.orientation() == Qt.Orientation.Horizontal
        panel.shutdown()
        panel.close()
        view.close()


def test_find_replace_is_topmost_and_clear_buttons_clear_only_their_input():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    panel.resize(720, 320)
    panel.show()
    panel.find_input.set_text("needle")
    panel.replace_input.set_text("replacement")
    app.processEvents()

    assert panel.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert panel.testAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow)
    assert panel.find_clear_button.accessibleName() == "Clear Find"
    assert panel.replace_clear_button.accessibleName() == "Clear Replace"
    for field, button in (
        (panel.find_input, panel.find_clear_button),
        (panel.replace_input, panel.replace_clear_button),
    ):
        assert button.width() == button.height()
        assert button.x() >= field.width() - button.width() - 8
        assert button.y() <= 8

    panel.find_clear_button.click()
    assert panel.find_input.text() == ""
    assert panel.replace_input.text() == "replacement"
    panel.replace_clear_button.click()
    assert panel.replace_input.text() == ""
    panel.shutdown()
    panel.close()
    app.processEvents()


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


def test_navigation_publishes_loading_then_current_and_next_capture_report(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import uniti.ui.find_replace as find_replace

    real = find_replace.resolve_capture_report
    started = threading.Event()
    release = threading.Event()

    def delayed(snapshot, compiled, request, **options):
        started.set()
        release.wait(5)
        return real(snapshot, compiled, request, **options)

    monkeypatch.setattr(find_replace, "resolve_capture_report", delayed)
    app, document, view, panel = _make_panel(tmp_path, "aaa bbb")
    try:
        _run_regex_search(app, panel, r"(?P<letter>[a-z])+", expected=2)
        _wait_until(app, started.is_set)
        assert panel.capture_model.rows() == ("loading captures…",)
        release.set()
        _wait_until(
            app,
            lambda: panel.capture_model.rows()
            and panel.capture_model.rows()[0] == "Match 1 of 2",
        )
        rows = panel.capture_model.rows()
        assert "1 letter │ a | a | a (3 occurrences)" in rows
        assert "Match 2 of 2" in rows
        assert "1 letter │ b | b | b (3 occurrences)" in rows
        assert all("group 0" not in row.lower() for row in rows)
        assert panel.capture_view.accessibleName() == "Match Report"
    finally:
        release.set()
        _close_panel(app, document, view, panel)


def test_rapid_navigation_publishes_only_latest_capture_generation(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import uniti.ui.find_replace as find_replace

    real = find_replace.resolve_capture_report
    started = threading.Event()
    release = threading.Event()

    def delayed(snapshot, compiled, request, **options):
        if request.requested_index == 0:
            started.set()
            release.wait(5)
        return real(snapshot, compiled, request, **options)

    monkeypatch.setattr(find_replace, "resolve_capture_report", delayed)
    app, document, view, panel = _make_panel(tmp_path, "a b c")
    try:
        _run_regex_search(app, panel, r"(?P<letter>\w)", expected=3)
        _wait_until(app, started.is_set)
        panel.next_match()
        panel.next_match()
        release.set()
        _wait_until(app, lambda: panel.capture_model.current_index == 2)

        assert panel.capture_model.rows()[0] == "Match 3 of 3"
        assert panel._current_index == 2
        assert panel.result_count == 3
    finally:
        release.set()
        _close_panel(app, document, view, panel)


def test_capture_failure_leaves_valid_match_navigation_intact(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import uniti.ui.find_replace as find_replace

    def failed(*_args, **_kwargs):
        raise RuntimeError("sensitive detail must not escape")

    monkeypatch.setattr(find_replace, "resolve_capture_report", failed)
    app, document, view, panel = _make_panel(tmp_path, "a b")
    try:
        _run_regex_search(app, panel, r"(\w)", expected=2)
        _wait_until(
            app,
            lambda: "capture details unavailable" in panel.capture_model.rows(),
        )

        assert panel.result_count == 2
        assert panel._current_index == 0
        assert panel.next_button.isEnabled()
        assert "sensitive" not in "\n".join(panel.capture_model.rows())
    finally:
        _close_panel(app, document, view, panel)


def test_single_match_capture_report_is_not_duplicated(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "a")
    try:
        _run_regex_search(app, panel, r"(?P<letter>a)", expected=1)
        _wait_until(app, lambda: panel.capture_model.current_index == 0)

        rows = panel.capture_model.rows()
        assert rows.count("Match 1 of 1") == 1
        assert "─────────────────" not in rows
    finally:
        _close_panel(app, document, view, panel)


def test_capture_admission_failure_closes_snapshot_and_keeps_navigation(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from uniti.resources import MemorySnapshot

    app, document, view, panel = _make_panel(tmp_path, "a a")
    try:
        _run_regex_search(app, panel, r"(a)", expected=2)
        _wait_until(app, lambda: panel.capture_model.current_index == 0)
        real_snapshot = document.snapshot
        observed: list[_ObservedSnapshot] = []

        def snapshot():
            proxy = _ObservedSnapshot(real_snapshot())
            observed.append(proxy)
            return proxy

        monkeypatch.setattr(document, "snapshot", snapshot)
        panel._resource_manager.observe_memory(MemorySnapshot(16 << 30, 1 << 20))
        panel.next_match()
        _wait_until(
            app,
            lambda: panel.capture_model.current_index == 1
            and "capture details unavailable" in panel.capture_model.rows(),
        )

        assert len(observed) == 1
        assert observed[0].closed
        assert panel.result_count == 2
        assert panel._current_index == 1
    finally:
        _close_panel(app, document, view, panel)


def test_snapshot_failure_cancels_obsolete_capture_work(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import uniti.ui.find_replace as find_replace

    app, document, view, panel = _make_panel(tmp_path, "a a a")
    release = threading.Event()
    try:
        _run_regex_search(app, panel, r"(a)", expected=3)
        _wait_until(app, lambda: panel.capture_model.current_index == 0)
        started = threading.Event()
        real_resolve = find_replace.resolve_capture_report

        def delayed(snapshot, compiled, request, **options):
            started.set()
            release.wait(5)
            return real_resolve(snapshot, compiled, request, **options)

        monkeypatch.setattr(find_replace, "resolve_capture_report", delayed)
        panel.next_match()
        _wait_until(app, started.is_set)
        active_handle = panel._capture_slot._active_handle
        assert active_handle is not None

        def snapshot_failure():
            raise OSError("snapshot unavailable")

        monkeypatch.setattr(document, "snapshot", snapshot_failure)
        panel.next_match()

        assert active_handle.token.cancelled
        assert panel.capture_model.current_index == 2
        assert "capture details unavailable" in panel.capture_model.rows()
    finally:
        release.set()
        _close_panel(app, document, view, panel)


@pytest.mark.parametrize(
    "invalidation",
    ("edit", "pattern", "target", "reject", "replace", "shutdown"),
)
def test_capture_snapshot_closes_on_every_invalidation_boundary(
    tmp_path: Path,
    monkeypatch,
    invalidation: str,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import uniti.ui.find_replace as find_replace

    app, document, view, panel = _make_panel(tmp_path, "a a")
    release = threading.Event()
    try:
        _run_regex_search(app, panel, r"(a)", expected=2)
        _wait_until(app, lambda: panel.capture_model.current_index == 0)
        if invalidation == "replace":
            panel.replace_input.set_text("X")

        real_snapshot = document.snapshot
        observed: list[_ObservedSnapshot] = []

        def snapshot():
            if invalidation == "replace" and observed:
                return real_snapshot()
            proxy = _ObservedSnapshot(real_snapshot())
            observed.append(proxy)
            return proxy

        started = threading.Event()
        real_resolve = find_replace.resolve_capture_report

        def delayed(snapshot, compiled, request, **options):
            started.set()
            release.wait(5)
            return real_resolve(snapshot, compiled, request, **options)

        monkeypatch.setattr(document, "snapshot", snapshot)
        monkeypatch.setattr(find_replace, "resolve_capture_report", delayed)
        panel.next_match()
        _wait_until(app, started.is_set)

        if invalidation == "edit":
            document.insert(0, "x")
        elif invalidation == "pattern":
            panel.find_input.set_text("(b)")
        elif invalidation == "target":
            panel.document_changed()
        elif invalidation == "reject":
            panel.reject()
        elif invalidation == "replace":
            panel.replace_current()
        else:
            panel.shutdown()
        release.set()
        _wait_until(app, lambda: bool(observed) and all(item.closed for item in observed))
        if invalidation == "replace":
            _wait_until(app, lambda: not panel.busy)
            assert document.read(0, document.total_chars()) == "a X"

        assert panel.capture_model.rows() == ()
    finally:
        release.set()
        _close_panel(app, document, view, panel)


def test_replaced_pending_capture_snapshot_closes_before_active_work_finishes(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import uniti.ui.find_replace as find_replace

    app, document, view, panel = _make_panel(tmp_path, "a a")
    release = threading.Event()
    try:
        _run_regex_search(app, panel, r"(a)", expected=2)
        _wait_until(app, lambda: panel.capture_model.current_index == 0)

        real_snapshot = document.snapshot
        observed: list[_ObservedSnapshot] = []

        def snapshot():
            proxy = _ObservedSnapshot(real_snapshot())
            observed.append(proxy)
            return proxy

        started = threading.Event()
        real_resolve = find_replace.resolve_capture_report

        def delayed(snapshot, compiled, request, **options):
            started.set()
            release.wait(5)
            return real_resolve(snapshot, compiled, request, **options)

        monkeypatch.setattr(document, "snapshot", snapshot)
        monkeypatch.setattr(find_replace, "resolve_capture_report", delayed)
        panel.next_match()
        _wait_until(app, started.is_set)
        panel.next_match()
        panel.next_match()

        assert len(observed) == 3
        assert sum(item.closed for item in observed) == 1
        release.set()
        _wait_until(app, lambda: all(item.closed for item in observed))
        _wait_until(app, lambda: panel.capture_model.current_index == 1)
    finally:
        release.set()
        _close_panel(app, document, view, panel)


def test_shutdown_drops_late_capture_completion_after_dialog_is_deleted(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QCoreApplication, QEvent

    import uniti.ui.find_replace as find_replace

    app, document, view, panel = _make_panel(tmp_path, "a a")
    release = threading.Event()
    resources = panel._resource_manager
    try:
        _run_regex_search(app, panel, r"(a)", expected=2)
        _wait_until(app, lambda: panel.capture_model.current_index == 0)
        started = threading.Event()
        real_resolve = find_replace.resolve_capture_report

        def delayed(snapshot, compiled, request, **options):
            started.set()
            release.wait(5)
            return real_resolve(snapshot, compiled, request, **options)

        monkeypatch.setattr(find_replace, "resolve_capture_report", delayed)
        panel.next_match()
        _wait_until(app, started.is_set)
        completion_called = threading.Event()
        panel._capture_task_finished = lambda *_args: completion_called.set()

        panel.shutdown()
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(panel, QEvent.Type.DeferredDelete)
        release.set()
        resources.workers.shutdown(wait=True, cancel_pending=True)

        assert not completion_called.is_set()
    finally:
        release.set()
        resources.workers.shutdown(wait=True, cancel_pending=True)
        view.close()
        view.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        document.close()
        app.processEvents()


def test_find_replace_settings_are_startup_defaults_not_runtime_state(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.settings import Settings, SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    store = SettingsStore(tmp_path / "settings.json")
    defaults = Settings(
        find_replace_zoom_percent=140,
        find_replace_report_location="Right",
        find_replace_geometry=(20, 30, 640, 280),
    )
    store.save(defaults)
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
    find_window.set_zoom_percent(170)
    find_window.set_report_location("Hidden")
    app.processEvents()
    actual = find_window.geometry()
    assert (actual.width(), actual.height()) == (700, 330)
    assert store.load() == defaults
    find_window.shutdown()
    find_window.close()
    window.close()
