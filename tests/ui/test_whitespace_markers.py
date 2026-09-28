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


def test_compact_markers_are_distinct_and_transparent(app):
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QImage, QPainter, QColor
    from uniti.ui.whitespace_painter import paint_compact_marker

    labels = ["EMSP", "ENSP", "NBSP", "NNBSP", "THINSP", "HAIRSP", "IDSP",
        "ZWSP", "ZWNJ", "ZWJ", "WJ", "LRM", "RLM", "BOM"]
    images = []
    for label in labels:
        image = QImage(24, 32, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setPen(QColor("#ff00ff"))
        paint_compact_marker(painter, label, QRectF(4, 4, 16, 24))
        painter.end()
        assert any(image.pixelColor(x, y).alpha()
            for x in range(24) for y in range(32)), label
        assert all(image != earlier for earlier in images), label
        assert image.pixelColor(0, 0).alpha() == 0
        images.append(image)


def test_whitespace_positions_after_supplementary_character(app, tmp_path, monkeypatch):
    from PySide6.QtGui import QTextLayout
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "supplementary.txt"
    text = "\U0001f642  "
    # Keep the synthetic LF fixture byte-exact on Windows, where text mode
    # writes otherwise translate it to CRLF.
    path.write_bytes((text + "\n").encode("utf-8"))
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.set_whitespace_mode("all")
        view.resize(600, 300)
        positions = {}
        monkeypatch.setattr(view, "_paint_whitespace_marker",
            lambda painter, kind, label, x1, x2, y, **_kwargs: positions.update({label: x1}))
        try:
            view.show()
            app.processEvents()
            layout = QTextLayout(text, view.font())
            layout.beginLayout()
            line = layout.createLine()
            line.setLineWidth(600)
            layout.endLayout()
            for label, utf16_index in (("SPACE", 2), ("NBSP", 3), ("LF", 4)):
                expected = view._gutter_width + view._layout_cursor_x(line, utf16_index)
                assert positions[label] == pytest.approx(expected)
        finally:
            view.close()


@pytest.mark.parametrize("font_scale", [0.5, 1.0, 2.0, 3.0])
@pytest.mark.parametrize("device_scale", [1.0, 2.0])
def test_space_marker_alpha_centroid_is_centered(app, tmp_path, font_scale, device_scale):
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPainter
    from uniti.app.editor_state import EditorState
    from uniti.core.document import Document
    from uniti.ui.text_view import UNITITextView
    from uniti.ui.whitespace import WhitespaceKind

    path = tmp_path / "centroid.txt"
    path.write_bytes(b" ")
    with Document.open(path, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document))
        view.set_zoom_percent(int(font_scale * 100))
        # The canvas must contain the full fallback row at every zoom.
        width, height = 96, int(13.25 + view._line_height + 8)
        image = QImage(int(width * device_scale), int(height * device_scale),
            QImage.Format.Format_ARGB32)
        image.setDevicePixelRatio(device_scale)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        view._paint_whitespace_marker(painter, WhitespaceKind.SPACE, "SPACE",
            21.25, 29.75, 13.25)
        painter.end()
        total = 0.0
        x_moment = 0.0
        y_moment = 0.0
        for py in range(image.height()):
            for px in range(image.width()):
                alpha = image.pixelColor(px, py).alpha()
                total += alpha
                x_moment += alpha * (px + 0.5) / device_scale
                y_moment += alpha * (py + 0.5) / device_scale
        assert total > 0
        assert x_moment / total == pytest.approx((21.25 + 29.75) / 2, abs=0.2)
        assert y_moment / total == pytest.approx(13.25 + view._line_height / 2, abs=0.2)
        view.close()
