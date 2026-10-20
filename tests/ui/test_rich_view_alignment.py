"""`\\Justification` values in the rich views (plan 2026-10-15-usfm-hyphenation-and-spelling-followups, J1)."""

from __future__ import annotations

import importlib.util
import os

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF  # noqa: E402
from PySide6.QtGui import QColor, QImage, QPainter, QTextCursor, QTextDocument  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from uniti.ui.rich_view import block_format  # noqa: E402

_APP = QApplication.instance() or QApplication([])
_WIDTH = 300
LTR, RTL = "shalom", "שלום"


def _side(text: str, align: str) -> str:
    """Which edge the painted text sits against: "left" or "right"."""

    document = QTextDocument()
    document.setTextWidth(_WIDTH)
    document.setPlainText(text)
    cursor = QTextCursor(document)
    cursor.select(QTextCursor.SelectionType.Document)
    cursor.setBlockFormat(block_format({"align": align}))
    image = QImage(_WIDTH, 40, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    document.drawContents(painter, QRectF(0, 0, _WIDTH, 40))
    painter.end()
    xs = [x for x in range(_WIDTH) for y in range(40) if image.pixelColor(x, y).lightness() < 128]
    assert xs
    return "left" if min(xs) < _WIDTH - max(xs) else "right"


def test_left_and_right_are_the_start_and_end_edges():
    """Logical, as in PTXprint (text direction plan W-D1, point 13)."""

    assert (_side(LTR, "left"), _side(LTR, "right")) == ("left", "right")
    assert (_side(RTL, "left"), _side(RTL, "right")) == ("right", "left")


def test_margins_are_start_and_end_side():
    inch = 96.0
    attrs = {"left_margin": "1", "right_margin": "0.25"}
    ltr = block_format({**attrs, "direction": "ltr"})
    assert (ltr.leftMargin(), ltr.rightMargin()) == (inch, inch / 4)
    for rtl in (block_format({**attrs, "direction": "rtl"}), block_format(attrs, right_to_left=True)):
        assert (rtl.leftMargin(), rtl.rightMargin()) == (inch / 4, inch)
    # A given direction wins over the guess; one margin still sets both.
    assert block_format({**attrs, "direction": "ltr"}, right_to_left=True).leftMargin() == inch
    assert (block_format({"left_margin": "1", "direction": "rtl"}).rightMargin()) == inch


def test_start_and_end_follow_the_reading_direction():
    assert (_side(LTR, "start"), _side(LTR, "end")) == ("left", "right")
    assert (_side(RTL, "start"), _side(RTL, "end")) == ("right", "left")


def test_justify_and_center_are_not_direction_dependent():
    from PySide6.QtCore import Qt

    assert block_format({"align": "justify"}).alignment() & Qt.AlignmentFlag.AlignJustify
    assert block_format({"align": "center"}).alignment() & Qt.AlignmentFlag.AlignHCenter


# --- the stock usfm.sty in a right-to-left book (text direction plan W3) -----------

_PAGE = 480
_INCH = 96.0
HEB_WORDS = " ".join(["שלום", "עולם", "אור", "מים"] * 12)
LAT_WORDS = " ".join(["peace", "world", "light", "water"] * 12)


def _gaps(source: str, direction: str | None) -> dict[str, list[tuple[float, float]]]:
    """Per paragraph marker, per painted line: (gap at the left edge, gap at
    the right edge) of its ink, in inches, in the stock stylesheet's Preview."""

    from PySide6.QtGui import QFont, QPalette

    from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry, build_layers
    from uniti.core.environments.sfm.usfm_baseline import load_usfm_baseline
    from uniti.core.environments.sfm.views import SfmPreviewView
    from uniti.ui.rich_view import RichPalette, render_projection

    styles = LayeredStyleRegistry(build_layers(load_usfm_baseline(), None))
    projection = SfmPreviewView(lambda: styles).project_with(source, direction=direction)
    document = QTextDocument()
    document.setDocumentMargin(0)
    render_projection(document, projection, QFont(), RichPalette.from_widget_palette(QPalette()))
    document.setTextWidth(_PAGE)
    height = int(document.size().height()) + 2
    image = QImage(_PAGE, height, QImage.Format.Format_RGB32)
    image.fill(QColor("white"))
    painter = QPainter(image)
    document.drawContents(painter, QRectF(0, 0, _PAGE, height))
    painter.end()
    markers = {block.view_start: block.marker for block in projection.blocks}
    result: dict[str, list[tuple[float, float]]] = {}
    block = document.begin()
    while block.isValid():
        marker = markers.get(block.position())
        layout, top = block.layout(), document.documentLayout().blockBoundingRect(block).top()
        for index in range(layout.lineCount() if marker else 0):
            line = layout.lineAt(index)
            y0, y1 = int(top + line.y()), int(top + line.y() + line.height())
            xs = [x for x in range(_PAGE) for y in range(y0, min(y1, height)) if image.pixelColor(x, y).lightness() < 128]
            if xs:
                result.setdefault(marker, []).append((min(xs) / _INCH, (_PAGE - 1 - max(xs)) / _INCH))
        block = block.next()
    return result


def _near(value: float, expected: float) -> bool:
    return abs(value - expected) < 0.06  # glyph side bearings


@pytest.mark.parametrize("direction", ["rtl", None])
def test_stock_styles_mirror_in_a_right_to_left_book(direction):
    """\\q1's hanging indent is on the start side, \\qr on the end edge and
    \\s3 on the start edge — with the project's direction, or with none
    (Qt's guess from the Hebrew text)."""

    gaps = _gaps(f"\\c 1\n\\q1 {HEB_WORDS}\n\\qr שלום\n\\s3 שלום\n\\p שלום\n", direction)
    first, *rest = gaps["q1"]
    assert rest
    assert _near(first[1], 0.25)  # 0.75" margin, -0.5" first line, on the right
    assert all(_near(line[1], 0.75) for line in rest)
    assert gaps["qr"][0][1] > 3 and _near(gaps["qr"][0][0], 0)
    assert _near(gaps["s3"][0][1], 0) and gaps["s3"][0][0] > 3


def test_stock_styles_are_unchanged_in_a_left_to_right_book():
    gaps = _gaps(f"\\c 1\n\\q1 {LAT_WORDS}\n\\qr peace\n\\s3 peace\n\\p peace\n", None)
    first, *rest = gaps["q1"]
    assert rest
    assert _near(first[0], 0.25)
    assert all(_near(line[0], 0.75) for line in rest)
    assert gaps["qr"][0][0] > 3 and _near(gaps["qr"][0][1], 0)
    assert _near(gaps["s3"][0][0], 0) and gaps["s3"][0][1] > 3


def test_a_latin_led_paragraph_without_a_direction_keeps_its_margins():
    gaps = _gaps(f"\\c 1\n\\q1 Paul {HEB_WORDS}\n", None)
    first, *rest = gaps["q1"]
    assert _near(first[0], 0.25) and all(_near(line[0], 0.75) for line in rest)
