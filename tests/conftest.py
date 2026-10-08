"""Suite-wide test defaults."""

from __future__ import annotations

import importlib.util

import pytest


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
