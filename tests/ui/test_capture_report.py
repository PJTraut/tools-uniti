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


def test_panel_keeps_capture_delegate_in_right_report_when_attached_or_detached(app):
    from PySide6.QtCore import QRect
    from PySide6.QtWidgets import QMainWindow, QStyleOptionViewItem

    from uniti.ui.capture_report_delegate import CaptureReportDelegate
    from uniti.ui.find_replace import FindReplacePanel

    host = QMainWindow()
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
