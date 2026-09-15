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


def _report():
    from uniti.regex.captures import (
        CaptureGroupRow,
        CaptureMatchReport,
        CapturePreview,
        CaptureReport,
        CaptureReportRequest,
    )
    from uniti.regex.results import MatchRecord

    request = CaptureReportRequest(
        pattern_generation=7,
        pattern_text="pattern",
        document_key="doc",
        revision=3,
        store_id="store",
        requested_index=8,
        match_count=100,
        matches=((8, MatchRecord(0, 3)), (9, MatchRecord(4, 7))),
    )
    long_name = "a-name-that-is-deliberately-long-enough-to-exceed-the-report-pane"
    return CaptureReport(
        request=request,
        matches=(
            CaptureMatchReport(
                index=8,
                total=100,
                groups=(
                    CaptureGroupRow(
                        1,
                        "letter",
                        "value",
                        1,
                        (CapturePreview(0, 3, "漢 字", False),),
                    ),
                    CaptureGroupRow(
                        9,
                        "empty",
                        "empty",
                        9,
                        (CapturePreview(12, 12, "", True),),
                    ),
                    CaptureGroupRow(
                        10,
                        None,
                        "value",
                        10,
                        (CapturePreview(13, 14, "x", False),),
                    ),
                    CaptureGroupRow(
                        100,
                        long_name,
                        "value",
                        100,
                        (CapturePreview(15, 16, "y", False),),
                    ),
                    CaptureGroupRow(101, "optional", "not_matched", 0, ()),
                ),
            ),
            CaptureMatchReport(
                index=9,
                total=100,
                groups=(),
                unavailable_reason="capture details unavailable",
            ),
        ),
        payload_bytes=1024,
    )


def test_capture_rows_expose_literal_labels_content_and_accessible_text(app):
    from PySide6.QtCore import Qt

    from uniti.ui.capture_report import CaptureReportModel

    model = CaptureReportModel()
    model.set_report(_report())

    assert model.rows()[0] == "Match 9 of 100"
    assert model.rows()[-2:] == (
        "Match 10 of 100",
        "capture details unavailable",
    )
    assert "─────────────────" in model.rows()

    expected = (
        (r"\1 :", "漢 字 [letter]"),
        (r"\9 :", "empty at 12 … (9 occurrences) [empty]"),
        (r"\10 :", "x … (10 occurrences)"),
        (
            r"\100 :",
            "y … (100 occurrences) "
            "[a-name-that-is-deliberately-long-enough-to-exceed-the-report-pane]",
        ),
        (r"\101 :", "not matched [optional]"),
    )
    for row_number, (label, content) in enumerate(expected, start=1):
        index = model.index(row_number, 0)
        assert model.data(index, CaptureReportModel.LabelRole) == label
        assert model.data(index, CaptureReportModel.ContentRole) == content
        assert model.data(index, Qt.ItemDataRole.DisplayRole) == f"{label} {content}"
        accessible = model.data(index, Qt.ItemDataRole.AccessibleTextRole)
        assert accessible == f"{label} {content}"

    header = model.index(0, 0)
    assert model.data(header, CaptureReportModel.LabelRole) is None
    assert model.data(header, CaptureReportModel.ContentRole) is None


def test_capture_rows_expose_their_owning_match_index_for_click_to_jump(app):
    from uniti.ui.capture_report import CaptureReportModel

    model = CaptureReportModel()
    model.set_report(_report())

    rows = model.rows()
    assert rows[0] == "Match 9 of 100"
    separator_row = rows.index("─────────────────")
    second_header_row = separator_row + 1
    assert rows[second_header_row] == "Match 10 of 100"
    unavailable_row = second_header_row + 1
    assert rows[unavailable_row] == "capture details unavailable"

    def match_index(row: int) -> int | None:
        return model.data(model.index(row, 0), CaptureReportModel.MatchIndexRole)

    assert match_index(0) == 8
    for row in range(1, separator_row):
        assert match_index(row) == 8
    assert match_index(separator_row) is None
    assert match_index(second_header_row) == 9
    assert match_index(unavailable_row) == 9


def test_replacement_preview_appends_a_row_after_the_matchs_groups(app):
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
        pattern_generation=1,
        pattern_text="pattern",
        document_key="doc",
        revision=1,
        store_id="store",
        requested_index=0,
        match_count=1,
        matches=((0, MatchRecord(0, 5)),),
    )
    report = CaptureReport(
        request=request,
        matches=(
            CaptureMatchReport(
                index=0,
                total=1,
                groups=(
                    CaptureGroupRow(
                        1, None, "value", 1, (CapturePreview(0, 5, "alpha", False),)
                    ),
                ),
                replacement_preview="omega",
            ),
        ),
        payload_bytes=0,
    )
    model = CaptureReportModel()
    model.set_report(report)

    rows = model.rows()
    assert rows == ("Match 1 of 1", r"\1 : alpha", "→ omega")
    preview_index = model.index(2, 0)
    assert model.data(preview_index, CaptureReportModel.LabelRole) == "→"
    assert model.data(preview_index, CaptureReportModel.ContentRole) == "omega"
    assert model.data(preview_index, CaptureReportModel.ContentGroupSpansRole) == ()


def test_replacement_preview_row_exposes_its_group_spans(app):
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
        pattern_generation=1,
        pattern_text="pattern",
        document_key="doc",
        revision=1,
        store_id="store",
        requested_index=0,
        match_count=1,
        matches=((0, MatchRecord(0, 5)),),
    )
    report = CaptureReport(
        request=request,
        matches=(
            CaptureMatchReport(
                index=0,
                total=1,
                groups=(
                    CaptureGroupRow(
                        1, None, "value", 1, (CapturePreview(0, 5, "alpha", False),)
                    ),
                ),
                replacement_preview="X-alpha-Y",
                replacement_preview_group_spans=((2, 7, 1),),
            ),
        ),
        payload_bytes=0,
    )
    model = CaptureReportModel()
    model.set_report(report)

    preview_index = model.index(2, 0)
    assert model.data(preview_index, CaptureReportModel.ContentGroupSpansRole) == (
        (2, 7, 1),
    )
    assert model.data(preview_index, CaptureReportModel.MatchIndexRole) == 0
    assert model.data(preview_index, CaptureReportModel.GroupNumberRole) is None


def test_capture_group_rows_expose_their_group_number_for_coloring(app):
    from uniti.ui.capture_report import CaptureReportModel

    model = CaptureReportModel()
    model.set_report(_report())

    def group_number(row: int) -> int | None:
        return model.data(model.index(row, 0), CaptureReportModel.GroupNumberRole)

    # Header row (0) carries no group number; group rows 1-5 do, in order.
    assert group_number(0) is None
    assert [group_number(row) for row in range(1, 6)] == [1, 9, 10, 100, 101]


@pytest.mark.parametrize("zoom", (50, 100, 140, 200, 300))
@pytest.mark.parametrize("pane_width", (120, 320))
def test_delegate_uses_one_bounded_content_tab_stop_at_every_zoom_and_width(
    app, zoom, pane_width
):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QListView, QStyleOptionViewItem

    from uniti.ui.capture_report import CaptureReportModel
    from uniti.ui.capture_report_delegate import CaptureReportDelegate

    model = CaptureReportModel()
    model.set_report(_report())
    view = QListView()
    view.resize(pane_width, 240)
    font = QFont(view.font())
    font.setPointSizeF(max(1.0, font.pointSizeF() * zoom / 100))
    view.setFont(font)
    delegate = CaptureReportDelegate(view)
    view.setModel(model)
    view.setItemDelegate(delegate)

    content_rects = []
    for row in range(1, 6):
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.rect = QRect(0, row * 30, pane_width, 30)
        option.font = font
        option.fontMetrics = view.fontMetrics()
        content_rects.append(delegate.content_rect(option, model.index(row, 0)))

    assert len({rect.x() for rect in content_rects}) == 1
    assert all(rect.width() >= 0 for rect in content_rects)
    assert content_rects[0].x() < pane_width
    view.close()


@pytest.mark.parametrize("zoom", (50, 100, 140, 200, 300))
@pytest.mark.parametrize("pane_width", (120, 320))
def test_label_column_never_shrinks_below_its_measured_width(app, zoom, pane_width):
    """BF-019: the label (`\\N :`) must never be clipped/elided by the
    content column competing for space — regardless of how narrow the pane
    is or how large the zoom, every row's label rect is sized to the exact
    measured label width, and every row shares the identical rect (so `\\1`
    and `\\2` never render at different x-offsets)."""

    from PySide6.QtCore import QRect
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QListView, QStyleOptionViewItem

    from uniti.ui.capture_report import CaptureReportModel
    from uniti.ui.capture_report_delegate import CaptureReportDelegate

    model = CaptureReportModel()
    model.set_report(_report())
    view = QListView()
    view.resize(pane_width, 240)
    font = QFont(view.font())
    font.setPointSizeF(max(1.0, font.pointSizeF() * zoom / 100))
    view.setFont(font)
    delegate = CaptureReportDelegate(view)
    view.setModel(model)
    view.setItemDelegate(delegate)

    label_rows = [
        row
        for row in range(model.rowCount())
        if model.data(model.index(row, 0), CaptureReportModel.LabelRole) is not None
    ]
    label_rects = []
    for row in label_rows:
        option = QStyleOptionViewItem()
        option.initFrom(view)
        option.rect = QRect(0, row * 30, pane_width, 30)
        option.font = font
        option.fontMetrics = view.fontMetrics()
        index = model.index(row, 0)
        label_rects.append((delegate.label_rect(option, index), delegate._label_width(option, model)))

    for rect, measured_width in label_rects:
        assert rect.width() == measured_width

    assert len({(rect.x(), rect.width()) for rect, _ in label_rects}) == 1
    view.close()


def test_panel_keeps_capture_delegate_in_right_report_when_attached_or_detached(app):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QStyleOptionViewItem

    from uniti.ui.capture_report_delegate import CaptureReportDelegate
    from uniti.ui.find_replace import FindReplacePanel
    from uniti.ui.main_window import UNITIMainWindow

    host = UNITIMainWindow()
    panel = FindReplacePanel(lambda: None)
    try:
        panel.capture_model.set_report(_report())
        delegate = panel.capture_view.itemDelegate()
        assert isinstance(delegate, CaptureReportDelegate)
        expected_x = None
        for placement in ("detached", "attached", "detached"):
            if placement == "attached":
                panel.attach_to(host)
            elif panel.placement != "detached":
                panel.detach()
            panel.set_report_location("Right")
            panel.resize(720, 320)
            app.processEvents()
            option = QStyleOptionViewItem()
            option.initFrom(panel.capture_view)
            option.rect = QRect(0, 0, panel.capture_view.viewport().width(), 30)
            x_positions = {
                delegate.content_rect(option, panel.capture_model.index(row, 0)).x()
                for row in range(1, 6)
            }
            assert len(x_positions) == 1
            expected_x = expected_x or next(iter(x_positions))
            assert next(iter(x_positions)) == expected_x
            assert panel.report_location == "Right"
    finally:
        panel.shutdown()
        panel.close()
        host.close()


@pytest.mark.parametrize("base_hex", ("#ffffff", "#1e1e1e"))
def test_bracket_color_is_distinct_from_every_group_color(app, base_hex):
    from PySide6.QtGui import QColor

    from uniti.ui.regex_input import bracket_color, group_palette

    base = QColor(base_hex)
    bracket = bracket_color(base)
    palette = group_palette(base)

    assert bracket.name() not in {color.name() for color in palette}


@pytest.mark.parametrize("base_hex", ("#ffffff", "#1e1e1e"))
def test_non_capturing_bracket_color_is_distinct_from_capturing_and_every_group(
    app, base_hex
):
    from PySide6.QtGui import QColor

    from uniti.ui.regex_input import (
        bracket_color,
        group_palette,
        non_capturing_bracket_color,
    )

    base = QColor(base_hex)
    capturing = bracket_color(base)
    non_capturing = non_capturing_bracket_color(base)
    palette = group_palette(base)

    assert non_capturing.name() != capturing.name()
    assert non_capturing.name() not in {color.name() for color in palette}


@pytest.mark.parametrize("base_hex", ("#ffffff", "#1e1e1e"))
def test_category_palette_colors_are_distinct_from_every_group_color_and_each_other(
    app, base_hex
):
    from PySide6.QtGui import QColor

    from uniti.ui.regex_input import category_palette, group_palette

    base = QColor(base_hex)
    categories = category_palette(base)
    group_names = {color.name() for color in group_palette(base)}

    category_names = [color.name() for color in categories.values()]
    assert not (set(category_names) & group_names)
    assert len(set(category_names)) == len(category_names)


def test_delegate_paints_replacement_preview_spans_in_their_group_colors(app):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPainter, QPalette, QPixmap
    from PySide6.QtWidgets import QListView, QStyleOptionViewItem

    from uniti.regex.captures import (
        CaptureGroupRow,
        CaptureMatchReport,
        CapturePreview,
        CaptureReport,
        CaptureReportRequest,
    )
    from uniti.regex.results import MatchRecord
    from uniti.ui.capture_report import CaptureReportModel
    from uniti.ui.capture_report_delegate import CaptureReportDelegate

    request = CaptureReportRequest(
        pattern_generation=1,
        pattern_text="p",
        document_key="d",
        revision=1,
        store_id="s",
        requested_index=0,
        match_count=1,
        matches=((0, MatchRecord(0, 1)),),
    )
    report = CaptureReport(
        request=request,
        matches=(
            CaptureMatchReport(
                index=0,
                total=1,
                groups=(
                    CaptureGroupRow(1, None, "value", 1, (CapturePreview(0, 1, "a", False),)),
                ),
                replacement_preview="AAAA",
                replacement_preview_group_spans=((0, 4, 1),),
            ),
        ),
        payload_bytes=0,
    )
    model = CaptureReportModel()
    model.set_report(report)
    view = QListView()
    view.resize(400, 200)
    delegate = CaptureReportDelegate(view)
    view.setModel(model)
    view.setItemDelegate(delegate)

    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.rect = QRect(0, 0, 400, 30)
    option.font = view.font()
    option.fontMetrics = view.fontMetrics()

    preview_row = next(
        row
        for row in range(model.rowCount())
        if model.data(model.index(row, 0), CaptureReportModel.LabelRole) == "→"
    )
    preview_index = model.index(preview_row, 0)
    content_rect = delegate.content_rect(option, preview_index)

    pixmap = QPixmap(400, 30)
    pixmap.fill(option.palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Base))
    painter = QPainter(pixmap)
    try:
        delegate.paint(painter, option, preview_index)
    finally:
        painter.end()

    base = option.palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Base)
    text_color = option.palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Text)
    # Antialiasing blends the group color with the background at glyph
    # edges, so no single pixel need equal the group color exactly — assert
    # instead that something was painted, and that it isn't the plain
    # default text color the old single-color path would have used.
    image = pixmap.toImage()
    y = content_rect.center().y()
    painted_colors = {
        image.pixelColor(x, y).name()
        for x in range(content_rect.left(), content_rect.left() + 100)
    } - {base.name()}
    assert painted_colors
    assert text_color.name() not in painted_colors
    view.close()


def test_delegate_paints_each_group_label_in_its_matching_palette_color(app):
    from PySide6.QtCore import QRect
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QListView, QStyle, QStyleOptionViewItem

    from uniti.ui.capture_report import CaptureReportModel
    from uniti.ui.capture_report_delegate import CaptureReportDelegate
    from uniti.ui.regex_input import group_palette

    model = CaptureReportModel()
    model.set_report(_report())
    view = QListView()
    view.resize(320, 240)
    delegate = CaptureReportDelegate(view)
    view.setModel(model)
    view.setItemDelegate(delegate)

    option = QStyleOptionViewItem()
    option.initFrom(view)
    option.rect = QRect(0, 30, 320, 30)
    option.font = view.font()
    option.fontMetrics = view.fontMetrics()

    base = option.palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Base)
    expected = group_palette(base)
    default = delegate._text_color(option)

    for row, expected_group in zip(range(1, 6), (1, 9, 10, 100, 101)):
        index = model.index(row, 0)
        color = delegate._label_color(option, index, default)
        assert color == expected[(expected_group - 1) % len(expected)]
        assert color != default

    separator_index = model.index(model.rows().index("─────────────────"), 0)
    assert delegate._label_color(option, separator_index, default) == default

    option.state |= QStyle.StateFlag.State_Selected
    selected_index = model.index(1, 0)
    assert delegate._label_color(option, selected_index, default) == default
    view.close()
