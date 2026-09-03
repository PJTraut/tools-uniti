import importlib.util
import os
import time
from pathlib import Path

import pytest

from uniti.app.smoke import run_alpha_smoke
from uniti.core.document import Document


def test_alpha_headless_smoke_remains_green(tmp_path: Path):
    assert run_alpha_smoke(tmp_path / "smoke")["ok"] is True


def test_a11_gib_sparse_file_stays_lazy_during_early_edit(tmp_path: Path):
    path = tmp_path / "gib-sparse.txt"
    with path.open("wb") as handle:
        handle.write(b"abc\n")
        handle.seek((1 << 30) + 123)
        handle.write(b"END")

    with Document.open(path, encoding="utf-8") as document:
        document.insert(1, "X")
        assert document.read(0, 5) == "aXbc\n"
        assert not document.offset_mapper.complete
        assert not document.document_line_index.complete
        assert document.source.size > 1 << 30


def test_a11_offscreen_open_find_edit_save_when_pyside6_available(tmp_path: Path):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.paths import AppPaths
    from uniti.app.recovery_manager import RecoveryManager
    from uniti.app.settings import SettingsStore
    from uniti.ui.main_window import UNITIMainWindow

    source = tmp_path / "ui-source.txt"
    target = tmp_path / "ui-target.txt"
    source.write_text("abc 123\nabc 456\n", encoding="utf-8")
    paths = AppPaths.for_platform("linux", home=tmp_path / "home", environ={})
    paths.ensure()

    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow(
        recovery_manager=RecoveryManager(paths.recovery_dir),
        settings_store=SettingsStore(paths.settings_file),
    )
    view = window.open_path(source)
    panel = window._find_replace
    panel.regex_checkbox.setChecked(True)
    panel.find_input.setPlainText(r"abc\s+\d+")
    analysis_deadline = time.monotonic() + 5.0
    while panel.compile_current() is None and time.monotonic() < analysis_deadline:
        app.processEvents()
        time.sleep(0.01)
    assert panel.compile_current() is not None
    panel.find_all()
    deadline = time.monotonic() + 5.0
    while panel.busy and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    app.processEvents()
    assert panel.result_count == 2

    view.state.move_to(3)
    view.state.insert_text("X")
    window.save_current_as(target)
    assert target.read_text(encoding="utf-8").startswith("abcX 123")
    window.close_all_documents(force=True)
    window.close()
