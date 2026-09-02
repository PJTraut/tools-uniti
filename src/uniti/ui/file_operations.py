"""Progressive GUI coordination for snapshot-backed file output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal

from uniti.core.save_job import (
    DocumentSaveRequest,
    PreparedDocumentSave,
    prepare_document_save,
)
from uniti.core.text_format import OutputFormat
from uniti.resources import ResourceManager, TaskHandle, TaskKind, TaskSpec
from uniti.ui.task_bridge import TaskBridge


@dataclass(frozen=True, slots=True)
class FileOperationHandle:
    task: TaskHandle[PreparedDocumentSave]
    request: DocumentSaveRequest

    @property
    def task_id(self) -> str:
        return self.task.spec.task_id

    @property
    def done(self) -> bool:
        return self.task.done

    def cancel(self) -> None:
        self.task.cancel()


class FileOperationController(QObject):
    operationFinished = Signal(object)
    taskSnapshotChanged = Signal(object)

    def __init__(self, resources: ResourceManager, parent=None) -> None:
        super().__init__(parent)
        self._resources = resources
        self._operations: dict[str, FileOperationHandle] = {}
        self._closed = False
        self._bridge = TaskBridge(resources.tasks, self)
        self._bridge.taskFinished.connect(
            self._task_finished,
            Qt.ConnectionType.QueuedConnection,
        )
        self._bridge.snapshotChanged.connect(
            self.taskSnapshotChanged,
            Qt.ConnectionType.QueuedConnection,
        )

    def start(
        self,
        document,
        destination: str | Path,
        output_format: OutputFormat,
        *,
        expected_destination_identity,
    ) -> FileOperationHandle:
        request = document.create_save_request(
            destination,
            output_format,
            expected_destination_identity=expected_destination_identity,
        )
        source_bytes = request.snapshot.source.size
        spec = TaskSpec.create(
            TaskKind.SAVE,
            foreground=True,
            document_key=str(id(document)),
            revision=request.snapshot.revision,
            estimated_memory_bytes=8 << 20,
            estimated_disk_bytes=max(1 << 20, source_bytes * 4),
        )
        try:
            task = self._resources.tasks.submit(
                spec,
                lambda context: prepare_document_save(request, context),
            )
        except Exception:
            request.snapshot.close()
            raise
        operation = FileOperationHandle(task, request)
        self._operations[operation.task_id] = operation
        task.future.add_done_callback(self._discard_if_closed)
        self._bridge.watch(task)
        return operation

    def _discard_if_closed(self, future) -> None:
        if not self._closed or future.cancelled():
            return
        try:
            prepared = future.result()
        except Exception:
            return
        prepared.discard()

    def _task_finished(self, task: TaskHandle) -> None:
        operation = self._operations.pop(task.spec.task_id, None)
        if operation is not None and not self._closed:
            self.operationFinished.emit(operation)
        elif operation is not None:
            self._discard_if_closed(task.future)

    def cancel_all(self) -> None:
        for operation in tuple(self._operations.values()):
            operation.cancel()

    def shutdown(self) -> None:
        self._closed = True
        self.cancel_all()
        for operation in tuple(self._operations.values()):
            if operation.done:
                self._discard_if_closed(operation.task.future)
        self._operations.clear()
        self._bridge.close()


__all__ = ["FileOperationController", "FileOperationHandle"]
