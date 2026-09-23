import os

import pytest


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

PySide6 = pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QLabel, QListView

from uniti.ui.character_inspector import (
    DEFAULT_ZOOM_PERCENT,
    MAX_INSPECT_SELECTION_CHARACTERS,
    MAX_ZOOM_PERCENT,
    MIN_ZOOM_PERCENT,
    CharacterInspectorDialog,
    CharacterListModel,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_single_character_shows_the_character_inspector_form(qapp):
    dialog = CharacterInspectorDialog("A", output_encoding="utf-8")
    try:
        assert dialog.windowTitle() == "UNITI — Character Inspector"
        assert dialog.findChildren(QListView) == []
    finally:
        dialog.close()


def test_selection_list_has_one_row_per_character(qapp):
    dialog = CharacterInspectorDialog("A1", output_encoding="utf-8")
    try:
        assert dialog.windowTitle() == "UNITI — Inspect Selection"
        model = dialog._character_model
        assert isinstance(model, CharacterListModel)
        assert model.rowCount() == 2
        first = model.index(0, 0)
        assert model.data(first, CharacterListModel.CodePointRole) == "U+0041"
        assert model.data(first, CharacterListModel.NameRole) == "LATIN CAPITAL LETTER A"
        second = model.index(1, 0)
        assert model.data(second, CharacterListModel.CodePointRole) == "U+0031"
    finally:
        dialog.close()


def test_control_character_shows_its_code_point_instead_of_a_raw_glyph(qapp):
    dialog = CharacterInspectorDialog("A\tB", output_encoding="utf-8")
    try:
        model = dialog._character_model
        tab_index = model.index(1, 0)
        assert model.data(tab_index, CharacterListModel.CharRole) == "U+0009"
    finally:
        dialog.close()


def test_clicking_a_row_populates_the_detail_panel(qapp):
    dialog = CharacterInspectorDialog("Aé", output_encoding="utf-8")
    try:
        model = dialog._character_model
        # Row 0 ("A") is shown by default on open.
        assert dialog._detail_layout.rowCount() > 0

        def row_labels():
            return [
                dialog._detail_layout.itemAt(
                    row, dialog._detail_layout.ItemRole.LabelRole
                )
                .widget()
                .text()
                for row in range(dialog._detail_layout.rowCount())
            ]

        def field_value(label_text: str) -> str:
            labels = row_labels()
            row = labels.index(label_text)
            return (
                dialog._detail_layout.itemAt(
                    row, dialog._detail_layout.ItemRole.FieldRole
                )
                .widget()
                .text()
            )

        assert dialog._detail_glyph_label.text() == "A"
        assert field_value("General category") == "Lu"

        dialog._show_character_detail(model.index(1, 0))
        assert dialog._detail_glyph_label.text() == "é"
        assert field_value("Canonical combining class") == "0"
        assert field_value("Character decomposition mapping") == "U+0065 U+0301"
        assert field_value("Uppercase mapping") == "É (U+00C9)"
        assert field_value("Unicode version") == "1.1"
    finally:
        dialog.close()


def test_arrow_key_navigation_updates_the_detail_panel(qapp):
    """2026-09-20 report: mouse click works but Up/Down arrow-key
    navigation moved the list's selection highlight without updating the
    detail panel -- `clicked` only fires for a mouse click, not keyboard
    navigation; `selectionModel().currentChanged` fires for both."""

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent

    dialog = CharacterInspectorDialog("AB", output_encoding="utf-8")
    try:
        dialog.show()
        QApplication.instance().processEvents()
        assert dialog._detail_glyph_label.text() == "A"

        down = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier
        )
        QApplication.instance().sendEvent(dialog._character_list, down)
        QApplication.instance().processEvents()
        assert dialog._detail_glyph_label.text() == "B"

        up = QKeyEvent(
            QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier
        )
        QApplication.instance().sendEvent(dialog._character_list, up)
        QApplication.instance().processEvents()
        assert dialog._detail_glyph_label.text() == "A"
    finally:
        dialog.close()


def test_long_selection_is_truncated_with_a_notice(qapp):
    text = "A" * (MAX_INSPECT_SELECTION_CHARACTERS + 50)
    dialog = CharacterInspectorDialog(text, output_encoding="utf-8")
    try:
        labels = [label.text() for label in dialog.findChildren(QLabel)]
        assert any("first" in label.lower() for label in labels)
        assert dialog._character_model.rowCount() == MAX_INSPECT_SELECTION_CHARACTERS
    finally:
        dialog.close()


def test_empty_text_is_rejected(qapp):
    with pytest.raises(ValueError):
        CharacterInspectorDialog("", output_encoding="utf-8")


def test_window_has_no_minimize_or_maximize_and_stays_on_top(qapp):
    """2026-09-20 requests: styled/behaved like the Find/Replace detached
    window -- frameless (the only reliable cross-platform way to remove
    the native OS frame's rounded corners and minimize/close controls,
    since `Qt.WindowType.Tool` alone still draws them), a `Tool` window
    that stays above the editor, and no redundant in-content Close button
    (its own custom title bar's drag area plus Escape both close it)."""

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QPushButton

    dialog = CharacterInspectorDialog("A", output_encoding="utf-8")
    try:
        assert bool(dialog.windowFlags() & Qt.WindowType.Tool)
        assert bool(dialog.windowFlags() & Qt.WindowType.WindowStaysOnTopHint)
        assert bool(dialog.windowFlags() & Qt.WindowType.FramelessWindowHint)
        assert dialog.findChildren(QPushButton) == []
    finally:
        dialog.close()


def test_zoom_scales_text_and_the_large_glyph_preview_together(qapp):
    dialog = CharacterInspectorDialog("Hé", output_encoding="utf-8")
    try:
        assert dialog.zoom_percent == DEFAULT_ZOOM_PERCENT
        base_glyph_size = dialog._detail_glyph_label.font().pointSizeF()
        base_list_size = dialog._character_list.font().pointSizeF()
        # The glyph preview is meant to read as a dedicated, much larger
        # "character area" than ordinary list/detail text, not just an
        # incidental table cell (2026-09-20 report).
        assert base_glyph_size > base_list_size

        dialog.zoom_in()
        assert dialog.zoom_percent == DEFAULT_ZOOM_PERCENT + 10
        assert dialog._detail_glyph_label.font().pointSizeF() > base_glyph_size
        assert dialog._character_list.font().pointSizeF() > base_list_size

        dialog.reset_zoom()
        assert dialog.zoom_percent == DEFAULT_ZOOM_PERCENT
        assert dialog._detail_glyph_label.font().pointSizeF() == pytest.approx(
            base_glyph_size
        )

        dialog.set_zoom_percent(10_000)
        assert dialog.zoom_percent == MAX_ZOOM_PERCENT
        dialog.set_zoom_percent(-10)
        assert dialog.zoom_percent == MIN_ZOOM_PERCENT
    finally:
        dialog.close()


def test_ctrl_wheel_zooms_the_dialog(qapp):
    from PySide6.QtCore import QPoint, QPointF, Qt
    from PySide6.QtGui import QWheelEvent

    dialog = CharacterInspectorDialog("A", output_encoding="utf-8")
    try:
        assert dialog.zoom_percent == DEFAULT_ZOOM_PERCENT
        event = QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.ControlModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        dialog.wheelEvent(event)
        assert dialog.zoom_percent == DEFAULT_ZOOM_PERCENT + 10

        # A plain (no-modifier) wheel event must not zoom.
        plain_event = QWheelEvent(
            QPointF(5, 5),
            QPointF(5, 5),
            QPoint(0, 0),
            QPoint(0, 120),
            Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase,
            False,
        )
        dialog.wheelEvent(plain_event)
        assert dialog.zoom_percent == DEFAULT_ZOOM_PERCENT + 10
    finally:
        dialog.close()


def test_mapping_and_decomposition_fields_show_codepoints_not_just_glyphs(qapp):
    """2026-09-20 request: "display unicode values for UPPERCASE/TITLECASE
    and DECOMPOSITION when relevant" -- a mapping/decomposition value is
    shown alongside its U+XXXX codepoint(s), not just the resulting
    glyph(s). Covers the multi-character case too (German "ss".upper() ==
    "SS", two codepoints), and a compatibility-decomposition tag like
    "<super>", which must pass through untouched (it isn't a codepoint)."""

    from uniti.ui.character_inspector import _decomposition_or_dash, _mapping_or_dash

    assert _mapping_or_dash("é", str.upper) == "É (U+00C9)"
    assert _mapping_or_dash("ß", str.upper) == "SS (U+0053 U+0053)"
    assert _mapping_or_dash("A", str.upper) == "—"
    assert _decomposition_or_dash("é") == "U+0065 U+0301"
    assert _decomposition_or_dash("²") == "<super> U+0032"
    assert _decomposition_or_dash("A") == "—"


def test_detail_form_titles_are_left_aligned_at_a_fixed_column(qapp):
    """2026-09-20 request: title column left-aligned, not centered or the
    platform-default ragged-right alignment -- both the single-character
    form and the multi-character detail panel."""

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFormLayout

    single = CharacterInspectorDialog("A", output_encoding="utf-8")
    try:
        form = single.findChild(QFormLayout)
        alignment = form.labelAlignment()
        assert alignment & Qt.AlignmentFlag.AlignLeft
        assert not alignment & Qt.AlignmentFlag.AlignRight
        assert not alignment & Qt.AlignmentFlag.AlignHCenter
    finally:
        single.close()

    multi = CharacterInspectorDialog("AB", output_encoding="utf-8")
    try:
        alignment = multi._detail_layout.labelAlignment()
        assert alignment & Qt.AlignmentFlag.AlignLeft
        assert not alignment & Qt.AlignmentFlag.AlignRight
        assert not alignment & Qt.AlignmentFlag.AlignHCenter
    finally:
        multi.close()


def test_glyph_preview_is_a_fixed_height_centered_box_that_scales_with_zoom(qapp):
    """2026-09-20 request: the large glyph preview sits in a fixed-height
    box (3 em of its own font), centered both horizontally and vertically,
    and that height tracks zoom -- not just the font size within it."""

    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFontMetrics

    dialog = CharacterInspectorDialog("é", output_encoding="utf-8")
    try:
        label = dialog._glyph_labels[0]
        assert label.alignment() == Qt.AlignmentFlag.AlignCenter
        expected = int(QFontMetrics(label.font()).height() * 3)
        assert label.height() == expected
        assert label.minimumHeight() == label.maximumHeight() == expected

        dialog.zoom_in()
        zoomed_expected = int(QFontMetrics(label.font()).height() * 3)
        assert label.height() == zoomed_expected
        assert zoomed_expected > expected
    finally:
        dialog.close()


def test_detail_content_anchors_to_the_top_not_centered_in_extra_space(qapp):
    """2026-09-20 request: content anchors to the top of the window rather
    than spreading/centering across whatever extra height the dialog or
    splitter pane is resized to."""

    dialog = CharacterInspectorDialog("AB", output_encoding="utf-8")
    try:
        dialog.resize(800, 900)
        dialog.show()
        QApplication.instance().processEvents()
        # A trailing stretch item is what pins content to the top --
        # confirm each detail container ends with one.
        container = dialog._detail_glyph_label.parent().layout()
        last_item = container.itemAt(container.count() - 1)
        assert last_item.spacerItem() is not None
    finally:
        dialog.close()


def test_no_refresh_button_or_shortcut_without_an_on_refresh_callback(qapp):
    from PySide6.QtWidgets import QPushButton

    dialog = CharacterInspectorDialog("A", output_encoding="utf-8")
    try:
        assert dialog.findChildren(QPushButton) == []
    finally:
        dialog.close()


def test_refresh_button_appears_and_calls_the_on_refresh_callback(qapp):
    """BF-076: a Refresh control lets the user re-inspect a newer
    selection without closing/reopening the dialog. The dialog itself
    stays unaware of the live document -- clicking Refresh (or the
    button matching a click on it) must call back into the caller-
    supplied closure, which is responsible for reading the current
    selection and calling `refresh()`."""

    from PySide6.QtWidgets import QPushButton

    calls = []
    dialog = CharacterInspectorDialog(
        "A", output_encoding="utf-8", on_refresh=lambda: calls.append(True)
    )
    try:
        buttons = dialog.findChildren(QPushButton)
        assert len(buttons) == 1
        assert buttons[0].text() == "Refresh"
        buttons[0].click()
        assert calls == [True]

        dialog._request_refresh()
        assert calls == [True, True]
    finally:
        dialog.close()


def test_refresh_rebuilds_content_in_place_keeping_window_geometry_and_zoom(qapp):
    dialog = CharacterInspectorDialog("A", output_encoding="utf-8", on_refresh=lambda: None)
    try:
        dialog.setGeometry(50, 60, 500, 400)
        dialog.zoom_in()
        geometry_before = dialog.geometry()
        zoom_before = dialog.zoom_percent

        assert dialog.windowTitle() == "UNITI — Character Inspector"
        dialog.refresh("é", output_encoding="utf-8")
        assert dialog.windowTitle() == "UNITI — Character Inspector"
        assert dialog.geometry() == geometry_before
        assert dialog.zoom_percent == zoom_before
    finally:
        dialog.close()


def test_refresh_switches_between_single_character_and_selection_shapes(qapp):
    """A refresh triggered while the dialog is open must be able to
    switch shapes entirely -- e.g. a single-character selection grows
    into a multi-character one, or vice versa -- not just update values
    within the shape it opened with."""

    dialog = CharacterInspectorDialog("A", output_encoding="utf-8", on_refresh=lambda: None)
    try:
        assert dialog.windowTitle() == "UNITI — Character Inspector"
        assert dialog.findChildren(QListView) == []

        dialog.refresh("AB1", output_encoding="utf-8")
        assert dialog.windowTitle() == "UNITI — Inspect Selection"
        model = dialog._character_model
        assert isinstance(model, CharacterListModel)
        assert model.rowCount() == 3

        dialog.refresh("Z", output_encoding="utf-8")
        assert dialog.windowTitle() == "UNITI — Character Inspector"
        assert dialog.findChildren(QListView) == []
    finally:
        dialog.close()


def test_refresh_rejects_empty_text(qapp):
    dialog = CharacterInspectorDialog("A", output_encoding="utf-8", on_refresh=lambda: None)
    try:
        with pytest.raises(ValueError):
            dialog.refresh("", output_encoding="utf-8")
    finally:
        dialog.close()
