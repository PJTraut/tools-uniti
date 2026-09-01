"""Single-line Qt text input with an explicit bounded snapshot history."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import QTextEdit


@dataclass(frozen=True, slots=True)
class InputSnapshot:
    text: str
    position: int
    anchor: int


class BoundedSingleLineTextEdit(QTextEdit):
    returnPressed = Signal()

    def __init__(self, parent=None, *, max_undo_steps: int = 50) -> None:
        if max_undo_steps <= 0:
            raise ValueError("max_undo_steps must be positive")
        super().__init__(parent)
        self._max_undo_steps = max_undo_steps
        self._undo_snapshots: list[InputSnapshot] = []
        self._redo_snapshots: list[InputSnapshot] = []
        self._restoring_snapshot = False
        self.setAcceptRichText(False)
        self.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setMinimumHeight(max(28, self.fontMetrics().height() + 10))
        self.document().setDocumentMargin(2.0)
        self.document().setUndoRedoEnabled(False)
        self._current_snapshot = self._snapshot()
        self.textChanged.connect(self._record_user_change)

    def _snapshot(self) -> InputSnapshot:
        cursor = self.textCursor()
        return InputSnapshot(self.toPlainText(), cursor.position(), cursor.anchor())

    def _record_user_change(self) -> None:
        if self._restoring_snapshot:
            return
        self._undo_snapshots.append(self._current_snapshot)
        if len(self._undo_snapshots) > self._max_undo_steps:
            del self._undo_snapshots[0]
        self._redo_snapshots.clear()
        self._current_snapshot = self._snapshot()

    def _apply_snapshot(self, snapshot: InputSnapshot) -> None:
        self._restoring_snapshot = True
        try:
            self.setPlainText(snapshot.text)
            cursor = self.textCursor()
            cursor.setPosition(snapshot.anchor)
            cursor.setPosition(
                snapshot.position,
                QTextCursor.MoveMode.KeepAnchor,
            )
            self.setTextCursor(cursor)
        finally:
            self._restoring_snapshot = False
        self._current_snapshot = snapshot

    @property
    def can_undo_input(self) -> bool:
        return bool(self._undo_snapshots)

    @property
    def can_redo_input(self) -> bool:
        return bool(self._redo_snapshots)

    def undo_input(self) -> bool:
        if not self._undo_snapshots:
            return False
        self._redo_snapshots.append(self._current_snapshot)
        self._apply_snapshot(self._undo_snapshots.pop())
        return True

    def redo_input(self) -> bool:
        if not self._redo_snapshots:
            return False
        self._undo_snapshots.append(self._current_snapshot)
        self._apply_snapshot(self._redo_snapshots.pop())
        return True

    def clear_input_history(self) -> None:
        self._undo_snapshots.clear()
        self._redo_snapshots.clear()
        self._current_snapshot = self._snapshot()

    def text(self) -> str:
        return self.toPlainText()

    def set_text(self, text: str) -> None:
        self._restoring_snapshot = True
        try:
            self.setPlainText(text)
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            self.setTextCursor(cursor)
        finally:
            self._restoring_snapshot = False
        self.clear_input_history()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.returnPressed.emit()
            event.accept()
            return
        super().keyPressEvent(event)
