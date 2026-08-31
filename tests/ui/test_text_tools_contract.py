import importlib.util
import os
from pathlib import Path

import pytest


MAIN = Path("src/uniti/ui/main_window.py")
STATUS = Path("src/uniti/ui/status_bar.py")
INSPECTOR = Path("src/uniti/ui/character_inspector.py")


def test_main_window_keeps_reinterpret_conversion_and_eol_commands_distinct():
    source = MAIN.read_text()
    for required in (
        "Reinterpret As",
        "Convert on Save",
        "Keep Source",
        "CRLF",
        "Character Inspector",
        "set_output_encoding",
        "set_output_eol",
        "Document.open",
    ):
        assert required in source


def test_status_bar_can_report_detected_and_output_text_state():
    source = STATUS.read_text()
    assert "EOLReport" in source
    assert "update_eol_report" in source
    assert "output_encoding" in source
    assert "detected" in source
    assert "MIXED" in source


def test_character_inspector_exposes_unicode_name_codepoint_and_encoding_bytes():
    assert INSPECTOR.exists()
    source = INSPECTOR.read_text()
    for required in (
        "unicodedata.name",
        "U+",
        "UTF-8",
        "Windows-1252",
        "UTF-16LE",
        "not representable",
    ):
        assert required in source


def test_main_window_background_eol_analysis_uses_independent_byte_source():
    source = MAIN.read_text()
    assert "analyze_eol" in source
    assert "ByteSource.open" in source
    assert "PriorityWorkerPool" in source


def test_text_tools_offscreen_smoke_when_pyside6_available(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    path = tmp_path / "mixed.txt"
    path.write_bytes(b"a\r\nb\nc\r")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    view = window.open_path(path)
    window.set_output_encoding("utf-8")
    window.set_output_eol("CRLF")
    app.processEvents()
    assert view.document.output_encoding == "utf-8"
    assert view.document.output_eol == "CRLF"
    window.close_all_documents(force=True)
    window.close()


def test_main_window_exposes_diagnostics_tool_without_using_it_as_document_storage():
    source = Path("src/uniti/ui/main_window.py").read_text()
    dialog = Path("src/uniti/ui/diagnostics_dialog.py")
    assert "Diagnostics" in source
    assert "diagnostics_snapshot" in source
    assert dialog.exists()
    assert "QPlainTextEdit" not in source


def test_reinterpret_uses_current_logical_path_after_save_as():
    source = MAIN.read_text()
    reinterpret = source[source.index("def reinterpret_current"):source.index("def _show_save_error")]
    assert "path = view.document.path" in reinterpret
    assert "path = view.document.source.path" not in reinterpret
