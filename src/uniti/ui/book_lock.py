"""USFM book lock (plan 2026-10-14-usfm-book-lock-plan): the questions the
lock asks, and the helpers that name a book. Each question is a function
here so tests can replace it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox

from uniti.core.environments.catalog import PROJECT_ENVIRONMENTS
from uniti.core.environments.sfm.paratext_project import project_for_file

if TYPE_CHECKING:
    from uniti.core.document import Document


def book_title(path: Path) -> str:
    """"GEN (NIV)" for a project book, else the file's name."""

    from uniti.core.environments.sfm.references import book_header_for_path

    project = project_for_file(Path(path))
    if project is None:
        return Path(path).name
    code = book_header_for_path(Path(path)).code
    return f"{code} ({project.name})" if code else Path(path).name


def document_title(document: "Document") -> str:
    return book_title(document.path)


def locked_message(title: str) -> str:
    return f"{title} is locked: right-click the Book list › Unlock to edit"


def ask_unlock_and_save(parent, title: str) -> bool:
    """Save on a locked book with changes: True for Unlock and Save."""

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Locked Book")
    box.setText(f"{title} is locked.")
    box.setInformativeText("It is unlocked to save its changes.")
    unlock = box.addButton("Unlock and Save", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(unlock)
    box.exec()
    return box.clickedButton() is unlock


def ask_unlock_and_save_them(parent, count: int) -> bool:
    """Save All with locked books that have changes: True for Unlock and
    Save Them, False for Skip Them."""

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Locked Books")
    box.setText(f"{count} locked book{'s' if count != 1 else ''} {'have' if count != 1 else 'has'} changes.")
    unlock = box.addButton("Unlock and Save Them", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Skip Them", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(unlock)
    box.exec()
    return box.clickedButton() is unlock


def ask_save_or_discard(parent, title: str, *, locked: bool) -> bool | None:
    """A book with changes leaves the pane: True saves (unlocking first when
    locked), False discards, None cancels."""

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Unsaved Changes")
    box.setText(f"Changes to {title} will be lost.")
    save = box.addButton("Unlock and Save" if locked else "Save", QMessageBox.ButtonRole.AcceptRole)
    discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(save)
    box.exec()
    clicked = box.clickedButton()
    if clicked is save:
        return True
    if clicked is discard:
        return False
    return None


def ask_update_or_close(parent, title: str, found: str) -> bool:
    """A project book that isn't UTF-8 with CRLF line endings: True for
    Update, False for Close."""

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Book Format")
    box.setText(f"{title} isn't UTF-8 with CRLF line endings (found: {found}).")
    update = box.addButton("Update", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Close", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(update)
    box.exec()
    return box.clickedButton() is update


def ask_unlock_and_replace(parent, title: str) -> bool:
    """Replace in a locked book: True for Unlock and Replace, False for Skip."""

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Locked Book")
    box.setText(f"{title} is locked.")
    unlock = box.addButton("Unlock and Replace", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Skip", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(unlock)
    box.exec()
    return box.clickedButton() is unlock


class BookLock(QObject):
    """One window's Unlock Book / Lock Book action. The shared `action`
    acts on the shown book (toolbar, USFM menu, Book selector's menu);
    `make_action` gives a menu its own, for the tab or text it opened on."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.action = QAction("Unlock Book", window)
        self.action.setIconText("🔒")
        self.action.triggered.connect(lambda _checked=False: self.toggle(window.current_view))

    # --- state ----------------------------------------------------------------

    def applies_to(self, view) -> bool:
        """Only a book in the USFM environment has a lock to change."""

        if view is None:
            return False
        document = view.document
        return document.locked or self._window._environment.environment_key_for(document) in PROJECT_ENVIRONMENTS

    def read_only_folder(self, view) -> str | None:
        from uniti.app.read_only import read_only_folder_for

        return read_only_folder_for(view.document.path, self._window._settings.read_only_folders)

    def describe(self, view) -> tuple[str, bool, str]:
        """The action's (text, enabled, tooltip) for `view`."""

        if not self.applies_to(view):
            return "Unlock Book", False, "Only a USFM book can be locked"
        locked = view.document.locked
        text = "Unlock Book" if locked else "Lock Book"
        folder = self.read_only_folder(view)
        if folder is not None:
            return text, False, f"{folder} is a read-only folder: its books can't be unlocked"
        if locked:
            return text, True, "Unlock this book to edit it; it locks again when it is closed"
        return text, True, "Lock this book: editing is off until it is unlocked"

    def refresh(self) -> None:
        text, enabled, tooltip = self.describe(self._window.current_view)
        self.action.setText(text)
        self.action.setIconText("🔓" if text == "Lock Book" else "🔒")  # the toolbar shows only this
        self.action.setEnabled(enabled)
        self.action.setToolTip(tooltip)

    def make_action(self, view, parent) -> QAction:
        text, enabled, tooltip = self.describe(view)
        action = QAction(text, parent)
        action.setEnabled(enabled)
        action.setToolTip(tooltip)
        action.triggered.connect(lambda _checked=False: self.toggle(view))
        return action

    def toggle(self, view) -> bool:
        """Lock the book, or unlock it; True when it is locked after."""

        if view is None or not self.describe(view)[1]:
            return False if view is None else view.document.locked
        view.document.set_locked(not view.document.locked)
        return view.document.locked


def ask_wrap_project(parent, *, forward: bool) -> bool:
    """Find or Replace ran past the project's last (or first) book: True to
    carry on from the other end."""

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("End of Project")
    box.setText(
        "No more matches to the end of the project."
        if forward
        else "No more matches back to the start of the project."
    )
    box.setInformativeText("Continue from the first book?" if forward else "Continue from the last book?")
    go = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(go)
    box.exec()
    return box.clickedButton() is go
