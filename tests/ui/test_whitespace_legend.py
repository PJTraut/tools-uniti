import importlib.util
import os

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None, reason="PySide6 is not installed"
)


@pytest.fixture(scope="module")
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_mouse_wheel_scrolls_over_content_not_only_the_scrollbar(app):
    """Regression: `QWidget.wheelEvent`'s default just ignores the event --
    Qt does not forward an unhandled wheel event up to the containing
    `QScrollArea` on its own. Since every row here is a `QLabel`/glyph
    widget filling nearly the full content width, without the event-filter
    forwarding installed in `__init__`, wheel-scrolling only worked over
    the thin sliver of empty margin or the scrollbar track itself -- the
    cursor is essentially never there while reading the legend."""

    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QLabel
    from uniti.ui.whitespace_legend import WhitespaceLegendWindow, _MarkerGlyphWidget

    window = WhitespaceLegendWindow()
    try:
        window.resize(340, 200)  # smaller than content, so it can scroll
        window.show()
        app.processEvents()
        vbar = window._scroll_area.verticalScrollBar()
        assert vbar.maximum() > 0

        def wheel_over(target, dy=-120):
            local = QPointF(2, 2)
            global_pos = QPointF(target.mapToGlobal(local.toPoint()))
            event = QWheelEvent(
                local, global_pos,
                QPoint(0, 0), QPoint(0, dy),
                Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            app.sendEvent(target, event)
            app.processEvents()

        for target in (
            window.findChildren(QLabel)[3],
            window.findChildren(_MarkerGlyphWidget)[0],
        ):
            vbar.setValue(0)
            wheel_over(target)
            assert vbar.value() > 0
    finally:
        window.close()


def test_ctrl_or_cmd_wheel_zooms_instead_of_scrolling(app):
    """Regression: the wheel-forwarding fix above (redirecting every Wheel
    event to the scroll area, added to fix scroll-over-content) initially
    did so unconditionally, which meant Ctrl/Cmd+wheel always scrolled and
    never zoomed -- same modifier-gated split as
    `UNITITextView.wheelEvent`/`FindReplaceWindow._handle_zoom_wheel` is
    needed inside the event filter itself, not a separate `wheelEvent`
    override (a plain override would never even see the event, since the
    filter consumes it first for every content descendant)."""

    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QLabel
    from uniti.ui.whitespace_legend import WhitespaceLegendWindow

    window = WhitespaceLegendWindow()
    try:
        window.resize(340, 200)
        window.show()
        app.processEvents()
        vbar = window._scroll_area.verticalScrollBar()
        label = window.findChildren(QLabel)[3]

        def wheel(modifiers, dy=-120):
            local = QPointF(2, 2)
            global_pos = QPointF(label.mapToGlobal(local.toPoint()))
            event = QWheelEvent(
                local, global_pos,
                QPoint(0, 0), QPoint(0, dy),
                Qt.MouseButton.NoButton, modifiers,
                Qt.ScrollPhase.NoScrollPhase, False,
            )
            app.sendEvent(label, event)
            app.processEvents()

        for modifiers in (
            Qt.KeyboardModifier.ControlModifier,
            Qt.KeyboardModifier.MetaModifier,
        ):
            window.set_zoom_percent(100)
            vbar.setValue(0)
            wheel(modifiers)
            assert window.zoom_percent != 100
            assert vbar.value() == 0

        window.set_zoom_percent(100)
        vbar.setValue(0)
        wheel(Qt.KeyboardModifier.NoModifier)
        assert window.zoom_percent == 100
        assert vbar.value() > 0
    finally:
        window.close()


def test_zoom_shortcuts_use_widget_scoped_context_not_window_active_context(app):
    """Regression: the default `Qt.ShortcutContext.WindowShortcut` only
    fires while Qt considers this window the *active* top-level window,
    which a frameless `Tool`-flagged window doesn't reliably become on
    every platform -- `WidgetWithChildrenShortcut` ties activation to this
    widget (or a descendant) actually holding Qt-level focus instead,
    which this class already claims explicitly in `showEvent`."""

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QShortcut
    from uniti.ui.whitespace_legend import WhitespaceLegendWindow

    window = WhitespaceLegendWindow()
    try:
        shortcuts = window.findChildren(QShortcut)
        assert shortcuts
        assert all(
            shortcut.context() == Qt.ShortcutContext.WidgetWithChildrenShortcut
            for shortcut in shortcuts
        )
    finally:
        window.close()


def test_window_claims_keyboard_focus_when_shown(app):
    """Regression: every widget in this window (labels, glyphs) is
    non-focusable, so without an explicit focus policy and a
    `showEvent`-time claim, a `Tool`-flagged frameless window doesn't
    reliably become the real key/active window on some platforms
    (notably macOS) -- Ctrl+=/Ctrl+-/Ctrl+0 then keep reaching the
    editor's own zoom shortcuts underneath instead of this window's,
    even though this window is visibly on top and `isActiveWindow()`
    reports true."""

    from PySide6.QtCore import Qt
    from uniti.ui.whitespace_legend import WhitespaceLegendWindow

    window = WhitespaceLegendWindow()
    try:
        assert window.focusPolicy() == Qt.FocusPolicy.StrongFocus
        window.show()
        app.processEvents()
        assert window.hasFocus()
    finally:
        window.close()


def test_window_is_frameless_tool_window_with_no_close_button(app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton
    from uniti.ui.whitespace_legend import WhitespaceLegendWindow

    window = WhitespaceLegendWindow()
    try:
        assert window.windowFlags() & Qt.WindowType.Tool
        assert window.windowFlags() & Qt.WindowType.FramelessWindowHint
        assert window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
        assert not any(
            button.text() in {"Close", "×", "X"}
            for button in window.findChildren(QPushButton)
        )
    finally:
        window.close()


def test_every_marker_category_and_row_is_present(app):
    from PySide6.QtWidgets import QLabel
    from uniti.ui.whitespace_legend import _CATEGORIES, WhitespaceLegendWindow

    window = WhitespaceLegendWindow()
    try:
        texts = {label.text() for label in window.findChildren(QLabel)}
        expected_categories = {category for category, _rows in _CATEGORIES}
        expected_names = {
            name for _category, rows in _CATEGORIES for _kind, _label, name, _code in rows
        }
        assert expected_categories <= texts
        assert expected_names <= texts
    finally:
        window.close()


def test_glyph_colors_follow_the_active_theme(app):
    from uniti.ui.theme import active_theme, apply_theme
    from uniti.ui.whitespace import WhitespaceKind
    from uniti.ui.whitespace_legend import _MarkerGlyphWidget, WhitespaceLegendWindow

    apply_theme(app, "Dark")
    tokens = active_theme(app).editor
    window = WhitespaceLegendWindow()
    try:
        glyphs = window.findChildren(_MarkerGlyphWidget)
        assert glyphs
        by_kind = {}
        for glyph in glyphs:
            by_kind.setdefault(glyph._kind, glyph)
        assert by_kind[WhitespaceKind.SPACE]._color == tokens.space_marker
        assert by_kind[WhitespaceKind.TAB]._color == tokens.tab_marker
        assert by_kind["eol"]._color == tokens.eol_marker
        assert by_kind[WhitespaceKind.INVISIBLE]._color == tokens.invisible_marker
    finally:
        window.close()
        apply_theme(app, "System")


def test_category_headings_are_centered(app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    from uniti.ui.whitespace_legend import _CATEGORIES, WhitespaceLegendWindow

    window = WhitespaceLegendWindow()
    try:
        category_names = {category for category, _rows in _CATEGORIES}
        headings = [
            label for label in window.findChildren(QLabel) if label.text() in category_names
        ]
        assert len(headings) == len(category_names)
        assert all(
            label.alignment() & Qt.AlignmentFlag.AlignCenter for label in headings
        )
    finally:
        window.close()


def test_codepoint_column_is_left_aligned_not_right_aligned(app):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QLabel
    from uniti.ui.whitespace_legend import WhitespaceLegendWindow

    window = WhitespaceLegendWindow()
    try:
        codepoint_label = next(
            label for label in window.findChildren(QLabel) if label.text() == "U+0020"
        )
        assert codepoint_label.alignment() & Qt.AlignmentFlag.AlignLeft
        assert not codepoint_label.alignment() & Qt.AlignmentFlag.AlignRight
    finally:
        window.close()


def test_glyph_name_and_codepoint_form_proportional_table_columns(app):
    """One shared `QGridLayout` spans the *entire* table, not one per
    category, so Qt sizes every column to its widest cell across all
    rows -- every category's name/codepoint columns line up at the same
    horizontal position ("tab") the whole way down, not just within their
    own category (a per-category grid let e.g. "ORDINARY"'s unusually
    wide "U+000D U+000A" row shift only that category's own columns)."""

    from PySide6.QtWidgets import QGridLayout
    from uniti.ui.whitespace_legend import WhitespaceLegendWindow

    window = WhitespaceLegendWindow()
    try:
        window.show()
        window.resize(400, 600)
        app.processEvents()
        tables = window.findChildren(QGridLayout)
        assert len(tables) == 1
        table = tables[0]
        name_column_widths = set()
        codepoint_column_widths = set()
        for row in range(table.rowCount()):
            item0 = table.itemAtPosition(row, 0)
            item1 = table.itemAtPosition(row, 1)
            item2 = table.itemAtPosition(row, 2)
            if item0 is None or item1 is None or item2 is None:
                continue
            if item0.widget() is item1.widget():
                continue  # a spanning category-heading row, not a data row
            name_column_widths.add(item1.widget().width())
            codepoint_column_widths.add(item2.widget().width())
        # All data rows' name/codepoint cells each share exactly one
        # column width across the whole table.
        assert len(name_column_widths) <= 1
        assert len(codepoint_column_widths) <= 1
    finally:
        window.close()


def test_zoom_shortcuts_scale_font_and_glyph_size(app):
    from uniti.ui.whitespace_legend import (
        DEFAULT_ZOOM_PERCENT,
        MAX_ZOOM_PERCENT,
        MIN_ZOOM_PERCENT,
        WhitespaceLegendWindow,
    )

    window = WhitespaceLegendWindow()
    try:
        assert window.zoom_percent == DEFAULT_ZOOM_PERCENT
        base_glyph_size = window._glyphs[0].size()

        window.zoom_in()
        assert window.zoom_percent == DEFAULT_ZOOM_PERCENT + 10
        assert window._glyphs[0].size().width() > base_glyph_size.width()

        window.reset_zoom()
        assert window.zoom_percent == DEFAULT_ZOOM_PERCENT
        assert window._glyphs[0].size() == base_glyph_size

        window.set_zoom_percent(MAX_ZOOM_PERCENT + 999)
        assert window.zoom_percent == MAX_ZOOM_PERCENT
        window.set_zoom_percent(MIN_ZOOM_PERCENT - 999)
        assert window.zoom_percent == MIN_ZOOM_PERCENT
    finally:
        window.close()


def test_table_columns_widen_with_zoom(app):
    """Column widths come from Qt's own `QGridLayout` sizing (widest cell
    per column), which is driven by each `QLabel`'s font-metric-based
    `sizeHint` -- so zooming (which changes every label's font via
    `_apply_zoom_fonts`) should widen the name/codepoint columns too, not
    just the glyph boxes."""

    from PySide6.QtWidgets import QGridLayout, QLabel
    from uniti.ui.whitespace_legend import WhitespaceLegendWindow

    window = WhitespaceLegendWindow()
    try:
        window.show()
        window.resize(500, 700)
        app.processEvents()
        table = window.findChildren(QGridLayout)[0]

        def codepoint_column_width():
            for row in range(table.rowCount()):
                item = table.itemAtPosition(row, 2)
                if item is not None and isinstance(item.widget(), QLabel):
                    return table.cellRect(row, 2).width()
            raise AssertionError("no codepoint cell found")

        before = codepoint_column_width()
        window.set_zoom_percent(300)
        app.processEvents()
        after = codepoint_column_width()
        assert after > before
    finally:
        window.close()


def test_zoom_percent_persists_across_reopen(tmp_path):
    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    store = SettingsStore(tmp_path / "settings.json")
    window = UNITIMainWindow(settings_store=store)
    try:
        window.show_whitespace_legend()
        window._whitespace_legend_window.set_zoom_percent(150)
        window.show_whitespace_legend()  # close, persisting zoom

        window.show_whitespace_legend()  # reopen
        assert window._whitespace_legend_window.zoom_percent == 150
    finally:
        window.close()


def test_geometry_persists_across_reopen(tmp_path):
    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    store = SettingsStore(tmp_path / "settings.json")
    window = UNITIMainWindow(settings_store=store)
    try:
        window.show_whitespace_legend()
        window._whitespace_legend_window.setGeometry(50, 60, 300, 400)
        window.show_whitespace_legend()  # close, persisting geometry

        window.show_whitespace_legend()  # reopen
        reopened = window._whitespace_legend_window
        assert (reopened.x(), reopened.y(), reopened.width(), reopened.height()) == (
            50, 60, 300, 400,
        )
    finally:
        window.close()
