"""USFM book lock (plan 2026-10-14-usfm-book-lock-plan): the questions the
lock asks, and the helpers that name a book. Each question is a function
here so tests can replace it."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QHBoxLayout, QLabel, QMessageBox, QPushButton, QWidget

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


def document_title(document: Document) -> str:
    return book_title(document.path)


def project_title(path: Path) -> str:
    """The project's short name, else the file's name."""

    project = project_for_file(Path(path))
    return Path(path).name if project is None else project.name


def locked_message(title: str) -> str:
    return f"{title} is locked: right-click the Book list › Unlock Project to edit"


def ask_unlock_and_save(parent, title: str) -> bool:
    """Save on a locked book with changes: True for Unlock and Save."""

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Locked Project")
    box.setText(f"{title} is locked.")
    box.setInformativeText("Its project is unlocked to save its changes.")
    unlock = box.addButton("Unlock Project and Save", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(unlock)
    box.exec()
    return box.clickedButton() is unlock


def ask_unlock_and_save_them(parent, count: int) -> bool:
    """Save All with locked books that have changes: True for Unlock and
    Save Them, False for Skip Them."""

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Locked Project")
    box.setText(f"{count} locked book{'s' if count != 1 else ''} {'have' if count != 1 else 'has'} changes.")
    unlock = box.addButton("Unlock Project and Save Them", QMessageBox.ButtonRole.AcceptRole)
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
    save = box.addButton("Unlock Project and Save Book" if locked else "Save Book", QMessageBox.ButtonRole.AcceptRole)
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
    """Replace in a locked book: True to unlock its project, False to abort."""

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle("Locked Project")
    box.setText(f"{title} is locked.")
    box.setInformativeText("Unlock the project to replace, or abort the replace.")
    unlock = box.addButton("Unlock Project", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Abort", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(unlock)
    box.exec()
    return box.clickedButton() is unlock


class BookLock(QObject):
    """One window's Unlock Project / Lock Project action. The lock is the
    project's: every open book of it. The shared `action` acts on the shown book's project (toolbar, USFM menu, Book selector's menu);
    `make_action` gives a menu its own, for the tab or text it opened on."""

    def __init__(self, window) -> None:
        super().__init__(window)
        self._window = window
        self.action = QAction("Unlock Project", window)
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
            return "Unlock Project", False, "Only a USFM project can be locked"
        locked = view.document.locked
        text = "Unlock Project" if locked else "Lock Project"
        folder = self.read_only_folder(view)
        if folder is not None:
            return text, False, f"{folder} is a read-only folder: its books can't be unlocked"
        if locked:
            return text, True, "Unlock this project: every book of it can be edited until it is locked again or closed"
        return text, True, "Lock this project: editing is off in every book of it until it is unlocked"

    def refresh(self) -> None:
        text, enabled, tooltip = self.describe(self._window.current_view)
        banner = getattr(self._window, "_unlock_banner", None)
        if banner is not None:
            banner.refresh(self._window.current_view)
        self.action.setText(text)
        self.action.setIconText("🔓" if text == "Lock Project" else "🔒")  # the toolbar shows only this
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
        locked = not view.document.locked
        self._window._set_project_locked(view.document, locked)
        if not locked:
            self._window.statusBar().showMessage(
                f"{project_title(view.document.path)} is unlocked: every book of it is editable", 6000
            )
        return view.document.locked


def ask_wrap_project(parent, *, forward: bool, group: bool = False) -> bool:
    """Find or Replace ran past the project's (or, with `group`, the
    group's) last or first book: True to carry on from the other end."""

    what = "group" if group else "project"
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Question)
    box.setWindowTitle(f"End of {what.capitalize()}")
    box.setText(
        f"No more matches to the end of the {what}."
        if forward
        else f"No more matches back to the start of the {what}."
    )
    box.setInformativeText(
        ("Continue from the first book?" if forward else "Continue from the last book?")
        if not group
        else ("Continue from the first project's first book?" if forward else "Continue from the last project's last book?")
    )
    go = box.addButton("Continue", QMessageBox.ButtonRole.AcceptRole)
    box.addButton(QMessageBox.StandardButton.Cancel)
    box.setDefaultButton(go)
    box.exec()
    return box.clickedButton() is go


class UnlockBanner(QWidget):
    """A red bar above the editor while the shown book's project is
    unlocked: every book of it can be changed. Its button locks the
    project again."""

    def __init__(self, window, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._window = window
        self._message = ""
        self.setObjectName("unlockBanner")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(
            "#unlockBanner { background: #b3261e; }"
            "#unlockBanner QLabel { color: #ffffff; font-weight: bold; }"
            "#unlockBanner QPushButton { color: #b3261e; background: #ffffff; border: none; padding: 2px 10px; }"
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 3, 10, 3)
        self.label = QLabel(self)
        layout.addWidget(self.label, 1)
        self.button = QPushButton("Lock Project", self)
        self.button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.button.clicked.connect(lambda _checked=False: window._book_lock.toggle(window.current_view))
        layout.addWidget(self.button)
        # The same height with or without the button, so a permanent row doesn't jump.
        self.setMinimumHeight(self.button.sizeHint().height() + 6)
        self.hide()

    _IDLE_STYLE = (
        "#unlockBanner { background: transparent; }"
        "#unlockBanner QLabel { color: palette(mid); font-weight: normal; }"
    )
    _LOCKED_STYLE = (
        "#unlockBanner { background: #b3261e; }"
        "#unlockBanner QLabel { color: #ffffff; font-weight: bold; }"
        "#unlockBanner QPushButton { color: #b3261e; background: #ffffff; border: none; padding: 2px 10px; }"
    )

    def set_message(self, text: str) -> None:
        """A message in the permanent status line of an environment window
        (N38: warnings and function messages); "" blanks it. The unlock
        notice takes the line while a project is unlocked."""

        self._message = text
        self.refresh(self._window.current_view)

    def refresh(self, view) -> None:
        """An environment window always shows this row (blank when idle, so
        the layout never jumps); other windows show it only while a project
        is unlocked. Unlocked: the red notice and its Lock button."""

        unlocked = (
            view is not None
            and self._window._book_lock.applies_to(view)
            and not view.document.locked
            and not view.document.read_only
        )
        permanent = getattr(self._window, "environment_window", None) is not None
        if unlocked:
            self.label.setText(
                f"UNLOCKED: {project_title(view.document.path)} can be edited, every book of it"
            )
            self.setStyleSheet(self._LOCKED_STYLE)
        else:
            self.label.setText(self._message)
            self.setStyleSheet(self._IDLE_STYLE)
        self.button.setVisible(unlocked)
        self.setVisible(unlocked or permanent)
