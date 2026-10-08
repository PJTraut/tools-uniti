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
