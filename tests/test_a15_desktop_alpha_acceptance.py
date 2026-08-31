import importlib.util
import os
from pathlib import Path

import pytest

from uniti.app.editor_state import EditorState
from uniti.core.document import Document
from uniti.regex.replace import replace_all
from uniti.regex.engine import compile_pattern


@pytest.mark.parametrize(
    ("encoding", "bom"),
    [
        ("utf-16-le", b"\xff\xfe"),
        ("utf-16-be", b"\xfe\xff"),
        ("utf-32-le", b"\xff\xfe\x00\x00"),
        ("utf-32-be", b"\x00\x00\xfe\xff"),
    ],
)
def test_alpha_candidate_roundtrips_utf16_utf32_endianness_with_edit_and_save(
    tmp_path: Path, encoding: str, bom: bytes
):
    source = tmp_path / f"{encoding}.txt"
    source.write_bytes(bom + "A\r\né\r\n".encode(encoding))
    destination = tmp_path / f"{encoding}-saved.txt"

    with Document.open(source) as document:
        assert document.encoding_info.detected == encoding
        state = EditorState(document)
        state.move_end()
        state.insert_text("Ω")
        document.save(destination)

    with Document.open(destination) as reopened:
        assert reopened.encoding_info.detected == encoding
        assert "Ω" in reopened.read(0, reopened.total_chars())


def test_alpha_candidate_regex_replace_and_invalid_byte_annotation(tmp_path: Path):
    path = tmp_path / "regex-invalid.txt"
    path.write_bytes(b"A\xff 2026-08-31\n")
    with Document.open(path, encoding="utf-8") as document:
        annotated = document.read_with_annotations(0, 2)
        assert annotated.invalid_bytes[0].raw == b"\xff"
        compiled = compile_pattern(r"(?P<y>\d{4})-(\d{2})-(\d{2})")
        count = replace_all(document, compiled, r"\g<y>/\2/\3")
        assert count == 1
        assert "2026/08/31" in document.read(0, document.total_chars())


def test_alpha_candidate_giant_line_end_navigation_is_bounded(tmp_path: Path):
    path = tmp_path / "giant.txt"
    path.write_bytes(b"x" * (2 * 1024 * 1024))
    with Document.open(path, encoding="utf-8") as document:
        state = EditorState(document)
        state.move_end()
        assert state.cursor == 2 * 1024 * 1024


def test_alpha_candidate_qt_clipboard_and_ime_when_pyside6_available(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtGui import QGuiApplication, QInputMethodEvent
    from PySide6.QtWidgets import QApplication

    from uniti.ui.text_view import UNITITextView

    path = tmp_path / "ime.txt"
    path.write_text("abc", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    document = Document.open(path, encoding="utf-8")
    try:
        state = EditorState(document)
        state.move_to(0)
        state.move_to(3, selecting=True)
        view = UNITITextView(state)
        view.copy_selection()
        assert QGuiApplication.clipboard().text() == "abc"
        state.move_to(3)
        event = QInputMethodEvent("", [])
        event.setCommitString("漢")
        view.inputMethodEvent(event)
        assert document.read(0, document.total_chars()) == "abc漢"
        view.close()
        app.processEvents()
    finally:
        document.close()
