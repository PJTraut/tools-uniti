"""Aligned, bounded painting for capture-report group rows."""

from __future__ import annotations

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPalette, QFont, QFontMetrics
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate

from uniti.ui.capture_report import CaptureReportModel
from uniti.ui.font_policy import resolve_editor_font
from uniti.ui.regex_input import group_palette
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
        """Return the shared preview rectangle for a data-row style option.

        The label column always keeps its full measured width (`label_rect`,
        below, is sized identically); only the content preview shrinks when
        space is tight, since the label identifies which capture group a row
        belongs to and must never be the one that gets clipped.
        """

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

    def label_rect(self, option, index) -> QRect:
        """Return the shared label rectangle, sized to its full measured width."""

        bounds = self._text_bounds(option)
        width = min(self._label_width(option, index.model()), bounds.width())
        return QRect(bounds.left(), bounds.top(), width, bounds.height())

    @staticmethod
    def _text_color(option) -> QColor:
        group = (
            QPalette.ColorGroup.Disabled
            if not option.state & QStyle.StateFlag.State_Enabled
            else QPalette.ColorGroup.Normal
        )
        role = (
            QPalette.ColorRole.HighlightedText
            if option.state & QStyle.StateFlag.State_Selected
            else QPalette.ColorRole.Text
        )
        return option.palette.color(group, role)

    @staticmethod
    def _label_color(option, index, default: QColor) -> QColor:
        """The label's own capture-group color, matching the Find input's
        highlighter — unless the row is selected, where the normal
        selection text color takes priority for legibility."""

        if option.state & QStyle.StateFlag.State_Selected:
            return default
        group_number = index.data(CaptureReportModel.GroupNumberRole)
        if not isinstance(group_number, int):
            return default
        base = option.palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Base)
        palette_colors = group_palette(base)
        return palette_colors[(group_number - 1) % len(palette_colors)]

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

        content_rect = self.content_rect(styled, index)
        label_rect = self.label_rect(styled, index)
        text_color = self._text_color(styled)
        label_color = self._label_color(styled, index, text_color)
        painter.save()
        try:
            painter.setFont(styled.font)
            painter.setPen(label_color)
            vertical = Qt.AlignmentFlag.AlignVCenter | Qt.TextFlag.TextSingleLine
            painter.drawText(
                label_rect,
                vertical | Qt.AlignmentFlag.AlignRight,
                styled.fontMetrics.elidedText(
                    label, Qt.TextElideMode.ElideRight, label_rect.width()
                ),
            )
            painter.setPen(text_color)
            spans = index.data(CaptureReportModel.ContentGroupSpansRole) or ()
            painted = spans and self._paint_content_group_spans(
                painter, styled, content_rect, content, spans, text_color, vertical
            )
            if not painted:
                painter.drawText(
                    content_rect,
                    vertical | Qt.AlignmentFlag.AlignLeft,
                    styled.fontMetrics.elidedText(
                        content, Qt.TextElideMode.ElideRight, content_rect.width()
                    ),
                )
        finally:
            painter.restore()

    def _paint_content_group_spans(
        self, painter, option, content_rect, content, spans, base_color, vertical
    ) -> bool:
        """Paint `content` with each `spans` range in its group's own color
        (BF-052 item 5) — a replacement preview's substituted text should
        read like the pattern it came from. Only handles the common case
        where the full text fits without eliding; falls back to the
        existing plain single-color path otherwise, rather than tracking
        elided-text span remapping.
        """

        metrics = option.fontMetrics
        if metrics.horizontalAdvance(content) > content_rect.width():
            return False
        base = option.palette.color(QPalette.ColorGroup.Normal, QPalette.ColorRole.Base)
        palette_colors = group_palette(base)
        x = float(content_rect.left())
        cursor = 0
        for start, end, group_number in sorted(spans):
            start = max(cursor, min(len(content), start))
            end = max(start, min(len(content), end))
            if start > cursor:
                x = self._draw_content_segment(
                    painter, content_rect, vertical, x, content[cursor:start], base_color, metrics
                )
            if end > start:
                color = palette_colors[(group_number - 1) % len(palette_colors)]
                x = self._draw_content_segment(
                    painter, content_rect, vertical, x, content[start:end], color, metrics
                )
            cursor = end
        if cursor < len(content):
            self._draw_content_segment(
                painter, content_rect, vertical, x, content[cursor:], base_color, metrics
            )
        return True

    @staticmethod
    def _draw_content_segment(painter, content_rect, vertical, x, text, color, metrics) -> float:
        if not text:
            return x
        painter.setPen(color)
        painter.drawText(
            QRect(int(x), content_rect.top(), content_rect.width(), content_rect.height()),
            vertical | Qt.AlignmentFlag.AlignLeft,
            text,
        )
        return x + metrics.horizontalAdvance(text)
