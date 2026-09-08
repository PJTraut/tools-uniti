"""Modeless horizontal hotkey editor backed by the shared command registry."""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QGroupBox,
    QLabel,
    QPushButton,
    QKeySequenceEdit,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
)

from uniti.app.commands import CommandCategory, CommandRegistry, ShortcutCollision
from uniti.app.inspection_shortcut import (
    DEFAULT_INSPECTION_MODIFIERS,
    MODIFIER_NAMES,
    normalize_inspection_modifiers,
)


def _native_shortcut(shortcut: str) -> str:
    return QKeySequence.fromString(
        shortcut,
        QKeySequence.SequenceFormat.PortableText,
    ).toString(
        QKeySequence.SequenceFormat.NativeText
    )


class HotkeysPopup(QDialog):
    inspectionShortcutChanged = Signal(str)

    def __init__(self, registry: CommandRegistry, parent=None) -> None:
        super().__init__(parent)
        self.registry = registry
        self.last_error = ""
        self._category = CommandCategory.FILE
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowTitle("Hotkeys")
        self.resize(900, 430)

        category_row = QHBoxLayout()
        category_group = QButtonGroup(self)
        category_group.setExclusive(True)
        self.category_buttons: list[QToolButton] = []
        for category in CommandCategory:
            button = QToolButton(self)
            button.setText(category.value)
            button.setCheckable(True)
            button.clicked.connect(
                lambda _checked=False, category=category: self.select_category(category)
            )
            category_group.addButton(button)
            category_row.addWidget(button)
            self.category_buttons.append(button)
        self.category_buttons[0].setChecked(True)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(("Command", "Default", "Current"))
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.itemSelectionChanged.connect(self._load_selected_sequence)
        self.table.horizontalHeader().setStretchLastSection(True)

        assignment_row = QHBoxLayout()
        assignment_row.addWidget(QLabel("Shortcut:"))
        self.sequence_edit = QKeySequenceEdit(self)
        assignment_row.addWidget(self.sequence_edit, 1)
        assign_button = QPushButton("Assign / Change", self)
        clear_button = QPushButton("Clear", self)
        reset_selected_button = QPushButton("Reset Selected", self)
        reset_category_button = QPushButton("Reset Category", self)
        reset_all_button = QPushButton("Reset All", self)
        assignment_row.addWidget(assign_button)
        assignment_row.addWidget(clear_button)
        assignment_row.addWidget(reset_selected_button)
        assignment_row.addWidget(reset_category_button)
        assignment_row.addWidget(reset_all_button)

        self.error_label = QLabel("", self)
        self.error_label.setWordWrap(True)

        self.inspection_group = QGroupBox("Hold to inspect Unicode", self)
        inspection_layout = QVBoxLayout(self.inspection_group)
        self.inspection_label = QLabel(self.inspection_group)
        self.inspection_label.setWordWrap(True)
        inspection_layout.addWidget(self.inspection_label)
        inspection_layout.addWidget(QLabel(
            "Hold to reveal whitespace details in the selected whitespace mode, "
            "or inspect one selected Unicode code point. Release to hide.\n"
            "Choose at least two modifiers; clear all to disable.", self.inspection_group
        ))
        modifier_row = QHBoxLayout()
        native_names = (
            {"Ctrl": "Cmd", "Alt": "Option", "Shift": "Shift", "Meta": "Control"}
            if sys.platform == "darwin"
            else {"Ctrl": "Ctrl", "Alt": "Alt", "Shift": "Shift", "Meta": "Win / Meta"}
        )
        self._inspection_names = native_names
        self.inspection_checks = {}
        for name in MODIFIER_NAMES:
            checkbox = QCheckBox(native_names[name], self.inspection_group)
            self.inspection_checks[name] = checkbox
            modifier_row.addWidget(checkbox)
        apply_inspection = QPushButton("Apply Hold Shortcut", self.inspection_group)
        reset_inspection = QPushButton("Reset Hold Shortcut", self.inspection_group)
        modifier_row.addWidget(apply_inspection)
        modifier_row.addWidget(reset_inspection)
        inspection_layout.addLayout(modifier_row)
        apply_inspection.clicked.connect(self._apply_inspection_shortcut)
        reset_inspection.clicked.connect(self._reset_inspection_shortcut)
        self.set_inspection_modifiers(DEFAULT_INSPECTION_MODIFIERS)
        self.inspection_group.hide()

        layout = QVBoxLayout(self)
        layout.addLayout(category_row)
        layout.addWidget(self.table, 1)
        layout.addLayout(assignment_row)
        layout.addWidget(self.inspection_group)
        layout.addWidget(self.error_label)

        assign_button.clicked.connect(self._assign_selected)
        clear_button.clicked.connect(self._clear_selected)
        reset_selected_button.clicked.connect(self._reset_selected)
        reset_category_button.clicked.connect(self.reset_current_category)
        reset_all_button.clicked.connect(self.reset_all)
        self._remove_listener = self.registry.add_listener(
            lambda _command_id, _shortcut: self._populate_table()
        )
        self._populate_table()

    def set_inspection_modifiers(self, value: str) -> None:
        selected = normalize_inspection_modifiers(value)
        for name, checkbox in self.inspection_checks.items():
            checkbox.setChecked(name in selected.split("+"))
        def native(modifiers):
            return "+".join(self._inspection_names[n] for n in modifiers.split("+") if n) or "Disabled"
        self.inspection_label.setText(
            f"Current: {native(selected)}    Default: {native(DEFAULT_INSPECTION_MODIFIERS)}"
        )

    def _apply_inspection_shortcut(self) -> None:
        selected = "+".join(n for n, check in self.inspection_checks.items() if check.isChecked())
        try:
            selected = normalize_inspection_modifiers(selected)
        except ValueError as exc:
            self.last_error = str(exc)
            self.error_label.setText(self.last_error)
            return
        self.last_error = ""
        self.error_label.clear()
        self.set_inspection_modifiers(selected)
        self.inspectionShortcutChanged.emit(selected)

    def _reset_inspection_shortcut(self) -> None:
        self.set_inspection_modifiers(DEFAULT_INSPECTION_MODIFIERS)
        self._apply_inspection_shortcut()

    def _selected_command_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        if item is None:
            return None
        command_id = item.data(Qt.ItemDataRole.UserRole)
        return command_id if isinstance(command_id, str) else None

    def _populate_table(self) -> None:
        selected = self._selected_command_id()
        definitions = self.registry.definitions(category=self._category)
        self.table.setRowCount(len(definitions))
        selected_row = -1
        for row, definition in enumerate(definitions):
            command_item = QTableWidgetItem(definition.label)
            command_item.setData(Qt.ItemDataRole.UserRole, definition.command_id)
            self.table.setItem(row, 0, command_item)
            self.table.setItem(
                row,
                1,
                QTableWidgetItem(_native_shortcut(definition.default_shortcut)),
            )
            self.table.setItem(
                row,
                2,
                QTableWidgetItem(
                    _native_shortcut(self.registry.current(definition.command_id))
                ),
            )
            if definition.command_id == selected:
                selected_row = row
        self.table.resizeColumnsToContents()
        if selected_row >= 0:
            self.table.selectRow(selected_row)
        elif definitions:
            self.table.selectRow(0)

    def _load_selected_sequence(self) -> None:
        command_id = self._selected_command_id()
        if command_id is None:
            self.sequence_edit.clear()
            return
        self.sequence_edit.setKeySequence(
            QKeySequence.fromString(
                self.registry.current(command_id),
                QKeySequence.SequenceFormat.PortableText,
            )
        )

    def select_category(self, category: CommandCategory) -> None:
        self._category = category
        self.inspection_group.setVisible(category == CommandCategory.EDITOR_VIEW)
        for button, candidate in zip(self.category_buttons, CommandCategory):
            button.setChecked(candidate == category)
        self.last_error = ""
        self.error_label.clear()
        self._populate_table()

    def assign_sequence(self, command_id: str, shortcut: str) -> bool:
        portable = QKeySequence.fromString(
            shortcut,
            QKeySequence.SequenceFormat.PortableText,
        ).toString(
            QKeySequence.SequenceFormat.PortableText
        )
        if shortcut and not portable:
            self.last_error = f"Invalid shortcut: {shortcut}"
            self.error_label.setText(self.last_error)
            return False
        try:
            self.registry.assign(command_id, portable)
        except ShortcutCollision as exc:
            conflict = self.registry.definition(exc.conflicting_command_id)
            self.last_error = (
                f"{portable} is already assigned to {conflict.label} "
                f"in an overlapping scope."
            )
            self.error_label.setText(self.last_error)
            return False
        self.last_error = ""
        self.error_label.clear()
        return True

    def clear_sequence(self, command_id: str) -> bool:
        self.registry.clear(command_id)
        self.last_error = ""
        self.error_label.clear()
        return True

    def reset_selected(self, command_id: str) -> None:
        self.registry.reset(command_id)

    def reset_current_category(self) -> None:
        self.registry.reset_category(self._category)
        if self._category == CommandCategory.EDITOR_VIEW:
            self._reset_inspection_shortcut()

    def reset_all(self) -> None:
        self.registry.reset_all()
        self._reset_inspection_shortcut()

    def _assign_selected(self) -> None:
        command_id = self._selected_command_id()
        if command_id is None:
            return
        shortcut = self.sequence_edit.keySequence().toString(
            QKeySequence.SequenceFormat.PortableText
        )
        self.assign_sequence(command_id, shortcut)

    def _clear_selected(self) -> None:
        command_id = self._selected_command_id()
        if command_id is not None:
            self.clear_sequence(command_id)

    def _reset_selected(self) -> None:
        command_id = self._selected_command_id()
        if command_id is not None:
            self.reset_selected(command_id)

    def show_below(self, widget) -> None:
        point = widget.mapToGlobal(widget.rect().bottomLeft())
        self.move(point)
        self.show()
        self.raise_()
        self.activateWindow()

    def reject(self) -> None:
        self.hide()
