"""How a file of a defined environment opens (field test round 2, R6).

Opening a file whose extension belongs to an environment other than Plain
Text asks: open it in that environment (its environment window), or as
Plain Text — the default editor environment, with no extended features
while the file is worked on (user decisions D2, 2026-10-08).
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from PySide6.QtWidgets import QMessageBox, QWidget


class OpenMode(StrEnum):
    # Into the environment's window for the file's group.
    ENVIRONMENT = "environment"
    # Pinned to the Plain Text environment, in this window.
    PLAIN_TEXT = "plain_text"
    # This window, in the file's own environment, without asking — for
    # callers that have already decided (and the test suite's default).
    HERE = "here"


def prompt_open_mode(parent: QWidget | None, path: Path, environment_label: str, count: int = 1) -> OpenMode | None:
    """Ask how to open `path` (or `count` files like it); None is Cancel."""

    what = f"“{path.name}” is a {environment_label} file." if count == 1 else f"These {count} files are {environment_label} files."
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(f"Open {environment_label} File" if count == 1 else f"Open {count} {environment_label} Files")
    box.setText(what)
    box.setInformativeText(
        f"Open in the {environment_label} environment, with its views, tools and checks — or as plain text, "
        f"with no {environment_label} features while you work on {'it' if count == 1 else 'them'}?"
    )
    environment = box.addButton(f"Open in {environment_label} Environment", QMessageBox.ButtonRole.AcceptRole)
    plain = box.addButton("Open as Plain Text", QMessageBox.ButtonRole.ActionRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(environment)
    box.exec()
    clicked = box.clickedButton()
    if clicked is environment:
        return OpenMode.ENVIRONMENT
    if clicked is plain:
        return OpenMode.PLAIN_TEXT
    return None


__all__ = ["OpenMode", "prompt_open_mode"]
