"""Modal editor for renaming/removing saved Find/Replace recipes."""
from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from uniti.app.find_replace_recipes import FindReplaceRecipe


class FindReplaceRecipeEditor(QDialog):
    """Rename or remove saved recipes. New recipes are added from the panel
    itself ("Save Current as Recipe…"), not from this dialog."""

    def __init__(self, recipes: tuple[FindReplaceRecipe, ...], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Find/Replace Recipes")
        self._recipes: list[FindReplaceRecipe] = list(recipes)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._populate()

        self.rename_button = QPushButton("Rename", self)
        self.remove_button = QPushButton("Remove", self)
        self.save_button = QPushButton("Save", self)
        self.cancel_button = QPushButton("Cancel", self)
        self.rename_button.clicked.connect(self._rename)
        self.remove_button.clicked.connect(self._remove)
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        buttons.addWidget(self.rename_button)
        buttons.addWidget(self.remove_button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(buttons)
        self.resize(360, 320)

    def recipes(self) -> tuple[FindReplaceRecipe, ...]:
        return tuple(self._recipes)

    def _populate(self) -> None:
        self._list.clear()
        for recipe in self._recipes:
            item = QListWidgetItem(recipe.name)
            item.setData(0x0100, recipe.id)
            self._list.addItem(item)

    def _selected_index(self) -> int | None:
        row = self._list.currentRow()
        return row if row >= 0 else None

    def _rename(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        current = self._recipes[index]
        name, ok = QInputDialog.getText(
            self, "Rename Recipe", "Recipe name:", text=current.name
        )
        if not ok or not name.strip():
            return
        self._recipes[index] = replace(current, name=name.strip())
        self._populate()
        self._list.setCurrentRow(index)

    def _remove(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        del self._recipes[index]
        self._populate()
