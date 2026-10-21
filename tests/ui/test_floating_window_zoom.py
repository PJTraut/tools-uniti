"""BF-097: keyboard zoom in a floating (toggle) window zooms that window,
never the editor behind it."""

import os
from pathlib import Path

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

import uniti.ui.main_window as main_window


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


class _StubPicker:
    def __init__(self, candidates, *, parent=None):
        self._candidates = candidates

    def exec(self):
        return QDialog.DialogCode.Accepted

    def left_choice(self):
        return self._candidates[0]

    def right_choice(self):
        return self._candidates[1]


@pytest.fixture
def window(qapp, tmp_path: Path, monkeypatch):
    monkeypatch.setattr(main_window, "CompareDocumentPickerDialog", _StubPicker)
    first = tmp_path / "a.txt"
    second = tmp_path / "b.txt"
    first.write_text("alpha\nbeta", encoding="utf-8")
    second.write_text("alpha\nBETA", encoding="utf-8")
    win = main_window.UNITIMainWindow()
    win.show()
    assert win.open_path(first) is not None
    assert win.open_path(second) is not None
    qapp.processEvents()
    try:
        yield win
    finally:
        win.close_all_documents(force=True)
        win.close()
        qapp.processEvents()


def _zoom_shortcuts(widget):
    # Built here, not at import: a `QKeySequence` needs the application.
    zoom_keys = {
        QKeySequence(QKeySequence.StandardKey.ZoomIn),
        QKeySequence(QKeySequence.StandardKey.ZoomOut),
        QKeySequence("Ctrl+0"),
        QKeySequence("Ctrl+="),
    }
    return [
        s
        for s in widget.findChildren(QShortcut)
        if s.parent() is widget and s.key() in zoom_keys
    ]


def _assert_zooms_itself_not_the_editor(qapp, window, floating, zoom_of):
    editor_before = window.current_view.zoom_percent
    before = zoom_of(floating)

    QTest.keySequence(floating, QKeySequence(QKeySequence.StandardKey.ZoomIn))
    qapp.processEvents()
    assert zoom_of(floating) > before
    assert window.current_view.zoom_percent == editor_before

    QTest.keySequence(floating, QKeySequence(QKeySequence.StandardKey.ZoomOut))
    qapp.processEvents()
    assert zoom_of(floating) == before
    assert window.current_view.zoom_percent == editor_before

    QTest.keySequence(floating, QKeySequence("Ctrl+="))
    QTest.keySequence(floating, QKeySequence("Ctrl+0"))
    qapp.processEvents()
    assert window.current_view.zoom_percent == editor_before


def _assert_shortcuts_follow_focus_not_window_activation(floating):
    shortcuts = _zoom_shortcuts(floating)
    assert len(shortcuts) >= 4
    assert all(
        s.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut for s in shortcuts
    )
    assert floating.focusPolicy() == Qt.FocusPolicy.StrongFocus


def test_compare_keyboard_zoom_zooms_both_panes_not_the_editor(qapp, window):
    window.show_compare()
    compare = window._toggle_windows["compare"]
    qapp.processEvents()

    _assert_shortcuts_follow_focus_not_window_activation(compare)
    assert compare.isAncestorOf(qapp.focusWidget()) or qapp.focusWidget() is compare
    _assert_zooms_itself_not_the_editor(
        qapp, window, compare, lambda c: c._left_view.zoom_percent
    )
    assert compare._right_view.zoom_percent == compare._left_view.zoom_percent
    compare.close_compare()


def test_character_inspector_keyboard_zoom_zooms_itself_not_the_editor(qapp, window):
    window.current_view.select_all()
    window.show_character_inspector()
    inspector = window._toggle_windows["character_inspector"]
    qapp.processEvents()

    _assert_shortcuts_follow_focus_not_window_activation(inspector)
    assert inspector.isAncestorOf(qapp.focusWidget()) or qapp.focusWidget() is inspector
    _assert_zooms_itself_not_the_editor(
        qapp, window, inspector, lambda i: i.zoom_percent
    )
    inspector.close()


def test_character_inspector_keeps_keyboard_focus_after_refresh(qapp, window):
    window.current_view.select_all()
    window.show_character_inspector()
    inspector = window._toggle_windows["character_inspector"]
    qapp.processEvents()

    inspector.refresh("xyz", output_encoding="utf-8")
    qapp.processEvents()

    assert inspector.focusWidget() is not None
    inspector.close()


def test_whitespace_legend_keyboard_zoom_zooms_itself_not_the_editor(qapp, window):
    window.show_whitespace_legend()
    legend = window._toggle_windows["whitespace_legend"]
    qapp.processEvents()

    _assert_shortcuts_follow_focus_not_window_activation(legend)
    _assert_zooms_itself_not_the_editor(qapp, window, legend, lambda w: w.zoom_percent)
    legend.close()


def _activate(qapp, widget):
    widget.show()
    widget.raise_()
    widget.activateWindow()
    qapp.processEvents()


@pytest.mark.parametrize("which", ["character_inspector", "whitespace_legend", "compare"])
def test_view_menu_zoom_handlers_route_to_the_active_floating_window(
    qapp, window, which
):
    """On macOS the View menu's Zoom In/Out/Reset items take the key before
    any shortcut inside a floating window, so the handlers themselves must
    zoom the window you are in -- and the editor again once you are not."""

    window.current_view.select_all()
    opener = {
        "character_inspector": window.show_character_inspector,
        "whitespace_legend": window.show_whitespace_legend,
        "compare": window.show_compare,
    }[which]
    opener()
    floating = window._toggle_windows[which]
    _activate(qapp, floating)
    if qapp.activeWindow() is not floating:
        pytest.skip("this platform will not make the floating window active")

    editor = window.current_view.zoom_percent
    before = floating.zoom_percent
    window.zoom_in_editor()
    assert floating.zoom_percent > before
    assert window.current_view.zoom_percent == editor
    window.zoom_out_editor()
    assert floating.zoom_percent == before
    window.zoom_in_editor()
    window.reset_editor_zoom()
    assert floating.zoom_percent == 100
    assert window.current_view.zoom_percent == editor

    _activate(qapp, window)
    if qapp.activeWindow() is window:
        window.zoom_in_editor()
        assert window.current_view.zoom_percent > editor
        assert floating.zoom_percent == 100
    floating.close()
