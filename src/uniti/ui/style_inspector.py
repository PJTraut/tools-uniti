"""Marker/Style Inspector window (ADR-0015; spec §47).

A filterable list of every marker the active document's layered
stylesheets define, and — for the selected one — its identity, structure,
semantics and presentation, each with the stylesheet layer it came from
and the base value it overrides. Pure presentation over
`core/environments/sfm/inspection.py`.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from uniti.core.environments.sfm.inspection import inspect_marker
from uniti.core.environments.sfm.style_layers import LayeredStyleRegistry


class StyleInspector(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setModal(False)
        self.setWindowTitle("Style Inspector")
        self._registry: LayeredStyleRegistry | None = None

        self.filter = QLineEdit(self)
        self.filter.setPlaceholderText("Filter markers")
        self.filter.textChanged.connect(self._apply_filter)
        self.markers = QListWidget(self)
        self.markers.currentItemChanged.connect(self._show_current)
        left = QWidget(self)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(self.filter)
        left_layout.addWidget(self.markers)

        self.heading = QLabel(self)
        self.heading.setTextFormat(Qt.TextFormat.PlainText)
        font = self.heading.font()
        font.setBold(True)
        self.heading.setFont(font)
        self.details = QTreeWidget(self)
        self.details.setColumnCount(4)
        self.details.setHeaderLabels(["Property", "Value", "Source", "Base"])
        right = QWidget(self)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.addWidget(self.heading)
        right_layout.addWidget(self.details)

        splitter = QSplitter(self)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setStretchFactor(1, 3)
        layout = QHBoxLayout(self)
        layout.addWidget(splitter)
        self.resize(820, 480)

    def set_registry(self, title: str, registry: LayeredStyleRegistry, selected: str | None) -> None:
        self.setWindowTitle(title)
        self._registry = registry
        self.filter.blockSignals(True)
        self.filter.clear()
        self.filter.blockSignals(False)
        self.markers.clear()
        names = list(registry.markers())
        if selected is not None and selected not in names:
            names.append(selected)
        for name in sorted(names):
            item = QListWidgetItem(f"\\{name}")
            item.setData(Qt.ItemDataRole.UserRole, name)
            self.markers.addItem(item)
        self.select_marker(selected)

    def select_marker(self, marker: str | None) -> None:
        for row in range(self.markers.count()):
            item = self.markers.item(row)
            if item.data(Qt.ItemDataRole.UserRole) == marker:
                self.markers.setCurrentItem(item)
                return
        if self.markers.count():
            self.markers.setCurrentRow(0)
        else:
            self.heading.setText("No markers defined by the loaded stylesheets.")
            self.details.clear()

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lstrip("\\").lower()
        for row in range(self.markers.count()):
            item = self.markers.item(row)
            item.setHidden(bool(needle) and needle not in item.data(Qt.ItemDataRole.UserRole).lower())

    def _show_current(self, current: QListWidgetItem | None, _previous=None) -> None:
        self.details.clear()
        if current is None or self._registry is None:
            return
        inspection = inspect_marker(self._registry, current.data(Qt.ItemDataRole.UserRole))
        self.heading.setText(f"Marker: \\{inspection.marker}")
        for heading, rows in inspection.sections:
            section = QTreeWidgetItem(self.details, [heading])
            section.setFirstColumnSpanned(True)
            for row in rows:
                QTreeWidgetItem(section, [row.label, row.value, row.origin or "", row.base or ""])
            section.setExpanded(True)
        for column in range(4):
            self.details.resizeColumnToContents(column)

    def current_marker(self) -> str | None:
        item = self.markers.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def detail_rows(self) -> dict[str, tuple[str, str, str]]:
        """Flattened {label: (value, source, base)} for the selected marker (tests)."""

        rows: dict[str, tuple[str, str, str]] = {}
        for index in range(self.details.topLevelItemCount()):
            section = self.details.topLevelItem(index)
            for child_index in range(section.childCount()):
                child = section.child(child_index)
                rows[child.text(0)] = (child.text(1), child.text(2), child.text(3))
        return rows
