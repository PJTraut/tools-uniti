"""Worker-backed regex Find/Replace panel for UNITI."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
import time
import weakref

from PySide6.QtCore import QEvent, QTimer, Qt, Signal
from PySide6.QtGui import QFont, QIcon, QPainter, QWheelEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QApplication,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from uniti.app.session import (
    FindReplaceRecord,
    bound_find_replace_histories,
)
from uniti.app.dogfood import Durability, Operation, Outcome
from uniti.regex.analysis import (
    AnalysisState,
    ExpressionRole,
    RegexAnalysis,
    analyze_pattern,
    analyze_replacement,
    pending_pattern_analysis,
)
from uniti.regex.captures import (
    CaptureMatchReport,
    CaptureReport,
    CaptureReportRequest,
    resolve_capture_report,
)
from uniti.regex.match_store import MatchStore
from uniti.regex.replace import (
    Replacement,
    collect_replacement_plan,
    collect_replacements,
)
from uniti.regex.replacement_plan import ReplacementPlan
from uniti.regex.results import MatchIndex, advance_result_index
from uniti.regex.search import (
    RegexContextLimitError,
    RegexSearchTimeout,
    SearchOptions,
    search_document,
)
from uniti.resources import (
    LatestTaskSlot,
    ResourceManager,
    TaskAdmissionError,
    TaskContext,
    TaskHandle,
    TaskKind,
    TaskSpec,
)
from uniti.ui.capture_report import CaptureReportModel
from uniti.ui.icons import lucide_icon
from uniti.ui.regex_input import RegexInput, ReplacementInput


_FIND_RESULT_MEMORY_BYTES = 1 << 20


@dataclass(frozen=True, slots=True)
class OperationSeal:
    pattern_generation: int
    pattern_text: str
    document_key: str
    revision: int


@dataclass(frozen=True, slots=True)
class FindRequest:
    compiled: object
    seal: OperationSeal
    direction: int
    origin: int


class _IconLabel(QWidget):
    """A non-interactive, accessible label painted by the shared icon renderer."""

    def __init__(self, icon_name: str, accessible_name: str, parent=None) -> None:
        super().__init__(parent)
        self._icon = lucide_icon(icon_name)
        self.setAccessibleName(accessible_name)
        self.setToolTip(accessible_name)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setFixedSize(24, 24)

    def icon(self) -> QIcon:
        return self._icon

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        self._icon.paint(
            painter,
            self.rect().adjusted(2, 2, -2, -2),
            mode=QIcon.Mode.Normal if self.isEnabled() else QIcon.Mode.Disabled,
        )


class FindReplaceWindow(QDockWidget):
    """Modeless Find/Replace utility; match records never become document state."""

    zoomChanged = Signal(int)
    reportLocationChanged = Signal(str)
    geometryChanged = Signal(tuple)
    placementChanged = Signal(str)
    _jobCompleted = Signal()
    _analysisCompleted = Signal(int, object)
    _captureCompleted = Signal(int, object)

    def __init__(
        self,
        view_provider: Callable[[], object | None],
        parent=None,
        *,
        resource_manager: ResourceManager | None = None,
        dogfood_observer: Callable[..., None] | None = None,
    ) -> None:
        if dogfood_observer is not None and not callable(dogfood_observer):
            raise TypeError("dogfood observer must be callable or None")
        super().__init__("Find / Replace", parent)
        self.setAllowedAreas(Qt.DockWidgetArea.BottomDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self._placement = "detached"
        self._changing_placement = False
        self._dock_host: QMainWindow | None = None
        self._detached_geometry = (0, 0, 720, 320)
        self._restoring_state = False
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.resize(720, 320)
        self._view_provider = view_provider
        self._dogfood_observer = dogfood_observer
        self._shutdown = False
        self._owns_resources = resource_manager is None
        self._resource_manager = resource_manager or ResourceManager(max_workers=1)
        self._future: Future | None = None
        self._task_handle: TaskHandle | None = None
        self._job_kind: str | None = None
        self._job_context: object | None = None
        self._job_operation: Operation | None = None
        self._job_started_at: float | None = None
        self._target_view = None
        self._job_edit_listener_remove = None
        self._results = MatchIndex(())
        self._results_view = None
        self._result_listener_remove = None
        self._current_index: int | None = None
        self._results_compiled = None
        self._zoom_percent = 100
        self._pattern_generation = 0
        self._pattern_analysis = RegexAnalysis.empty(
            role=ExpressionRole.PATTERN,
            expression="",
            engine_pattern="",
            generation=0,
            state=AnalysisState.PENDING,
        )
        self._replacement_generation = 0
        self._replacement_analysis = RegexAnalysis.empty(
            role=ExpressionRole.REPLACEMENT,
            expression="",
            engine_pattern="",
            generation=0,
            pattern_generation=0,
            state=AnalysisState.PENDING,
        )
        self._analysis_timer = QTimer(self)
        self._analysis_timer.setSingleShot(True)
        self._analysis_timer.setInterval(150)
        owner_ref = weakref.ref(self)

        def analysis_finished(generation, handle) -> None:
            owner = owner_ref()
            if owner is not None and not owner._shutdown:
                owner._analysis_task_finished(generation, handle)

        self._analysis_slot: LatestTaskSlot[RegexAnalysis] = LatestTaskSlot(
            self._resource_manager.tasks,
            analysis_finished,
        )
        self._capture_generation = 0
        self._capture_request: CaptureReportRequest | None = None

        def capture_finished(generation, handle) -> None:
            owner = owner_ref()
            if owner is not None and not owner._shutdown:
                owner._capture_task_finished(generation, handle)

        self._capture_slot: LatestTaskSlot[CaptureReport] = LatestTaskSlot(
            self._resource_manager.tasks,
            capture_finished,
        )

        content = QWidget(self)
        self.setWidget(content)
        self.find_input = RegexInput(content)
        self.replace_input = ReplacementInput(content)
        self.status_label = QLabel("0 matches", content)
        self.capture_view = QListView(content)
        self.capture_model = CaptureReportModel(self.capture_view)
        self.capture_view.setModel(self.capture_model)
        self.capture_view.setAccessibleName("Match Report")
        self.regex_checkbox = QCheckBox("Regex", content)
        self.case_sensitive_checkbox = QCheckBox("Case", content)
        self.whole_word_checkbox = QCheckBox("Whole word", content)

        self.find_clear_button = self._clear_button("Clear Find", self.find_input)
        self.replace_clear_button = self._clear_button(
            "Clear Replace", self.replace_input
        )
        self.find_clear_button.clicked.connect(self.find_input.clear)
        self.replace_clear_button.clicked.connect(self.replace_input.clear)
        self.find_input.textChanged.connect(
            lambda: self.find_clear_button.setEnabled(bool(self.find_input.text()))
        )
        self.replace_input.textChanged.connect(
            lambda: self.replace_clear_button.setEnabled(
                bool(self.replace_input.text())
            )
        )
        self.find_clear_button.setEnabled(False)
        self.replace_clear_button.setEnabled(False)

        self.find_indicator = _IconLabel("search", "Find", content)
        self.replace_indicator = _IconLabel("replace", "Replace", content)
        find_row = QHBoxLayout()
        find_row.addWidget(self.find_indicator)
        find_row.addWidget(self.find_input, 1)
        replace_row = QHBoxLayout()
        replace_row.addWidget(self.replace_indicator)
        replace_row.addWidget(self.replace_input, 1)

        options_row = QHBoxLayout()
        options_row.addWidget(self.regex_checkbox)
        options_row.addWidget(self.case_sensitive_checkbox)
        options_row.addWidget(self.whole_word_checkbox)
        options_row.addStretch(1)
        self.report_toggle_button = QPushButton(self)
        self.report_toggle_button.setSizePolicy(
            QSizePolicy.Policy.Fixed,
            QSizePolicy.Policy.Fixed,
        )
        self.report_toggle_button.setFixedWidth(34)
        options_row.addWidget(self.report_toggle_button)

        self.actions_widget = QWidget(content)
        actions = QHBoxLayout(self.actions_widget)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.setSpacing(4)
        self.find_all_button = self._compact_button(
            "search-check", "Find All", self.actions_widget
        )
        self.replace_all_button = self._compact_button(
            "replace-all", "Replace All", self.actions_widget
        )
        self.previous_button = self._compact_button(
            "chevron-left", "Previous Match", self.actions_widget
        )
        self.next_button = self._compact_button(
            "chevron-right", "Next Match", self.actions_widget
        )
        self.replace_button = self._compact_button(
            "replace", "Replace Current Match", self.actions_widget, width=34
        )
        actions.addWidget(self.find_all_button)
        actions.addWidget(self.replace_all_button)
        actions.addStretch(1)
        actions.addWidget(self.previous_button)
        actions.addWidget(self.next_button)
        actions.addWidget(self.replace_button)

        self.cancel_button = QPushButton("Cancel", content)
        self.cancel_button.setIcon(lucide_icon("circle-stop"))
        self.cancel_button.setEnabled(False)

        footer = QHBoxLayout()
        footer.addWidget(self.cancel_button)
        footer.addStretch(1)
        footer.addWidget(self.status_label)

        controls_widget = QWidget(content)
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
        bottom_controls_layout.addWidget(self.actions_widget)
        bottom_controls_layout.addLayout(footer)
        controls_layout.addWidget(self.bottom_controls_widget)

        self.report_frame = QFrame(content)
        report_layout = QVBoxLayout(self.report_frame)
        report_layout.setContentsMargins(4, 4, 4, 4)
        report_layout.addWidget(self.capture_view)

        self.report_splitter = QSplitter(Qt.Orientation.Horizontal, content)
        self.report_splitter.addWidget(controls_widget)
        self.report_splitter.addWidget(self.report_frame)
        self.report_splitter.setChildrenCollapsible(False)
        self.report_splitter.setCollapsible(0, False)
        self.report_splitter.setCollapsible(1, False)
        self.report_splitter.setStretchFactor(0, 1)
        self.report_splitter.setStretchFactor(1, 1)
        layout = QVBoxLayout(content)
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
        self.replace_input.textChanged.connect(self._replacement_changed)
        self.regex_checkbox.toggled.connect(self._search_mode_changed)
        self.case_sensitive_checkbox.toggled.connect(self._pattern_changed)
        self.whole_word_checkbox.toggled.connect(self._pattern_changed)
        self.report_toggle_button.clicked.connect(self.toggle_report)

        # Worker futures may finish before the next Qt timer tick.  Deliver
        # completion through a queued Qt signal so result application happens
        # deterministically on the GUI thread.
        self._jobCompleted.connect(
            self._poll_job, Qt.ConnectionType.QueuedConnection
        )
        self._analysisCompleted.connect(
            self._apply_pattern_analysis,
            Qt.ConnectionType.QueuedConnection,
        )
        self._captureCompleted.connect(
            self._apply_capture_report,
            Qt.ConnectionType.QueuedConnection,
        )
        self._analysis_timer.timeout.connect(self._submit_pattern_analysis)
        self.topLevelChanged.connect(self._top_level_changed)
        self._search_mode_changed(False)
        self._report_open = True
        self._report_width = 260
        self.set_report_location("Right")
        for widget in self.findChildren(QWidget):
            widget.installEventFilter(self)
        self._position_clear_buttons()

    def _record_dogfood(
        self,
        operation: Operation,
        outcome: Outcome,
        *,
        started_at: float,
    ) -> None:
        observer = self._dogfood_observer
        if observer is None:
            return
        try:
            observer(
                operation,
                outcome,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                durability=Durability.NOT_APPLICABLE,
            )
        except Exception:
            return

    @property
    def placement(self) -> str:
        return self._placement

    def _set_placement(self, placement: str) -> None:
        if placement not in {"attached", "detached"}:
            raise ValueError(f"unsupported find/replace placement: {placement}")
        if placement == self._placement:
            return
        self._placement = placement
        if not self._restoring_state:
            self.placementChanged.emit(placement)

    @staticmethod
    def _geometry_tuple(widget: QWidget) -> tuple[int, int, int, int]:
        geometry = widget.geometry()
        return geometry.x(), geometry.y(), geometry.width(), geometry.height()

    def _top_level_changed(self, floating: bool) -> None:
        if self._changing_placement:
            return
        self._set_placement("detached" if floating else "attached")

    def attach_to(self, host: QMainWindow) -> None:
        if not isinstance(host, QMainWindow):
            raise TypeError("find/replace host must be a QMainWindow")
        if self._placement == "detached":
            self._detached_geometry = self._geometry_tuple(self)
        previous_host = self._dock_host
        self._changing_placement = True
        try:
            if previous_host is not None and previous_host is not host:
                previous_host.removeDockWidget(self)
            host.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self)
            self.setFloating(False)
            self._dock_host = host
        finally:
            self._changing_placement = False
        self._set_placement("attached")

    def detach(self) -> None:
        geometry = self._detached_geometry
        self._changing_placement = True
        try:
            self.setFloating(True)
            self.setWindowFlag(Qt.WindowType.Tool, True)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
            self.setGeometry(*geometry)
        finally:
            self._changing_placement = False
        self._set_placement("detached")
        self.show()

    def release_from(self, host: QMainWindow) -> None:
        if not isinstance(host, QMainWindow):
            raise TypeError("find/replace host must be a QMainWindow")
        if self.parentWidget() is not host and self._dock_host is not host:
            return
        was_visible = not self.isHidden()
        if self._placement == "detached":
            self._detached_geometry = self._geometry_tuple(self)
        self._changing_placement = True
        try:
            self.hide()
            host.removeDockWidget(self)
            self.setParent(None)
            self._dock_host = None
            if self._placement == "detached":
                self.setWindowFlag(Qt.WindowType.Tool, True)
                self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                self.setAttribute(
                    Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow,
                    True,
                )
                self.setGeometry(*self._detached_geometry)
        finally:
            self._changing_placement = False
        if was_visible and self._placement == "detached":
            self.show()

    @property
    def zoom_percent(self) -> int:
        return self._zoom_percent

    @property
    def report_location(self) -> str:
        return "Right" if self._report_open else "Hidden"

    @staticmethod
    def _compact_button(
        icon_name: str,
        accessible_name: str,
        parent: QWidget,
        *,
        width: int = 40,
    ) -> QPushButton:
        button = QPushButton(parent)
        button.setIcon(lucide_icon(icon_name))
        button.setAccessibleName(accessible_name)
        button.setToolTip(accessible_name)
        button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        button.setFixedWidth(width)
        return button

    @staticmethod
    def _clear_button(accessible_name: str, parent: QWidget) -> QToolButton:
        button = QToolButton(parent)
        button.setAutoRaise(True)
        button.setIcon(lucide_icon("circle-x"))
        button.setAccessibleName(accessible_name)
        button.setToolTip(accessible_name)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(20, 20)
        parent.setViewportMargins(0, 0, 26, 0)
        return button

    def _position_clear_buttons(self) -> None:
        for field, button in (
            (self.find_input, self.find_clear_button),
            (self.replace_input, self.replace_clear_button),
        ):
            button.move(max(0, field.width() - button.width() - 4), 4)
            button.raise_()

    def set_zoom_percent(self, percent: int) -> None:
        percent = max(50, min(300, int(percent)))
        if percent == self._zoom_percent:
            return
        scale = percent / self._zoom_percent
        self._zoom_percent = percent
        for widget in (self.find_input, self.replace_input, self.capture_view):
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
        if watched in (self.find_input, self.replace_input) and event.type() in {
            QEvent.Type.Resize,
            QEvent.Type.Show,
        }:
            self._position_clear_buttons()
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
        normalized = "Hidden" if location == "Hidden" else "Right"
        previous = self.report_location
        sizes = self.report_splitter.sizes()
        if normalized == "Hidden":
            if len(sizes) > 1 and sizes[1] > 0:
                self._report_width = sizes[1]
            self._report_open = False
            self.report_frame.hide()
        else:
            self._report_open = True
            self.report_frame.show()
            if len(sizes) < 2 or sizes[1] == 0:
                total = max(self.width(), 720)
                report_width = min(self._report_width, max(120, total // 2))
                self.report_splitter.setSizes((total - report_width, report_width))
        self._update_report_toggle_button()
        if normalized != previous:
            self.reportLocationChanged.emit(normalized)

    def cycle_report_location(self) -> None:
        self.toggle_report()

    def toggle_report(self) -> None:
        self.set_report_location("Hidden" if self._report_open else "Right")

    def _update_report_toggle_button(self) -> None:
        if self._report_open:
            self.report_toggle_button.setIcon(lucide_icon("panel-right-close"))
            label = "Hide Match Report"
        else:
            self.report_toggle_button.setIcon(lucide_icon("panel-right-open"))
            label = "Show Match Report"
        self.report_toggle_button.setAccessibleName(label)
        self.report_toggle_button.setToolTip(label)

    @property
    def regex_mode(self) -> bool:
        return self.regex_checkbox.isChecked()

    def _search_mode_changed(self, regex_mode: bool) -> None:
        self.case_sensitive_checkbox.setEnabled(not regex_mode)
        self.whole_word_checkbox.setEnabled(not regex_mode)
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

    def set_view_provider(self, provider: Callable[[], object | None]) -> None:
        if not callable(provider):
            raise TypeError("view provider must be callable")
        self._view_provider = provider
        self._update_actions()

    def target_changed(self) -> None:
        if self.busy:
            self.cancel_search()
        self._clear_results()
        self._refresh_analysis_status()

    def export_state(self, last_target_view_id: str | None) -> FindReplaceRecord:
        find, replace = bound_find_replace_histories(
            self.find_input.export_history(),
            self.replace_input.export_history(),
        )
        if self._placement == "detached":
            self._detached_geometry = self._geometry_tuple(self)
        return FindReplaceRecord(
            find=find,
            replace=replace,
            regex=self.regex_checkbox.isChecked(),
            case_sensitive=self.case_sensitive_checkbox.isChecked(),
            whole_word=self.whole_word_checkbox.isChecked(),
            visible=not self.isHidden(),
            geometry=self._detached_geometry,
            zoom_percent=self.zoom_percent,
            report_visible=self._report_open,
            last_target_view_id=last_target_view_id,
            placement=self._placement,
        )

    def restore_state(self, record: FindReplaceRecord) -> None:
        if not isinstance(record, FindReplaceRecord):
            raise TypeError("record must be a FindReplaceRecord")
        self.target_changed()
        widgets = (
            self,
            self.find_input,
            self.replace_input,
            self.regex_checkbox,
            self.case_sensitive_checkbox,
            self.whole_word_checkbox,
        )
        blocked = tuple(widget.blockSignals(True) for widget in widgets)
        self._restoring_state = True
        try:
            if record.geometry is not None:
                self._detached_geometry = record.geometry
                self.setGeometry(*record.geometry)
            self.set_zoom_percent(record.zoom_percent)
            self.set_report_location("Right" if record.report_visible else "Hidden")
            self.find_input.restore_history(record.find)
            self.replace_input.restore_history(record.replace)
            self.regex_checkbox.setChecked(record.regex)
            self.case_sensitive_checkbox.setChecked(record.case_sensitive)
            self.whole_word_checkbox.setChecked(record.whole_word)
            self.case_sensitive_checkbox.setEnabled(not record.regex)
            self.whole_word_checkbox.setEnabled(not record.regex)
            self.find_clear_button.setEnabled(bool(record.find.current.text))
            self.replace_clear_button.setEnabled(bool(record.replace.current.text))
            self._set_placement(record.placement)
            self.show() if record.visible else self.hide()
        finally:
            self._restoring_state = False
            for widget, was_blocked in zip(widgets, blocked):
                widget.blockSignals(was_blocked)
        self._pattern_changed()

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
        analysis = self._pattern_analysis
        if (
            analysis.state is AnalysisState.VALID
            and analysis.generation == self._pattern_generation
            and analysis.expression == self.find_input.text()
        ):
            return analysis.compiled
        return None

    def _compile_current(self):
        return self.compile_current()

    def _replacement_expression(self) -> str:
        replacement = self.replace_input.text()
        if self.regex_mode:
            return replacement
        return replacement.replace("\\", "\\\\")

    def _pattern_changed(self, *_args) -> None:
        if self.busy:
            self.cancel_search()
        self._analysis_slot.cancel()
        self._analysis_timer.stop()
        self._pattern_generation += 1
        self._clear_results()
        expression = self.find_input.text()
        self._pattern_analysis = pending_pattern_analysis(
            expression,
            self._pattern_generation,
            literal=not self.regex_mode,
            case_sensitive=self.case_sensitive_checkbox.isChecked(),
            whole_word=self.whole_word_checkbox.isChecked(),
        )
        self.find_input.set_analysis(self._pattern_analysis)
        self._reanalyze_replacement()
        if expression and self._pattern_analysis.state is AnalysisState.PENDING:
            self._analysis_timer.start()
        self._refresh_analysis_status()
        self._update_actions()

    def _replacement_changed(self, *_args) -> None:
        self._reanalyze_replacement()
        self._refresh_analysis_status()
        self._update_actions()

    def _reanalyze_replacement(self) -> None:
        self._replacement_generation += 1
        self._replacement_analysis = analyze_replacement(
            self.replace_input.text(),
            self._pattern_analysis,
            self._replacement_generation,
            literal=not self.regex_mode,
        )
        self.replace_input.set_analysis(self._replacement_analysis)

    def _submit_pattern_analysis(self) -> None:
        generation = self._pattern_generation
        expression = self.find_input.text()
        if (
            not expression
            or self._pattern_analysis.state is not AnalysisState.PENDING
            or self._pattern_analysis.generation != generation
        ):
            return
        options = {
            "literal": not self.regex_mode,
            "case_sensitive": self.case_sensitive_checkbox.isChecked(),
            "whole_word": self.whole_word_checkbox.isChecked(),
        }
        spec = TaskSpec.create(
            TaskKind.REGEX_ANALYSIS,
            foreground=False,
            estimated_memory_bytes=min(len(expression), 65_536) * 16,
        )
        self._analysis_slot.request(
            generation,
            spec,
            lambda _context: analyze_pattern(expression, generation, **options),
        )

    def _analysis_task_finished(
        self,
        generation: int,
        handle: TaskHandle[RegexAnalysis],
    ) -> None:
        self._analysisCompleted.emit(generation, handle)

    def _apply_pattern_analysis(
        self,
        generation: int,
        handle: TaskHandle[RegexAnalysis],
    ) -> None:
        try:
            analysis = handle.future.result()
        except Exception:
            return
        if (
            generation != self._pattern_generation
            or analysis.generation != generation
            or analysis.expression != self.find_input.text()
        ):
            return
        self._pattern_analysis = analysis
        self.find_input.set_analysis(analysis)
        self._reanalyze_replacement()
        self._refresh_analysis_status()
        self._update_actions()

    def _pattern_is_current(self) -> bool:
        return (
            bool(self.find_input.text())
            and self.compile_current() is not None
        )

    def _replacement_is_current(self) -> bool:
        analysis = self._replacement_analysis
        return (
            analysis.state is AnalysisState.VALID
            and analysis.expression == self.replace_input.text()
            and analysis.pattern_generation == self._pattern_generation
        )

    def _refresh_analysis_status(self) -> None:
        if self.busy:
            return
        expression = self.find_input.text()
        if not expression:
            self.status_label.setText("enter a pattern")
            return
        pattern = self._pattern_analysis
        if pattern.state is AnalysisState.PENDING:
            self.status_label.setText("checking pattern…")
            return
        if pattern.state in {AnalysisState.INVALID, AnalysisState.OVER_LIMIT}:
            message = (
                pattern.diagnostics[0].message
                if pattern.diagnostics
                else "invalid pattern"
            )
            self.status_label.setText(message)
            return
        replacement = self._replacement_analysis
        if replacement.state in {AnalysisState.INVALID, AnalysisState.OVER_LIMIT}:
            message = (
                replacement.diagnostics[0].message
                if replacement.diagnostics
                else "invalid replacement"
            )
            self.status_label.setText(message)
            return
        if len(self._results):
            if self._current_index is None:
                self.status_label.setText(f"{len(self._results):,} matches")
            else:
                self.status_label.setText(
                    f"match {self._current_index + 1:,}/{len(self._results):,}"
                )
            return
        suffix = "group" if pattern.group_count == 1 else "groups"
        self.status_label.setText(
            f"valid pattern — {pattern.group_count:,} {suffix}"
        )

    def _update_actions(self) -> None:
        view = self._current_view()
        idle = not self.busy
        pattern_valid = view is not None and self._pattern_is_current()
        replacement_valid = pattern_valid and self._replacement_is_current()
        results_current = bool(
            view is not None
            and len(self._results)
            and self._results_are_current(view)
        )
        self.find_all_button.setEnabled(idle and pattern_valid)
        self.previous_button.setEnabled(idle and pattern_valid)
        self.next_button.setEnabled(idle and pattern_valid)
        self.replace_button.setEnabled(
            idle and results_current and replacement_valid
        )
        self.replace_all_button.setEnabled(idle and replacement_valid)
        self.cancel_button.setEnabled(not idle)

    def _clear_results(self) -> None:
        self._cancel_capture_report(clear=True)
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
        self._results_compiled = None
        self._update_actions()

    def _cancel_capture_report(self, *, clear: bool) -> None:
        self._capture_generation += 1
        self._capture_request = None
        self._capture_slot.cancel()
        if clear:
            self.capture_model.clear()

    def _operation_seal(self, view) -> OperationSeal:
        return OperationSeal(
            pattern_generation=self._pattern_generation,
            pattern_text=self.find_input.text(),
            document_key=str(id(view.document)),
            revision=view.document.revision,
        )

    def _seal_is_current(self, seal: OperationSeal, view) -> bool:
        return (
            view is not None
            and seal.pattern_generation == self._pattern_generation
            and seal.pattern_text == self.find_input.text()
            and seal.document_key == str(id(view.document))
            and seal.revision == view.document.revision
        )

    @staticmethod
    def _safe_operation_error(error: Exception) -> str:
        if isinstance(error, RegexSearchTimeout):
            return "regex operation timed out"
        if isinstance(error, RegexContextLimitError):
            return "regex requires more bounded context than allowed"
        if isinstance(error, TaskAdmissionError):
            return "operation refused by current resource limits"
        return "regex operation failed"

    def _start_job(
        self,
        kind: str,
        view,
        fn,
        *,
        task_kind: TaskKind,
        dogfood_operation: Operation,
        started_at: float,
        context=None,
        rejected_cleanup: Callable[[], None] | None = None,
    ) -> bool:
        if self.busy:
            if rejected_cleanup is not None:
                rejected_cleanup()
            self.status_label.setText("busy — cancel current work first")
            self._record_dogfood(
                dogfood_operation,
                Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            return False
        self._job_kind = kind
        self._job_context = context
        self._job_operation = dogfood_operation
        self._job_started_at = started_at
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
            self._job_operation = None
            self._job_started_at = None
            self._target_view = None
            self.cancel_button.setEnabled(False)
            self.status_label.setText(self._safe_operation_error(exc))
            self._update_actions()
            self._record_dogfood(
                dogfood_operation,
                (
                    Outcome.UNAVAILABLE
                    if isinstance(exc, TaskAdmissionError)
                    else Outcome.FAILED
                ),
                started_at=started_at,
            )
            return False
        self._future = self._task_handle.future
        self._job_edit_listener_remove = view.document.add_edit_listener(
            lambda _operation, view=view: self._cancel_for_edit(view)
        )
        if rejected_cleanup is not None:
            self._future.add_done_callback(
                lambda _future: rejected_cleanup()
            )
        self._future.add_done_callback(lambda _future: self._jobCompleted.emit())
        self._update_actions()
        return True

    def _cancel_for_edit(self, view) -> None:
        if view is not self._target_view:
            return
        self.cancel_search()
        self.status_label.setText("text changed — search again")

    def _start_find(
        self,
        view,
        compiled,
        *,
        direction: int,
        origin: int,
        dogfood_operation: Operation,
        started_at: float,
    ) -> None:
        seal = self._operation_seal(view)
        revision = seal.revision
        snapshot = view.document.snapshot()

        def work(context: TaskContext):
            store = MatchStore(
                memory_budget_bytes=_FIND_RESULT_MEMORY_BYTES,
                document_revision=revision,
            )
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
            dogfood_operation=dogfood_operation,
            started_at=started_at,
            context=FindRequest(compiled, seal, direction, origin),
            rejected_cleanup=snapshot.close,
        )

    def find_all(self) -> None:
        started_at = time.monotonic()
        view = self._current_view()
        compiled = self.compile_current()
        if view is None or compiled is None:
            self._record_dogfood(
                Operation.FIND_ALL,
                Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            return
        if len(self._results) and self._results_are_current(view):
            self.status_label.setText(f"{len(self._results):,} matches")
            self._record_dogfood(
                Operation.FIND_ALL,
                Outcome.SUCCESS,
                started_at=started_at,
            )
            return
        self._start_find(
            view,
            compiled,
            direction=1,
            origin=view.state.cursor,
            dogfood_operation=Operation.FIND_ALL,
            started_at=started_at,
        )

    def replace_current(self) -> None:
        started_at = time.monotonic()
        view = self._current_view()
        compiled = self.compile_current()
        if (
            view is None
            or compiled is None
            or not self._replacement_is_current()
        ):
            self._record_dogfood(
                Operation.REPLACE,
                Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            return
        if self._current_index is None:
            self._record_dogfood(
                Operation.REPLACE,
                Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            self.find_all()
            return
        self._cancel_capture_report(clear=True)
        target_index = self._current_index
        seal = self._operation_seal(view)
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
            dogfood_operation=Operation.REPLACE,
            started_at=started_at,
            context=(target_index, seal),
            rejected_cleanup=snapshot.close,
        )

    def replace_all(self) -> None:
        started_at = time.monotonic()
        view = self._current_view()
        compiled = self.compile_current()
        if (
            view is None
            or compiled is None
            or not self._replacement_is_current()
        ):
            self._record_dogfood(
                Operation.REPLACE_ALL,
                Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            return
        self._cancel_capture_report(clear=True)
        seal = self._operation_seal(view)
        revision = seal.revision
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
            dogfood_operation=Operation.REPLACE_ALL,
            started_at=started_at,
            context=seal,
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
        dogfood_operation = self._job_operation
        started_at = self._job_started_at
        view = self._target_view
        task_handle = self._task_handle
        self._future = None
        self._task_handle = None
        self._job_kind = None
        self._job_context = None
        self._job_operation = None
        self._job_started_at = None
        self._target_view = None
        if self._job_edit_listener_remove is not None:
            self._job_edit_listener_remove()
            self._job_edit_listener_remove = None
        self.cancel_button.setEnabled(False)
        self._update_actions()
        try:
            payload = future.result()
        except Exception as exc:
            if task_handle is not None and task_handle.token.cancelled:
                if self.status_label.text() != "text changed — search again":
                    self.status_label.setText("cancelled")
                if dogfood_operation is not None and started_at is not None:
                    self._record_dogfood(
                        dogfood_operation,
                        Outcome.CANCELLED,
                        started_at=started_at,
                    )
                return
            self.status_label.setText(self._safe_operation_error(exc))
            if dogfood_operation is not None and started_at is not None:
                self._record_dogfood(
                    dogfood_operation,
                    (
                        Outcome.TIMEOUT
                        if isinstance(exc, RegexSearchTimeout)
                        else Outcome.FAILED
                    ),
                    started_at=started_at,
                )
            return

        if task_handle is not None and task_handle.token.cancelled:
            if isinstance(payload, (MatchStore, ReplacementPlan)):
                payload.close()
            if self.status_label.text() != "text changed — search again":
                self.status_label.setText("cancelled")
            if dogfood_operation is not None and started_at is not None:
                self._record_dogfood(
                    dogfood_operation,
                    Outcome.CANCELLED,
                    started_at=started_at,
                )
            return

        try:
            if kind == "find":
                matched = self._apply_find_results(view, payload, context)
                if matched is None:
                    operation_outcome = Outcome.UNAVAILABLE
                elif dogfood_operation is Operation.FIND_ALL or matched:
                    operation_outcome = Outcome.SUCCESS
                else:
                    operation_outcome = Outcome.UNAVAILABLE
            elif kind == "replace_current":
                operation_outcome = (
                    Outcome.SUCCESS
                    if self._apply_current_replacement(view, payload, context)
                    else Outcome.UNAVAILABLE
                )
            elif kind == "replace_all":
                operation_outcome = self._apply_replace_all(view, payload, context)
            else:
                operation_outcome = Outcome.FAILED
        except Exception:
            operation_outcome = Outcome.FAILED
            self.status_label.setText("regex operation failed")
        if dogfood_operation is not None and started_at is not None:
            self._record_dogfood(
                dogfood_operation,
                operation_outcome,
                started_at=started_at,
            )

    def _apply_find_results(self, view, store: MatchStore, context) -> bool | None:
        if (
            not isinstance(context, FindRequest)
            or not self._seal_is_current(context.seal, view)
            or view.document.revision != store.document_revision
        ):
            store.close()
            self._clear_results()
            self.status_label.setText("text changed — search again")
            return None
        self._clear_results()
        self._results = store
        self._results_view = view
        self._results_compiled = context.compiled
        self._result_listener_remove = view.document.add_edit_listener(
            lambda _operation, view=view: self._invalidate_results_for_edit(view)
        )
        view.set_match_index(self._results)
        self.status_label.setText(f"{len(self._results):,} matches")
        self._current_index = (
            self._results.previous_index(context.origin)
            if context.direction < 0
            else self._results.next_index(context.origin)
        )
        if self._current_index is not None:
            self._navigate_to(self._current_index)
        else:
            self.capture_model.clear()
        self._update_actions()
        return self._current_index is not None

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
    ) -> bool:
        if (
            not isinstance(context, tuple)
            or len(context) != 2
            or not isinstance(context[0], int)
            or not isinstance(context[1], OperationSeal)
            or view is None
            or not self._seal_is_current(context[1], view)
            or context[0] >= len(replacements)
        ):
            self.status_label.setText("match changed — search again")
            self._clear_results()
            return False
        replacement = replacements[context[0]]
        view.document.replace(replacement.start, replacement.end, replacement.text)
        view.state.move_to(replacement.start + len(replacement.text))
        self._clear_results()
        view._state_changed()
        self.status_label.setText("1 replaced")
        self._update_actions()
        return True

    def _apply_replace_all(
        self,
        view,
        plan: ReplacementPlan,
        seal: OperationSeal,
    ) -> Outcome:
        if not isinstance(seal, OperationSeal) or not self._seal_is_current(seal, view):
            plan.close()
            self.status_label.setText("text changed — search again")
            return Outcome.UNAVAILABLE
        memory_limit = max(
            1 << 20,
            min(256 << 20, self._resource_manager.status.available_memory // 4),
        )
        try:
            count = view.document.apply_replacement_plan(
                plan,
                expected_revision=seal.revision,
                memory_limit_bytes=memory_limit,
            )
        except Exception as exc:
            self.status_label.setText(self._safe_operation_error(exc))
            return Outcome.FAILED
        finally:
            plan.close()
        self._clear_results()
        view._state_changed()
        self.status_label.setText(f"{count:,} replaced")
        self._update_actions()
        return Outcome.SUCCESS

    @staticmethod
    def _navigation_origin(view, direction: int) -> int:
        selection = view.state.selection
        if selection is None:
            return view.state.cursor
        return selection[1] if direction > 0 else selection[0]

    def _current_result_is_selected(self, view) -> bool:
        index = self._current_index
        if index is None or index < 0 or index >= len(self._results):
            return False
        record = self._results.records[index]
        if record.start == record.end:
            return (
                view.state.selection is None
                and view.state.cursor == record.start
                and view.state.anchor == record.start
            )
        return view.state.selection == record.span

    def _navigation_index(self, view, direction: int) -> int | None:
        if self._current_result_is_selected(view):
            return advance_result_index(
                self._current_index,
                len(self._results),
                direction,
            )
        origin = self._navigation_origin(view, direction)
        if direction < 0:
            return self._results.previous_index(origin)
        return self._results.next_index(origin)

    def _navigate_match(self, direction: int) -> None:
        started_at = time.monotonic()
        dogfood_operation = (
            Operation.FIND_PREVIOUS if direction < 0 else Operation.FIND_NEXT
        )
        view = self._current_view()
        compiled = self.compile_current()
        if view is None or compiled is None:
            self._record_dogfood(
                dogfood_operation,
                Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            return
        if len(self._results) and self._results_are_current(view):
            index = self._navigation_index(view, direction)
            if index is not None:
                self._navigate_to(index)
            self._record_dogfood(
                dogfood_operation,
                Outcome.SUCCESS if index is not None else Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            return
        if len(self._results):
            self._clear_results()
        self._start_find(
            view,
            compiled,
            direction=direction,
            origin=self._navigation_origin(view, direction),
            dogfood_operation=dogfood_operation,
            started_at=started_at,
        )

    def next_match(self) -> None:
        self._navigate_match(1)

    def previous_match(self) -> None:
        self._navigate_match(-1)

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
        self._request_capture_report(view, index)

    def _request_capture_report(self, view, index: int) -> None:
        if (
            not isinstance(self._results, MatchStore)
            or self._results_compiled is None
            or not self._results_are_current(view)
        ):
            self._cancel_capture_report(clear=True)
            return
        count = len(self._results)
        indices = (index,) if count == 1 else (index, (index + 1) % count)
        request = CaptureReportRequest(
            pattern_generation=self._pattern_generation,
            pattern_text=self.find_input.text(),
            document_key=str(id(view.document)),
            revision=view.document.revision,
            store_id=self._results.store_id,
            requested_index=index,
            match_count=count,
            matches=tuple(
                (match_index, self._results.records[match_index])
                for match_index in indices
            ),
        )
        self._capture_generation += 1
        generation = self._capture_generation
        self._capture_request = request
        self.capture_model.set_loading()
        try:
            snapshot = view.document.snapshot()
        except Exception:
            self._capture_slot.cancel()
            self.capture_model.set_report(self._capture_failure(request))
            return
        compiled = self._results_compiled
        spec = TaskSpec.create(
            TaskKind.CAPTURE_REPORT,
            foreground=False,
            document_key=request.document_key,
            revision=request.revision,
            estimated_memory_bytes=2 << 20,
        )

        def work(context: TaskContext) -> CaptureReport:
            with snapshot:
                return resolve_capture_report(
                    snapshot,
                    compiled,
                    request,
                    cancelled=lambda: context.token.cancelled,
                )

        panel_ref = weakref.ref(self)

        def discard_snapshot() -> None:
            snapshot.close()
            panel = panel_ref()
            if panel is not None and not panel._shutdown:
                panel._captureCompleted.emit(generation, None)

        self._capture_slot.request(
            generation,
            spec,
            work,
            discard=discard_snapshot,
        )

    def _capture_task_finished(
        self,
        generation: int,
        handle: TaskHandle[CaptureReport],
    ) -> None:
        self._captureCompleted.emit(generation, handle)

    @staticmethod
    def _capture_failure(request: CaptureReportRequest) -> CaptureReport:
        reason = "capture details unavailable"
        matches = tuple(
            CaptureMatchReport(
                index=index,
                total=request.match_count,
                groups=(),
                unavailable_reason=reason,
            )
            for index, _record in request.matches
        )
        payload_bytes = (
            64 * (2 + len(request.matches) + len(matches))
            + len(request.pattern_text.encode("utf-8"))
            + len(reason.encode("utf-8")) * len(matches)
        )
        return CaptureReport(request, matches, payload_bytes)

    def _capture_request_is_current(self, request: CaptureReportRequest) -> bool:
        view = self._current_view()
        if (
            request is not self._capture_request
            or view is None
            or view is not self._results_view
            or not isinstance(self._results, MatchStore)
            or self._current_index != request.requested_index
            or len(self._results) != request.match_count
            or self._results.store_id != request.store_id
            or self._pattern_generation != request.pattern_generation
            or self.find_input.text() != request.pattern_text
            or str(id(view.document)) != request.document_key
        ):
            return False
        try:
            return view.document.revision == request.revision
        except Exception:
            return False

    def _apply_capture_report(
        self,
        generation: int,
        handle: TaskHandle[CaptureReport] | None,
    ) -> None:
        if generation != self._capture_generation:
            return
        request = self._capture_request
        if request is None or not self._capture_request_is_current(request):
            return
        try:
            if handle is None:
                raise RuntimeError("capture report unavailable")
            report = handle.future.result()
            if handle.token.cancelled or not isinstance(report, CaptureReport):
                raise RuntimeError("capture report unavailable")
        except Exception:
            report = self._capture_failure(request)
        if (
            generation == self._capture_generation
            and report.request is request
            and self._capture_request_is_current(request)
        ):
            self.capture_model.set_report(report)

    def reject(self) -> None:
        self._cancel_capture_report(clear=True)
        self.hide()

    def closeEvent(self, event) -> None:
        self._cancel_capture_report(clear=True)
        super().closeEvent(event)

    def _emit_geometry(self) -> None:
        if self._placement != "detached" or self._changing_placement:
            return
        self._detached_geometry = self._geometry_tuple(self)
        if not self._restoring_state:
            self.geometryChanged.emit(self._detached_geometry)

    def moveEvent(self, event) -> None:
        super().moveEvent(event)
        self._emit_geometry()

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        self._emit_geometry()

    def shutdown(self) -> None:
        self._shutdown = True
        self._analysis_timer.stop()
        self._analysis_slot.close()
        self._cancel_capture_report(clear=True)
        self._capture_slot.close()
        if self.capture_view.model() is self.capture_model:
            self.capture_view.setModel(None)
        self.cancel_search()
        if self._job_edit_listener_remove is not None:
            self._job_edit_listener_remove()
            self._job_edit_listener_remove = None
        if self._owns_resources:
            self._resource_manager.shutdown(wait=False)


# Compatibility name for implemented callers while the project migrates from
# the embedded-panel vocabulary to the floating utility.
FindReplacePanel = FindReplaceWindow
