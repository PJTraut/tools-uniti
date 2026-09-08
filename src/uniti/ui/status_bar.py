"""Operational status bar for the UNITI desktop shell."""

from __future__ import annotations

from uniti.core.eol import EOLReport
from uniti.core.text_format import EOLPolicy, format_summary
from uniti.resources import ResourceStatus, TaskProgress
from PySide6.QtWidgets import QLabel, QStatusBar


class UNITIStatusBar(QStatusBar):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._format = QLabel("—")
        self._position = QLabel("Ln 1:1")
        self._zoom = QLabel("—")
        self._wrap = QLabel("—")
        self._size = QLabel("0 B")
        self._task = QLabel("")
        self._resources = QLabel("Resources: Normal")
        self._eol_report: EOLReport | None = None
        self._active_task: TaskProgress | None = None
        for label in (
            self._format,
            self._position,
            self._zoom,
            self._wrap,
        ):
            self.addWidget(label)
        self.addWidget(self._task, 1)
        self.addPermanentWidget(self._resources)
        self.addPermanentWidget(self._size)

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
            if value < 1024.0 or unit == "TiB":
                if unit == "B":
                    return f"{int(value)} {unit}"
                return f"{value:.1f} {unit}"
            value /= 1024.0
        return f"{size} B"

    def update_eol_report(self, report: EOLReport | None) -> None:
        self._eol_report = report

    @property
    def format_label(self) -> QLabel:
        return self._format

    @property
    def resource_label(self) -> QLabel:
        return self._resources

    @property
    def task_label(self) -> QLabel:
        return self._task

    @property
    def active_task(self) -> TaskProgress | None:
        return self._active_task

    def update_resources(self, status: ResourceStatus) -> None:
        state = status.state.value.title()
        suffix = " · Paused" if status.background_paused else ""
        self._resources.setText(f"Resources: {state}{suffix}")
        load = (
            "unavailable"
            if status.load_per_logical_core is None
            else f"{status.load_per_logical_core:.2f}/core"
        )
        self._resources.setToolTip(
            "\n".join(
                (
                    f"CPU load: {load}",
                    f"Available memory: {self._format_size(status.available_memory)}",
                    f"Process RSS: {self._format_size(status.process_rss)}",
                    (
                        f"Cache: {self._format_size(status.cache_used)} / "
                        f"{self._format_size(status.cache_budget)}"
                    ),
                    f"Active/queued: {status.active_workers}/{status.queued_tasks}",
                )
            )
        )

    def update_task(self, progress: TaskProgress) -> None:
        self._active_task = progress
        if progress.total:
            percent = min(100, progress.completed * 100 // progress.total)
            self._task.setText(f"{progress.phase}: {percent}%")
        else:
            self._task.setText(progress.phase)
        self._task.setToolTip(
            f"{progress.phase}: {progress.completed:,}"
            + ("" if progress.total is None else f" / {progress.total:,}")
        )

    def clear_task(self, task_id: str) -> None:
        if self._active_task is None or self._active_task.task_id != task_id:
            return
        self._active_task = None
        self._task.clear()
        self._task.setToolTip("")

    @staticmethod
    def _source_eol_label(report: EOLReport | None) -> str:
        if report is None:
            return "Analyzing…"
        if report.kind == "MIXED":
            return "Mixed"
        if report.kind == "NONE":
            return "No EOL"
        return report.kind

    def update_document(self, document, eol_report: EOLReport | None = None) -> None:
        if eol_report is not None:
            self._eol_report = eol_report
        source_eol = self._source_eol_label(self._eol_report)
        saved = document.saved_output_format
        saved_text = format_summary(saved.encoding, source_eol)

        pending = document.output_format
        pending_eol = (
            source_eol
            if pending.eol is EOLPolicy.PRESERVE
            else pending.eol.value
        )
        pending_text = format_summary(pending.encoding, pending_eol)
        self._format.setText(
            saved_text if pending == saved else f"{saved_text} (on save: {pending_text})"
        )

        try:
            size = document.path.stat().st_size
        except OSError:
            size = document.source.size
        self._size.setText(self._format_size(size))

    def update_cursor(self, line: int, column: int) -> None:
        self._position.setText(f"Ln {line + 1}:{column + 1}")

    def update_view(self, zoom_percent: int, *, soft_wrap: bool) -> None:
        self._zoom.setText(f"{zoom_percent}%")
        self._wrap.setText("Wrap" if soft_wrap else "No Wrap")

    def clear_document(self) -> None:
        self._eol_report = None
        self._format.setText("—")
        self._position.setText("Ln 1:1")
        self._zoom.setText("—")
        self._wrap.setText("—")
        self._size.setText("0 B")
