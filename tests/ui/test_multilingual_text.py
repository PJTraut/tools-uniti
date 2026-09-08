"""LTR shaping and editing regressions. Synthetic IME is not host qualification."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import pytest
import regex
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QInputMethodEvent
from uniti.core.document import Document
from uniti.app.editor_state import EditorState


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


@pytest.mark.parametrize(
    "cluster",
    [
        "é",
        "क्षि",
        "ক্কি",
        "ક્કિ",
        "ਕਿ",
        "ಕಿ",
        "ക്കി",
        "କ୍କି",
        "கி",
        "క్కి",
        "한",
        "👩‍💻",
        "🇿🇦",
        "✈️",
    ],
)
def test_user_navigation_deletes_complete_grapheme_and_undo(tmp_path, cluster):
    p = tmp_path / "text"
    p.write_text("A" + cluster + "B", encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        state = EditorState(doc)
        state.move_to(1)
        state.move_right()
        assert state.cursor == 1 + len(cluster)
        state.backspace()
        assert doc.read(0, 2) == "AB"
        state.undo()
        assert doc.read(0, len(cluster) + 2) == "A" + cluster + "B"
        state.move_to(1)
        state.delete_forward()
        assert doc.read(0, 2) == "AB"


def test_utf16_surrogate_inverse_is_explicit(qapp):
    from uniti.ui import text_layout

    mapping = text_layout.Utf16Map("A😀B")
    assert [mapping.cp_to_u16(i) for i in range(4)] == [0, 1, 3, 4]
    assert mapping.u16_to_cp(2, bias="floor") == 1
    assert mapping.u16_to_cp(2, bias="ceil") == 2


@pytest.mark.parametrize("zoom", [100, 150, 200])
def test_shaped_hit_caret_agree_at_clusters(qapp, tmp_path, zoom):
    from uniti.ui.text_view import UNITITextView

    text = "Latin क्षि ক্কি 中文 한국어 👩‍💻 é\tX\u200bY"
    p = tmp_path / "text"
    p.write_text(text, encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.resize(1200, 120)
        view.set_zoom_percent(zoom)
        boundaries = {m.start() for m in regex.finditer(r"\X", text)} | {len(text)}
        from uniti.ui.text_layout import ShapedWindow

        shaped = ShapedWindow(text, view.font(), tab_stop_px=view._cell_width * 4)
        for cp in boundaries:
            view.state.move_to(cp)
            x = view._cursor_rectangle().x()
            assert x == pytest.approx(view._gutter_width + shaped.x_for_cp(cp), abs=0.1)
            hit = view._char_for_point(x, 0)
            assert hit in boundaries
            assert shaped.x_for_cp(hit) == pytest.approx(shaped.x_for_cp(cp), abs=0.1)
        view.close()


def test_ime_utf16_replacement_deletion_and_cancel(qapp, tmp_path):
    from uniti.ui.text_view import UNITITextView

    p = tmp_path / "text"
    p.write_text("A😀B", encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.state.move_to(2)
        assert view.inputMethodQuery(Qt.InputMethodQuery.ImCursorPosition) == 3
        event = QInputMethodEvent()
        event.setCommitString("", -2, 2)
        view.inputMethodEvent(event)
        assert doc.read(0, 2) == "AB"
        before = doc.revision
        view.inputMethodEvent(QInputMethodEvent("中文", []))
        assert doc.revision == before
        view.inputMethodEvent(QInputMethodEvent("", []))
        assert doc.revision == before
        view.close()


def test_wrap_uses_shaped_grapheme_boundaries(qapp, tmp_path):
    from uniti.ui.text_view import UNITITextView
    from uniti.ui.text_layout import ShapedWindow

    text = "क्षि 中文 한국어 👩‍💻 é\tX" * 8
    p = tmp_path / "wrap"
    p.write_text(text, encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.resize(180, 160)
        view.set_soft_wrap(True)
        index = view._wrapped_row_index()
        rows = []
        for i in range(100):
            try:
                row = index.row(i)
            except ValueError:
                break
            rows.append(row)
        assert sum(r.length for r in rows) == len(text)
        boundaries = {0, *[m.end() for m in regex.finditer(r"\X", text)]}
        for row in rows:
            assert row.column_start in boundaries
            assert row.column_start + row.length in boundaries
            shape = ShapedWindow(
                text[row.column_start : row.column_start + row.length].rstrip(" \t"),
                view.font(),
                tab_stop_px=view._cell_width * 4,
            )
            assert shape.width <= view.viewport().width() - view._gutter_width + 1
        view.close()


def test_over_budget_grapheme_is_not_partially_deleted(tmp_path):
    from uniti.app.graphemes import neighbor_boundary

    p = tmp_path / "long"
    p.write_text("A" + "́" * 9000 + "B", encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        state = EditorState(doc)
        state.move_to(4500)
        revision = doc.revision
        assert not neighbor_boundary(doc, 4500, -1).complete
        state.backspace()
        state.delete_forward()
        assert doc.revision == revision


def test_preedit_shifts_following_text_without_document_edit(qapp, tmp_path):
    from uniti.ui.text_view import UNITITextView

    p = tmp_path / "ime"
    p.write_text("AB", encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.state.move_to(1)
        before = view._cursor_rectangle().x()
        view.inputMethodEvent(QInputMethodEvent("中文", []))
        assert view._cursor_rectangle().x() > before
        assert doc.read(0, 2) == "AB"
        view.inputMethodEvent(QInputMethodEvent("", []))
        assert view._cursor_rectangle().x() == before
        view.close()


def test_horizontal_progress_is_bounded_and_cached(qapp):
    from uniti.ui.horizontal_layout import HorizontalLayouts
    from uniti.ui.font_policy import resolve_editor_font

    class Giant:
        reads = 0

        def read_line_window(self, line, *, column_start, max_chars):
            assert max_chars <= 8192
            self.reads += max_chars
            return ("中" * max_chars)[
                : max(0, min(max_chars, 8_000_000 - column_start))
            ]

    doc = Giant()
    layout = HorizontalLayouts(doc, resolve_editor_font().font, 32)
    for _ in range(4):
        before = doc.reads
        start, offset, shape, ready = layout.window(0, column=25000)
        assert doc.reads - before <= 8192
        if ready:
            break
    assert ready
    before = doc.reads
    assert layout.window(0, column=25000)[3]
    assert doc.reads == before


def test_shaped_wrap_far_request_is_bounded_and_rebuild_uses_checkpoint(qapp):
    from uniti.ui.shaped_wrap import ShapedRowProvider
    from uniti.ui.wrap_index import WrappedRowIndex
    from uniti.ui.font_policy import resolve_editor_font

    class Giant:
        reads = 0
        minimum = 8_000_000

        def line_start(self, line):
            if line:
                raise ValueError("EOF")
            return 0

        def read_line_window(self, line, *, column_start, max_chars):
            assert max_chars <= 8192
            self.reads += max_chars
            self.minimum = min(self.minimum, column_start)
            return "中" * max(0, min(max_chars, 8_000_000 - column_start))

    doc = Giant()
    provider = ShapedRowProvider(doc, resolve_editor_font().font, 600, 32)
    index = WrappedRowIndex(doc, 80, row_provider=provider)
    for _ in range(20):
        before = doc.reads
        known = index.known_count
        index.ensure_row(5000)
        assert doc.reads - before <= 8192
        assert index.known_count - known <= 512
        assert index.resident_row_count <= 2048
        if index.known_count > 5000:
            break
    assert index.known_count > 1000
    doc.minimum = 8_000_000
    index.row(600)
    assert doc.minimum > 0  # Eviction does not replay document prefix.


def test_ime_format_attribute_and_surrogate_replacement(qapp, tmp_path):
    from PySide6.QtGui import QTextCharFormat, QColor
    from uniti.ui.text_view import UNITITextView

    p = tmp_path / "ime"
    p.write_text("A😀B", encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.state.move_to(2)
        fmt = QTextCharFormat()
        fmt.setForeground(QColor("red"))
        attr = QInputMethodEvent.Attribute(
            QInputMethodEvent.AttributeType.TextFormat, 0, 1, fmt
        )
        view.inputMethodEvent(QInputMethodEvent("中", [attr]))
        assert len(view._preedit_formats) == 1
        event = QInputMethodEvent()
        event.setCommitString("한", -2, 2)
        view.inputMethodEvent(event)
        assert doc.read(0, 3) == "A한B"
        view.state.undo()
        assert doc.read(0, 3) == "A😀B"
        view.close()


def test_regex_highlights_utf16_after_emoji(qapp):
    from uniti.ui.regex_input import RegexInput
    from uniti.regex.analysis import analyze_pattern

    widget = RegexInput()
    widget.setPlainText("😀(中)")
    widget.set_analysis(analyze_pattern("😀(中)", 1))
    widget.highlighter.rehighlight()
    ranges = widget.document().firstBlock().layout().formats()
    assert any(r.start == 2 for r in ranges)
    assert "Noto Sans Devanagari" in widget.font().families()
    widget.close()


def test_capture_row_height_contains_fallback_glyphs(qapp):
    from PySide6.QtGui import QStandardItemModel, QStandardItem
    from PySide6.QtWidgets import QStyleOptionViewItem
    from uniti.ui.capture_report_delegate import CaptureReportDelegate
    from uniti.ui.text_layout import ShapedWindow
    from uniti.ui.font_policy import resolve_editor_font

    text = "क्षि ক্কি 中文 한국어"
    model = QStandardItemModel()
    model.appendRow(QStandardItem(text))
    option = QStyleOptionViewItem()
    option.font = resolve_editor_font().font
    delegate = CaptureReportDelegate()
    shape = ShapedWindow(text, option.font)
    assert delegate.sizeHint(option, model.index(0, 0)).height() >= max(
        l.height() for l in shape.lines
    )


@pytest.mark.parametrize(
    "sample",
    [
        "क्षि",
        "ক্কি",
        "ક્કિ",
        "ਕਿ",
        "ಕ್ಕಿ",
        "ക്കി",
        "କ୍କି",
        "க்கி",
        "క్కి",
        "汉字",
        "漢字",
        "한국어",
        "👩‍💻",
    ],
)
@pytest.mark.parametrize("zoom", [100, 200])
def test_actual_fallback_ink_fits_common_row_envelope(qapp, tmp_path, sample, zoom):
    from PySide6.QtGui import QImage, QPainter, QColor
    from uniti.ui.text_view import UNITITextView

    p = tmp_path / "ink"
    p.write_text(sample, encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.set_zoom_percent(zoom)
        image = QImage(240, view._line_height * 3, QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.setPen(QColor("black"))
        view._paint_line_text(painter, sample, 10, view._line_height)
        painter.end()
        ink = [
            y
            for y in range(image.height())
            for x in range(10, image.width())
            if image.pixelColor(x, y) != QColor("white")
        ]
        assert ink
        assert min(ink) >= view._line_height
        assert max(ink) < view._line_height * 2
        view.close()


def test_multilingual_edit_copy_exact_inspection_save_and_reopen(qapp, tmp_path):
    from uniti.ui.text_view import UNITITextView

    text = "क्षि ক্কি ક્કિ ਕਿ ಕ್ಕಿ ക്കി କ୍କି க்கி క్కి 汉漢 한국어 👩‍💻 é\t\u200b"
    p = tmp_path / "save"
    p.write_bytes(text.encode("utf-8"))
    with Document.open(p, encoding="utf-8") as doc:
        state = EditorState(doc)
        view = UNITITextView(state)
        state.move_to(0)
        state.move_to(1, selecting=True)
        assert (
            view.copy_selection() == text[0]
        )  # Explicit code-point selection remains exact.
        assert state.selection == (0, 1)
        state.move_to(len(text))
        state.insert_text("中文한")
        doc.save()
        assert p.read_bytes() == (text + "中文한").encode("utf-8")
        state.undo()
        assert doc.read(0, len(text)) == text
        state.redo()
        assert doc.read(0, len(text) + 3) == text + "中文한"
        view.close()
    with Document.open(p, encoding="utf-8") as doc:
        assert doc.read(0, len(text) + 3) == text + "中文한"


def test_horizontal_checkpoint_tabs_keep_global_tab_origin(qapp):
    from uniti.ui.horizontal_layout import HorizontalLayouts
    from uniti.ui.font_policy import resolve_editor_font

    text = "a" * 8191 + "X\tY"

    class Text:
        def read_line_window(self, line, *, column_start, max_chars):
            return text[column_start : column_start + max_chars]

    font = resolve_editor_font().font
    layouts = HorizontalLayouts(Text(), font, 32)
    layouts.window(0, column=8193)
    start, offset, shape, ready = layouts.window(0, column=8193)
    assert ready
    # The tab advances to a document-line tab stop, not a chunk-local stop.
    x = offset + shape.x_for_cp(8193 - start)
    assert x / 32 == pytest.approx(round(x / 32), abs=0.001)


@pytest.mark.parametrize("backwards", [False, True])
def test_plain_delete_from_explicit_interior_cursor_removes_whole_cluster(
    tmp_path, backwards
):
    p = tmp_path / "interior"
    p.write_text("AéB", encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        state = EditorState(doc)
        state.move_to(2)
        (state.backspace if backwards else state.delete_forward)()
        assert doc.read(0, 2) == "AB"
        assert state.cursor == 1


def test_paint_keeps_bounded_windows_without_discovering_line_end(
    qapp, tmp_path, monkeypatch
):
    from uniti.ui.text_view import UNITITextView

    p = tmp_path / "bounded"
    p.write_text("A" * 8190 + "क्षि" + "中" * 12000, encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.resize(400, 120)
        view.show()
        qapp.processEvents()
        calls = []
        original_end = Document.line_end

        def line_end(self, *args, **kwargs):
            calls.append("line_end")
            return original_end(self, *args, **kwargs)

        original_window = Document.read_line_window_annotated

        def window(self, *args, **kwargs):
            assert kwargs["max_chars"] <= 8192
            return original_window(self, *args, **kwargs)

        monkeypatch.setattr(Document, "line_end", line_end)
        monkeypatch.setattr(Document, "read_line_window_annotated", window)
        view.set_whitespace_mode("all")
        view.viewport().repaint()
        assert not calls
        start, offset, shape, ready = view._horizontal_geometry(0)
        assert shape.text == "A" * 8190  # The split conjunct is held for continuation.
        view.close()


def test_ime_selection_attribute_uses_utf16_context(qapp, tmp_path):
    from uniti.ui.text_view import UNITITextView

    p = tmp_path / "ime-selection"
    p.write_text("A😀B", encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.state.move_to(3)
        selection = QInputMethodEvent.Attribute(
            QInputMethodEvent.AttributeType.Selection, 1, 2, None
        )
        view.inputMethodEvent(QInputMethodEvent("", [selection]))
        assert view.state.selection == (1, 2)
        assert view.state.selected_text() == "😀"
        view.close()


def test_narrow_shaped_wrap_keeps_first_row_when_window_has_many_rows(qapp):
    from uniti.ui.shaped_wrap import ShapedRowProvider
    from uniti.ui.font_policy import resolve_editor_font

    class Text:
        def read_line_window(self, line, *, column_start, max_chars):
            return "x" * max(0, min(max_chars, 8192 - column_start))

    provider = ShapedRowProvider(Text(), resolve_editor_font().font, 1, 32)
    assert provider(0, 0) == (1, False)
    assert len(provider.cache) <= 512


def test_wrap_resize_inside_latin_column_bucket_uses_exact_pixel_width(qapp, tmp_path):
    from uniti.ui.text_view import UNITITextView
    from uniti.ui.shaped_wrap import ShapedRowProvider

    p = tmp_path / "pixel-wrap"
    p.write_text("中文éकिक्षि한국어" * 80, encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.resize(400, 240)
        view.set_soft_wrap(True)
        view.show()
        qapp.processEvents()
        checked_same_bucket = False
        try:
            for width in range(401, 421):
                original = view._wrapped_row_index()
                original_columns = view._wrap_columns()
                initial_width = view.viewport().width() - view._gutter_width - 8
                view.resize(width, 240)
                qapp.processEvents()
                available = view.viewport().width() - view._gutter_width - 8
                if (
                    view._wrap_columns() != original_columns
                    or available <= initial_width
                ):
                    continue
                current = view._prepare_wrapped_rows(0, 1)
                fresh = ShapedRowProvider(
                    doc, view.font(), available, view._cell_width * 4
                )
                assert current is not original
                assert current._row_provider.width_px == available
                assert current.row(0).length == fresh(0, 0)[0]
                checked_same_bucket = True
            assert checked_same_bucket
        finally:
            view.close()


@pytest.mark.parametrize("wrapped", [False, True])
def test_long_preedit_keeps_caret_visible_and_cancel_restores_geometry(
    qapp, tmp_path, wrapped, monkeypatch
):
    from uniti.ui.text_view import UNITITextView

    p = tmp_path / "composition-pan"
    p.write_text("AB", encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.resize(180, 220)
        view.set_zoom_percent(250)
        view.set_soft_wrap(wrapped)
        view.show()
        qapp.processEvents()
        view.state.move_to(1)
        view._state_changed()
        before = view._cursor_rectangle()
        revision = doc.revision
        horizontal = view.horizontalScrollBar().value()
        try:
            view.inputMethodEvent(QInputMethodEvent("中文한국어" * 12, []))
            caret = view._cursor_rectangle()
            painted_carets = []
            original_paint = view._paint_line_text

            def observe_paint(painter, text, x, y, **kwargs):
                shaped = kwargs.get("shaped")
                if shaped is not None and shaped.preedit is not None:
                    painted_carets.append(x + shaped.preedit_x(view._preedit_cursor))
                return original_paint(painter, text, x, y, **kwargs)

            monkeypatch.setattr(view, "_paint_line_text", observe_paint)
            view.viewport().repaint()
            assert painted_carets == pytest.approx([caret.left()])
            assert (
                view._char_for_point(caret.center().x(), caret.center().y())
                == view.state.cursor
            )
            assert view._gutter_width <= caret.left()
            assert caret.right() <= view.viewport().width()
            assert doc.revision == revision
            assert not doc.can_undo
            assert view.soft_wrap == wrapped
            assert view.horizontalScrollBar().value() == horizontal
            view.inputMethodEvent(QInputMethodEvent("", []))
            assert view._cursor_rectangle() == before
            assert doc.revision == revision
            view.inputMethodEvent(QInputMethodEvent("中文한국어" * 12, []))
            commit = QInputMethodEvent()
            commit.setCommitString("中文")
            view.inputMethodEvent(commit)
            assert view._preedit_text == ""
            assert doc.read(0, 4) == "A中文B"
            assert view.soft_wrap == wrapped
            view.state.undo()
            assert doc.read(0, 2) == "AB"
        finally:
            view.close()


def test_wrapped_seam_has_one_composition_owner_for_paint_pan_and_hit(
    qapp, tmp_path, monkeypatch
):
    from uniti.ui.text_view import UNITITextView

    original_text = "中文한국어abc" * 30
    p = tmp_path / "composition-seam"
    p.write_text(original_text, encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.resize(300, 220)
        view.set_soft_wrap(True)
        view.show()
        qapp.processEvents()
        index = view._wrapped_row_index()
        second = index.row(1)
        seam = doc.line_start(second.line) + second.column_start
        view.state.move_to(seam)
        view._state_changed()
        before = view._cursor_rectangle()
        previous_hit = view._char_for_point(
            view._gutter_width + 10, view._line_height / 2
        )
        revision = doc.revision
        painted = []
        original_paint = view._paint_line_text

        def observe_paint(painter, text, x, y, **kwargs):
            shape = kwargs["shaped"]
            painted.append((x, y, shape))
            return original_paint(painter, text, x, y, **kwargs)

        monkeypatch.setattr(view, "_paint_line_text", observe_paint)
        try:
            view.inputMethodEvent(QInputMethodEvent(" composing 中文한국어" * 5, []))
            view.viewport().repaint()
            owners = [
                (x, y, shape) for x, y, shape in painted if shape.preedit is not None
            ]
            assert len(owners) == 1
            x, y, shape = owners[0]
            assert y == view._line_height
            assert x < view._gutter_width  # Only the owning row is panned.
            assert painted[0][0] == view._gutter_width
            assert painted[0][2].preedit is None
            caret = view._cursor_rectangle()
            assert caret.top() == y
            assert x + shape.preedit_x(view._preedit_cursor) == pytest.approx(
                caret.left()
            )
            assert view._char_for_point(caret.center().x(), caret.center().y()) == seam
            assert (
                view._char_for_point(view._gutter_width + 10, view._line_height / 2)
                == previous_hit
            )
            assert doc.revision == revision
            view.inputMethodEvent(QInputMethodEvent("", []))
            painted.clear()
            view.viewport().repaint()
            assert all(
                shape.preedit is None and x == view._gutter_width
                for x, _, shape in painted
            )
            assert view._cursor_rectangle() == before
            assert doc.revision == revision
            view.inputMethodEvent(QInputMethodEvent(" composing 中文", []))
            commit = QInputMethodEvent()
            commit.setCommitString("中文")
            view.inputMethodEvent(commit)
            assert (
                doc.read(0, len(original_text) + 2)
                == original_text[:seam] + "中文" + original_text[seam:]
            )
            painted.clear()
            view.viewport().repaint()
            assert all(
                shape.preedit is None and x == view._gutter_width
                for x, _, shape in painted
            )
            view.state.undo()
            assert doc.read(0, len(original_text)) == original_text
        finally:
            view.close()


@pytest.mark.parametrize("text", ["", "中文", "中文\n"])
def test_logical_eol_keeps_one_composition_owner(qapp, tmp_path, monkeypatch, text):
    from uniti.ui.text_view import UNITITextView

    p = tmp_path / "composition-eol"
    p.write_text(text, encoding="utf-8")
    with Document.open(p, encoding="utf-8") as doc:
        view = UNITITextView(EditorState(doc))
        view.resize(300, 220)
        view.set_soft_wrap(True)
        view.show()
        qapp.processEvents()
        view.state.move_to(len(text.rstrip("\n")))
        view._state_changed()
        owners = []
        original_paint = view._paint_line_text

        def observe(painter, content, x, y, **kwargs):
            shape = kwargs["shaped"]
            if shape.preedit is not None:
                owners.append((y, x + shape.preedit_x(view._preedit_cursor)))
            return original_paint(painter, content, x, y, **kwargs)

        monkeypatch.setattr(view, "_paint_line_text", observe)
        try:
            view.inputMethodEvent(QInputMethodEvent("한", []))
            view.viewport().repaint()
            caret = view._cursor_rectangle()
            assert owners == pytest.approx([(caret.top(), caret.left())])
        finally:
            view.close()
