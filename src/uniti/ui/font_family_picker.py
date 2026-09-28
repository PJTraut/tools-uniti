"""Modal picker for the editor's per-view font family override (BF-074).

Restricted to fixed-pitch fonts: every metric this editor computes (cell
width, tab stops, whitespace-marker centering, cursor positioning) assumes
a uniform character width, an invariant a proportional font would
silently violate. Family only -- weight and zoom stay independent,
exactly as they already are for the auto-resolved default font.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


class FontFamilyPicker(QDialog):
    """Lets the user choose any installed fixed-pitch font as this view's
    font family override, or reset to the auto-resolved default."""

    def __init__(
        self,
        current_family: str | None,
        *,
        default_family: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Font")
        self.resize(360, 420)

        layout = QVBoxLayout(self)
        self._filter = QLineEdit(self)
        self._filter.setPlaceholderText("Filter fonts…")
        self._filter.setAccessibleName("Filter fonts")
        self._filter.textChanged.connect(self._apply_filter)
        layout.addWidget(self._filter)

        self._list = QListWidget(self)
        self._list.setAccessibleName("Font family")
        layout.addWidget(self._list, 1)

        default_item = QListWidgetItem(f"Default ({default_family})")
        default_item.setData(Qt.ItemDataRole.UserRole, None)
        self._list.addItem(default_item)

        families = sorted(
            family
            for family in QFontDatabase.families()
            if QFontDatabase.isFixedPitch(family)
        )
        for family in families:
            item = QListWidgetItem(family)
            item.setData(Qt.ItemDataRole.UserRole, family)
            item.setFont(QFont(family))
            self._list.addItem(item)

        self._select_current(current_family)
        self._list.itemDoubleClicked.connect(lambda _item: self.accept())

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _select_current(self, current_family: str | None) -> None:
        for row in range(self._list.count()):
            item = self._list.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == current_family:
                self._list.setCurrentItem(item)
                return
        self._list.setCurrentRow(0)

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for row in range(self._list.count()):
            item = self._list.item(row)
            item.setHidden(bool(needle) and needle not in item.text().lower())

    def selected_family(self) -> str | None:
        """The chosen family, or `None` for "use the auto-resolved
        default" -- only meaningful after `exec()` returns Accepted."""

        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item is not None else None


__all__ = ["FontFamilyPicker"]
