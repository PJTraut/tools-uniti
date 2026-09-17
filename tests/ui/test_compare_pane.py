"""BF-070 Phase 1: the Compare surface itself (diff highlighting, scroll
sync, hunk navigation, staleness recompute, and closing). Menu-driven
picker integration lives in `tests/ui/test_main_window_contract.py`."""

import importlib.util
import os
from pathlib import Path

import pytest


def _require_qt():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def _open(path: Path, text: str):
    from uniti.core.document import Document

    path.write_text(text, encoding="utf-8", newline="")
    return Document.open(path, encoding="utf-8")


def test_identical_documents_show_no_changes(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta\ngamma") as left, _open(
        tmp_path / "b.txt", "alpha\nbeta\ngamma"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert pane._changed == ()
        assert pane._left_edit._line_kinds == {}
        assert pane._status_label.text() == "0 changes"
        pane.close_compare()
        app.processEvents()


def test_a_changed_line_is_highlighted_on_both_sides(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.core.text_diff import HunkKind
    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta\ngamma") as left, _open(
        tmp_path / "b.txt", "alpha\nBETA\ngamma"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert len(pane._changed) == 1
        assert pane._left_edit._line_kinds == {1: HunkKind.REPLACE}
        assert pane._right_edit._line_kinds == {1: HunkKind.REPLACE}
        assert pane._status_label.text() == "1 change"
        pane.close_compare()
        app.processEvents()


def test_scrolling_the_left_pane_moves_the_right_pane_by_the_alignment_mapping(
    tmp_path: Path,
):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    left_text = "\n".join(f"left {i}" for i in range(200))
    # 100 extra lines inserted in the middle push every later right-side
    # line 100 ahead of its left-side counterpart.
    right_text = "\n".join(
        [f"left {i}" for i in range(100)]
        + [f"inserted {i}" for i in range(100)]
        + [f"left {i}" for i in range(100, 200)]
    )
    with _open(tmp_path / "a.txt", left_text) as left, _open(
        tmp_path / "b.txt", right_text
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        pane.resize(400, 200)
        pane.show()
        app.processEvents()
        pane._left_edit.verticalScrollBar().setValue(150)
        app.processEvents()
        assert pane._right_edit.verticalScrollBar().value() == 250
        pane.close_compare()
        app.processEvents()


def test_next_and_previous_hunk_jump_both_sides_to_the_hunks_own_start(
    tmp_path: Path,
):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    left_text = "alpha\nbeta\ngamma\ndelta"
    right_text = "alpha\nBETA\ngamma\nDELTA"
    with _open(tmp_path / "a.txt", left_text) as left, _open(
        tmp_path / "b.txt", right_text
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        pane._go_to_hunk(1)
        first_left = pane._left_edit.verticalScrollBar().value()
        first_right = pane._right_edit.verticalScrollBar().value()
        pane._go_to_hunk(1)
        second_left = pane._left_edit.verticalScrollBar().value()
        assert first_right == 1  # the "beta"/"BETA" hunk starts at line 1 too
        assert first_left == 1  # the "beta"/"BETA" hunk starts at line 1
        assert second_left == 3  # the "delta"/"DELTA" hunk starts at line 3
        pane._go_to_hunk(-1)
        assert pane._left_edit.verticalScrollBar().value() == first_left
        pane.close_compare()
        app.processEvents()


def test_editing_a_compared_document_recomputes_the_diff(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta") as left, _open(
        tmp_path / "b.txt", "alpha\nbeta"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert pane._changed == ()
        left.replace(6, 10, "BETA")
        deadline_events = 0
        while pane._changed == () and deadline_events < 50:
            app.processEvents()
            deadline_events += 1
        assert len(pane._changed) == 1
        pane.close_compare()
        app.processEvents()


def test_closing_the_pane_stops_further_recompute(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta") as left, _open(
        tmp_path / "b.txt", "alpha\nbeta"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        pane.close_compare()
        app.processEvents()
        left.replace(6, 10, "BETA")
        app.processEvents()
        # No crash, and the pane's cached diff is simply left stale rather
        # than recomputed after closing — see the module docstring.
        assert pane._changed == ()


def test_too_large_a_document_is_reported_instead_of_diffed(
    tmp_path: Path, monkeypatch
):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    import uniti.ui.compare_pane as compare_pane

    monkeypatch.setattr(compare_pane, "MAX_COMPARE_CHARS", 4)
    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta") as left, _open(
        tmp_path / "b.txt", "alpha\nbeta"
    ) as right:
        pane = compare_pane.ComparePane(left, "a.txt", right, "b.txt")
        assert "too large" in pane._status_label.text().lower()
        pane.close_compare()
        app.processEvents()


def test_document_lines_matches_documents_own_line_semantics(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import document_lines

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\r\nbeta\r\ngamma") as document:
        assert document_lines(document) == ["alpha", "beta", "gamma"]
