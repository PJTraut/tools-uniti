import importlib.util
import os
from pathlib import Path

import pytest


def _skip_without_pyside6():
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_shaped_row_provider_reuses_line_direction_for_continuation_windows(
    tmp_path: Path,
):
    """BF-064: `ShapedRowProvider` (the wrapped-mode row source) must detect
    a logical line's direction once, from its true start, and reuse it for
    every later window of that same line rather than re-detecting from a
    fragment that may not represent the whole paragraph."""

    _skip_without_pyside6()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from uniti.core.document import Document
    from uniti.ui.shaped_wrap import ShapedRowProvider

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "wrapped-rtl.txt"
    arabic = "مرحبا "
    text = arabic + "hello world"
    path.write_text(text, encoding="utf-8", newline="")

    with Document.open(path, encoding="utf-8") as document:
        provider = ShapedRowProvider(document, QFont("Arial", 12), width_px=1_000_000, tab_stop_px=32)
        provider(0, 0)
        assert provider.directions[0] == Qt.LayoutDirection.RightToLeft

        # A later call for a window starting mid-line (simulating a wrapped
        # continuation row) must not overwrite the cached direction, even
        # though its own fragment ("hello world") would detect as LTR.
        provider(0, len(arabic))
        assert provider.directions[0] == Qt.LayoutDirection.RightToLeft


def test_shaped_row_provider_detects_ltr_for_an_ordinary_line(tmp_path: Path):
    _skip_without_pyside6()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from uniti.core.document import Document
    from uniti.ui.shaped_wrap import ShapedRowProvider

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "wrapped-ltr.txt"
    path.write_text("hello world", encoding="utf-8", newline="")

    with Document.open(path, encoding="utf-8") as document:
        provider = ShapedRowProvider(document, QFont("Arial", 12), width_px=1_000_000, tab_stop_px=32)
        provider(0, 0)
        assert provider.directions[0] == Qt.LayoutDirection.LeftToRight


def test_horizontal_layouts_reuses_line_direction_for_later_checkpoints(
    tmp_path: Path,
):
    """Same detect-once-reuse contract as `ShapedRowProvider`, for the
    non-wrapped/horizontal-scroll path. The line is long enough to force a
    second, genuinely separate 8192-char checkpoint window starting well
    into a pure-Latin tail, so this actually exercises the mid-line reuse
    path rather than resolving everything through one short read."""

    _skip_without_pyside6()
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication

    from uniti.core.document import Document
    from uniti.ui.horizontal_layout import HorizontalLayouts

    app = QApplication.instance() or QApplication([])
    path = tmp_path / "horizontal-rtl.txt"
    arabic = "مرحبا "
    text = arabic + "a" * 9000
    path.write_text(text, encoding="utf-8", newline="")

    with Document.open(path, encoding="utf-8") as document:
        layouts = HorizontalLayouts(document, QFont("Arial", 12), tab_stop_px=32)
        layouts.window(0, column=0)
        assert layouts.directions[0] == Qt.LayoutDirection.RightToLeft

        # Force a second checkpoint window well past the first 8192-char
        # read, starting entirely within the pure-Latin tail.
        layouts.window(0, column=8500)
        assert layouts.directions[0] == Qt.LayoutDirection.RightToLeft
        assert len(layouts.checkpoints[0]) > 1
