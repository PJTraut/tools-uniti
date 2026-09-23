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


def _make_panel(
    tmp_path: Path,
    text: str,
    *,
    dogfood_observer=None,
    document_provider=None,
    group_provider=None,
    recipe_store=None,
):
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "analysis.txt"
    path.write_text(text, encoding="utf-8", newline="")
    app = QApplication.instance() or QApplication([])
    document = Document.open(path, encoding="utf-8")
    view = UNITITextView(EditorState(document))
    panel = FindReplacePanel(
        lambda: view,
        dogfood_observer=dogfood_observer,
        group_provider=group_provider,
        document_provider=document_provider,
        recipe_store=recipe_store,
    )
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


def test_replace_scope_combo_has_four_options_defaulting_to_whole_document(
    tmp_path: Path,
):
    from uniti.ui.find_replace import ReplaceScope

    app, document, view, panel = _make_panel(tmp_path, "alpha")
    try:
        assert panel.replace_scope_combo.count() == 4
        assert panel.replace_scope() == ReplaceScope.WHOLE_DOCUMENT
        labels = [panel.replace_scope_combo.itemText(i) for i in range(4)]
        assert labels == [
            "Whole Document",
            "Cursor to End",
            "Current Group",
            "All Open Documents",
        ]
    finally:
        _close_panel(app, document, view, panel)


def test_recipe_combo_lists_saved_recipes_after_placeholder(tmp_path: Path):
    from uniti.app.find_replace_recipes import FindReplaceRecipe, FindReplaceRecipeStore

    store = FindReplaceRecipeStore(tmp_path / "recipes.json")
    recipe = FindReplaceRecipe("r1", "Trim spaces", r"\s+", " ", True, False, False)
    store.save((recipe,))

    app, document, view, panel = _make_panel(tmp_path, "alpha", recipe_store=store)
    try:
        labels = [panel.recipe_combo.itemText(i) for i in range(panel.recipe_combo.count())]
        assert labels == ["Recipes", "Trim spaces", "", "Save Current…", "Manage…"]
        assert panel.recipe_combo.currentIndex() == 0
    finally:
        _close_panel(app, document, view, panel)


def test_selecting_a_recipe_loads_its_fields_and_resets_the_combo(tmp_path: Path):
    from uniti.app.find_replace_recipes import FindReplaceRecipe, FindReplaceRecipeStore

    store = FindReplaceRecipeStore(tmp_path / "recipes.json")
    recipe = FindReplaceRecipe("r1", "Trim spaces", r"\s+", " ", True, True, True)
    store.save((recipe,))

    app, document, view, panel = _make_panel(tmp_path, "alpha", recipe_store=store)
    try:
        panel.recipe_combo.activated.emit(1)

        assert panel.find_input.text() == r"\s+"
        assert panel.replace_input.text() == " "
        assert panel.regex_checkbox.isChecked() is True
        assert panel.case_sensitive_checkbox.isChecked() is True
        assert panel.whole_word_checkbox.isChecked() is True
        assert panel.recipe_combo.currentIndex() == 0
    finally:
        _close_panel(app, document, view, panel)


def test_save_current_as_recipe_persists_and_appears_in_the_combo(
    tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QInputDialog

    from uniti.app.find_replace_recipes import FindReplaceRecipeStore

    store = FindReplaceRecipeStore(tmp_path / "recipes.json")
    app, document, view, panel = _make_panel(tmp_path, "alpha", recipe_store=store)
    try:
        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        panel.regex_checkbox.setChecked(True)

        monkeypatch.setattr(
            QInputDialog, "getText", staticmethod(lambda *a, **k: ("My Recipe", True))
        )
        panel._save_current_as_recipe()

        assert [recipe.name for recipe in panel._recipes] == ["My Recipe"]
        saved = store.load()
        assert len(saved) == 1
        assert saved[0].name == "My Recipe"
        assert saved[0].expression == "alpha"
        assert saved[0].replacement == "omega"
        assert saved[0].regex is True
        labels = [panel.recipe_combo.itemText(i) for i in range(panel.recipe_combo.count())]
        assert "My Recipe" in labels
    finally:
        _close_panel(app, document, view, panel)


def test_manage_recipes_dialog_renames_and_removes(tmp_path: Path, monkeypatch):
    from uniti.app.find_replace_recipes import FindReplaceRecipe, FindReplaceRecipeStore

    store = FindReplaceRecipeStore(tmp_path / "recipes.json")
    store.save(
        (
            FindReplaceRecipe("r1", "Keep me", "a", "b", False, False, False),
            FindReplaceRecipe("r2", "Delete me", "c", "d", False, False, False),
        )
    )
    app, document, view, panel = _make_panel(tmp_path, "alpha", recipe_store=store)
    try:

        class FakeEditor:
            def __init__(self, recipes, parent=None) -> None:
                self._recipes = recipes

            def exec(self) -> bool:
                return True

            def recipes(self):
                return (self._recipes[0],)

        monkeypatch.setattr(
            "uniti.ui.find_replace_recipe_editor.FindReplaceRecipeEditor", FakeEditor
        )

        panel._show_recipe_manager()

        assert [recipe.name for recipe in panel._recipes] == ["Keep me"]
        assert [recipe.name for recipe in store.load()] == ["Keep me"]
    finally:
        _close_panel(app, document, view, panel)


def test_selection_only_checkbox_forces_and_disables_replace_scope_combo(
    tmp_path: Path,
):
    from uniti.ui.find_replace import ReplaceScope

    app, document, view, panel = _make_panel(tmp_path, "alpha")
    try:
        panel.replace_scope_combo.setCurrentIndex(
            panel.replace_scope_combo.findData(ReplaceScope.CURSOR_TO_END)
        )
        assert panel.replace_scope_combo.isEnabled()

        panel.selection_only_checkbox.setChecked(True)

        assert panel.replace_scope() == ReplaceScope.WHOLE_DOCUMENT
        assert not panel.replace_scope_combo.isEnabled()

        panel.selection_only_checkbox.setChecked(False)

        assert panel.replace_scope_combo.isEnabled()
    finally:
        _close_panel(app, document, view, panel)


def test_find_all_in_selection_only_returns_matches_within_the_selection(
    tmp_path: Path,
):
    app, document, view, panel = _make_panel(tmp_path, "alpha alpha alpha")
    try:
        # Select the middle "alpha" only (offsets 6-11).
        view.state.move_to(6)
        view.state.move_to(11, selecting=True)
        panel.selection_only_checkbox.setChecked(True)

        panel.find_input.set_text("alpha")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count >= 0)

        assert panel.result_count == 1
        assert panel._results.records[0].span == (6, 11)
    finally:
        _close_panel(app, document, view, panel)


def test_find_all_in_selection_without_a_selection_is_unavailable(tmp_path: Path):
    from uniti.app.dogfood import Operation, Outcome

    calls = []
    app, document, view, panel = _make_panel(
        tmp_path,
        "alpha",
        dogfood_observer=lambda operation, outcome, **facts: calls.append(
            (operation, outcome, facts)
        ),
    )
    try:
        panel.selection_only_checkbox.setChecked(True)
        panel.find_input.set_text("alpha")
        _wait_until(app, lambda: panel.compile_current() is not None)

        panel.find_all()

        assert not panel.busy
        assert calls[-1][0] is Operation.FIND_ALL
        assert calls[-1][1] is Outcome.UNAVAILABLE
        assert panel.result_count == 0
    finally:
        _close_panel(app, document, view, panel)


def test_replace_all_in_selection_only_replaces_matches_within_the_selection(
    tmp_path: Path,
):
    app, document, view, panel = _make_panel(tmp_path, "alpha alpha alpha")
    try:
        view.state.move_to(6)
        view.state.move_to(11, selecting=True)
        panel.selection_only_checkbox.setChecked(True)

        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )

        panel.replace_all()
        _wait_until(app, lambda: not panel.busy and "replaced" in panel.status_label.text())

        assert document.read(0, document.total_chars()) == "alpha omega alpha"
    finally:
        _close_panel(app, document, view, panel)


def test_find_all_in_selection_reruns_when_the_selection_changes(tmp_path: Path):
    app, document, view, panel = _make_panel(tmp_path, "alpha alpha alpha")
    try:
        view.state.move_to(0)
        view.state.move_to(5, selecting=True)
        panel.selection_only_checkbox.setChecked(True)
        panel.find_input.set_text("alpha")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 1)
        assert panel._results.records[0].span == (0, 5)

        view.state.move_to(6)
        view.state.move_to(11, selecting=True)
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 1)

        assert panel._results.records[0].span == (6, 11)
    finally:
        _close_panel(app, document, view, panel)


def test_replace_all_cursor_to_end_only_replaces_matches_after_cursor(
    tmp_path: Path,
):
    from uniti.ui.find_replace import ReplaceScope

    app, document, view, panel = _make_panel(tmp_path, "alpha alpha alpha")
    try:
        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )
        view.state.move_to(6)  # start of the second "alpha"
        panel.replace_scope_combo.setCurrentIndex(
            panel.replace_scope_combo.findData(ReplaceScope.CURSOR_TO_END)
        )

        panel.replace_all()
        _wait_until(
            app, lambda: not panel.busy and "replaced" in panel.status_label.text()
        )

        assert document.read(0, document.total_chars()) == "alpha omega omega"
    finally:
        _close_panel(app, document, view, panel)


def test_replace_all_open_documents_replaces_every_document_once(tmp_path: Path):
    from uniti.core.document import Document
    from uniti.ui.find_replace import ReplaceScope

    other_path = tmp_path / "other.txt"
    other_path.write_text("alpha alpha", encoding="utf-8", newline="")
    other_document = Document.open(other_path, encoding="utf-8")

    app, document, view, panel = _make_panel(
        tmp_path,
        "alpha alpha",
        document_provider=lambda: [document, other_document],
    )
    try:
        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )
        panel.replace_scope_combo.setCurrentIndex(
            panel.replace_scope_combo.findData(ReplaceScope.ALL_OPEN_DOCUMENTS)
        )

        panel.replace_all()
        _wait_until(
            app,
            lambda: not panel.busy and "replaced across" in panel.status_label.text(),
        )

        assert document.read(0, document.total_chars()) == "omega omega"
        assert other_document.read(0, other_document.total_chars()) == "omega omega"
        assert "2 document" in panel.status_label.text()
    finally:
        _close_panel(app, document, view, panel)
        other_document.close()


def test_replace_all_current_group_only_replaces_documents_in_that_group(
    tmp_path: Path,
):
    from uniti.core.document import Document
    from uniti.ui.find_replace import ReplaceScope

    grouped_path = tmp_path / "grouped.txt"
    grouped_path.write_text("alpha alpha", encoding="utf-8", newline="")
    grouped_document = Document.open(grouped_path, encoding="utf-8")
    ungrouped_path = tmp_path / "ungrouped.txt"
    ungrouped_path.write_text("alpha alpha", encoding="utf-8", newline="")
    ungrouped_document = Document.open(ungrouped_path, encoding="utf-8")

    app, document, view, panel = _make_panel(
        tmp_path,
        "alpha alpha",
        group_provider=lambda current: (
            [document, grouped_document] if current is document else []
        ),
    )
    try:
        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )
        panel.replace_scope_combo.setCurrentIndex(
            panel.replace_scope_combo.findData(ReplaceScope.CURRENT_GROUP)
        )

        panel.replace_all()
        _wait_until(
            app,
            lambda: not panel.busy and "replaced across" in panel.status_label.text(),
        )

        assert document.read(0, document.total_chars()) == "omega omega"
        assert grouped_document.read(0, grouped_document.total_chars()) == "omega omega"
        assert ungrouped_document.read(0, ungrouped_document.total_chars()) == "alpha alpha"
        assert "2 document" in panel.status_label.text()
    finally:
        _close_panel(app, document, view, panel)
        grouped_document.close()
        ungrouped_document.close()


def test_replace_all_current_group_is_unavailable_without_a_group_provider(
    tmp_path: Path,
):
    from uniti.app.dogfood import Operation, Outcome
    from uniti.ui.find_replace import ReplaceScope

    calls = []
    app, document, view, panel = _make_panel(
        tmp_path,
        "alpha",
        dogfood_observer=lambda operation, outcome, **facts: calls.append(
            (operation, outcome, facts)
        ),
    )
    try:
        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )
        panel.replace_scope_combo.setCurrentIndex(
            panel.replace_scope_combo.findData(ReplaceScope.CURRENT_GROUP)
        )

        panel.replace_all()

        assert not panel.busy
        assert calls[-1][0] is Operation.REPLACE_ALL
        assert calls[-1][1] is Outcome.UNAVAILABLE
        assert document.read(0, document.total_chars()) == "alpha"
    finally:
        _close_panel(app, document, view, panel)


def test_replace_all_open_documents_is_unavailable_without_a_document_provider(
    tmp_path: Path,
):
    from uniti.app.dogfood import Operation, Outcome
    from uniti.ui.find_replace import ReplaceScope

    calls = []
    app, document, view, panel = _make_panel(
        tmp_path,
        "alpha",
        dogfood_observer=lambda operation, outcome, **facts: calls.append(
            (operation, outcome, facts)
        ),
    )
    try:
        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )
        panel.replace_scope_combo.setCurrentIndex(
            panel.replace_scope_combo.findData(ReplaceScope.ALL_OPEN_DOCUMENTS)
        )

        panel.replace_all()

        assert not panel.busy
        assert calls[-1][0] is Operation.REPLACE_ALL
        assert calls[-1][1] is Outcome.UNAVAILABLE
        assert document.read(0, document.total_chars()) == "alpha"
    finally:
        _close_panel(app, document, view, panel)


def test_replace_and_find_next_confirms_then_advances_through_every_match(
    tmp_path: Path,
):
    app, document, view, panel = _make_panel(tmp_path, "alpha alpha alpha")
    try:
        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 3)
        assert panel._current_index == 0

        panel.replace_and_find_next()
        _wait_until(
            app,
            lambda: document.read(0, document.total_chars())
            == "omega alpha alpha",
        )
        _wait_until(app, lambda: not panel.busy and panel.result_count == 2)

        panel.replace_and_find_next()
        _wait_until(
            app,
            lambda: document.read(0, document.total_chars())
            == "omega omega alpha",
        )
        _wait_until(app, lambda: not panel.busy and panel.result_count == 1)

        panel.replace_and_find_next()
        _wait_until(
            app,
            lambda: document.read(0, document.total_chars())
            == "omega omega omega",
        )
    finally:
        _close_panel(app, document, view, panel)


def test_skip_current_match_advances_without_changing_the_document(tmp_path: Path):
    app, document, view, panel = _make_panel(tmp_path, "alpha alpha")
    try:
        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 2)
        assert panel._current_index == 0

        panel.skip_current_match()
        _wait_until(app, lambda: not panel.busy and panel._current_index == 1)

        assert document.read(0, document.total_chars()) == "alpha alpha"
    finally:
        _close_panel(app, document, view, panel)


def test_find_replace_reports_fixed_operations_without_content(tmp_path: Path):
    from uniti.app.dogfood import Durability, Operation, Outcome

    calls = []

    def observe(operation, outcome, **facts):
        calls.append((operation, outcome, facts))

    app, document, view, panel = _make_panel(
        tmp_path,
        "alpha beta alpha",
        dogfood_observer=observe,
    )
    try:
        panel.find_input.set_text("alpha")
        panel.replace_input.set_text("omega")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )

        panel.next_match()
        _wait_until(app, lambda: not panel.busy and panel._current_index is not None)
        panel.previous_match()
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 2)
        panel.replace_current()
        _wait_until(app, lambda: not panel.busy and "replaced" in panel.status_label.text())

        panel.find_input.set_text("alpha")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.replace_all()
        _wait_until(app, lambda: not panel.busy and "replaced" in panel.status_label.text())

        operations = [call[0] for call in calls]
        assert Operation.FIND_NEXT in operations
        assert Operation.FIND_PREVIOUS in operations
        assert Operation.FIND_ALL in operations
        assert Operation.REPLACE in operations
        assert Operation.REPLACE_ALL in operations
        for operation, outcome, facts in calls:
            assert isinstance(operation, Operation)
            assert isinstance(outcome, Outcome)
            assert set(facts) == {"elapsed_ms", "durability"}
            assert isinstance(facts["elapsed_ms"], (int, float, type(None)))
            assert facts["durability"] is Durability.NOT_APPLICABLE
            assert "alpha" not in repr((operation, outcome, facts))
            assert "omega" not in repr((operation, outcome, facts))
    finally:
        _close_panel(app, document, view, panel)


def test_find_replace_recording_failure_does_not_change_search(tmp_path: Path):
    def fail_observation(*_args, **_kwargs):
        raise RuntimeError("private observation failure")

    app, document, view, panel = _make_panel(
        tmp_path,
        "one two one",
        dogfood_observer=fail_observation,
    )
    try:
        panel.find_input.set_text("one")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: not panel.busy)
        assert panel.result_count == 2
    finally:
        _close_panel(app, document, view, panel)


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
    source = REGEX_INPUT.read_text(encoding="utf-8")
    assert "QSyntaxHighlighter" in source
    assert "set_analysis" in source
    assert "tokenize_pattern" not in source
    assert "tokenize_replacement" not in source
    assert "RegexInput" in source
    assert "ReplacementInput" in source


def test_find_replace_panel_has_worker_cancellation_navigation_and_capture_ui():
    assert PANEL.exists()
    source = PANEL.read_text(encoding="utf-8")
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
        r"\1 a | a | a (3 occurrences) [letter]",
        r"\2 empty at 3 [empty]",
        r"\3 not matched [missing]",
        r"\4 a | empty at 1 (2 occurrences) [mixed]",
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


def test_capture_view_minimum_height_never_grows_with_match_report_content(
    tmp_path: Path,
):
    """The Find/Replace panel must not auto-expand to fit the match report:
    `capture_view`'s minimum height sits in a horizontal `QSplitter` beside
    the controls pane, so growing it directly grows the whole panel window.
    It must stay tied only to the current zoom/font size, regardless of how
    many matches or capture-group rows a search result contains — content
    that needs more room scrolls instead of resizing the window."""

    from uniti.regex.captures import (
        CaptureGroupRow,
        CaptureMatchReport,
        CapturePreview,
        CaptureReport,
        CaptureReportRequest,
    )
    from uniti.regex.results import MatchRecord

    app, document, view, panel = _make_panel(tmp_path, "alpha")
    try:

        def group(number: int) -> CaptureGroupRow:
            return CaptureGroupRow(
                number, None, "value", 1, (CapturePreview(0, 1, "x", False),)
            )

        def report(*, huge: bool) -> CaptureReport:
            groups = tuple(group(n) for n in range(1, 21)) if huge else (group(1),)
            matches = (CaptureMatchReport(index=0, total=1, groups=groups),)
            request = CaptureReportRequest(
                pattern_generation=1,
                pattern_text="pattern",
                document_key="doc",
                revision=1,
                store_id="store",
                requested_index=0,
                match_count=1,
                matches=((0, MatchRecord(0, 1)),),
            )
            return CaptureReport(request=request, matches=matches, payload_bytes=1024)

        height_before_any_search = panel.capture_view.minimumHeight()

        # A match with 20 capture-group rows must not inflate the minimum
        # height — the panel's own size must not react to match content.
        panel.capture_model.set_report(report(huge=True))
        app.processEvents()
        assert panel.capture_view.minimumHeight() == height_before_any_search

        panel.capture_model.set_report(report(huge=False))
        app.processEvents()
        assert panel.capture_view.minimumHeight() == height_before_any_search

        # Zoom, a deliberate user action, is still allowed to change it --
        # the report's own zoom (BF-092), independent of the fields'.
        panel.set_report_zoom_percent(200)
        app.processEvents()
        assert panel.capture_view.minimumHeight() > height_before_any_search
    finally:
        _close_panel(app, document, view, panel)


def test_text_view_paints_compact_match_index_intersections_only():
    source = VIEW.read_text(encoding="utf-8")
    assert "MatchIndex" in source
    assert "intersecting" in source
    assert "set_match_index" in source


def test_main_window_integrates_bottom_find_replace_panel_and_shortcuts():
    source = MAIN.read_text(encoding="utf-8")
    shortcut_source = SHORTCUT_POLICY.read_text(encoding="utf-8")
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


def test_find_replace_attach_inserts_a_pane_tree_leaf_and_detach_preserves_state():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FIND_REPLACE_VIEW_ID
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    host = UNITIMainWindow()
    panel = host.find_replace
    placements: list[str] = []
    panel.placementChanged.connect(placements.append)
    try:
        assert panel.content.isAncestorOf(panel.find_input)
        assert panel.content.isAncestorOf(panel.replace_input)
        assert panel.placement == "detached"
        assert not host.panes.contains_view(FIND_REPLACE_VIEW_ID)

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
        assert panel.isFloating() is True  # the (now hidden) shell's own flag; irrelevant while attached
        assert host.panes.contains_view(FIND_REPLACE_VIEW_ID)
        leaf = host.panes.leaf_for_view(FIND_REPLACE_VIEW_ID)
        assert leaf.widget(leaf.index_of(FIND_REPLACE_VIEW_ID)) is panel.content

        panel.detach()
        app.processEvents()

        assert panel.placement == "detached"
        assert not host.panes.contains_view(FIND_REPLACE_VIEW_ID)
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


def test_attaching_with_no_document_open_reserves_height_instead_of_filling_the_window():
    """BF-090: attaching with zero documents open used to have no view to
    anchor a split against, so it fell back to adding Find/Replace as the
    pane tree's sole tab -- filling the whole window instead of the usual
    bounded height. It now splits the (empty) root pane directly
    (`EditorPaneTree.split_pane`), leaving an empty sibling leaf reserving
    space exactly like an ordinary document-less window already shows."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FIND_REPLACE_VIEW_ID
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    host = UNITIMainWindow()
    panel = host.find_replace
    try:
        assert host.panes.view_ids == ()

        panel.attach_to(host)
        app.processEvents()

        assert host.panes.leaf_count == 2
        leaf = host.panes.leaf_for_view(FIND_REPLACE_VIEW_ID)
        assert leaf.widget(leaf.index_of(FIND_REPLACE_VIEW_ID)) is panel.content
        other_leaves = [
            host.panes.leaf(pane_id)
            for pane_id in host.panes.pane_ids
            if pane_id != leaf.pane_id
        ]
        assert len(other_leaves) == 1
        assert other_leaves[0].count() == 0
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

    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    restored = FindReplacePanel(lambda: None)
    geometry_events: list[tuple[int, int, int, int]] = []
    panel.geometryChanged.connect(geometry_events.append)
    host = None
    try:
        panel.setGeometry(23, 31, 760, 410)
        panel.show()
        app.processEvents()
        detached = panel.export_state("view-target")
        assert detached.placement == "detached"
        # The offscreen QPA platform can nudge a freshly shown top-level
        # window's position to avoid exactly overlapping another one already
        # on screen (order-dependent on what other tests left behind), so
        # the rest of this test compares round-trip preservation against
        # whichever geometry was actually realized rather than asserting an
        # exact absolute value here.
        assert geometry_events

        host = UNITIMainWindow()
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
        panel.detach()
        for item in (panel, restored):
            item.shutdown()
            item.close()
        if host is not None:
            host.close()
        app.processEvents()


def test_find_replace_title_bar_has_no_attach_toggle_button(tmp_path: Path):
    """The title-bar attach/detach toggle button was removed (it only ever
    worked once a host had already been recorded via an explicit
    ``attach_to`` call, so clicking it on a never-yet-attached panel was a
    silent no-op) — attach/detach stays available via the View menu command
    (``toggle_find_replace_attachment``) and the programmatic ``attach_to``/
    ``detach`` API, which do not have that limitation."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    host = UNITIMainWindow()
    panel = host.find_replace
    try:
        assert panel.titleBarWidget() is not None
        assert not hasattr(panel, "attach_toggle_button")

        assert panel.placement == "detached"
        panel.attach_to(host)
        assert panel.placement == "attached"
        panel.detach()
        assert panel.placement == "detached"
    finally:
        panel.shutdown()
        panel.close()
        host.close()
        app.processEvents()


def test_toggle_find_replace_visibility_shows_then_hides_a_detached_panel():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    host = UNITIMainWindow()
    panel = host.find_replace
    try:
        assert panel.placement == "detached"
        assert not panel.is_visible()

        host.toggle_find_replace_visibility()
        app.processEvents()
        assert panel.is_visible()

        host.toggle_find_replace_visibility()
        app.processEvents()
        assert not panel.is_visible()
    finally:
        panel.shutdown()
        panel.close()
        host.close()
        app.processEvents()


def test_toggle_find_replace_visibility_closes_and_reopens_an_attached_tab():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FIND_REPLACE_VIEW_ID
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    host = UNITIMainWindow()
    panel = host.find_replace
    try:
        panel.attach_to(host)
        app.processEvents()
        assert panel.placement == "attached"
        assert panel.is_visible()

        host.toggle_find_replace_visibility()
        app.processEvents()
        assert panel.placement == "attached"  # preference unchanged, just hidden
        assert not panel.is_visible()
        assert not host.panes.contains_view(FIND_REPLACE_VIEW_ID)

        host.toggle_find_replace_visibility()
        app.processEvents()
        assert panel.placement == "attached"
        assert panel.is_visible()
        assert host.panes.contains_view(FIND_REPLACE_VIEW_ID)
    finally:
        panel.shutdown()
        panel.close()
        host.close()
        app.processEvents()


def _title_bar_mouse_event(kind, title_bar, local: "QPoint", *, button, buttons):
    from PySide6.QtCore import QPointF, Qt
    from PySide6.QtGui import QMouseEvent

    global_point = title_bar.mapToGlobal(local)
    return QMouseEvent(
        kind,
        QPointF(local),
        QPointF(global_point),
        button,
        buttons,
        Qt.KeyboardModifier.NoModifier,
    )


def test_find_replace_title_bar_drag_moves_a_floating_window(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, Qt
    from PySide6.QtGui import QMouseEvent

    app, document, view, panel = _make_panel(tmp_path, "alpha")
    try:
        panel.show()
        panel.move(100, 100)
        app.processEvents()
        assert panel.isFloating() is True
        title_bar = panel.titleBarWidget()
        start_pos = panel.pos()

        press_local = QPoint(10, 5)
        press = _title_bar_mouse_event(
            QMouseEvent.Type.MouseButtonPress,
            title_bar,
            press_local,
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.LeftButton,
        )
        title_bar.mousePressEvent(press)

        move_local = press_local + QPoint(40, 25)
        move = _title_bar_mouse_event(
            QMouseEvent.Type.MouseMove,
            title_bar,
            move_local,
            button=Qt.MouseButton.NoButton,
            buttons=Qt.MouseButton.LeftButton,
        )
        title_bar.mouseMoveEvent(move)
        app.processEvents()

        assert panel.pos() == start_pos + QPoint(40, 25)

        release = _title_bar_mouse_event(
            QMouseEvent.Type.MouseButtonRelease,
            title_bar,
            move_local,
            button=Qt.MouseButton.LeftButton,
            buttons=Qt.MouseButton.NoButton,
        )
        title_bar.mouseReleaseEvent(release)
    finally:
        _close_panel(app, document, view, panel)


def test_find_replace_title_bar_only_shows_while_floating(tmp_path: Path):
    """Attaching now means inserting into the host's pane tree (see
    ``test_find_replace_attach_inserts_a_pane_tree_leaf_...``), so the
    floating shell's title bar has nothing left to drag-dock/undock onto —
    it only ever needs to move the floating window, and it only appears
    while detached."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from uniti.ui.main_window import UNITIMainWindow

    app, document, view, panel = _make_panel(tmp_path, "alpha")
    host = UNITIMainWindow()
    try:
        assert panel.isFloating() is True

        panel.attach_to(host)
        app.processEvents()

        assert panel.placement == "attached"
        assert panel.isHidden() is True
    finally:
        panel.detach()
        _close_panel(app, document, view, panel)
        host.close()


def test_closing_the_panel_while_busy_cancels_the_running_job(
    tmp_path: Path, monkeypatch
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import uniti.ui.find_replace as find_replace

    started = threading.Event()
    release = threading.Event()
    real = find_replace.search_document

    def delayed(*args, **kwargs):
        started.set()
        release.wait(5)
        yield from real(*args, **kwargs)

    monkeypatch.setattr(find_replace, "search_document", delayed)
    app, document, view, panel = _make_panel(tmp_path, "alpha")
    try:
        panel.find_input.set_text("alpha")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, started.is_set)
        assert panel.busy

        task_handle = panel._task_handle
        panel.close()

        assert task_handle.token.cancelled
        release.set()
    finally:
        release.set()
        _close_panel(app, document, view, panel)


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
    path.write_text(text, encoding="utf-8", newline="")
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
    source = PANEL.read_text(encoding="utf-8")
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


def test_status_distinguishes_zero_matches_from_not_yet_searched(tmp_path: Path):
    """A pattern that compiles but hasn't been searched yet, and one that
    was searched and genuinely found nothing, must not read identically --
    a user debugging a pattern (e.g. a mistyped SFM marker name) needs to
    know a real search actually ran and found zero, not just that the
    pattern happens to be syntactically valid."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "alpha")
    try:
        panel.regex_checkbox.setChecked(True)
        panel.find_input.set_text(r"(z)")
        _wait_until(app, lambda: panel.compile_current() is not None)
        # "valid pattern -- N groups" lives in its own label under the
        # Match Report (2026-09-20), decoupled from status_label's
        # busy/match/error messages -- status_label itself is blank here,
        # since no search has run yet.
        assert panel.pattern_info_label.text() == "valid pattern — 1 group"
        assert panel.status_label.text() == ""

        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 0)
        assert panel.status_label.text() == "0 matches"
        assert panel.pattern_info_label.text() == "valid pattern — 1 group"
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


def _format_color_at(editor, position: int) -> str:
    formats = editor.document().firstBlock().layout().formats()
    for item in formats:
        if item.start <= position < item.start + item.length:
            return item.format.foreground().color().name()
    raise AssertionError(f"no format covers position {position}")


def test_find_input_distinguishes_capturing_and_non_capturing_brackets(
    tmp_path: Path,
):
    # BF-052: non-capturing groups must render with a color different from
    # every capturing group's own color. A capturing group's own brackets
    # deliberately keep painting in that group's own identity color (same
    # as its backreferences) — users rely on this to trace which parens
    # belong to which group at a glance; an earlier pass here mistakenly
    # moved capturing brackets to a neutral color reading BF-020's own
    # wording too literally, which regressed to a real reported bug
    # ("capturing groups all white").
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from uniti.ui.regex_input import group_palette, non_capturing_bracket_color

    app, document, view, panel = _make_panel(tmp_path, "abcdef")
    try:
        panel.regex_checkbox.setChecked(True)
        pattern = r"(abc)(?:def)"
        panel.find_input.set_text(pattern)
        _wait_until(app, lambda: panel.compile_current() is not None)
        app.processEvents()

        base = panel.find_input.palette().base().color()
        capturing_open = _format_color_at(panel.find_input, pattern.index("("))
        non_capturing_open = _format_color_at(
            panel.find_input, pattern.index("(?:")
        )
        group_one = group_palette(base)[0].name()

        assert capturing_open == group_one
        assert non_capturing_open == non_capturing_bracket_color(base).name()
        assert non_capturing_open != group_one
    finally:
        _close_panel(app, document, view, panel)


def test_find_input_colors_unicode_escapes_as_their_own_category(tmp_path: Path):
    # BF-052: \uXXXX/\UXXXXXXXX/\xXX/\N{...} must be recognized as one
    # distinct category, not the generic (and previously group-color-
    # colliding) "escape" formatting.
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "abc")
    try:
        panel.regex_checkbox.setChecked(True)
        pattern = "\\u00e9\\d"
        panel.find_input.set_text(pattern)
        _wait_until(app, lambda: panel.compile_current() is not None)
        app.processEvents()

        unicode_escape_color = _format_color_at(panel.find_input, 0)
        generic_escape_color = _format_color_at(
            panel.find_input, pattern.index("\\d")
        )
        assert unicode_escape_color != generic_escape_color
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


def test_invalid_diagnostic_also_gets_a_background_tint(tmp_path: Path):
    """BF-086: the reported error's location was previously only a
    text-only status message ("... at column N") -- the same span that
    gets the wavy underline now also gets a background tint, so the
    problem is visible in the pattern field itself, not just described.
    `ReplacementHighlighter(_AnalysisHighlighter): pass` shares this exact
    `highlightBlock` with no override, so the replacement field gets the
    same treatment for free."""

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
        formats = panel.find_input.document().firstBlock().layout().formats()
        tinted = [
            item for item in formats if item.format.background().color().alpha() > 0
        ]
        assert tinted
        expected = panel.find_input.highlighter._invalid_color
        background = tinted[0].format.background().color()
        assert (background.red(), background.green(), background.blue()) == (
            expected.red(),
            expected.green(),
            expected.blue(),
        )
    finally:
        _close_panel(app, document, view, panel)


def test_regex_mode_paste_converts_literal_whitespace_to_regex_escapes(
    tmp_path: Path,
):
    """BF-088: pasting literal CR/LF/TAB into either field while Regex mode
    is on converts them to their regex escapes, instead of inserting the
    raw control characters into a single-line pattern/replacement field."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QMimeData

    app, document, view, panel = _make_panel(tmp_path, "abc")
    try:
        panel.regex_checkbox.setChecked(True)

        mime = QMimeData()
        mime.setText("a\tb\r\nc")
        panel.find_input.insertFromMimeData(mime)
        assert panel.find_input.text() == "a\\tb\\r\\nc"

        panel.replace_input.insertFromMimeData(mime)
        assert panel.replace_input.text() == "a\\tb\\r\\nc"
    finally:
        _close_panel(app, document, view, panel)


def test_literal_mode_paste_keeps_whitespace_unconverted(tmp_path: Path):
    """BF-088: a literal (non-regex) search/replace must still be able to
    match an actual tab/newline, so paste stays raw with Regex mode off."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QMimeData

    app, document, view, panel = _make_panel(tmp_path, "abc")
    try:
        assert panel.regex_checkbox.isChecked() is False

        mime = QMimeData()
        mime.setText("a\tb")
        panel.find_input.insertFromMimeData(mime)
        assert panel.find_input.text() == "a\tb"
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


def test_find_jobs_limit_resident_match_records_to_one_mib(
    tmp_path: Path,
    monkeypatch,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    import uniti.ui.find_replace as find_replace

    observed_budgets = []
    real_store = find_replace.MatchStore

    class ObservedStore(real_store):
        def __init__(self, **options):
            observed_budgets.append(options.get("memory_budget_bytes"))
            super().__init__(**options)

    monkeypatch.setattr(find_replace, "MatchStore", ObservedStore)
    app, document, view, panel = _make_panel(tmp_path, "one two one")
    try:
        panel.find_input.set_text("one")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 2)

        assert observed_budgets == [1 << 20]
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


def test_find_all_reuses_current_complete_navigation_results(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    app, document, view, panel = _make_panel(tmp_path, "one x one x one")
    try:
        panel.find_input.set_text("one")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.next_match()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 3)
        current_results = panel._results

        panel.find_all()

        assert panel._results is current_results
        assert not panel.busy
        assert panel.status_label.text() == "3 matches"
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
    from PySide6.QtTest import QSignalSpy

    app, document, view, panel = _make_panel(tmp_path, "aa")
    try:
        panel.regex_checkbox.setChecked(True)
        panel.find_input.set_text(r"^")
        _wait_until(app, lambda: panel.compile_current() is not None)
        panel.find_all()
        _wait_until(app, lambda: panel.result_count == 1 and not panel.busy)
        position_spy = QSignalSpy(panel.matchPositionChanged)
        panel.next_match()
        panel.previous_match()

        assert panel._current_index == 0
        assert view.state.selection is None
        assert position_spy.count() >= 1
        assert list(position_spy.at(position_spy.count() - 1)) == [
            view.view_id,
            "Match 1 of 1",
        ]
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
    source = PANEL.read_text(encoding="utf-8")
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

    def button_names(widget):
        layout = widget.layout()
        return [
            layout.itemAt(index).widget().accessibleName()
            for index in range(layout.count())
            if layout.itemAt(index).widget() is not None
        ]

    # Cancel was folded into this same row (2026-09-20 request) instead of
    # sitting alone on its own footer line below. status_label moved here
    # too (2026-09-21 request), centered between the left- and right-hand
    # button groups rather than living in the Find row, so it stays
    # visible even when the Match Report panel is collapsed.
    assert button_names(panel.actions_widget) == [
        "Find All",
        "Replace All",
        "Status",
        "Previous Match",
        "Next Match",
        "Replace Current Match",
        "Replace & Find Next",
        "Cancel",
    ]
    expected_names = {
        panel.find_all_button: "Find All",
        panel.replace_all_button: "Replace All",
        panel.previous_button: "Previous Match",
        panel.next_button: "Next Match",
        panel.replace_button: "Replace Current Match",
        panel.replace_and_next_button: "Replace & Find Next",
    }
    for button, name in expected_names.items():
        assert not button.icon().isNull()
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
        assert panel.report_toggle_button.accessibleName() == "Hide Match Report"
        assert panel.report_splitter.orientation() == Qt.Orientation.Horizontal
        panel.set_report_location("Hidden")
        assert panel.report_frame.isVisible() is False
        assert panel.report_toggle_button.accessibleName() == "Show Match Report"
        panel.set_report_location("Bottom")
        assert panel.report_frame.isHidden() is False
        assert panel.report_location == "Right"
        assert panel.report_toggle_button.accessibleName() == "Hide Match Report"
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


def test_find_replace_wrap_toggle_sets_line_wrap_without_changing_text():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QTextEdit

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    panel.resize(720, 320)
    panel.show()
    panel.find_input.set_text("needle")
    panel.replace_input.set_text("replacement")
    app.processEvents()

    try:
        assert panel.find_wrap_button.isCheckable()
        assert panel.replace_wrap_button.isCheckable()
        assert panel.find_wrap_button.accessibleName() == "Wrap Find"
        assert panel.replace_wrap_button.accessibleName() == "Wrap Replace"
        for field, clear_button, wrap_button in (
            (panel.find_input, panel.find_clear_button, panel.find_wrap_button),
            (
                panel.replace_input,
                panel.replace_clear_button,
                panel.replace_wrap_button,
            ),
        ):
            assert field.lineWrapMode() == QTextEdit.LineWrapMode.NoWrap
            assert wrap_button.width() == wrap_button.height()
            assert wrap_button.x() == clear_button.x()
            assert wrap_button.y() >= clear_button.y() + clear_button.height()

        panel.find_wrap_button.setChecked(True)
        assert panel.find_input.lineWrapMode() == QTextEdit.LineWrapMode.WidgetWidth
        assert panel.find_input.text() == "needle"
        assert panel.replace_input.lineWrapMode() == QTextEdit.LineWrapMode.NoWrap

        panel.replace_wrap_button.setChecked(True)
        assert panel.replace_input.lineWrapMode() == QTextEdit.LineWrapMode.WidgetWidth
        assert panel.replace_input.text() == "replacement"

        panel.find_wrap_button.setChecked(False)
        assert panel.find_input.lineWrapMode() == QTextEdit.LineWrapMode.NoWrap
        assert panel.find_input.text() == "needle"
    finally:
        panel.shutdown()
        panel.close()
        app.processEvents()


def test_find_replace_wrap_state_persists_through_restore():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QTextEdit

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    restored = FindReplacePanel(lambda: None)
    try:
        panel.find_wrap_button.setChecked(True)
        record = panel.export_state("view-target")
        assert record.find_wrap is True
        assert record.replace_wrap is False

        restored.restore_state(record)
        assert restored.find_wrap_button.isChecked() is True
        assert restored.replace_wrap_button.isChecked() is False
        assert restored.find_input.lineWrapMode() == QTextEdit.LineWrapMode.WidgetWidth
        assert restored.replace_input.lineWrapMode() == QTextEdit.LineWrapMode.NoWrap
        assert restored.export_state("view-target") == record
    finally:
        for item in (panel, restored):
            item.shutdown()
            item.close()
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


def test_report_zoom_is_independent_of_the_input_fields_zoom(tmp_path: Path):
    """BF-092: the Match Report's font size no longer moves in lockstep
    with the find/replace fields' -- each has its own persisted state and
    its own scale factor."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    try:
        original_field_size = panel.find_input.font().pointSizeF()
        original_report_size = panel.capture_view.font().pointSizeF()

        panel.set_zoom_percent(140)
        assert panel.zoom_percent == 140
        assert panel.report_zoom_percent == 100
        assert panel.find_input.font().pointSizeF() > original_field_size
        assert panel.capture_view.font().pointSizeF() == original_report_size

        panel.set_report_zoom_percent(160)
        assert panel.report_zoom_percent == 160
        assert panel.zoom_percent == 140
        assert panel.capture_view.font().pointSizeF() > original_report_size
        assert panel.find_input.font().pointSizeF() == pytest.approx(
            original_field_size * 1.4
        )

        panel.reset_report_zoom()
        assert panel.report_zoom_percent == 100
        assert panel.zoom_percent == 140
    finally:
        panel.shutdown()
        panel.close()


def test_primary_modifier_wheel_over_the_report_zooms_the_report_only(
    tmp_path: Path,
):
    """BF-092: a Ctrl+scroll directly over the Match Report changes only
    its own font size, not the find/replace fields' -- companion to
    test_primary_modifier_wheel_zooms_focused_find_replace_only above,
    which covers the reverse (wheel over a field leaves the report alone)."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    try:
        panel.show()
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

        QApplication.sendEvent(panel.capture_view.viewport(), event)

        assert panel.report_zoom_percent == 110
        assert panel.zoom_percent == 100
    finally:
        panel.shutdown()
        panel.close()


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
        assert r"\1 a | a | a (3 occurrences) [letter]" in rows
        assert "Match 2 of 2" in rows
        assert r"\1 b | b | b (3 occurrences) [letter]" in rows
        assert all("group 0" not in row.lower() for row in rows)
        assert panel.capture_view.accessibleName() == "Match Report"
    finally:
        release.set()
        _close_panel(app, document, view, panel)


def test_clicking_a_match_report_row_jumps_to_that_match(tmp_path: Path):
    from uniti.ui.capture_report import CaptureReportModel

    app, document, view, panel = _make_panel(tmp_path, "aaa bbb")
    try:
        _run_regex_search(app, panel, r"(?P<letter>[a-z])+", expected=2)
        _wait_until(
            app,
            lambda: panel.capture_model.rows()
            and "Match 2 of 2" in panel.capture_model.rows(),
        )
        assert panel._current_index == 0

        rows = panel.capture_model.rows()
        second_header_row = rows.index("Match 2 of 2")
        index = panel.capture_model.index(second_header_row, 0)
        assert index.data(CaptureReportModel.MatchIndexRole) == 1

        panel.capture_view.clicked.emit(index)

        assert panel._current_index == 1
        assert view.state.selection == (4, 7)
    finally:
        _close_panel(app, document, view, panel)


def test_match_report_shows_and_live_updates_the_replacement_preview(
    tmp_path: Path,
):
    app, document, view, panel = _make_panel(tmp_path, "alpha beta")
    try:
        panel.regex_checkbox.setChecked(True)
        panel.find_input.set_text(r"(?P<first>\w+) (?P<second>\w+)")
        panel.replace_input.set_text(r"\2 \1")
        _wait_until(
            app,
            lambda: panel.compile_current() is not None
            and panel._replacement_is_current(),
        )
        panel.find_all()
        _wait_until(app, lambda: not panel.busy and panel.result_count == 1)
        _wait_until(app, lambda: "→ beta alpha" in panel.capture_model.rows())

        panel.replace_input.set_text(r"\1-\2")
        _wait_until(app, lambda: "→ alpha-beta" in panel.capture_model.rows())
        assert "→ beta alpha" not in panel.capture_model.rows()
        # The preview must never mutate the document itself.
        assert document.read(0, document.total_chars()) == "alpha beta"
    finally:
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
    find_window.resize(800, 330)
    find_window.set_zoom_percent(170)
    find_window.set_report_location("Hidden")
    app.processEvents()
    actual = find_window.geometry()
    assert (actual.width(), actual.height()) == (800, 330)
    assert store.load() == defaults
    find_window.shutdown()
    find_window.close()
    window.close()


def test_attached_find_replace_uses_remembered_height_not_fifty_percent(
    tmp_path: Path,
):
    """BF-059: attaching must not default to a 50/50 split of the window."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FIND_REPLACE_VIEW_ID
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    host = UNITIMainWindow()
    panel = host.find_replace
    try:
        path = tmp_path / "doc.txt"
        path.write_text("hello", encoding="utf-8")
        host.open_path(path)
        host.resize(900, 700)
        host.show()
        app.processEvents()

        panel.set_attached_height(250)
        panel.attach_to(host)
        app.processEvents()

        leaf = host.panes.leaf_for_view(FIND_REPLACE_VIEW_ID)
        branch = leaf._parent_branch
        sizes = branch.widget.sizes()
        assert abs(sizes[1] - 250) <= 4
        assert sizes[1] < host.panes.height() * 0.4
    finally:
        panel.detach()
        host.close_all_documents(force=True)
        host.close()


def test_attached_find_replace_panel_height_is_unaffected_by_window_resize(
    tmp_path: Path,
):
    """BF-059: the attached panel must not resize when the main window does;
    the editor pane absorbs the resize delta instead (stretch factors)."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FIND_REPLACE_VIEW_ID
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    host = UNITIMainWindow()
    panel = host.find_replace
    try:
        path = tmp_path / "doc.txt"
        path.write_text("hello", encoding="utf-8")
        host.open_path(path)
        host.resize(900, 700)
        host.show()
        app.processEvents()

        panel.set_attached_height(150)
        panel.attach_to(host)
        app.processEvents()

        leaf = host.panes.leaf_for_view(FIND_REPLACE_VIEW_ID)
        branch = leaf._parent_branch
        before = branch.widget.sizes()[1]

        host.resize(900, 1100)
        app.processEvents()

        after = branch.widget.sizes()[1]
        assert after == before
    finally:
        panel.detach()
        host.close_all_documents(force=True)
        host.close()


def test_manually_resizing_attached_panel_is_remembered_for_next_attach(
    tmp_path: Path,
):
    """BF-059: dragging the attached splitter updates the remembered
    height, which the next attach (e.g. after detach/reattach) honors."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FIND_REPLACE_VIEW_ID
    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication([])
    host = UNITIMainWindow()
    panel = host.find_replace
    changes: list[int] = []
    panel.attachedHeightChanged.connect(changes.append)
    try:
        path = tmp_path / "doc.txt"
        path.write_text("hello", encoding="utf-8")
        host.open_path(path)
        host.resize(900, 700)
        host.show()
        app.processEvents()

        panel.set_attached_height(150)
        panel.attach_to(host)
        app.processEvents()

        leaf = host.panes.leaf_for_view(FIND_REPLACE_VIEW_ID)
        branch = leaf._parent_branch
        splitter = branch.widget
        splitter.setSizes([host.panes.height() - 220, 220])
        splitter.splitterMoved.emit(0, 1)

        assert panel.attached_height == 220
        assert changes and changes[-1] == 220

        panel.detach()
        panel.attach_to(host)
        app.processEvents()

        leaf = host.panes.leaf_for_view(FIND_REPLACE_VIEW_ID)
        branch = leaf._parent_branch
        assert abs(branch.widget.sizes()[1] - 220) <= 4
    finally:
        panel.detach()
        host.close_all_documents(force=True)
        host.close()


def test_detach_clamps_a_geometry_from_a_since_removed_screen():
    """If the panel was last detached on an external monitor that has
    since been unplugged, re-detaching must not restore a position that's
    now off every connected screen."""

    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    try:
        panel.show()
        app.processEvents()
        panel._detached_geometry = (2200, 200, 820, 320)

        import uniti.ui.find_replace as find_replace_module

        original = find_replace_module.current_screen_geometries
        find_replace_module.current_screen_geometries = lambda: ((0, 0, 1920, 1080),)
        try:
            panel.detach()
        finally:
            find_replace_module.current_screen_geometries = original
        app.processEvents()

        x, y, width, height = panel._detached_geometry
        assert 0 <= x <= 1920 - width
        assert 0 <= y <= 1080 - height
    finally:
        panel.shutdown()
        panel.close()


def test_restore_state_clamps_a_geometry_from_a_since_removed_screen():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from dataclasses import replace

    from PySide6.QtWidgets import QApplication

    from uniti.ui.find_replace import FindReplacePanel

    app = QApplication.instance() or QApplication([])
    panel = FindReplacePanel(lambda: None)
    try:
        panel.show()
        app.processEvents()
        record = replace(
            panel.export_state("view-target"),
            geometry=(2200, 200, 820, 320),
        )

        import uniti.ui.find_replace as find_replace_module

        original = find_replace_module.current_screen_geometries
        find_replace_module.current_screen_geometries = lambda: ((0, 0, 1920, 1080),)
        try:
            panel.restore_state(record)
        finally:
            find_replace_module.current_screen_geometries = original
        app.processEvents()

        x, y, width, height = panel._detached_geometry
        assert 0 <= x <= 1920 - width
        assert 0 <= y <= 1080 - height
    finally:
        panel.shutdown()
        panel.close()
