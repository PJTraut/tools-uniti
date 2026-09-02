"""Worker-backed regex Find/Replace panel for UNITI."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future

import regex
from PySide6.QtCore import QEvent, Qt, Signal
from PySide6.QtGui import QFont, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from uniti.regex.engine import compile_pattern
from uniti.regex.match_store import MatchStore
from uniti.regex.replace import (
    Replacement,
    collect_replacement_plan,
    collect_replacements,
)
from uniti.regex.replacement_plan import ReplacementPlan
from uniti.regex.results import MatchIndex, MatchRecord
from uniti.regex.search import SearchOptions, resolve_captures, search_document
from uniti.resources import (
    ResourceManager,
    TaskAdmissionError,
    TaskContext,
    TaskHandle,
    TaskKind,
    TaskSpec,
)
from uniti.ui.regex_input import RegexInput, ReplacementInput


class FindReplaceWindow(QDialog):
    """Modeless Find/Replace utility; match records never become document state."""

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
        self.setSizeGripEnabled(True)
        self.setWindowTitle("Find / Replace")
        self.resize(720, 320)
        self._view_provider = view_provider
        self._owns_resources = resource_manager is None
        self._resource_manager = resource_manager or ResourceManager(max_workers=1)
        self._future: Future | None = None
        self._task_handle: TaskHandle | None = None
        self._job_kind: str | None = None
        self._job_context: object | None = None
        self._target_view = None
        self._job_edit_listener_remove = None
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
        self.search_mode_combo = QComboBox(self)
        self.search_mode_combo.addItems(("Literal", "Regex"))
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
        options_row.addWidget(QLabel("Mode:"))
        options_row.addWidget(self.search_mode_combo)
        options_row.addWidget(self.case_sensitive_checkbox)
        options_row.addWidget(self.whole_word_checkbox)
        options_row.addStretch(1)
        options_row.addWidget(QLabel("Report:"))
        options_row.addWidget(self.report_location_combo)

        self.batch_actions_widget = QWidget(self)
        batch_actions = QHBoxLayout(self.batch_actions_widget)
        batch_actions.setContentsMargins(0, 0, 0, 0)
        batch_actions.setSpacing(4)
        self.find_all_button = QPushButton("Find All", self.batch_actions_widget)
        self.replace_all_button = QPushButton(
            "Replace All", self.batch_actions_widget
        )
        batch_actions.addWidget(self.find_all_button)
        batch_actions.addWidget(self.replace_all_button)

        self.match_actions_widget = QWidget(self)
        match_actions = QHBoxLayout(self.match_actions_widget)
        match_actions.setContentsMargins(0, 0, 0, 0)
        match_actions.setSpacing(4)
        self.previous_button = QPushButton("Previous", self.match_actions_widget)
        self.next_button = QPushButton("Next", self.match_actions_widget)
        self.replace_button = QPushButton("Replace", self.match_actions_widget)
        match_actions.addWidget(self.previous_button)
        match_actions.addWidget(self.next_button)
        match_actions.addWidget(self.replace_button)

        self.cancel_button = QPushButton("Cancel", self)
        self.cancel_button.setEnabled(False)

        footer = QHBoxLayout()
        footer.addWidget(self.cancel_button)
        footer.addStretch(1)
        footer.addWidget(self.status_label)

        controls_widget = QWidget(self)
        controls_layout = QVBoxLayout(controls_widget)
        controls_layout.setContentsMargins(4, 4, 4, 4)
        controls_layout.setSpacing(3)
        controls_layout.addLayout(find_row, 1)
        controls_layout.addLayout(replace_row, 1)

        self.bottom_controls_widget = QWidget(controls_widget)
        self.bottom_controls_widget.setSizePolicy(
            QSizePolicy.Policy.Preferred,
            QSizePolicy.Policy.Fixed,
        )
        bottom_controls_layout = QVBoxLayout(self.bottom_controls_widget)
        bottom_controls_layout.setContentsMargins(0, 0, 0, 0)
        bottom_controls_layout.setSpacing(3)
        bottom_controls_layout.addLayout(options_row)
        bottom_controls_layout.addWidget(self.batch_actions_widget)
        bottom_controls_layout.addWidget(self.match_actions_widget)
        bottom_controls_layout.addLayout(footer)
        controls_layout.addWidget(self.bottom_controls_widget)

        self.report_frame = QFrame(self)
        report_layout = QVBoxLayout(self.report_frame)
        report_layout.setContentsMargins(4, 4, 4, 4)
        report_layout.addWidget(self.capture_list)

        self.report_splitter = QSplitter(Qt.Orientation.Vertical, self)
        self.report_splitter.addWidget(controls_widget)
        self.report_splitter.addWidget(self.report_frame)
        self.report_splitter.setChildrenCollapsible(True)
        self.report_splitter.setCollapsible(0, False)
        self.report_splitter.setCollapsible(1, True)
        self.report_splitter.setStretchFactor(0, 1)
        self.report_splitter.setStretchFactor(1, 1)
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
        self.search_mode_combo.currentTextChanged.connect(
            self._search_mode_changed
        )
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
        self._search_mode_changed("Literal")
        self.set_report_location("Bottom")
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)

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
        for field in (self.find_input, self.replace_input):
            field.setMinimumHeight(max(28, field.fontMetrics().height() + 10))
        self.zoomChanged.emit(percent)

    def zoom_in(self) -> None:
        self.set_zoom_percent(self._zoom_percent + 10)

    def zoom_out(self) -> None:
        self.set_zoom_percent(self._zoom_percent - 10)

    def reset_zoom(self) -> None:
        self.set_zoom_percent(100)

    def _handle_zoom_wheel(self, event: QWheelEvent) -> bool:
        delta = event.angleDelta().y()
        primary = bool(
            event.modifiers()
            & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier)
        )
        if not primary or not delta:
            return False
        steps = max(1, abs(delta) // 120)
        for _ in range(steps):
            self.zoom_in() if delta > 0 else self.zoom_out()
        event.accept()
        return True

    def eventFilter(self, watched, event) -> bool:
        if event.type() == QEvent.Type.Wheel and self._handle_zoom_wheel(event):
            return True
        return super().eventFilter(watched, event)

    def wheelEvent(self, event: QWheelEvent) -> None:
        if self._handle_zoom_wheel(event):
            return
        super().wheelEvent(event)

    def set_report_location(self, location: str) -> None:
        if location not in {"Hidden", "Bottom", "Right"}:
            raise ValueError(f"unsupported report location: {location}")
        if self.report_location_combo.currentText() != location:
            blocked = self.report_location_combo.blockSignals(True)
            self.report_location_combo.setCurrentText(location)
            self.report_location_combo.blockSignals(blocked)
        self.report_frame.setHidden(location == "Hidden")
        if location == "Bottom":
            self.report_splitter.setOrientation(Qt.Orientation.Vertical)
            if self.report_splitter.sizes()[1] == 0:
                self.report_splitter.setSizes((220, 100))
        elif location == "Right":
            self.report_splitter.setOrientation(Qt.Orientation.Horizontal)
            if self.report_splitter.sizes()[1] == 0:
                self.report_splitter.setSizes((460, 260))
        self.reportLocationChanged.emit(location)

    def cycle_report_location(self) -> None:
        locations = ("Hidden", "Bottom", "Right")
        current = locations.index(self.report_location)
        self.set_report_location(locations[(current + 1) % len(locations)])

    @property
    def regex_mode(self) -> bool:
        return self.search_mode_combo.currentText() == "Regex"

    def _search_mode_changed(self, mode: str) -> None:
        regex_mode = mode == "Regex"
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

    def undo_focused_input(self) -> bool:
        field = self.focused_input()
        if field is not None:
            field.undo_input()
            return True
        return False

    def redo_focused_input(self) -> bool:
        field = self.focused_input()
        if field is not None:
            field.redo_input()
            return True
        return False

    def focused_input(self):
        focus = QApplication.focusWidget()
        for field in (self.find_input, self.replace_input):
            if focus is field or (focus is not None and field.isAncestorOf(focus)):
                return field
        return None

    def _current_view(self):
        return self._view_provider()

    def compile_current(self):
        pattern = self.find_input.text()
        if not pattern:
            self.status_label.setText("enter a pattern")
            self.replace_input.set_groups(0, {})
            return None
        flags = 0
        if not self.regex_mode:
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
        if self.regex_mode:
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
        task_kind: TaskKind,
        context=None,
        rejected_cleanup: Callable[[], None] | None = None,
    ) -> bool:
        if self.busy:
            if rejected_cleanup is not None:
                rejected_cleanup()
            self.status_label.setText("busy — cancel current work first")
            return False
        self._job_kind = kind
        self._job_context = context
        self._target_view = view
        self.cancel_button.setEnabled(True)
        self.status_label.setText(
            "Searching…" if kind == "find" else "Replacing…"
        )
        spec = TaskSpec.create(
            task_kind,
            foreground=True,
            document_key=str(id(view.document)),
            revision=view.document.revision,
            estimated_memory_bytes=8 << 20,
        )
        try:
            self._task_handle = self._resource_manager.tasks.submit(spec, fn)
        except Exception as exc:
            if rejected_cleanup is not None:
                rejected_cleanup()
            self._job_kind = None
            self._job_context = None
            self._target_view = None
            self.cancel_button.setEnabled(False)
            if isinstance(exc, TaskAdmissionError):
                self.status_label.setText(f"operation refused: {exc}")
                return False
            raise
        self._future = self._task_handle.future
        self._job_edit_listener_remove = view.document.add_edit_listener(
            lambda _operation, view=view: self._cancel_for_edit(view)
        )
        if rejected_cleanup is not None:
            self._future.add_done_callback(
                lambda _future: rejected_cleanup()
            )
        self._future.add_done_callback(lambda _future: self._jobCompleted.emit())
        return True

    def _cancel_for_edit(self, view) -> None:
        if view is not self._target_view:
            return
        self.cancel_search()
        self.status_label.setText("text changed — search again")

    def find_all(self) -> None:
        view = self._current_view()
        compiled = self._compile_current()
        if view is None or compiled is None:
            return
        revision = view.document.revision
        snapshot = view.document.snapshot()

        def work(context: TaskContext):
            store = MatchStore(document_revision=revision)
            try:
                with snapshot:
                    for record in search_document(
                        snapshot,
                        compiled,
                        options=SearchOptions(timeout=0.5, include_captures=False),
                        cancelled=lambda: context.token.cancelled,
                        progress=lambda completed, total: context.report(
                            "Searching",
                            completed,
                            total,
                        ),
                    ):
                        store.append(record)
            except Exception:
                store.close()
                raise
            return store

        self._start_job(
            "find",
            view,
            work,
            task_kind=TaskKind.SEARCH,
            context=compiled,
            rejected_cleanup=snapshot.close,
        )

    def replace_current(self) -> None:
        view = self._current_view()
        compiled = self._compile_current()
        if view is None or compiled is None:
            return
        if self._current_index is None:
            self.find_all()
            return
        target_index = self._current_index
        revision = view.document.revision
        replacement_text = self._replacement_expression()
        snapshot = view.document.snapshot()

        def work(context: TaskContext):
            with snapshot:
                return collect_replacements(
                    snapshot,
                    compiled,
                    replacement_text,
                    options=SearchOptions(
                        timeout=0.5,
                        max_matches=target_index + 1,
                    ),
                    cancelled=lambda: context.token.cancelled,
                )

        self._start_job(
            "replace_current",
            view,
            work,
            task_kind=TaskKind.REPLACE,
            context=(target_index, revision),
            rejected_cleanup=snapshot.close,
        )

    def replace_all(self) -> None:
        view = self._current_view()
        compiled = self._compile_current()
        if view is None or compiled is None:
            return
        revision = view.document.revision
        replacement_text = self._replacement_expression()
        snapshot = view.document.snapshot()

        def work(context: TaskContext):
            with snapshot:
                return collect_replacement_plan(
                    snapshot,
                    compiled,
                    replacement_text,
                    document_revision=revision,
                    options=SearchOptions(timeout=0.5),
                    cancelled=lambda: context.token.cancelled,
                    progress=lambda completed, total: context.report(
                        "Planning replacements",
                        completed,
                        total,
                    ),
                )

        self._start_job(
            "replace_all",
            view,
            work,
            task_kind=TaskKind.REPLACE,
            context=revision,
            rejected_cleanup=snapshot.close,
        )

    def cancel_search(self) -> None:
        if self._task_handle is not None:
            self._task_handle.cancel()
            self.status_label.setText("Cancelling…")

    def _poll_job(self) -> None:
        future = self._future
        if future is None or not future.done():
            return
        kind = self._job_kind
        context = self._job_context
        view = self._target_view
        task_handle = self._task_handle
        self._future = None
        self._task_handle = None
        self._job_kind = None
        self._job_context = None
        self._target_view = None
        if self._job_edit_listener_remove is not None:
            self._job_edit_listener_remove()
            self._job_edit_listener_remove = None
        self.cancel_button.setEnabled(False)
        try:
            payload = future.result()
        except Exception as exc:
            if task_handle is not None and task_handle.token.cancelled:
                if self.status_label.text() != "text changed — search again":
                    self.status_label.setText("cancelled")
                return
            self.status_label.setText(f"operation failed: {exc}")
            return

        if task_handle is not None and task_handle.token.cancelled:
            if isinstance(payload, (MatchStore, ReplacementPlan)):
                payload.close()
            if self.status_label.text() != "text changed — search again":
                self.status_label.setText("cancelled")
            return

        if kind == "find":
            self._apply_find_results(view, payload, context)
        elif kind == "replace_current":
            self._apply_current_replacement(view, payload, context)
        elif kind == "replace_all":
            self._apply_replace_all(view, payload, context)

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
        if (
            not isinstance(context, tuple)
            or len(context) != 2
            or not isinstance(context[0], int)
            or view is None
            or view.document.revision != context[1]
            or context[0] >= len(replacements)
        ):
            self.status_label.setText("match changed — search again")
            self._clear_results()
            return
        replacement = replacements[context[0]]
        view.document.replace(replacement.start, replacement.end, replacement.text)
        view.state.move_to(replacement.start + len(replacement.text))
        self._clear_results()
        view._state_changed()
        self.status_label.setText("1 replaced")

    def _apply_replace_all(self, view, plan: ReplacementPlan, revision) -> None:
        if view is None or view.document.revision != revision:
            plan.close()
            self.status_label.setText("text changed — search again")
            return
        memory_limit = max(
            1 << 20,
            min(256 << 20, self._resource_manager.status.available_memory // 4),
        )
        try:
            count = view.document.apply_replacement_plan(
                plan,
                expected_revision=revision,
                memory_limit_bytes=memory_limit,
            )
        except Exception as exc:
            self.status_label.setText(f"operation failed: {exc}")
            return
        finally:
            plan.close()
        self._clear_results()
        view._state_changed()
        self.status_label.setText(f"{count:,} replaced")

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
        if self._job_edit_listener_remove is not None:
            self._job_edit_listener_remove()
            self._job_edit_listener_remove = None
        if self._owns_resources:
            self._resource_manager.shutdown(wait=False)


# Compatibility name for implemented callers while the project migrates from
# the embedded-panel vocabulary to the floating utility.
FindReplacePanel = FindReplaceWindow
