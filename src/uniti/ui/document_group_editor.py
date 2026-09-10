"""Modal editor for document group (tag) names and colors."""
from __future__ import annotations

from dataclasses import replace
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from uniti.app.document_groups import DocumentGroup, MAX_GROUPS


def _swatch_icon(color: str) -> QIcon:
    pixmap = QPixmap(14, 14)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 12, 12)
    finally:
        painter.end()
    return QIcon(pixmap)


class DocumentGroupEditor(QDialog):
    """Add, rename, recolor, and remove document groups before Save/Cancel."""

    def __init__(self, groups: tuple[DocumentGroup, ...], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Document Groups")
        self._groups: list[DocumentGroup] = list(groups)

        self._list = QListWidget(self)
        self._list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._populate()

        self.add_button = QPushButton("Add", self)
        self.rename_button = QPushButton("Rename", self)
        self.recolor_button = QPushButton("Recolor", self)
        self.remove_button = QPushButton("Remove", self)
        self.save_button = QPushButton("Save", self)
        self.cancel_button = QPushButton("Cancel", self)
        self.add_button.clicked.connect(self._add)
        self.rename_button.clicked.connect(self._rename)
        self.recolor_button.clicked.connect(self._recolor)
        self.remove_button.clicked.connect(self._remove)
        self.save_button.clicked.connect(self.accept)
        self.cancel_button.clicked.connect(self.reject)

        buttons = QHBoxLayout()
        for button in (
            self.add_button,
            self.rename_button,
            self.recolor_button,
            self.remove_button,
        ):
            buttons.addWidget(button)
        buttons.addStretch(1)
        buttons.addWidget(self.cancel_button)
        buttons.addWidget(self.save_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self._list)
        layout.addLayout(buttons)
        self.resize(360, 320)

    def groups(self) -> tuple[DocumentGroup, ...]:
        return tuple(self._groups)

    def _populate(self) -> None:
        self._list.clear()
        for group in self._groups:
            item = QListWidgetItem(group.name)
            item.setData(Qt.ItemDataRole.UserRole, group.id)
            item.setIcon(_swatch_icon(group.color))
            self._list.addItem(item)

    def _selected_index(self) -> int | None:
        row = self._list.currentRow()
        return row if row >= 0 else None

    def _warn(self, message: str) -> None:
        QMessageBox.warning(self, "Document Groups", message)

    def _add(self) -> None:
        if len(self._groups) >= MAX_GROUPS:
            self._warn(f"At most {MAX_GROUPS} groups are supported.")
            return
        name, ok = QInputDialog.getText(self, "Add Group", "Group name:")
        if not ok or not name.strip():
            return
        color = QColorDialog.getColor(QColor("#8888ff"), self, "Group Color")
        if not color.isValid():
            return
        try:
            group = DocumentGroup(uuid.uuid4().hex, name.strip(), color.name())
        except ValueError as exc:
            self._warn(str(exc))
            return
        self._groups.append(group)
        self._populate()
        self._list.setCurrentRow(len(self._groups) - 1)

    def _rename(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        current = self._groups[index]
        name, ok = QInputDialog.getText(
            self, "Rename Group", "Group name:", text=current.name
        )
        if not ok or not name.strip():
            return
        try:
            self._groups[index] = replace(current, name=name.strip())
        except ValueError as exc:
            self._warn(str(exc))
            return
        self._populate()
        self._list.setCurrentRow(index)

    def _recolor(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        current = self._groups[index]
        color = QColorDialog.getColor(QColor(current.color), self, "Group Color")
        if not color.isValid():
            return
        self._groups[index] = replace(current, color=color.name())
        self._populate()
        self._list.setCurrentRow(index)

    def _remove(self) -> None:
        index = self._selected_index()
        if index is None:
            return
        del self._groups[index]
        self._populate()
