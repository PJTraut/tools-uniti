"""Modal editor for the file-extension → syntax-profile assignment (BF-063).

Only the mapping half of BF-063's two-piece request (`settings.
syntax_extension_overrides`, `uniti.core.syntax_profiles.profile_for_extension`)
— the syntax-category color half stays parked; see the Parked Capability
Catalog and ADR-0009's un-parking precedent.
"""
from __future__ import annotations

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from uniti.core.syntax_profiles import PROFILES, PROFILES_BY_KEY

MAX_OVERRIDES = 64
_EXTENSION_RE = re.compile(r"[A-Za-z0-9_-]{1,32}")


def _normalize_extension(text: str) -> str | None:
    normalized = text.strip().lower().lstrip(".")
    if not _EXTENSION_RE.fullmatch(normalized):
        return None
    return normalized


class ExtensionProfileEditor(QDialog):
    """Assign/reassign which syntax profile applies to a file extension."""

    def __init__(self, overrides: dict[str, str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Text-Type Profiles")
        self._overrides: dict[str, str] = dict(overrides)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._populate()

        self.add_button = QPushButton("Add", self)
        self.change_button = QPushButton("Change Profile", self)
        self.remove_button = QPushButton("Remove", self)
        self.save_button = QPushButton("Save", self)
        self.cancel_button = QPushButton("Cancel", self)
        self.add_button.clicked.connect(self._add)
        self.change_button.clicked.connect(self._change)
        self.remove_button.clicked.connect(self._remove)
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        for button in (self.add_button, self.change_button, self.remove_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(buttons)
        self.resize(360, 320)

    def overrides(self) -> dict[str, str]:
        return dict(self._overrides)

    def _populate(self) -> None:
        self._list.clear()
        for extension, profile_key in sorted(self._overrides.items()):
            profile = PROFILES_BY_KEY.get(profile_key)
            label = profile.label if profile is not None else profile_key
            item = QListWidgetItem(f".{extension} → {label}")
            item.setData(Qt.ItemDataRole.UserRole, extension)
            self._list.addItem(item)

    def _selected_extension(self) -> str | None:
        row = self._list.currentRow()
        if row < 0:
            return None
        return self._list.item(row).data(Qt.ItemDataRole.UserRole)

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Text-Type Profiles", message)

    def _choose_profile(self, current_key: str | None = None) -> str | None:
        labels = [profile.label for profile in PROFILES]
        current_index = 0
        if current_key is not None:
            for index, profile in enumerate(PROFILES):
                if profile.key == current_key:
                    current_index = index
                    break
        label, accepted = QInputDialog.getItem(
            self,
            "Text-Type Profiles",
            "Syntax profile:",
            labels,
            current_index,
            editable=False,
        )
        if not accepted:
            return None
        return PROFILES[labels.index(label)].key

    def _add(self) -> None:
        if len(self._overrides) >= MAX_OVERRIDES:
            self._warn(f"At most {MAX_OVERRIDES} extension assignments are supported.")
            return
        text, ok = QInputDialog.getText(
            self, "Add Extension", "File extension (e.g. usj):"
        )
        if not ok:
            return
        extension = _normalize_extension(text)
        if extension is None:
            self._warn("Extension must be 1-32 letters, digits, underscores or hyphens.")
            return
        profile_key = self._choose_profile(self._overrides.get(extension))
        if profile_key is None:
            return
        self._overrides[extension] = profile_key
        self._populate()

    def _change(self) -> None:
        extension = self._selected_extension()
        if extension is None:
            return
        profile_key = self._choose_profile(self._overrides.get(extension))
        if profile_key is None:
            return
        self._overrides[extension] = profile_key
        self._populate()

    def _remove(self) -> None:
        extension = self._selected_extension()
        if extension is None:
            return
        self._overrides.pop(extension, None)
        self._populate()
