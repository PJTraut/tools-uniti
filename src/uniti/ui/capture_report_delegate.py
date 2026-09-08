"""Aligned, bounded painting for capture-report group rows."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QPalette, QFont, QFontMetrics
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate

from uniti.ui.capture_report import CaptureReportModel
from uniti.ui.font_policy import resolve_editor_font
from uniti.ui.text_layout import ShapedWindow


class CaptureReportDelegate(QStyledItemDelegate):
    """Paint every capture preview after one measured label-column tab stop."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._width_cache_key: tuple[int, int, str] | None = None
        self._cached_label_width = 0

    @staticmethod
    def _fallback_font(font):
        result = QFont(font)
        result.setFamilies(
            list(dict.fromkeys([font.family(), *resolve_editor_font().font.families()]))
        )
        return result

    def sizeHint(self, option, index):
        result = super().sizeHint(option, index)
        font = self._fallback_font(option.font)
        text = str(index.data() or "")[:8192]
        shaped = ShapedWindow(text, font)
        result.setHeight(
            max(
                result.height(),
                int(max((line.height() for line in shaped.lines), default=0)) + 4,
            )
        )
        return result

    def _label_width(self, option, model) -> int:
        cache_key = (
            id(model),
            getattr(model, "layout_revision", -1),
            option.font.key(),
        )
        if cache_key != self._width_cache_key:
            self._cached_label_width = max(
                (
                    option.fontMetrics.horizontalAdvance(
                        model.data(model.index(row, 0), CaptureReportModel.LabelRole)
                    )
                    for row in range(model.rowCount())
                    if model.data(model.index(row, 0), CaptureReportModel.LabelRole)
                    is not None
                ),
                default=0,
            )
            self._width_cache_key = cache_key
        return self._cached_label_width

    @staticmethod
    def _text_bounds(option) -> QRect:
        style = (
            option.widget.style() if option.widget is not None else QApplication.style()
        )
        margin = style.pixelMetric(
            QStyle.PixelMetric.PM_FocusFrameHMargin,
            None,
            option.widget,
        )
        return option.rect.adjusted(margin + 1, 0, -(margin + 1), 0)

    def content_rect(self, option, index) -> QRect:
        """Return the shared preview rectangle for a data-row style option."""

        bounds = self._text_bounds(option)
        gap = option.fontMetrics.horizontalAdvance("    ")
        natural_x = bounds.left() + self._label_width(option, index.model()) + gap
        reserved_content = max(1, option.fontMetrics.averageCharWidth())
        content_x = min(
            natural_x,
            max(bounds.left(), bounds.right() - reserved_content),
        )
        return QRect(
            content_x,
            bounds.top(),
            max(0, bounds.right() - content_x + 1),
            bounds.height(),
        )

    def paint(self, painter, option, index) -> None:
        label = index.data(CaptureReportModel.LabelRole)
        content = index.data(CaptureReportModel.ContentRole)
        if label is None or content is None:
            super().paint(painter, option, index)
            return

        styled = option.__class__(option)
        self.initStyleOption(styled, index)
        styled.font = self._fallback_font(styled.font)
        styled.fontMetrics = QFontMetrics(styled.font)
        styled.text = ""
        style = (
            styled.widget.style() if styled.widget is not None else QApplication.style()
        )
        style.drawControl(
            QStyle.ControlElement.CE_ItemViewItem,
            styled,
            painter,
            styled.widget,
        )

        bounds = self._text_bounds(styled)
        content_rect = self.content_rect(styled, index)
        gap = styled.fontMetrics.horizontalAdvance("    ")
        label_rect = QRect(
            bounds.left(),
            bounds.top(),
            max(0, content_rect.left() - gap - bounds.left()),
            bounds.height(),
        )
        group = (
            QPalette.ColorGroup.Disabled
            if not styled.state & QStyle.StateFlag.State_Enabled
            else QPalette.ColorGroup.Normal
        )
        role = (
            QPalette.ColorRole.HighlightedText
            if styled.state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text
        )
        painter.save()
        try:
            painter.setFont(styled.font)
            painter.setPen(styled.palette.color(group, role))
            vertical = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine
            painter.drawText(
                label_rect,
                vertical | Qt.AlignmentFlag.AlignRight,
                styled.fontMetrics.elidedText(
                    label, Qt.TextElideMode.ElideRight, label_rect.width()
                ),
            )
            painter.drawText(
                content_rect,
                vertical | Qt.AlignmentFlag.AlignLeft,
                styled.fontMetrics.elidedText(
                    content, Qt.TextElideMode.ElideRight, content_rect.width()
                ),
            )
        finally:
            painter.restore()
