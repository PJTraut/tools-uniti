"""N39-N41: backslash markers in right-to-left lines of the plain Text view."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from uniti.core.bidi import is_rtl_paragraph
from uniti.ui.text_layout import LRM, RLM, ShapedWindow, direction_for_text

RTL = Qt.LayoutDirection.RightToLeft
LINE = "\\v 1 در ابتدا \\f + \\ft یادداشت\\f* کلمه"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_a_marker_led_persian_line_reads_right_to_left(qapp):
    assert is_rtl_paragraph(LINE)
    assert direction_for_text(LINE) == RTL
    assert not is_rtl_paragraph("\\c 1")  # no letters: left to right
    assert not is_rtl_paragraph("\\v 1 In the beginning")
    assert is_rtl_paragraph("در ابتدا")  # unchanged


def test_each_marker_and_range_is_isolated_in_a_right_to_left_layout_only(qapp):
    shape = ShapedWindow(LINE, QFont(), direction=RTL)
    assert shape.layout.text().count(RLM) == 8 and shape.layout.text().count(LRM) == 8  # \\v, \\f, \\ft, \\f*
    assert LRM not in ShapedWindow(LINE, QFont()).layout.text()
    assert LRM not in ShapedWindow("در ابتدا", QFont(), direction=RTL).layout.text()
    ranged = ShapedWindow("\\xt 2:3\u20135 \u06f1\u06f2-\u06f4\\xt*", QFont(), direction=RTL).layout.text()
    assert ranged.count(RLM) == 8  # \\xt, the range, the Persian-digit range, \\xt*
    assert f"{RLM}{LRM}2:3\u20135{LRM}{RLM}" in ranged


def test_the_isolates_change_no_text_position(qapp):
    for line in (LINE, "\\xt 2:3\u20135 در\\xt*"):
        shape = ShapedWindow(line, QFont(), direction=RTL)
        assert shape.row_span() == (0, len(line))
        for cp in range(len(line) + 1):
            assert shape._text_cp(shape._display_cp(cp)) == cp
            assert shape.mapping.u16_to_cp(shape.unit_for_cp(cp)) == shape._display_cp(cp)
    shape = ShapedWindow(LINE, QFont(), direction=RTL)
    for cp in (LINE.index("ابتدا"), LINE.index("کلمه")):
        assert shape.cp_for_x(shape.x_for_cp(cp)) == cp  # a click on a character lands on it


def test_the_number_sits_left_of_its_tag_and_a_range_keeps_its_order(qapp):
    """`\\c 1` drew as `c 1\\`; now the tag reads `\\c` at the right with the
    number left of it. A range such as `2:3\u20135` read backwards."""

    shape = ShapedWindow("\\c 1", QFont(), direction=RTL)
    backslash, c, number = shape.x_for_cp(0), shape.x_for_cp(1), shape.x_for_cp(3)
    assert backslash < c  # the tag itself reads left to right
    assert number < backslash  # ...and the number is on its left

    text = "در 2:3\u20135 در"
    ranged = ShapedWindow(text, QFont(), direction=RTL)
    start = text.index("2")
    digits = [ranged.x_for_cp(start + i) for i in range(5)]
    assert digits == sorted(digits)  # 2 : 3 \u2013 5 run left to right


def test_a_tag_only_line_takes_the_books_direction(qapp):
    assert direction_for_text("\\p") == Qt.LayoutDirection.LeftToRight
    assert direction_for_text("\\p", RTL) == RTL
    assert direction_for_text("\\c 1", RTL) == RTL
    assert direction_for_text("\\rem Latin note", RTL) == Qt.LayoutDirection.LeftToRight  # its own letters decide


def test_a_closing_marker_keeps_its_asterisk_on_its_right(qapp):
    """`(\\xt 12:15\\xt*)` showed `\\xt` and `*` apart with the numbers
    scrambled between them."""

    from PySide6.QtGui import QTextLine

    text = "(\\xt 12:15\\xt*)"
    shape = ShapedWindow(text, QFont(), direction=RTL, align_width_px=400)
    line = shape.lines[0]

    def left(cp):
        edges = [line.cursorToX(shape.unit_for_cp(cp), edge) for edge in (QTextLine.Edge.Leading, QTextLine.Edge.Trailing)]
        return min(e[0] if isinstance(e, tuple) else e for e in edges)

    closer = text.index("\\xt*")
    xs = [left(closer + i) for i in range(4)]  # \, x, t, *
    assert xs == sorted(xs)  # the closing tag reads \xt* left to right
    assert left(text.index("12")) > left(closer + 3)  # the range is to the right of the closer's end


def test_a_number_before_a_closing_marker_is_not_merged_into_it(qapp):
    """`(\\xt \u06f2\u062a\u0648\u0627\u0631\u06cc\u062e \u06f7\u200f:\u06f1\u06f4\\xt*)`: the verse digits and the closer are both
    left to right at one level, so Qt joined them and put the closer between `\u06f7:`
    and `\u06f1\u06f4`. The number stays together, to the right of the closer."""

    from PySide6.QtGui import QTextLine

    text = "(\\xt \u06f2\u062a\u0648\u0627\u0631\u06cc\u062e \u06f7\u200f:\u06f1\u06f4\\xt*)"
    shape = ShapedWindow(text, QFont(), direction=RTL, align_width_px=600)
    line = shape.lines[0]

    def span(cp):
        edges = [line.cursorToX(shape.unit_for_cp(cp), e) for e in (QTextLine.Edge.Leading, QTextLine.Edge.Trailing)]
        edges = [e[0] if isinstance(e, tuple) else e for e in edges]
        return min(edges), max(edges)

    verse = text.index("\u06f1")
    closer = text.index("\\xt*")
    assert abs(span(verse)[0] - span(verse + 1)[0]) < 40  # the two digits are side by side
    assert span(closer + 3)[1] <= min(span(verse)[0], span(verse + 1)[0]) + 1  # `*` ends left of the number
