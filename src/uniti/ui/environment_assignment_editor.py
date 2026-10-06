"""View > File Type Environments… — assign file extensions to environments (ADR-0014).

Replaces BF-063's flat "extension -> syntax profile" override list with one
row per environment showing every extension it owns (defaults included), so
e.g. giving USFM both ``.usfm`` and ``.sfm`` is one edit on one row. Saving
stores only the difference from the defaults, in the same
`Settings.syntax_extension_overrides` map BF-063 already persisted.
"""

from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from uniti.core.environments.catalog import (
    ENVIRONMENTS,
    PLAIN_ENVIRONMENT_KEY,
    ExtensionAssignmentError,
    extension_assignments,
    overrides_for_assignments,
)

_SEPARATORS = re.compile(r"[\s,;+]+")


def parse_extensions(text: str) -> list[str]:
    """``".USFM + .sfm"`` / ``"usfm, sfm"`` -> ``[".USFM", ".sfm"]`` (normalized later)."""

    return [part for part in _SEPARATORS.split(text) if part]


def format_extensions(extensions: tuple[str, ...]) -> str:
    return ", ".join(f".{extension}" for extension in extensions)


class EnvironmentAssignmentEditor(QDialog):
    TITLE = "File Type Environments"

    def __init__(self, overrides: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(self.TITLE)
        self._overrides = dict(overrides)

        hint = QLabel(
            "Extensions each environment opens, separated by commas "
            "(e.g. .usfm, .sfm). Unlisted extensions open as Plain Text.",
            self,
        )
        hint.setWordWrap(True)
        self.table = QTableWidget(len(ENVIRONMENTS), 2, self)
        self.table.setHorizontalHeaderLabels(["Environment", "Extensions"])
        self.table.verticalHeader().setVisible(False)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        self._populate(self._overrides)

        self.reset_button = QPushButton("Reset to Defaults", self)
        self.save_button = QPushButton("Save", self)
        self.cancel_button = QPushButton("Cancel", self)
        self.reset_button.clicked.connect(lambda: self._populate({}))
        self.save_button.clicked.connect(self._save)
        self.cancel_button.clicked.connect(self.reject)
        self.save_button.setDefault(True)

        buttons = QHBoxLayout()
        buttons.addWidget(self.reset_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)
        layout = QVBoxLayout(self)
        layout.addWidget(hint)
        layout.addWidget(self.table)
        layout.addLayout(buttons)
        self.resize(460, 380)

    def overrides(self) -> dict[str, str]:
        return dict(self._overrides)

    def assignments(self) -> dict[str, list[str]]:
        result: dict[str, list[str]] = {}
        for row, descriptor in enumerate(ENVIRONMENTS):
            item = self.table.item(row, 1)
            result[descriptor.key] = parse_extensions(item.text() if item is not None else "")
        return result

    def set_extensions(self, environment_key: str, text: str) -> None:
        for row, descriptor in enumerate(ENVIRONMENTS):
            if descriptor.key == environment_key:
                self.table.item(row, 1).setText(text)
                return
        raise KeyError(environment_key)

    def _populate(self, overrides: dict[str, str]) -> None:
        assignments = extension_assignments(overrides)
        for row, descriptor in enumerate(ENVIRONMENTS):
            label = QTableWidgetItem(descriptor.label)
            label.setFlags(label.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if descriptor.key == PLAIN_ENVIRONMENT_KEY:
                label.setToolTip("Extensions listed here are forced to Plain Text.")
            self.table.setItem(row, 0, label)
            self.table.setItem(
                row, 1, QTableWidgetItem(format_extensions(assignments[descriptor.key]))
            )

    def _save(self) -> None:
        try:
            self._overrides = overrides_for_assignments(self.assignments())
        except ExtensionAssignmentError as exc:
            QMessageBox.warning(self, self.TITLE, str(exc))
            return
        self.accept()
