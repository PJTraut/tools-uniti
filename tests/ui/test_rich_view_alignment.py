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


def test_left_and_right_are_physical_in_either_direction():
    assert (_side(LTR, "left"), _side(LTR, "right")) == ("left", "right")
    assert (_side(RTL, "left"), _side(RTL, "right")) == ("left", "right")


def test_start_and_end_follow_the_reading_direction():
    assert (_side(LTR, "start"), _side(LTR, "end")) == ("left", "right")
    assert (_side(RTL, "start"), _side(RTL, "end")) == ("right", "left")


def test_justify_and_center_are_not_direction_dependent():
    from PySide6.QtCore import Qt

    assert block_format({"align": "justify"}).alignment() & Qt.AlignmentFlag.AlignJustify
    assert block_format({"align": "center"}).alignment() & Qt.AlignmentFlag.AlignHCenter
