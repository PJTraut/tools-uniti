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
        assert pane._left_kinds == {}
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
        assert pane._left_kinds == {1: HunkKind.REPLACE}
        assert pane._right_kinds == {1: HunkKind.REPLACE}
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
        pane._left_view.verticalScrollBar().setValue(150)
        app.processEvents()
        assert pane._right_view.verticalScrollBar().value() == 250
        pane.close_compare()
        app.processEvents()


def test_next_and_previous_hunk_jump_both_sides_to_the_hunks_own_start(
    tmp_path: Path,
):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    # Extra trailing equal lines (beyond the two hunks at lines 1 and 3)
    # give the viewport plenty of scroll headroom regardless of exact
    # font metrics -- see the resize note below.
    tail = "\n".join(f"line{i}" for i in range(20))
    left_text = f"alpha\nbeta\ngamma\ndelta\n{tail}"
    right_text = f"alpha\nBETA\ngamma\nDELTA\n{tail}"
    with _open(tmp_path / "a.txt", left_text) as left, _open(
        tmp_path / "b.txt", right_text
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        # `UNITITextView`'s vertical scrollbar range depends on its actual
        # viewport size (unlike the old `QPlainTextEdit`-backed pane,
        # whose document-derived range didn't need a real layout pass) --
        # give it one before checking scrollbar values, short enough that
        # the document doesn't fit whole (otherwise there would be
        # nothing to scroll to and every value would clamp to 0).
        pane.resize(400, 40)
        pane.show()
        app.processEvents()
        pane._go_to_hunk(1)
        first_left = pane._left_view.verticalScrollBar().value()
        first_right = pane._right_view.verticalScrollBar().value()
        pane._go_to_hunk(1)
        second_left = pane._left_view.verticalScrollBar().value()
        assert first_right == 1  # the "beta"/"BETA" hunk starts at line 1 too
        assert first_left == 1  # the "beta"/"BETA" hunk starts at line 1
        assert second_left == 3  # the "delta"/"DELTA" hunk starts at line 3
        pane._go_to_hunk(-1)
        assert pane._left_view.verticalScrollBar().value() == first_left
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


def test_apply_current_hunk_left_to_right_is_one_undo_step(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta\ngamma") as left, _open(
        tmp_path / "b.txt", "alpha\nBETA\ngamma"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert len(pane._changed) == 1
        pane._apply_current(direction="left_to_right")
        assert right.read(0, right.total_chars()) == "alpha\nbeta\ngamma"
        assert left.read(0, left.total_chars()) == "alpha\nbeta\ngamma"
        right.undo()
        assert right.read(0, right.total_chars()) == "alpha\nBETA\ngamma"
        pane.close_compare()
        app.processEvents()


def test_apply_current_hunk_right_to_left_copies_the_other_direction(
    tmp_path: Path,
):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta\ngamma") as left, _open(
        tmp_path / "b.txt", "alpha\nBETA\ngamma"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        pane._apply_current(direction="right_to_left")
        assert left.read(0, left.total_chars()) == "alpha\nBETA\ngamma"
        assert right.read(0, right.total_chars()) == "alpha\nBETA\ngamma"
        left.undo()
        assert left.read(0, left.total_chars()) == "alpha\nbeta\ngamma"
        pane.close_compare()
        app.processEvents()


def test_apply_current_defaults_to_the_first_hunk_before_navigating(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta\ngamma\ndelta") as left, _open(
        tmp_path / "b.txt", "alpha\nBETA\ngamma\nDELTA"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert len(pane._changed) == 2
        # No Previous/Next click yet -- Apply should still act on the
        # first hunk, not silently do nothing.
        pane._apply_current(direction="left_to_right")
        assert right.read(0, right.total_chars()) == "alpha\nbeta\ngamma\nDELTA"
        pane.close_compare()
        app.processEvents()


def test_apply_all_left_to_right_is_one_undo_step_for_every_hunk(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    left_text = "alpha\nbeta\ngamma\ndelta\nepsilon"
    right_text = "alpha\nBETA\ngamma\nDELTA\nEPSILON"
    with _open(tmp_path / "a.txt", left_text) as left, _open(
        tmp_path / "b.txt", right_text
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        # "delta"/"DELTA" and "epsilon"/"EPSILON" are adjacent changed
        # lines, so SequenceMatcher merges them into one replace hunk.
        assert len(pane._changed) == 2
        pane._apply_all(direction="left_to_right")
        assert right.read(0, right.total_chars()) == left_text
        right.undo()
        assert right.read(0, right.total_chars()) == right_text
        pane.close_compare()
        app.processEvents()


def test_apply_all_handles_insertions_and_deletions_not_just_replacements(
    tmp_path: Path,
):
    """Also a real regression guard: applying an insertion whose target
    line falls at the very end of a document that doesn't already end
    with a terminator used to glue the inserted line directly onto the
    existing final line with no separator at all -- confirmed directly,
    this produced "gammadelta" instead of "gamma\\ndelta" before
    `_insertion_text`'s fix. Every other insertion point sits right after
    some existing line's own terminator, so only this end-of-document case
    needed it."""

    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    left_text = "alpha\nbeta\ngamma"
    right_text = "alpha\ngamma\ndelta"  # "beta" deleted, "delta" appended
    with _open(tmp_path / "a.txt", left_text) as left, _open(
        tmp_path / "b.txt", right_text
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        pane._apply_all(direction="right_to_left")
        assert left.read(0, left.total_chars()) == right_text
        left.undo()
        assert left.read(0, left.total_chars()) == left_text
        pane.close_compare()
        app.processEvents()


def test_applying_a_hunk_updates_an_ordinary_tab_on_the_same_document(
    tmp_path: Path,
):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane
    from uniti.ui.text_view import UNITITextView
    from uniti.app.editor_state import EditorState

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta") as left, _open(
        tmp_path / "b.txt", "alpha\nBETA"
    ) as right:
        ordinary_tab = UNITITextView(EditorState(right))
        pane = ComparePane(left, "a.txt", right, "b.txt")
        pane._apply_current(direction="left_to_right")
        app.processEvents()
        assert right.read(0, right.total_chars()) == "alpha\nbeta"
        # The same shared Document backs both; undoing through the
        # ordinary tab's own document reference reverts it too.
        right.undo()
        assert right.read(0, right.total_chars()) == "alpha\nBETA"
        pane.close_compare()
        ordinary_tab.close()
        app.processEvents()


def test_document_lines_matches_documents_own_line_semantics(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import document_lines

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\r\nbeta\r\ngamma") as document:
        assert document_lines(document) == ["alpha", "beta", "gamma"]


def test_panes_are_real_read_only_editor_views_onto_the_live_documents(
    tmp_path: Path,
):
    """"Full editor parity" (BF-070 follow-up, 2026-09-18): each side is a
    genuine `UNITITextView` bound to the actual compared `Document`, not a
    bespoke widget fed a text snapshot -- so it's read-only, and it must
    already show real editor features (line numbers via its own gutter,
    for one) with no separate implementation needed here."""

    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane
    from uniti.ui.text_view import UNITITextView

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha\nbeta") as left, _open(
        tmp_path / "b.txt", "alpha\nBETA"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert isinstance(pane._left_view, UNITITextView)
        assert isinstance(pane._right_view, UNITITextView)
        assert pane._left_view.read_only is True
        assert pane._right_view.read_only is True
        assert pane._left_view.document is left
        assert pane._right_view.document is right
        pane.close_compare()
        app.processEvents()


def test_compare_is_a_standalone_top_level_window(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha") as left, _open(
        tmp_path / "b.txt", "beta"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert pane.isWindow()
        pane.close_compare()
        app.processEvents()


def test_zoom_stays_in_sync_between_the_two_panes(tmp_path: Path):
    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "alpha") as left, _open(
        tmp_path / "b.txt", "beta"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert pane._left_view.zoom_percent == pane._right_view.zoom_percent == 100

        pane._left_view.zoom_in()
        assert pane._right_view.zoom_percent == pane._left_view.zoom_percent

        pane._right_view.zoom_out()
        pane._right_view.zoom_out()
        assert pane._left_view.zoom_percent == pane._right_view.zoom_percent
        pane.close_compare()
        app.processEvents()


def test_moving_the_cursor_marks_the_corresponding_line_on_the_other_side(
    tmp_path: Path,
):
    """2026-09-18 follow-up: the current-cursor line in either pane should
    highlight the corresponding mapped line in the *other* pane."""

    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    left_text = "\n".join(f"left {i}" for i in range(10))
    # 3 extra lines inserted before line 5 push every later right-side
    # line 3 ahead of its left-side counterpart.
    right_text = "\n".join(
        [f"left {i}" for i in range(5)]
        + ["inserted 0", "inserted 1", "inserted 2"]
        + [f"left {i}" for i in range(5, 10)]
    )
    with _open(tmp_path / "a.txt", left_text) as left, _open(
        tmp_path / "b.txt", right_text
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert pane._right_marker_line is None

        pane._left_view.state.move_to(left.line_start(7))
        pane._left_view._state_changed()
        assert pane._right_marker_line == 10  # line 7 + the 3-line insertion

        pane._right_view.state.move_to(right.line_start(2))
        pane._right_view._state_changed()
        assert pane._left_marker_line == 2  # before the insertion, still aligned
        pane.close_compare()
        app.processEvents()


def test_apply_view_defaults_matches_an_ordinary_editor_tabs_appearance(
    tmp_path: Path,
):
    """Regression guard, reported 2026-09-18 after the "full editor
    parity" rework shipped: the panes were still plain, unstyled text --
    no whitespace markers, no syntax highlighting -- because they're built
    directly rather than through `UNITIMainWindow._add_document`, which is
    what normally seeds a new view from the current settings."""

    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.core.syntax_profiles import MARKDOWN
    from uniti.ui.compare_pane import ComparePane
    from uniti.ui.whitespace import WhitespaceMode

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.md", "# alpha") as left, _open(
        tmp_path / "b.md", "# beta"
    ) as right:
        pane = ComparePane(left, "a.md", right, "b.md")
        assert pane._left_view.whitespace_mode is WhitespaceMode.OFF
        assert pane._left_view.syntax_profile is not MARKDOWN

        pane.apply_view_defaults(
            whitespace_mode="all", tab_width=8, syntax_extension_overrides={}
        )

        for view in (pane._left_view, pane._right_view):
            assert view.whitespace_mode is WhitespaceMode.ALL
            assert view.tab_width == 8
            assert view.syntax_profile is MARKDOWN
        pane.close_compare()
        app.processEvents()


def test_a_changed_line_highlights_only_the_differing_character_span(
    tmp_path: Path,
):
    """2026-09-18 follow-up, reported after native use: a single-character
    change ("cat" -> "fat") should highlight just the differing character
    on each side, layered on top of the existing whole-line REPLACE tint,
    not leave the line looking uniformly (and unhelpfully) colored."""

    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane, _INTRA_LINE_CHANGE_COLOR

    app = QApplication.instance() or QApplication([])
    with _open(tmp_path / "a.txt", "cat") as left, _open(
        tmp_path / "b.txt", "fat"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert pane._left_char_spans == {0: ((0, 1, _INTRA_LINE_CHANGE_COLOR),)}
        assert pane._right_char_spans == {0: ((0, 1, _INTRA_LINE_CHANGE_COLOR),)}
        assert pane._left_view._line_span_highlights == pane._left_char_spans
        assert pane._right_view._line_span_highlights == pane._right_char_spans
        pane.close_compare()
        app.processEvents()


def test_char_diff_spans_pairs_replace_hunk_lines_up_to_the_shorter_side(
    tmp_path: Path,
):
    """An `INSERT`/`DELETE` hunk has no counterpart line to diff
    character-by-character, and a `REPLACE` hunk with unequal side
    lengths only pairs lines up to the shorter side -- both stay
    whole-line-only beyond that, per `_char_diff_spans`'s own docstring."""

    _require_qt()
    from PySide6.QtWidgets import QApplication

    from uniti.ui.compare_pane import ComparePane

    app = QApplication.instance() or QApplication([])
    # "delta" anchors the matcher so "gamma"/"GAMMA" is its own one-line
    # REPLACE hunk, separate from "epsilon"'s pure insertion after it.
    with _open(tmp_path / "a.txt", "alpha\ngamma\ndelta") as left, _open(
        tmp_path / "b.txt", "alpha\nGAMMA\ndelta\nepsilon"
    ) as right:
        pane = ComparePane(left, "a.txt", right, "b.txt")
        assert 3 not in pane._right_char_spans  # "epsilon", pure insertion
        assert 1 in pane._right_char_spans  # "GAMMA", paired with "gamma"
        assert 1 in pane._left_char_spans  # "gamma", paired with "GAMMA"
        pane.close_compare()
        app.processEvents()
