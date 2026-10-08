"""Modal editor for document group (tag) names and colors: one environment's
groups, with the environment chosen at the top (round 3 T2)."""
from __future__ import annotations

from dataclasses import replace
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QColorDialog,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
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
    """Add, rename, recolor, and remove document groups before Save/Cancel.

    With `environments` ([(key, label, groups)]) it edits each environment's
    groups, starting at `environment`; `groups` is then that environment's.
    With `window_names` ({key: [name, …]}) it also edits each environment's
    window names (round 3 T3, D4), as one comma-separated line.
    """

    def __init__(
        self,
        groups: tuple[DocumentGroup, ...],
        parent=None,
        *,
        environments=None,
        environment: str | None = None,
        window_names=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Document Groups")
        self._by_environment: dict[str | None, list[DocumentGroup]] = {}
        self._labels: dict[str | None, str] = {}
        for key, label, environment_groups in environments or ():
            self._by_environment[key] = list(environment_groups)
            self._labels[key] = label
        self._key = environment if environment in self._by_environment else None
        self._by_environment[self._key] = list(groups)
        self.environment_choice = QComboBox(self)
        for key, label in self._labels.items():
            self.environment_choice.addItem(label, key)
        self.environment_choice.setVisible(bool(self._labels))
        if self._key is not None:
            self.environment_choice.setCurrentIndex(self.environment_choice.findData(self._key))
        self.environment_choice.currentIndexChanged.connect(self._environment_chosen)
        self._window_names: dict[str | None, str] = {
            key: ", ".join(names) for key, names in (window_names or {}).items()
        }
        self.window_names_label = QLabel("Window names:", self)
        self.window_names_edit = QLineEdit(self)
        self.window_names_edit.setAccessibleName("Window names")
        self.window_names_edit.setToolTip("This environment's windows, in order, separated by commas (e.g. A, B, C)")
        self.window_names_edit.setText(self._window_names.get(self._key, ""))
        for widget in (self.window_names_label, self.window_names_edit):
            widget.setVisible(bool(self._window_names))

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
        layout.addWidget(self.environment_choice)
        layout.addWidget(self._list)
        names_row = QHBoxLayout()
        names_row.addWidget(self.window_names_label)
        names_row.addWidget(self.window_names_edit, 1)
        layout.addLayout(names_row)
        layout.addLayout(buttons)
        self.resize(360, 320)

    @property
    def _groups(self) -> list[DocumentGroup]:
        return self._by_environment[self._key]

    def groups(self) -> tuple[DocumentGroup, ...]:
        """The shown environment's groups."""

        return tuple(self._groups)

    def groups_by_environment(self) -> dict[str, tuple[DocumentGroup, ...]]:
        """Every environment's groups, as edited."""

        return {key: tuple(groups) for key, groups in self._by_environment.items() if key is not None}

    def window_names_by_environment(self) -> dict[str, list[str]]:
        """Every environment's window names, as edited."""

        self._window_names[self._key] = self.window_names_edit.text()
        return {
            key: [name.strip() for name in text.split(",") if name.strip()]
            for key, text in self._window_names.items()
            if key is not None
        }

    def set_environment(self, key: str) -> None:
        self.environment_choice.setCurrentIndex(self.environment_choice.findData(key))

    def _environment_chosen(self, index: int) -> None:
        key = self.environment_choice.itemData(index)
        if key in self._by_environment:
            if self._window_names:
                self._window_names[self._key] = self.window_names_edit.text()
            self._key = key
            self.window_names_edit.setText(self._window_names.get(key, ""))
            self._populate()

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
