"""Worker-backed regex Find/Replace panel for UNITI."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future

import regex
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QMessageBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from uniti.regex.engine import compile_pattern
from uniti.regex.match_store import MatchStore
from uniti.regex.replace import (
    Replacement,
    ReplacementProbe,
    StreamReplaceResult,
    collect_replacements,
    probe_replacements,
    stream_replace_to_file,
)
from uniti.regex.results import MatchIndex, MatchRecord
from uniti.regex.search import SearchOptions, resolve_captures, search_document
from uniti.resources import CancellationToken, PriorityWorkerPool, ResourceManager, WorkPriority
from uniti.ui.regex_input import RegexInput, ReplacementInput


STREAM_REPLACE_THRESHOLD = 50_000


class FindReplaceWindow(QDialog):
    """Modeless Find/Replace utility; match records never become document state."""

    streamReplaceCommitted = Signal(object, str, int)
    zoomChanged = Signal(int)
    reportLocationChanged = Signal(str)
    geometryChanged = Signal(tuple)
    _jobCompleted = Signal()

    def __init__(
        self,
        view_provider: Callable[[], object | None],
        parent=None,
        *,
        resource_manager: ResourceManager | None = None,
    ) -> None:
        super().__init__(parent)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowTitle("Find / Replace")
        self.resize(720, 320)
        self._view_provider = view_provider
        self._resource_manager = resource_manager
        self._owns_pool = resource_manager is None
        self._pool = (
            PriorityWorkerPool(max_workers=1, thread_name_prefix="uniti-regex")
            if resource_manager is None
            else resource_manager.workers
        )
        self._future: Future | None = None
        self._token: CancellationToken | None = None
        self._job_kind: str | None = None
        self._job_context: object | None = None
        self._target_view = None
        self._results = MatchIndex(())
        self._results_view = None
        self._result_listener_remove = None
        self._current_index: int | None = None
        self._results_compiled = None
        self._zoom_percent = 100

        self.find_input = RegexInput(self)
        self.replace_input = ReplacementInput(self)
        self.status_label = QLabel("0 matches", self)
        self.capture_list = QListWidget(self)
        self.capture_list.setMaximumHeight(82)
        self.regex_checkbox = QCheckBox("Regex", self)
        self.case_sensitive_checkbox = QCheckBox("Case Sensitive", self)
        self.whole_word_checkbox = QCheckBox("Whole Word", self)
        self.report_location_combo = QComboBox(self)
        self.report_location_combo.addItems(("Hidden", "Bottom", "Right"))

        find_row = QHBoxLayout()
        find_row.addWidget(QLabel("F>"))
        find_row.addWidget(self.find_input, 1)
        replace_row = QHBoxLayout()
        replace_row.addWidget(QLabel("R>"))
        replace_row.addWidget(self.replace_input, 1)

        options_row = QHBoxLayout()
        options_row.addWidget(self.regex_checkbox)
        options_row.addWidget(self.case_sensitive_checkbox)
        options_row.addWidget(self.whole_word_checkbox)
        options_row.addStretch(1)
        options_row.addWidget(QLabel("Report:"))
        options_row.addWidget(self.report_location_combo)

        self.find_all_button = QPushButton("Find All", self)
        self.previous_button = QPushButton("Previous", self)
        self.next_button = QPushButton("Next", self)
        self.replace_button = QPushButton("Replace", self)
        self.replace_all_button = QPushButton("Replace All", self)
        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setEnabled(False)

        controls = QHBoxLayout()
        for button in (
            self.find_all_button,
            self.previous_button,
            self.next_button,
            self.replace_button,
            self.replace_all_button,
            self.cancel_button,
        ):
            controls.addWidget(button)
        controls.addStretch(1)
        controls.addWidget(self.status_label)

        controls_widget = QWidget(self)
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(4, 4, 4, 4)
        controls_layout.setSpacing(3)
        controls_layout.addLayout(find_row)
        controls_layout.addLayout(replace_row)
        controls_layout.addLayout(options_row)
        controls_layout.addLayout(controls)

        self.report_frame = QFrame(self)
        report_layout = QVBoxLayout(self.report_frame)
        report_layout.setContentsMargins(4, 4, 4, 4)
        report_layout.addWidget(self.capture_list)

        self.report_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.report_splitter.addWidget(controls_widget)
        self.report_splitter.addWidget(self.report_frame)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.report_splitter)

        self.find_all_button.clicked.connect(self.find_all)
        self.previous_button.clicked.connect(self.previous_match)
        self.next_button.clicked.connect(self.next_match)
        self.replace_button.clicked.connect(self.replace_current)
        self.replace_all_button.clicked.connect(self.replace_all)
        self.cancel_button.clicked.connect(self.cancel_search)
        self.find_input.returnPressed.connect(self.next_match)
        self.replace_input.returnPressed.connect(self.replace_current)
        self.find_input.textChanged.connect(self._pattern_changed)
        self.regex_checkbox.toggled.connect(self._search_mode_changed)
        self.case_sensitive_checkbox.toggled.connect(self._pattern_changed)
        self.whole_word_checkbox.toggled.connect(self._pattern_changed)
        self.report_location_combo.currentTextChanged.connect(
            self.set_report_location
        )

        # Worker futures may finish before the next Qt timer tick.  Deliver
        # completion through a queued Qt signal so result application happens
        # deterministically on the GUI thread.
        self._jobCompleted.connect(
            self._poll_job, Qt.ConnectionType.QueuedConnection
        )
        self._search_mode_changed(False)
        self.set_report_location("Bottom")

    @property
    def zoom_percent(self) -> int:
        return self._zoom_percent

    @property
    def report_location(self) -> str:
        return self.report_location_combo.currentText()

    def set_zoom_percent(self, percent: int) -> None:
        percent = max(50, min(300, int(percent)))
        if percent == self._zoom_percent:
            return
        scale = percent / self._zoom_percent
        self._zoom_percent = percent
        for widget in (self.find_input, self.replace_input, self.capture_list):
            font = QFont(widget.font())
            point_size = font.pointSizeF()
            if point_size <= 0:
                point_size = 12.0
            font.setPointSizeF(point_size * scale)
            widget.setFont(font)
        self.zoomChanged.emit(percent)

    def zoom_in(self) -> None:
        self.set_zoom_percent(self._zoom_percent + 10)

    def zoom_out(self) -> None:
        self.set_zoom_percent(self._zoom_percent - 10)

    def reset_zoom(self) -> None:
        self.set_zoom_percent(100)

    def set_report_location(self, location: str) -> None:
        if location not in {"Hidden", "Bottom", "Right"}:
            raise ValueError(f"unsupported report location: {location}")
        if self.report_location_combo.currentText() != location:
            self.report_location_combo.setCurrentText(location)
        self.report_frame.setHidden(location == "Hidden")
        if location == "Bottom":
            self.report_splitter.setOrientation(Qt.Orientation.Vertical)
            self.capture_list.setMaximumHeight(82)
        elif location == "Right":
            self.report_splitter.setOrientation(Qt.Orientation.Horizontal)
            self.capture_list.setMaximumHeight(16_777_215)
        self.reportLocationChanged.emit(location)

    def _search_mode_changed(self, regex_mode: bool) -> None:
        self.case_sensitive_checkbox.setVisible(not regex_mode)
        self.whole_word_checkbox.setVisible(not regex_mode)
        self._pattern_changed()

    @property
    def result_count(self) -> int:
        return len(self._results)

    @property
    def busy(self) -> bool:
        # A completed Future is still busy until its payload has been applied on
        # the GUI thread.  Callers may safely wait on this property while
        # pumping QApplication events.
        return self._future is not None

    def focus_find(self) -> None:
        self.show()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def focus_replace(self) -> None:
        self.show()
        self.replace_input.setFocus()
        self.replace_input.selectAll()

    def document_changed(self) -> None:
        if self.busy:
            self.cancel_search()
        self._clear_results()

    def _current_view(self):
        return self._view_provider()

    def compile_current(self):
        pattern = self.find_input.text()
        if not pattern:
            self.status_label.setText("enter a pattern")
            self.replace_input.set_groups(0, {})
            return None
        flags = 0
        if not self.regex_checkbox.isChecked():
            pattern = regex.escape(pattern)
            if self.whole_word_checkbox.isChecked():
                pattern = rf"\b(?:{pattern})\b"
            if not self.case_sensitive_checkbox.isChecked():
                flags |= regex.IGNORECASE
        try:
            compiled = compile_pattern(pattern, flags)
        except regex.error as exc:
            self.status_label.setText(f"regex error: {exc}")
            self.replace_input.set_groups(0, {})
            return None
        self.replace_input.set_groups(compiled.groups, dict(compiled.groupindex))
        return compiled

    def _compile_current(self):
        return self.compile_current()

    def _replacement_expression(self) -> str:
        replacement = self.replace_input.text()
        if self.regex_checkbox.isChecked():
            return replacement
        return replacement.replace("\\", "\\\\")

    def _pattern_changed(self) -> None:
        if self.busy:
            self.cancel_search()
        self._clear_results()
        self._compile_current()

    def _clear_results(self) -> None:
        if self._result_listener_remove is not None:
            self._result_listener_remove()
            self._result_listener_remove = None
        if self._results_view is not None:
            self._results_view.set_match_index(None)
        if isinstance(self._results, MatchStore):
            self._results.close()
        self._results = MatchIndex(())
        self._results_view = None
        self._result_listener_remove = None
        self._current_index = None
        self.capture_list.clear()
        self._results_compiled = None

    def _start_job(
        self,
        kind: str,
        view,
        fn,
        *,
        token: CancellationToken,
        context=None,
    ) -> bool:
        if self.busy:
            self.status_label.setText("busy — cancel current work first")
            return False
        self._token = token
        self._job_kind = kind
        self._job_context = context
        self._target_view = view
        view.setEnabled(False)
        self.cancel_button.setEnabled(True)
        self.status_label.setText(
            "Searching…" if kind == "find" else "Replacing…"
        )
        self._future = self._pool.submit(
            WorkPriority.SEARCH,
            fn,
            token=token,
        )
        self._future.add_done_callback(lambda _future: self._jobCompleted.emit())
        return True

    def find_all(self) -> None:
        view = self._current_view()
        compiled = self._compile_current()
        if view is None or compiled is None:
            return
        token = CancellationToken()

        revision = view.document.revision

        def work():
            store = MatchStore(document_revision=revision)
            try:
                for record in search_document(
                    view.document,
                    compiled,
                    options=SearchOptions(timeout=0.5, include_captures=False),
                    cancelled=lambda: token.cancelled,
                ):
                    store.append(record)
            except Exception:
                store.close()
                raise
            return store

        self._start_job("find", view, work, token=token, context=compiled)

    def replace_current(self) -> None:
        view = self._current_view()
        compiled = self._compile_current()
        if view is None or compiled is None:
            return
        if self._current_index is None:
            self.find_all()
            return
        target_index = self._current_index
        token = CancellationToken()

        def work():
            return collect_replacements(
                view.document,
                compiled,
                self._replacement_expression(),
                options=SearchOptions(timeout=0.5, max_matches=target_index + 1),
                cancelled=lambda: token.cancelled,
            )

        self._start_job(
            "replace_current",
            view,
            work,
            token=token,
            context=target_index,
        )

    def replace_all(self) -> None:
        view = self._current_view()
        compiled = self._compile_current()
        if view is None or compiled is None:
            return
        token = CancellationToken()
        revision = view.document.revision
        replacement_text = self._replacement_expression()

        def work():
            return probe_replacements(
                view.document,
                compiled,
                replacement_text,
                threshold=STREAM_REPLACE_THRESHOLD,
                options=SearchOptions(timeout=0.5),
                cancelled=lambda: token.cancelled,
            )

        self._start_job(
            "replace_all_probe",
            view,
            work,
            token=token,
            context=(compiled, replacement_text, revision),
        )

    def cancel_search(self) -> None:
        if self._token is not None:
            self._token.cancel()
            self.status_label.setText("Cancelling…")

    def _poll_job(self) -> None:
        future = self._future
        if future is None or not future.done():
            return
        kind = self._job_kind
        context = self._job_context
        view = self._target_view
        token = self._token
        self._future = None
        self._job_kind = None
        self._job_context = None
        self._target_view = None
        self._token = None
        self.cancel_button.setEnabled(False)
        if view is not None:
            view.setEnabled(True)

        if token is not None and token.cancelled:
            self.status_label.setText("cancelled")
            return
        try:
            payload = future.result()
        except Exception as exc:
            self.status_label.setText(f"operation failed: {exc}")
            return

        if kind == "find":
            self._apply_find_results(view, payload, context)
        elif kind == "replace_current":
            self._apply_current_replacement(view, payload, context)
        elif kind == "replace_all_probe":
            self._apply_replace_probe(view, payload, context)
        elif kind == "replace_all_stream":
            self._apply_stream_replace(view, payload, context)

    def _apply_find_results(self, view, store: MatchStore, compiled) -> None:
        if view is None or view.document.revision != store.document_revision:
            store.close()
            self._clear_results()
            self.status_label.setText("text changed — search again")
            return
        self._clear_results()
        self._results = store
        self._results_view = view
        self._results_compiled = compiled
        self._result_listener_remove = view.document.add_edit_listener(
            lambda _operation, view=view: self._invalidate_results_for_edit(view)
        )
        view.set_match_index(self._results)
        self.status_label.setText(f"{len(self._results):,} matches")
        self._current_index = self._results.next_index(view.state.cursor)
        if self._current_index is not None:
            self._navigate_to(self._current_index)
        else:
            self.capture_list.clear()

    def _invalidate_results_for_edit(self, view) -> None:
        if view is not self._results_view:
            return
        self._clear_results()
        self.status_label.setText("text changed — search again")

    def _results_are_current(self, view) -> bool:
        if isinstance(self._results, MatchStore):
            return (
                view is self._results_view
                and view.document.revision == self._results.document_revision
            )
        return view is self._results_view

    def _apply_current_replacement(
        self,
        view,
        replacements: list[Replacement],
        context,
    ) -> None:
        if not isinstance(context, int) or context >= len(replacements):
            self.status_label.setText("match changed — search again")
            self._clear_results()
            return
        replacement = replacements[context]
        view.document.replace(replacement.start, replacement.end, replacement.text)
        view.state.move_to(replacement.start + len(replacement.text))
        self._clear_results()
        view._state_changed()
        self.status_label.setText("1 replaced")

    def _apply_replace_all(self, view, replacements) -> None:
        view.document.replace_many(
            [(item.start, item.end, item.text) for item in replacements]
        )
        count = len(replacements)
        self._clear_results()
        view._state_changed()
        self.status_label.setText(f"{count:,} replaced")

    def _apply_replace_probe(self, view, probe: ReplacementProbe, context) -> None:
        if view is None or not isinstance(context, tuple) or len(context) != 3:
            self.status_label.setText("match changed — search again")
            return
        compiled, replacement_text, revision = context
        if view.document.revision != revision:
            self.status_label.setText("text changed — search again")
            return
        if not probe.truncated:
            self._apply_replace_all(view, probe.replacements)
            return

        choice = QMessageBox.warning(
            self,
            "Large Replace All",
            f"More than {STREAM_REPLACE_THRESHOLD:,} replacements were found. "
            "UNITI will stream the transformation atomically to the current "
            "file to keep memory bounded. This commits current unsaved changes "
            "and resets undo history. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if choice != QMessageBox.StandardButton.Yes:
            self.status_label.setText("large Replace All cancelled")
            return

        token = CancellationToken()

        def work():
            view.document.assert_safe_overwrite()
            return stream_replace_to_file(
                view.document,
                compiled,
                replacement_text,
                view.document.path,
                options=SearchOptions(timeout=0.5),
                cancelled=lambda: token.cancelled,
            )

        self._start_job(
            "replace_all_stream",
            view,
            work,
            token=token,
            context=revision,
        )

    def _apply_stream_replace(
        self,
        view,
        result: StreamReplaceResult,
        revision,
    ) -> None:
        if view is None or view.document.revision != revision:
            self.status_label.setText("text changed after streamed replacement")
            return
        self._clear_results()
        self.streamReplaceCommitted.emit(view, str(result.path), result.count)
        self.status_label.setText(f"{result.count:,} replaced (streamed)")

    def next_match(self) -> None:
        if not len(self._results):
            self.find_all()
            return
        if self._current_index is None:
            index = 0
        else:
            index = (self._current_index + 1) % len(self._results)
        self._navigate_to(index)

    def previous_match(self) -> None:
        if not len(self._results):
            self.find_all()
            return
        if self._current_index is None:
            index = len(self._results) - 1
        else:
            index = (self._current_index - 1) % len(self._results)
        self._navigate_to(index)

    def _navigate_to(self, index: int) -> None:
        view = self._current_view()
        if view is None or not len(self._results):
            return
        if not self._results_are_current(view):
            self._clear_results()
            self.status_label.setText("text changed — search again")
            return
        self._current_index = index
        record = self._results.records[index]
        view.state.move_to(record.start)
        if record.end > record.start:
            view.state.move_to(record.end, selecting=True)
        view._state_changed()
        self.status_label.setText(
            f"match {index + 1:,}/{len(self._results):,}"
        )
        self._show_capture_details(view, record)

    @staticmethod
    def _display_text(text: str, limit: int = 80) -> str:
        text = text.replace("\r", "\\r").replace("\n", "\\n")
        return text if len(text) <= limit else text[: limit - 1] + "…"

    def _resolved_capture_record(self, view, record: MatchRecord) -> MatchRecord:
        if record.captures or self._results_compiled is None:
            return record
        try:
            return resolve_captures(
                view.document,
                self._results_compiled,
                record,
                timeout=0.15,
            )
        except Exception:
            return record

    def _append_capture_record(self, view, record: MatchRecord) -> None:
        record = self._resolved_capture_record(view, record)
        for capture in record.captures:
            label = str(capture.group)
            if capture.name:
                label += f" {capture.name}"
            values = [
                self._display_text(view.document.read(start, end))
                for start, end in capture.spans[:5]
            ]
            suffix = " …" if len(capture.spans) > 5 else ""
            self.capture_list.addItem(
                f"{label} │ {' | '.join(values)}{suffix}"
            )

    def _show_capture_details(self, view, record: MatchRecord) -> None:
        self.capture_list.clear()
        self._append_capture_record(view, record)
        if len(self._results) > 1 and self._current_index is not None:
            next_index = (self._current_index + 1) % len(self._results)
            next_record = self._results.records[next_index]
            self.capture_list.addItem("─────────────────")
            self._append_capture_record(view, next_record)

    def reject(self) -> None:
        self.hide()

    def _emit_geometry(self) -> None:
        geometry = self.geometry()
        self.geometryChanged.emit(
            (geometry.x(), geometry.y(), geometry.width(), geometry.height())
        )

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._emit_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._emit_geometry()

    def shutdown(self) -> None:
        self.cancel_search()
        if self._target_view is not None:
            self._target_view.setEnabled(True)
        if self._owns_pool:
            self._pool.shutdown(wait=False, cancel_pending=True)


# Compatibility name for implemented callers while the project migrates from
# the embedded-panel vocabulary to the floating utility.
FindReplacePanel = FindReplaceWindow
