"""Suite-wide test defaults."""

from __future__ import annotations

import faulthandler
import importlib.util
import signal
import sys
from pathlib import Path

import pytest

# The suite's rare interpreter crash (2026-10-08) came once as SIGTRAP,
# which faulthandler's default set (SIGSEGV, SIGFPE, SIGABRT, SIGBUS,
# SIGILL) doesn't cover: dump every thread's traceback for it too, then let
# it end the run as before.
if hasattr(signal, "SIGTRAP") and sys.platform != "win32":
    faulthandler.register(signal.SIGTRAP, all_threads=True, chain=True)


@pytest.fixture(autouse=True)
def _open_files_here_without_asking(monkeypatch):
    """Opening a file of a defined environment asks how to open it (field
    test round 2, R6) in a modal dialog. Tests that aren't about that
    dialog open files the way they always did: in the window they ask, in
    the file's own environment. The R6 tests set their own answer."""

    if importlib.util.find_spec("PySide6") is None:
        return
    from uniti.ui import open_mode

    monkeypatch.setattr(open_mode, "prompt_open_mode", lambda *args, **kwargs: open_mode.OpenMode.HERE)


@pytest.fixture(autouse=True)
def _keep_unsaved_books_without_asking(monkeypatch):
    """Changing the book in a USFM project tab with unsaved changes asks
    whether to save (field test round 3, T4) in a modal dialog. Tests that
    aren't about that question answer No: the changes stay in the book."""

    if importlib.util.find_spec("PySide6") is None:
        return
    from uniti.ui import project_tabs

    monkeypatch.setattr(project_tabs, "ask_save_before_switch", lambda *args, **kwargs: False)


# Tests build their text files with `Path.write_text` and count offsets on
# the LF text they wrote. On Windows `write_text` translates "\n" to "\r\n"
# by default, shifting every offset (Windows CI, 2026-10-14). Write exactly
# the given text on every platform; a test that wants CRLF writes "\r\n".
_write_text = Path.write_text


def _write_text_verbatim(self, data, encoding=None, errors=None, newline="\n"):
    return _write_text(self, data, encoding=encoding, errors=errors, newline=newline)


Path.write_text = _write_text_verbatim
