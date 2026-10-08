"""Configuration Files… — the configuration that applies to a document
(field test round 2, R8).

Lists every configuration file of the active tab's environment, in the
order they apply (`core.environments.configuration`), and lets the user
open and edit them in UNITI, create the ones that don't exist yet from a
template, copy a built-in file to read, or show a file in its folder.
Saving one of these files reloads the environment (see
`UNITIMainWindow._configuration_saved`).
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QUrl, Qt
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

import uniti
from uniti.core.environments.configuration import BUILT_IN, ConfigurationFile, configuration_files, reference_copy_path

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

_KIND_LABELS = {"built-in": "Built in", "yours": "Yours", "project": "Project", "loaded": "Loaded"}


def environment_documentation(environment_key: str) -> Path | None:
    """`docs/environments/<page>.md` of a source checkout, when present."""

    page = {"plain_text": "plain-text"}.get(environment_key, environment_key)
    root = Path(uniti.__file__).resolve().parents[2] / "docs" / "environments"
    path = root / f"{page}.md"
    return path if path.is_file() else None


class ConfigurationFilesDialog(QDialog):
    def __init__(self, window: "UNITIMainWindow", view: "UNITITextView") -> None:
        super().__init__(window)
        self._window = window
        self._view = view
        descriptor = window._environment.descriptor_for(view.document)
        self.environment_key = descriptor.key
        self.environment_label = descriptor.label
        self.setWindowTitle(f"{descriptor.label} Configuration Files")
        self.resize(820, 420)
        self.rows: tuple[ConfigurationFile, ...] = ()

        intro = QLabel(
            f"The configuration that applies to {view.document.path.name}, in the order it applies "
            "(later rows win). Built-in files can't be changed; your files and the project's can be "
            "opened and edited here, and saving one reloads the environment.",
            self,
        )
        intro.setWordWrap(True)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["File", "Kind", "Location", "Status"])
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.itemSelectionChanged.connect(self._sync_buttons)
        self.tree.itemDoubleClicked.connect(lambda _item, _column: self.open_selected())
        self.note = QLabel(self)
        self.note.setWordWrap(True)

        self.open_button = QPushButton("Open", self)
        self.open_button.clicked.connect(self.open_selected)
        self.create_button = QPushButton("Create", self)
        self.create_button.clicked.connect(self.create_selected)
        self.copy_button = QPushButton("Copy to My Configuration and Open", self)
        self.copy_button.clicked.connect(self.copy_selected)
        self.folder_button = QPushButton("Show in Folder", self)
        self.folder_button.clicked.connect(self.show_selected_in_folder)
        self.docs_button = QPushButton(f"{descriptor.label} Documentation", self)
        self.docs_button.clicked.connect(self.open_documentation)
        self.docs_button.setEnabled(environment_documentation(self.environment_key) is not None)
        actions = QHBoxLayout()
        for button in (self.open_button, self.create_button, self.copy_button, self.folder_button):
            actions.addWidget(button)
        actions.addStretch(1)
        actions.addWidget(self.docs_button)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(intro)
        layout.addWidget(self.tree, 1)
        layout.addWidget(self.note)
        layout.addLayout(actions)
        layout.addWidget(close)
        self.refresh()

    # --- rows -------------------------------------------------------------------

    def refresh(self) -> None:
        environment = self._window._environment.active_for(self._view.document).environment
        self.rows = configuration_files(
            self.environment_key, self.environment_label, self._view.document.path, environment
        )
        selected = self.tree.currentIndex().row()
        self.tree.clear()
        for row in self.rows:
            if row.exists:
                status = "folder" if row.is_folder else "in use"
            else:
                status = "can be created" if row.template is not None else "not present"
            item = QTreeWidgetItem(
                [row.role, _KIND_LABELS.get(row.kind, row.kind), "" if row.path is None else str(row.path), status]
            )
            item.setToolTip(2, "" if row.path is None else str(row.path))
            if not row.exists:
                for column in range(4):
                    item.setForeground(column, self.palette().placeholderText())
            self.tree.addTopLevelItem(item)
        for column in range(3):
            self.tree.resizeColumnToContents(column)
        if self.rows:
            self.tree.setCurrentItem(self.tree.topLevelItem(min(max(selected, 0), len(self.rows) - 1)))
        self._sync_buttons()

    def selected(self) -> ConfigurationFile | None:
        index = self.tree.currentIndex().row()
        return self.rows[index] if 0 <= index < len(self.rows) else None

    def select_role(self, role: str) -> None:
        for index, row in enumerate(self.rows):
            if row.role == role:
                self.tree.setCurrentItem(self.tree.topLevelItem(index))
                return

    def _sync_buttons(self) -> None:
        row = self.selected()
        self.open_button.setEnabled(row is not None and row.exists and not row.is_folder)
        self.create_button.setEnabled(row is not None and not row.exists and row.template is not None)
        self.copy_button.setEnabled(row is not None and row.kind == BUILT_IN and row.exists and reference_copy_path(self.environment_label, row.path) is not None)
        self.folder_button.setEnabled(row is not None and row.path is not None and (row.exists or row.kind == "yours"))
        self.note.setText("" if row is None else row.note)

    # --- actions --------------------------------------------------------------------

    def open_selected(self):
        row = self.selected()
        if row is None or not row.exists:
            return None
        if row.is_folder:
            return self.show_selected_in_folder()
        if row.kind == BUILT_IN:
            return self.copy_selected()
        return self._window.open_configuration_file(row.path)

    def create_selected(self):
        """Write the row's template where it belongs, then open it."""

        row = self.selected()
        if row is None or row.exists or row.template is None or row.path is None:
            return None
        try:
            row.path.parent.mkdir(parents=True, exist_ok=True)
            with row.path.open("x", encoding="utf-8") as handle:
                handle.write(row.template)
        except OSError as exc:
            QMessageBox.warning(self, "Create Configuration File", f"{row.path}\n\n{exc}")
            return None
        self.refresh()
        return self._window.open_configuration_file(row.path)

    def copy_selected(self):
        """Copy a built-in file into the user's folder to read it there."""

        row = self.selected()
        if row is None or row.kind != BUILT_IN or row.path is None:
            return None
        target = reference_copy_path(self.environment_label, row.path)
        if target is None:
            return None
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(row.path, target)
        except OSError as exc:
            QMessageBox.warning(self, "Copy Configuration File", f"{target}\n\n{exc}")
            return None
        return self._window.open_configuration_file(target)

    def show_selected_in_folder(self) -> Path | None:
        row = self.selected()
        if row is None or row.path is None:
            return None
        folder = row.path if row.is_folder else row.path.parent
        if row.kind == "yours":
            folder.mkdir(parents=True, exist_ok=True)
            self.refresh()
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
        return folder

    def open_documentation(self) -> None:
        path = environment_documentation(self.environment_key)
        if path is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


__all__ = ["ConfigurationFilesDialog", "environment_documentation"]
