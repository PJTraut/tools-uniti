"""Bounded, model-backed startup recovery decisions."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from PySide6.QtCore import QAbstractListModel, QModelIndex, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QListView,
    QMessageBox,
    QVBoxLayout,
)


MAX_RECOVERY_ENTRIES = 256


class RecoveryEntryKind(StrEnum):
    RECOVERABLE = "recoverable"
    SESSION_READY = "session_ready"
    CHANGED = "changed"
    MISSING = "missing"
    TRUNCATED = "truncated"
    CORRUPT = "corrupt"
    UNSUPPORTED = "unsupported"
    DEGRADED = "degraded"


class RecoveryAction(StrEnum):
    RECOVER = "recover"
    OPEN_DISK = "open_disk"
    LOCATE_MATCH = "locate_match"
    SKIP = "skip"
    DISCARD = "discard"


_ACTIONS_BY_KIND: dict[RecoveryEntryKind, tuple[RecoveryAction, ...]] = {
    RecoveryEntryKind.RECOVERABLE: (
        RecoveryAction.RECOVER,
        RecoveryAction.SKIP,
        RecoveryAction.DISCARD,
    ),
    RecoveryEntryKind.SESSION_READY: (
        RecoveryAction.RECOVER,
        RecoveryAction.SKIP,
        RecoveryAction.DISCARD,
    ),
    RecoveryEntryKind.CHANGED: (
        RecoveryAction.OPEN_DISK,
        RecoveryAction.SKIP,
        RecoveryAction.DISCARD,
    ),
    RecoveryEntryKind.MISSING: (
        RecoveryAction.LOCATE_MATCH,
        RecoveryAction.SKIP,
        RecoveryAction.DISCARD,
    ),
    RecoveryEntryKind.TRUNCATED: (
        RecoveryAction.RECOVER,
        RecoveryAction.SKIP,
        RecoveryAction.DISCARD,
    ),
    RecoveryEntryKind.CORRUPT: (
        RecoveryAction.SKIP,
        RecoveryAction.DISCARD,
    ),
    RecoveryEntryKind.UNSUPPORTED: (
        RecoveryAction.SKIP,
        RecoveryAction.DISCARD,
    ),
    RecoveryEntryKind.DEGRADED: (
        RecoveryAction.RECOVER,
        RecoveryAction.SKIP,
        RecoveryAction.DISCARD,
    ),
}

_KIND_LABELS = {
    RecoveryEntryKind.RECOVERABLE: "Recoverable changes",
    RecoveryEntryKind.SESSION_READY: "Saved session ready",
    RecoveryEntryKind.CHANGED: "File changed outside UNITI",
    RecoveryEntryKind.MISSING: "Source file missing",
    RecoveryEntryKind.TRUNCATED: "Recoverable durable prefix",
    RecoveryEntryKind.CORRUPT: "Invalid recovery data",
    RecoveryEntryKind.UNSUPPORTED: "Unsupported saved state",
    RecoveryEntryKind.DEGRADED: "Recovery durability degraded",
}

_ACTION_LABELS = {
    RecoveryAction.RECOVER: "Recover",
    RecoveryAction.OPEN_DISK: "Open Disk",
    RecoveryAction.LOCATE_MATCH: "Locate Matching File",
    RecoveryAction.SKIP: "Skip",
    RecoveryAction.DISCARD: "Discard",
}

_ACTION_CONSEQUENCES = {
    RecoveryAction.RECOVER: "Recover restores saved UNITI state.",
    RecoveryAction.OPEN_DISK: "Open Disk opens current bytes with fresh history.",
    RecoveryAction.LOCATE_MATCH: (
        "Locate Matching File imports only after an exact SHA-256 match."
    ),
    RecoveryAction.SKIP: "Skip preserves this evidence for later.",
    RecoveryAction.DISCARD: "Discard permanently removes only this UNITI evidence.",
}


def _bounded_text(value: str, label: str, *, maximum: int = 4096) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a nonempty string")
    if len(value.encode("utf-8")) > maximum:
        raise ValueError(f"{label} exceeds its safe display limit")
    return value


@dataclass(frozen=True, slots=True)
class RecoveryEntry:
    entry_id: str
    kind: RecoveryEntryKind
    path: Path
    message: str
    actions: tuple[RecoveryAction, ...]
    evidence_path: Path

    def __post_init__(self) -> None:
        _bounded_text(self.entry_id, "recovery entry ID", maximum=512)
        if not isinstance(self.kind, RecoveryEntryKind):
            raise TypeError("recovery entry kind must be a RecoveryEntryKind")
        if not isinstance(self.path, Path) or not isinstance(self.evidence_path, Path):
            raise TypeError("recovery entry paths must be Path values")
        _bounded_text(str(self.path), "recovery path")
        _bounded_text(str(self.evidence_path), "recovery evidence path")
        _bounded_text(self.message, "recovery message")
        if self.actions != _ACTIONS_BY_KIND[self.kind]:
            raise ValueError("recovery entry actions are unsafe for its kind")

    @classmethod
    def create(
        cls,
        *,
        entry_id: str,
        kind: RecoveryEntryKind,
        path: Path,
        message: str,
        evidence_path: Path,
    ) -> "RecoveryEntry":
        if not isinstance(kind, RecoveryEntryKind):
            raise TypeError("recovery entry kind must be a RecoveryEntryKind")
        return cls(
            entry_id,
            kind,
            Path(path),
            message,
            _ACTIONS_BY_KIND[kind],
            Path(evidence_path),
        )


@dataclass(frozen=True, slots=True)
class RecoveryDecision:
    entry_id: str
    action: RecoveryAction
    located_path: Path | None = None

    def __post_init__(self) -> None:
        _bounded_text(self.entry_id, "recovery decision entry ID", maximum=512)
        if not isinstance(self.action, RecoveryAction):
            raise TypeError("recovery decision action must be a RecoveryAction")
        if self.located_path is not None and not isinstance(self.located_path, Path):
            raise TypeError("located path must be a Path or None")
        if self.action is RecoveryAction.LOCATE_MATCH:
            if self.located_path is None:
                raise ValueError("Locate Matching File requires a selected path")
        elif self.located_path is not None:
            raise ValueError("only Locate Matching File accepts a selected path")


class RecoveryCenterModel(QAbstractListModel):
    """Expose immutable entries through bounded display and accessibility roles."""

    EntryRole = int(Qt.ItemDataRole.UserRole) + 1
    KindRole = EntryRole + 1
    ActionsRole = EntryRole + 2
    PathRole = EntryRole + 3

    def __init__(self, entries: Iterable[RecoveryEntry], parent=None) -> None:
        super().__init__(parent)
        selected = tuple(entries)
        if len(selected) > MAX_RECOVERY_ENTRIES:
            raise ValueError("too many recovery entries")
        if any(not isinstance(entry, RecoveryEntry) for entry in selected):
            raise TypeError("recovery model requires RecoveryEntry values")
        identifiers = tuple(entry.entry_id for entry in selected)
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("recovery entries contain duplicate IDs")
        self._entries = selected

    @property
    def entries(self) -> tuple[RecoveryEntry, ...]:
        return self._entries

    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._entries)

    @staticmethod
    def _display_text(entry: RecoveryEntry) -> str:
        return f"{_KIND_LABELS[entry.kind]} — {entry.path}\n{entry.message}"

    @staticmethod
    def _accessible_text(entry: RecoveryEntry) -> str:
        consequences = " ".join(
            _ACTION_CONSEQUENCES[action] for action in entry.actions
        )
        return (
            f"{_KIND_LABELS[entry.kind]}. Path: {entry.path}. "
            f"{entry.message} {consequences}"
        )

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._entries):
            return None
        entry = self._entries[index.row()]
        if role == Qt.ItemDataRole.DisplayRole:
            return self._display_text(entry)
        if role == Qt.ItemDataRole.AccessibleTextRole:
            return self._accessible_text(entry)
        if role == self.EntryRole:
            return entry
        if role == self.KindRole:
            return entry.kind
        if role == self.ActionsRole:
            return entry.actions
        if role == self.PathRole:
            return str(entry.path)
        return None

    def roleNames(self):
        names = dict(super().roleNames())
        names.update(
            {
                self.EntryRole: b"entry",
                self.KindRole: b"kind",
                self.ActionsRole: b"actions",
                self.PathRole: b"path",
            }
        )
        return names


class RecoveryCenterDialog(QDialog):
    """Collect explicit per-entry actions; dismissal always means Skip All."""

    def __init__(
        self,
        entries: Iterable[RecoveryEntry],
        parent=None,
        *,
        confirm_discard: Callable[[RecoveryEntry], bool] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("UNITI Recovery Center")
        self.setSizeGripEnabled(True)
        self.resize(760, 460)
        self.model = RecoveryCenterModel(entries, self)
        self._entries = {entry.entry_id: entry for entry in self.model.entries}
        self._selected = {
            entry.entry_id: RecoveryDecision(entry.entry_id, RecoveryAction.SKIP)
            for entry in self.model.entries
        }
        self._confirm_discard = confirm_discard or self._confirm_discard_dialog

        summary = QLabel(
            "Choose a safe action for each saved UNITI recovery item. "
            "Closing this window skips every item and preserves its evidence.",
            self,
        )
        summary.setWordWrap(True)
        self.entry_view = QListView(self)
        self.entry_view.setObjectName("recoveryEntryView")
        self.entry_view.setModel(self.model)
        self.action_combo = QComboBox(self)
        self.action_combo.setObjectName("recoveryActionCombo")
        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Continue")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(summary)
        layout.addWidget(self.entry_view, 1)
        layout.addWidget(QLabel("Action for selected item:", self))
        layout.addWidget(self.action_combo)
        layout.addWidget(self.buttons)

        selection = self.entry_view.selectionModel()
        selection.currentChanged.connect(self._current_changed)
        self.action_combo.currentIndexChanged.connect(self._combo_changed)
        if self.model.rowCount():
            self.entry_view.setCurrentIndex(self.model.index(0, 0))

    def _entry_for_row(self, row: int) -> RecoveryEntry | None:
        if 0 <= row < len(self.model.entries):
            return self.model.entries[row]
        return None

    def _current_changed(self, current, _previous) -> None:
        entry = self._entry_for_row(current.row())
        self.action_combo.blockSignals(True)
        self.action_combo.clear()
        if entry is not None:
            for action in entry.actions:
                self.action_combo.addItem(_ACTION_LABELS[action], action)
            selected = self._selected[entry.entry_id].action
            self.action_combo.setCurrentIndex(entry.actions.index(selected))
        self.action_combo.blockSignals(False)

    def _combo_changed(self, combo_index: int) -> None:
        entry = self._entry_for_row(self.entry_view.currentIndex().row())
        if entry is None or not 0 <= combo_index < self.action_combo.count():
            return
        action = RecoveryAction(self.action_combo.itemData(combo_index))
        located_path: Path | None = None
        if action is RecoveryAction.LOCATE_MATCH:
            selected, _filter = QFileDialog.getOpenFileName(
                self,
                "Locate Matching File",
                str(entry.path.parent),
            )
            if not selected:
                self._sync_current_combo()
                return
            located_path = Path(selected)
        if not self.select_action(entry.entry_id, action, located_path=located_path):
            self._sync_current_combo()

    def _sync_current_combo(self) -> None:
        entry = self._entry_for_row(self.entry_view.currentIndex().row())
        if entry is None:
            return
        self.action_combo.blockSignals(True)
        selected = self._selected[entry.entry_id].action
        self.action_combo.setCurrentIndex(entry.actions.index(selected))
        self.action_combo.blockSignals(False)

    def _confirm_discard_dialog(self, entry: RecoveryEntry) -> bool:
        result = QMessageBox.question(
            self,
            "Discard UNITI Evidence?",
            f"Permanently discard only UNITI-owned evidence for:\n{entry.path}?",
            QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Discard

    def select_action(
        self,
        entry_id: str,
        action: RecoveryAction,
        *,
        located_path: Path | None = None,
    ) -> bool:
        try:
            entry = self._entries[entry_id]
        except KeyError as exc:
            raise KeyError(entry_id) from exc
        if not isinstance(action, RecoveryAction):
            raise TypeError("recovery action must be a RecoveryAction")
        if action not in entry.actions:
            raise ValueError("recovery action is not safe for this entry")
        if action is RecoveryAction.DISCARD and not self._confirm_discard(entry):
            return False
        decision = RecoveryDecision(
            entry.entry_id,
            action,
            None if located_path is None else Path(located_path),
        )
        self._selected[entry.entry_id] = decision
        self._sync_current_combo()
        return True

    def decisions(self) -> tuple[RecoveryDecision, ...]:
        return tuple(
            self._selected[entry.entry_id] for entry in self.model.entries
        )

    def _skip_all(self) -> None:
        self._selected = {
            entry.entry_id: RecoveryDecision(entry.entry_id, RecoveryAction.SKIP)
            for entry in self.model.entries
        }

    def reject(self) -> None:
        self._skip_all()
        super().reject()

    def closeEvent(self, event) -> None:
        self._skip_all()
        super().closeEvent(event)


__all__ = [
    "MAX_RECOVERY_ENTRIES",
    "RecoveryAction",
    "RecoveryCenterDialog",
    "RecoveryCenterModel",
    "RecoveryDecision",
    "RecoveryEntry",
    "RecoveryEntryKind",
]
