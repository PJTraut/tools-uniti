"""Progressive GUI coordination for snapshot-backed file output."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import time

from PySide6.QtCore import QObject, Qt, Signal

from uniti.core.save_job import (
    DocumentSaveRequest,
    PreparedDocumentSave,
    prepare_document_save,
)
from uniti.core.text_format import OutputFormat
from uniti.app.dogfood import Durability, Operation, Outcome
from uniti.core.durability import DurabilityError, DurabilityLevel, DurabilityResult
from uniti.core.file_identity import ExternalFileChangedError
from uniti.resources import ResourceManager, TaskHandle, TaskKind, TaskSpec
from uniti.ui.task_bridge import TaskBridge


@dataclass(frozen=True, slots=True)
class FileOperationHandle:
    task: TaskHandle[PreparedDocumentSave]
    request: DocumentSaveRequest
    started_at: float

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
    taskSnapshotChanged = Signal()

    def __init__(
        self,
        resources: ResourceManager,
        parent=None,
        *,
        dogfood_observer=None,
    ) -> None:
        if dogfood_observer is not None and not callable(dogfood_observer):
            raise TypeError("dogfood observer must be callable or None")
        super().__init__(parent)
        self._resources = resources
        self._dogfood_observer = dogfood_observer
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

    def set_dogfood_observer(self, observer) -> None:
        if observer is not None and not callable(observer):
            raise TypeError("dogfood observer must be callable or None")
        self._dogfood_observer = observer

    @staticmethod
    def _operation_for_request(request: DocumentSaveRequest) -> Operation:
        return Operation.SAVE if request.in_place else Operation.SAVE_AS

    def _observe(
        self,
        operation: Operation,
        outcome: Outcome,
        *,
        started_at: float,
        durability: Durability = Durability.NOT_APPLICABLE,
    ) -> None:
        observer = self._dogfood_observer
        if observer is None:
            return
        try:
            observer(
                operation,
                outcome,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                durability=durability,
            )
        except Exception:
            return

    def record_completion(
        self,
        operation: FileOperationHandle,
        *,
        error: Exception | None = None,
        cancelled: bool = False,
        durability_result: DurabilityResult | None = None,
        unavailable: bool = False,
    ) -> None:
        selected = self._operation_for_request(operation.request)
        durability = Durability.NOT_APPLICABLE
        if cancelled:
            outcome = Outcome.CANCELLED
        elif isinstance(error, ExternalFileChangedError):
            outcome = Outcome.REFUSED_EXTERNAL_CHANGE
        elif error is not None:
            outcome = Outcome.FAILED
            if isinstance(error, DurabilityError):
                durability = Durability.UNSAFE
        elif unavailable:
            outcome = Outcome.UNAVAILABLE
        elif durability_result is None:
            outcome = Outcome.SUCCESS
        elif durability_result.level is DurabilityLevel.FULL:
            outcome = Outcome.SUCCESS
            durability = Durability.FULL
        elif durability_result.level is DurabilityLevel.FILE_SYNCED:
            outcome = Outcome.REDUCED_DURABILITY
            durability = Durability.FILE_SYNCED
        else:
            outcome = Outcome.FAILED
            durability = Durability.UNSAFE
        self._observe(
            selected,
            outcome,
            started_at=operation.started_at,
            durability=durability,
        )

    def start(
        self,
        document,
        destination: str | Path,
        output_format: OutputFormat,
        *,
        expected_destination_identity,
    ) -> FileOperationHandle:
        started_at = time.monotonic()
        try:
            request = document.create_save_request(
                destination,
                output_format,
                expected_destination_identity=expected_destination_identity,
            )
        except Exception:
            self._observe(
                (
                    Operation.SAVE
                    if Path(destination) == Path(document.path)
                    else Operation.SAVE_AS
                ),
                Outcome.FAILED,
                started_at=started_at,
            )
            raise
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
            self._observe(
                self._operation_for_request(request),
                Outcome.FAILED,
                started_at=started_at,
            )
            raise
        operation = FileOperationHandle(task, request, started_at)
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
