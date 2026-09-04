"""Single-line Qt text input with an explicit bounded snapshot history."""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QTextCursor
from PySide6.QtWidgets import QTextEdit

from uniti.app.session import (
    MAX_INPUT_HISTORY_STATES,
    InputHistoryRecord,
    InputStateRecord,
    PersistenceNotice,
    estimate_input_history_bytes,
)


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
        self._history_notices: tuple[PersistenceNotice, ...] = ()
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
        self._history_notices = ()
        self._current_snapshot = self._snapshot()

    @staticmethod
    def _state_record(snapshot: InputSnapshot) -> InputStateRecord:
        return InputStateRecord(
            snapshot.text,
            snapshot.position,
            snapshot.anchor,
        )

    @staticmethod
    def _input_snapshot(record: InputStateRecord) -> InputSnapshot:
        return InputSnapshot(record.text, record.position, record.anchor)

    def export_history(self, max_steps: int = 50) -> InputHistoryRecord:
        if type(max_steps) is not int or max_steps <= 0:
            raise ValueError("max_steps must be a positive integer")
        limit = min(max_steps, MAX_INPUT_HISTORY_STATES)
        undo = list(self._undo_snapshots)
        redo = list(self._redo_snapshots)
        while len(undo) + len(redo) > limit:
            if undo:
                del undo[0]
            else:
                del redo[0]
        current = self._state_record(self._snapshot())
        undo_records = tuple(self._state_record(item) for item in undo)
        redo_records = tuple(self._state_record(item) for item in redo)
        return InputHistoryRecord(
            current=current,
            undo=undo_records,
            redo=redo_records,
            decoded_bytes=estimate_input_history_bytes(
                current,
                undo_records,
                redo_records,
            ),
            notices=self._history_notices,
        )

    def restore_history(self, record: InputHistoryRecord) -> None:
        if not isinstance(record, InputHistoryRecord):
            raise TypeError("record must be an InputHistoryRecord")
        if len(record.undo) + len(record.redo) > self._max_undo_steps:
            raise ValueError("input history exceeds this field's Undo limit")
        undo = [self._input_snapshot(item) for item in record.undo]
        redo = [self._input_snapshot(item) for item in record.redo]
        self._apply_snapshot(self._input_snapshot(record.current))
        self._undo_snapshots = undo
        self._redo_snapshots = redo
        self._history_notices = record.notices

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
