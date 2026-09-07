"""Bundled Lucide SVG icons rendered using the current application palette."""

from __future__ import annotations

from functools import lru_cache
from importlib.resources import files

from PySide6.QtCore import QByteArray, QRectF, QSize, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QIconEngine, QPainter, QPalette, QPixmap
from PySide6.QtSvg import QSvgRenderer


LUCIDE_ICONS = frozenset({
    "search-check",
    "replace-all",
    "chevron-left",
    "chevron-right",
    "replace",
    "x",
    "panel-right-open",
    "panel-right-close",
    "circle-stop",
})


@lru_cache(maxsize=len(LUCIDE_ICONS))
def _svg(name: str) -> bytes:
    return files("uniti.ui").joinpath("assets", "lucide", f"{name}.svg").read_bytes()


class _LucideEngine(QIconEngine):
    def __init__(self, name: str) -> None:
        super().__init__()
        self._name = name
        self._source = _svg(name)

    def clone(self) -> QIconEngine:
        return _LucideEngine(self._name)

    def isNull(self) -> bool:
        return False

    def paint(self, painter, rect, mode, state) -> None:
        pixmap = self.scaledPixmap(
            rect.size(), mode, state, painter.device().devicePixelRatioF()
        )
        painter.drawPixmap(rect, pixmap)

    def pixmap(self, size, mode, state) -> QPixmap:
        return self.scaledPixmap(size, mode, state, 1.0)

    def scaledPixmap(self, size, mode, state, scale) -> QPixmap:
        palette = QGuiApplication.palette()
        group = (
            QPalette.ColorGroup.Disabled
            if mode == QIcon.Mode.Disabled
            else QPalette.ColorGroup.Active
        )
        role = (
            QPalette.ColorRole.HighlightedText
            if mode == QIcon.Mode.Selected
            else QPalette.ColorRole.ButtonText
        )
        color = palette.color(group, role)
        pixels = QSize(round(size.width() * scale), round(size.height() * scale))
        pixmap = QPixmap(pixels)
        pixmap.setDevicePixelRatio(scale)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            rect = QRectF(0, 0, size.width(), size.height())
            renderer = QSvgRenderer(QByteArray(
                self._source.replace(b"currentColor", b"#000000")
            ))
            renderer.render(painter, rect)
            # Tint the complete silhouette so overlapping SVG strokes do not
            # accumulate opacity when the native palette uses translucent text.
            painter.setCompositionMode(
                QPainter.CompositionMode.CompositionMode_SourceIn
            )
            painter.fillRect(rect, color)
        finally:
            painter.end()
        return pixmap


def lucide_icon(name: str) -> QIcon:
    """Create a theme-aware icon from the pinned, packaged Lucide subset."""
    if name not in LUCIDE_ICONS:
        raise ValueError(f"unknown Lucide icon: {name}")
    return QIcon(_LucideEngine(name))
