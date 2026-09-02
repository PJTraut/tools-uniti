"""Queued Qt delivery for Qt-free UNITI task snapshots and completion."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal


class TaskBridge(QObject):
    snapshotChanged = Signal()
    taskFinished = Signal(object)

    def __init__(self, coordinator, parent=None) -> None:
        super().__init__(parent)
        self._coordinator = coordinator
        self._closed = False
        coordinator.add_listener(self._forward_snapshot)

    def _forward_snapshot(self) -> None:
        if not self._closed:
            self.snapshotChanged.emit()

    def watch(self, handle) -> None:
        handle.future.add_done_callback(
            lambda _future, handle=handle: self._forward_finished(handle)
        )

    def _forward_finished(self, handle) -> None:
        if not self._closed:
            self.taskFinished.emit(handle)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._coordinator.remove_listener(self._forward_snapshot)


__all__ = ["TaskBridge"]
