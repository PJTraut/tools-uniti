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
def _replace_all_changes_every_file(monkeypatch):
    """A multi-file Replace All lists its files for the user to tick (book-lock
    plan L4). Tests that aren't about that list tick every file the list
    allows; the ones that are replace `replace_files.choose` themselves."""

    if importlib.util.find_spec("PySide6") is None:
        return
    from uniti.ui import replace_files

    monkeypatch.setattr(
        replace_files,
        "choose",
        lambda parent, rows: {index for index, row in enumerate(rows) if not row.read_only},
    )


@pytest.fixture(autouse=True)
def _books_open_as_they_always_did(request, monkeypatch):
    """USFM project books open locked, ask Close or Update when they aren't
    UTF-8 with CRLF line endings, and ask Save or Discard when they leave
    their tab with changes (book-lock plan L2). Tests written for the plain
    book keep working: a book opens unlocked, isn't format-checked, and
    leaves its tab keeping its changes. A test of the lock itself is marked
    `book_lock` and gets the real behaviour."""

    if importlib.util.find_spec("PySide6") is None or request.node.get_closest_marker("book_lock"):
        return
    from uniti.ui.environment_window import EnvironmentBar
    from uniti.ui.main_window import UNITIMainWindow

    monkeypatch.setattr(UNITIMainWindow, "_lock_new_book", lambda self, document, **kwargs: False)
    monkeypatch.setattr(UNITIMainWindow, "_lock_book_on_becoming_usfm", lambda self, view: None)
    monkeypatch.setattr(UNITIMainWindow, "_check_book_format", lambda self, view, report: None)
    monkeypatch.setattr(EnvironmentBar, "_leave_book", lambda self, view: "keep")


# Tests build their text files with `Path.write_text` and count offsets on
# the LF text they wrote. On Windows `write_text` translates "\n" to "\r\n"
# by default, shifting every offset (Windows CI, 2026-10-14). Write exactly
# the given text on every platform; a test that wants CRLF writes "\r\n".
_write_text = Path.write_text


def _write_text_verbatim(self, data, encoding=None, errors=None, newline="\n"):
    return _write_text(self, data, encoding=encoding, errors=errors, newline=newline)


Path.write_text = _write_text_verbatim
