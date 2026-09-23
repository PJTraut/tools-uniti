"""Worker-backed regex Find/Replace panel for UNITI."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
from dataclasses import dataclass
from enum import Enum
import time
import uuid
import weakref

from PySide6.QtCore import QEvent, QPoint, QPointF, QTimer, Qt, Signal
from PySide6.QtGui import (
    QFont,
    QFontMetrics,
    QGuiApplication,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QCheckBox,
    QApplication,
    QComboBox,
    QDockWidget,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListView,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QTextEdit,
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
    MAX_CAPTURE_REPORT_MATCHES,
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
from uniti.ui.capture_report_delegate import CaptureReportDelegate
from uniti.ui.icons import lucide_icon
from uniti.ui.regex_input import RegexInput, ReplacementInput
from uniti.ui.screen_geometry import clamp_geometry_to_screens, current_screen_geometries


_FIND_RESULT_MEMORY_BYTES = 1 << 20

FIND_REPLACE_VIEW_ID = "uniti-find-replace"

# BF-059: a compact, reasonable default for the very first attach — not a
# proportion of the main window's height, which is the behavior being fixed.
DEFAULT_ATTACHED_HEIGHT = 280


class ReplaceScope(Enum):
    WHOLE_DOCUMENT = "whole_document"
    CURSOR_TO_END = "cursor_to_end"
    CURRENT_GROUP = "current_group"
    ALL_OPEN_DOCUMENTS = "all_open_documents"


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
    region: tuple[int, int] | None = None


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


class _FindReplaceTitleBar(QWidget):
    """Custom title bar installed via ``setTitleBarWidget`` on the detached
    floating shell. Qt's built-in drag-to-move gesture is wired to the
    *native* title bar area; installing a custom title bar widget disables
    it, since the custom widget now consumes the mouse events that
    machinery relied on. This widget reimplements drag-to-move directly.
    Attaching/detaching is no longer a drag gesture (see ``attach_to``) —
    this title bar only ever appears while floating, so it only needs to
    reposition the floating window.
    """

    def __init__(self, dock: QDockWidget) -> None:
        super().__init__(dock)
        self._dock = dock
        self._drag_offset: QPoint | None = None

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self._dock.pos()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._drag_offset is not None and event.buttons() & Qt.MouseButton.LeftButton:
            global_pos = event.globalPosition().toPoint()
            self._dock.move(global_pos - self._drag_offset)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if self._drag_offset is not None:
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)


class _FindReplaceContentHost(QWidget):
    """Wraps the Find/Replace content so it can be inserted as a real leaf
    in an ``EditorPaneTree`` (the same pane-splitting system text views use)
    when attached, instead of docking via Qt's native ``QDockWidget`` area
    mechanism. ``EditorPaneTree``/``PaneLeaf`` only require a ``QWidget``
    with a ``view_id`` attribute, plus an optional ``viewFocused`` signal for
    focus-follow (``panes.py``'s ``_connect_view_focus``) — this is the
    minimal adapter satisfying that contract."""

    viewFocused = Signal(str)

    def __init__(self, view_id: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.view_id = view_id

    def focusInEvent(self, event) -> None:
        super().focusInEvent(event)
        self.viewFocused.emit(self.view_id)


class FindReplaceWindow(QDockWidget):
    """Modeless Find/Replace utility; match records never become document state."""

    zoomChanged = Signal(int)
    reportLocationChanged = Signal(str)
    geometryChanged = Signal(tuple)
    attachedHeightChanged = Signal(int)
    placementChanged = Signal(str)
    matchPositionChanged = Signal(str, object)
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
        document_provider: Callable[[], object] | None = None,
        group_provider: Callable[[object], object] | None = None,
        recipe_store: object | None = None,
    ) -> None:
        if dogfood_observer is not None and not callable(dogfood_observer):
            raise TypeError("dogfood observer must be callable or None")
        if document_provider is not None and not callable(document_provider):
            raise TypeError("document provider must be callable or None")
        if group_provider is not None and not callable(group_provider):
            raise TypeError("group provider must be callable or None")
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
        self._detached_geometry = (0, 0, 820, 320)
        self._attached_height = DEFAULT_ATTACHED_HEIGHT
        self._attached_splitter: QSplitter | None = None
        self._restoring_state = False
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
        self.resize(820, 320)
        self._view_provider = view_provider
        self._document_provider = document_provider
        self._group_provider = group_provider
        self._recipe_store = recipe_store
        self._recipes: tuple = tuple(recipe_store.load()) if recipe_store is not None else ()
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
        self._results_region: tuple[int, int] | None = None
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

        content = _FindReplaceContentHost(FIND_REPLACE_VIEW_ID, self)
        self.content = content
        self.setWidget(content)
        self.find_input = RegexInput(content)
        self.replace_input = ReplacementInput(content)
        self.status_label = QLabel("0 matches", content)
        self.status_label.setAccessibleName("Status")
        self.pattern_info_label = QLabel(content)
        self.pattern_info_label.setAccessibleName("Pattern Info")
        self.capture_view = QListView(content)
        self.capture_model = CaptureReportModel(self.capture_view)
        self.capture_view.setModel(self.capture_model)
        self.capture_view.setItemDelegate(CaptureReportDelegate(self.capture_view))
        self.capture_view.setAccessibleName("Match Report")
        self.capture_view.clicked.connect(self._jump_to_report_row)
        self._update_capture_view_minimum_height()
        self.regex_checkbox = QCheckBox("Regex", content)
        self.case_sensitive_checkbox = QCheckBox("Case", content)
        self.whole_word_checkbox = QCheckBox("Whole word", content)
        self.selection_only_checkbox = QCheckBox("In Selection", content)

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

        self.find_wrap_button = self._wrap_toggle_button("Wrap Find", self.find_input)
        self.replace_wrap_button = self._wrap_toggle_button(
            "Wrap Replace", self.replace_input
        )
        self.find_wrap_button.toggled.connect(self._find_wrap_toggled)
        self.replace_wrap_button.toggled.connect(self._replace_wrap_toggled)

        self.find_indicator = _IconLabel("search", "Find", content)
        self.replace_indicator = _IconLabel("replace", "Replace", content)
        find_row = QHBoxLayout()
        find_row.addWidget(self.find_indicator)
        find_row.addWidget(self.find_input, 1)
        replace_row = QHBoxLayout()
        replace_row.addWidget(self.replace_indicator)
        replace_row.addWidget(self.replace_input, 1)

        self.replace_scope_combo = QComboBox(content)
        self.replace_scope_combo.setAccessibleName("Replace Scope")
        self.replace_scope_combo.setToolTip("Replace Scope")
        self.replace_scope_combo.addItem("Whole Document", ReplaceScope.WHOLE_DOCUMENT)
        self.replace_scope_combo.addItem("Cursor to End", ReplaceScope.CURSOR_TO_END)
        self.replace_scope_combo.addItem("Current Group", ReplaceScope.CURRENT_GROUP)
        self.replace_scope_combo.addItem(
            "All Open Documents", ReplaceScope.ALL_OPEN_DOCUMENTS
        )
        self.replace_scope_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )

        self.recipe_combo = QComboBox(content)
        self.recipe_combo.setAccessibleName("Find/Replace Recipes")
        self.recipe_combo.setToolTip("Find/Replace Recipes")
        self.recipe_combo.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToContents
        )

        options_row = QHBoxLayout()
        options_row.addWidget(self.regex_checkbox)
        options_row.addWidget(self.case_sensitive_checkbox)
        options_row.addWidget(self.whole_word_checkbox)
        options_row.addWidget(self.selection_only_checkbox)
        options_row.addWidget(self.replace_scope_combo)
        options_row.addWidget(self.recipe_combo)
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
        self.replace_and_next_button = self._compact_button(
            self._replace_and_advance_icon(),
            "Replace & Find Next",
            self.actions_widget,
            width=34,
        )
        self.cancel_button = QPushButton("Cancel", content)
        self.cancel_button.setIcon(lucide_icon("circle-stop"))
        self.cancel_button.setAccessibleName("Cancel")
        self.cancel_button.setEnabled(False)

        actions.addWidget(self.find_all_button)
        actions.addWidget(self.replace_all_button)
        actions.addStretch(1)
        # Centered on the actions row, between the left- and right-hand
        # button groups (2026-09-21 request) -- always visible here
        # regardless of whether the Match Report panel is open or
        # collapsed, unlike a position inside `report_frame` would be.
        actions.addWidget(self.status_label)
        actions.addStretch(1)
        actions.addWidget(self.previous_button)
        actions.addWidget(self.next_button)
        actions.addWidget(self.replace_button)
        actions.addWidget(self.replace_and_next_button)
        actions.addWidget(self.cancel_button)

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
        controls_layout.addWidget(self.bottom_controls_widget)

        self.report_frame = QFrame(content)
        report_layout = QVBoxLayout(self.report_frame)
        report_layout.setContentsMargins(4, 4, 4, 4)
        report_layout.addWidget(self.capture_view)
        report_layout.addWidget(self.pattern_info_label)

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
        self.replace_and_next_button.clicked.connect(self.replace_and_find_next)
        self.replace_all_button.clicked.connect(self.replace_all)
        self.cancel_button.clicked.connect(self.cancel_search)
        self.find_input.returnPressed.connect(self.next_match)
        self.replace_input.returnPressed.connect(self.replace_current)
        self.find_input.textChanged.connect(self._pattern_changed)
        self.replace_input.textChanged.connect(self._replacement_changed)
        self.regex_checkbox.toggled.connect(self._search_mode_changed)
        self.case_sensitive_checkbox.toggled.connect(self._pattern_changed)
        self.whole_word_checkbox.toggled.connect(self._pattern_changed)
        self.selection_only_checkbox.toggled.connect(self._selection_only_toggled)
        self.report_toggle_button.clicked.connect(self.toggle_report)
        self.recipe_combo.activated.connect(self._recipe_combo_activated)
        self._refresh_recipe_combo()

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
        self._search_mode_changed(False)
        self._report_open = True
        self._report_width = 260
        self.set_report_location("Right")

        title_bar = _FindReplaceTitleBar(self)
        title_bar_layout = QHBoxLayout(title_bar)
        title_bar_layout.setContentsMargins(6, 2, 2, 2)
        title_bar_label = QLabel("Find / Replace", title_bar)
        title_bar_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        title_bar_layout.addWidget(title_bar_label)
        title_bar_layout.addStretch(1)
        self.setTitleBarWidget(title_bar)
        # setTitleBarWidget rebuilds the floating window frame, which can
        # reset the window flags applied above; reassert them.
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)

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

    def is_visible(self) -> bool:
        """Whether the panel is currently visible to the user (BF-054),
        accounting for both placements: attached (its pane-tree tab exists
        in its host) and detached (the floating window's own visibility)."""

        if self._placement == "attached":
            return self._dock_host is not None and self._dock_host.panes.contains_view(
                self.content.view_id
            )
        return self.isVisible()

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

    def set_detached_geometry(self, geometry: tuple[int, int, int, int]) -> None:
        """Set this window's geometry to `geometry`, first clamping it back
        onto a currently connected screen if it no longer overlaps any
        (e.g. it was saved while on an external monitor that has since
        been unplugged) — otherwise it would restore to a position that is
        practically unreachable rather than merely off the panel's
        preferred spot."""

        clamped = clamp_geometry_to_screens(geometry, current_screen_geometries())
        self._detached_geometry = clamped
        self.setGeometry(*clamped)

    def _remove_content_from_pane_tree(self, host: QMainWindow) -> None:
        """Take the content widget out of ``host``'s pane tree, collapsing
        the split it lived in if that leaf is now empty (mirrors
        ``EditorPaneTree.remove_shell_view``'s take-then-collapse pattern,
        ``panes.py``)."""

        tree = host.panes
        view_id = self.content.view_id
        leaf = tree.leaf_for_view(view_id)
        if leaf is None:
            return
        leaf.take_view(view_id)
        if leaf.count() == 0 and tree.leaf_count > 1:
            tree.close_leaf(leaf.pane_id)

    def _insert_content_into_pane_tree(self, host: QMainWindow, *, select: bool) -> None:
        """Insert the content widget as a new split leaf in ``host``'s pane
        tree, anchored below the current document view (or added directly
        if the window has no views open yet). Splitting always makes the
        new leaf the tree's active leaf (``EditorPaneTree.split_view``), so
        unless ``select`` asks for Find/Replace to become focused, the
        previously active document tab is restored afterward."""

        tree = host.panes
        view_id = self.content.view_id
        if tree.contains_view(view_id):
            return
        previous_leaf = tree.active_leaf
        previous_view_id = (
            previous_leaf.selected_view_id if previous_leaf is not None else None
        )
        anchor = host.active_view_id
        if anchor is None and tree.view_ids:
            anchor = tree.view_ids[0]
        if anchor is None:
            tree.add_view(self.content, select=select, title="Find / Replace")
        else:
            # BF-059: attach at the remembered last-used height (never a
            # hardcoded 50%, and not computed as a proportion of the pane
            # tree's current height, which is unreliable before a layout
            # pass has run) and pin it against window-resize deltas via
            # stretch factors (1 for the editor pane, 0 for this one) rather
            # than the ordinary proportional-resize behavior `split_view`
            # gives user-created Split Right/Down panes.
            new_leaf = tree.split_view(
                anchor,
                Qt.Orientation.Vertical,
                stretch=(1, 0),
                fixed_sizes=(1, self._attached_height),
            )
            tree.add_view(
                self.content,
                pane_id=new_leaf.pane_id,
                select=select,
                title="Find / Replace",
            )
            self._track_attached_split(new_leaf)
        if not select and previous_view_id is not None:
            tree.activate_view(previous_view_id)

    def _track_attached_split(self, leaf) -> None:
        branch = leaf._parent_branch
        if branch is None:
            return
        splitter = branch.widget
        self._attached_splitter = splitter

        def _on_moved(_position: int, _index: int) -> None:
            if self._attached_splitter is not splitter:
                return
            sizes = splitter.sizes()
            if len(sizes) == 2 and sizes[1] > 0:
                self._attached_height = sizes[1]
                self.attachedHeightChanged.emit(sizes[1])

        splitter.splitterMoved.connect(_on_moved)

    def set_attached_height(self, height: int) -> None:
        """Seed the remembered attached-panel height (BF-059), e.g. from
        persisted settings on startup. Only affects the *next* attach."""

        if not isinstance(height, int) or isinstance(height, bool) or height <= 0:
            raise ValueError("attached height must be a positive integer")
        self._attached_height = height

    @property
    def attached_height(self) -> int:
        return self._attached_height

    def _reveal(self) -> None:
        if self._placement == "attached" and self._dock_host is not None:
            host = self._dock_host
            if host.panes.contains_view(self.content.view_id):
                host.panes.activate_view(self.content.view_id)
        else:
            self.show()

    def attach_to(self, host: QMainWindow) -> None:
        if not isinstance(host, QMainWindow):
            raise TypeError("find/replace host must be a QMainWindow")
        if self._changing_placement:
            # Removing content from a pane tree (``take_view``) synchronously
            # fires focus/active-view Qt signals that can cascade back into
            # application-level code (``set_active_view`` ->
            # ``_sync_find_replace_host`` -> ``attach_to``) before this call
            # finishes; ignore the reentrant call rather than recursing.
            return
        if self._placement == "detached":
            self._detached_geometry = self._geometry_tuple(self)
        previous_host = self._dock_host
        self._changing_placement = True
        try:
            if self._placement == "attached" and previous_host is not None and previous_host is not host:
                self._remove_content_from_pane_tree(previous_host)
            self.setWidget(None)
            self.hide()
            self._insert_content_into_pane_tree(host, select=False)
            self._dock_host = host
        finally:
            self._changing_placement = False
        self._set_placement("attached")

    def close_attached_tab(self) -> None:
        """Handle the pane-tree tab's own close button: park the content
        back in the (unshown) floating shell without forcing it to float
        visibly or changing the user's attached/detached preference —
        mirrors a native ``QDockWidget``'s own close button, which just
        hides it rather than undocking it. A later ``attach_to`` re-inserts
        it, honoring the preserved "attached" placement."""

        if self._changing_placement:
            return
        if self._placement == "attached" and self._dock_host is not None:
            self._changing_placement = True
            try:
                self._remove_content_from_pane_tree(self._dock_host)
                self.setWidget(self.content)
            finally:
                self._changing_placement = False

    def detach(self) -> None:
        if self._changing_placement:
            return
        geometry = self._detached_geometry
        self._changing_placement = True
        try:
            if self._placement == "attached" and self._dock_host is not None:
                self._remove_content_from_pane_tree(self._dock_host)
            self.setWidget(self.content)
            self.setWindowFlag(Qt.WindowType.Tool, True)
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            self.setAttribute(Qt.WidgetAttribute.WA_MacAlwaysShowToolWindow, True)
            self.set_detached_geometry(geometry)
        finally:
            self._changing_placement = False
        self._set_placement("detached")
        self.show()

    def release_from(self, host: QMainWindow) -> None:
        """Sever ties with a host that is going away (e.g. its last window
        closing) without another host to move to. Unlike ``detach()``, this
        does not change the user's "attached"/"detached" preference — it
        just parks the content safely in this shell (unshown) so it is not
        destroyed along with ``host``; a later ``attach_to`` honors the
        preserved placement once a host becomes available again."""

        if not isinstance(host, QMainWindow):
            raise TypeError("find/replace host must be a QMainWindow")
        if self._dock_host is not host or self._changing_placement:
            return
        self._changing_placement = True
        try:
            if self._placement == "attached":
                self._remove_content_from_pane_tree(host)
                self.setWidget(self.content)
            self._dock_host = None
        finally:
            self._changing_placement = False

    @property
    def zoom_percent(self) -> int:
        return self._zoom_percent

    @property
    def report_location(self) -> str:
        return "Right" if self._report_open else "Hidden"

    @staticmethod
    def _compact_button(
        icon_name: str | QIcon,
        accessible_name: str,
        parent: QWidget,
        *,
        width: int = 40,
    ) -> QPushButton:
        button = QPushButton(parent)
        button.setIcon(icon_name if isinstance(icon_name, QIcon) else lucide_icon(icon_name))
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
        parent.setViewportMargins(0, 0, 26, 22)
        return button

    @staticmethod
    def _wrap_toggle_icon() -> QIcon:
        """Theme-aware wrap glyph drawn without a bundled SVG asset."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            color = QGuiApplication.palette().color(
                QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText
            )
            pen = QPen(color, 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.drawLine(QPointF(3, 5), QPointF(12, 5))
            painter.drawPolyline(
                (
                    QPointF(12, 5),
                    QPointF(12, 10),
                    QPointF(5, 10),
                )
            )
            painter.drawLine(QPointF(5, 10), QPointF(8, 7.5))
            painter.drawLine(QPointF(5, 10), QPointF(8, 12.5))
        finally:
            painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _replace_and_advance_icon() -> QIcon:
        """Theme-aware checkmark-then-arrow glyph for step-through replace."""
        pixmap = QPixmap(16, 16)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            color = QGuiApplication.palette().color(
                QPalette.ColorGroup.Active, QPalette.ColorRole.ButtonText
            )
            pen = QPen(color, 1.4)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.drawPolyline(
                (QPointF(2, 8), QPointF(5.5, 11.5), QPointF(9, 4))
            )
            painter.drawLine(QPointF(9, 8), QPointF(14, 8))
            painter.drawLine(QPointF(11, 5.5), QPointF(14, 8))
            painter.drawLine(QPointF(11, 10.5), QPointF(14, 8))
        finally:
            painter.end()
        return QIcon(pixmap)

    @staticmethod
    def _wrap_toggle_button(accessible_name: str, parent: QWidget) -> QToolButton:
        button = QToolButton(parent)
        button.setAutoRaise(True)
        button.setCheckable(True)
        button.setIcon(FindReplaceWindow._wrap_toggle_icon())
        button.setAccessibleName(accessible_name)
        button.setToolTip(accessible_name)
        button.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        button.setFixedSize(20, 20)
        return button

    def _position_clear_buttons(self) -> None:
        for field, clear_button, wrap_button in (
            (self.find_input, self.find_clear_button, self.find_wrap_button),
            (self.replace_input, self.replace_clear_button, self.replace_wrap_button),
        ):
            right = max(0, field.width() - clear_button.width() - 4)
            clear_button.move(right, 4)
            wrap_button.move(right, clear_button.height() + 8)
            clear_button.raise_()
            wrap_button.raise_()

    @staticmethod
    def _apply_wrap_mode(field: QTextEdit, checked: bool) -> None:
        field.setLineWrapMode(
            QTextEdit.LineWrapMode.WidgetWidth
            if checked
            else QTextEdit.LineWrapMode.NoWrap
        )
        # Wrapped content can exceed the field's single-line height; allow
        # internal scrolling only while wrapped so the caret stays reachable.
        field.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAsNeeded
            if checked
            else Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

    def _find_wrap_toggled(self, checked: bool) -> None:
        self._apply_wrap_mode(self.find_input, checked)

    def _replace_wrap_toggled(self, checked: bool) -> None:
        self._apply_wrap_mode(self.replace_input, checked)

    def set_zoom_percent(self, percent: int) -> None:
        percent = max(50, min(500, int(percent)))
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
            field.setMinimumHeight(field.minimum_content_height())
        self._update_capture_view_minimum_height()
        self.zoomChanged.emit(percent)

    _CAPTURE_VIEW_MIN_VISIBLE_ROWS = MAX_CAPTURE_REPORT_MATCHES

    def _update_capture_view_minimum_height(self) -> None:
        """Keep the match report's minimum height tied only to the current
        zoom/font size, never to search-result content.

        A prior version (BF-050) grew this minimum to fit the first
        `_CAPTURE_VIEW_MIN_VISIBLE_ROWS` whole matches without scrolling,
        recomputed on every new search result. Because `capture_view` sits
        beside the controls pane in a horizontal `QSplitter`, that minimum
        became the splitter's (and so the whole panel window's) own minimum
        height — a match with many capture-group rows would silently grow
        the panel itself. Per explicit feedback the panel must not
        auto-expand to fit the match report, so this now only reflects a
        fixed row count at the current font size; a match report needing
        more room than that scrolls instead of resizing the window.
        """

        view = self.capture_view
        fallback_height = (
            QFontMetrics(view.font()).height() + 4
        ) * self._CAPTURE_VIEW_MIN_VISIBLE_ROWS
        view.setMinimumHeight(fallback_height)

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
        # BF-088: pasted literal whitespace converts to its regex escape
        # only in Regex mode -- a literal (non-regex) search/replace must
        # still be able to match an actual tab/newline, so it keeps
        # inserting the raw pasted bytes unchanged.
        self.find_input.set_regex_mode(regex_mode)
        self.replace_input.set_regex_mode(regex_mode)
        self._pattern_changed()

    def _selection_only_toggled(self, checked: bool) -> None:
        # "In Selection" and the Replace Scope combo are separate axes — a
        # selection region and "all open documents"/"cursor to end" don't
        # compose meaningfully, so selection scope wins outright while
        # checked, and the combo is unavailable rather than silently ignored.
        if checked:
            self.replace_scope_combo.setCurrentIndex(
                self.replace_scope_combo.findData(ReplaceScope.WHOLE_DOCUMENT)
            )
        self.replace_scope_combo.setEnabled(not checked)
        self._clear_results()

    def _search_region(self, view) -> tuple[int, int] | None:
        """The active selection's bounds when "In Selection" is checked, or
        None for an unrestricted (whole-document) search."""

        if not self.selection_only_checkbox.isChecked():
            return None
        return view.state.selection

    def _refresh_recipe_combo(self) -> None:
        blocked = self.recipe_combo.blockSignals(True)
        try:
            self.recipe_combo.clear()
            self.recipe_combo.addItem("Recipes", None)
            for recipe in self._recipes:
                self.recipe_combo.addItem(recipe.name, recipe)
            self.recipe_combo.insertSeparator(self.recipe_combo.count())
            self.recipe_combo.addItem("Save Current…", "__save__")
            self.recipe_combo.addItem("Manage…", "__manage__")
            self.recipe_combo.setCurrentIndex(0)
        finally:
            self.recipe_combo.blockSignals(blocked)

    def _recipe_combo_activated(self, index: int) -> None:
        data = self.recipe_combo.itemData(index)
        if data == "__save__":
            self._save_current_as_recipe()
        elif data == "__manage__":
            self._show_recipe_manager()
        elif data is not None:
            self._load_recipe(data)
        self.recipe_combo.setCurrentIndex(0)

    def _load_recipe(self, recipe) -> None:
        self.find_input.set_text(recipe.expression)
        self.replace_input.set_text(recipe.replacement)
        self.regex_checkbox.setChecked(recipe.regex)
        self.case_sensitive_checkbox.setChecked(recipe.case_sensitive)
        self.whole_word_checkbox.setChecked(recipe.whole_word)

    def _save_current_as_recipe(self) -> None:
        if self._recipe_store is None:
            return
        from PySide6.QtWidgets import QInputDialog

        from uniti.app.find_replace_recipes import FindReplaceRecipe

        name, ok = QInputDialog.getText(self, "Save Recipe", "Recipe name:")
        if not ok or not name.strip():
            return
        try:
            recipe = FindReplaceRecipe(
                uuid.uuid4().hex,
                name.strip(),
                self.find_input.text(),
                self.replace_input.text(),
                self.regex_checkbox.isChecked(),
                self.case_sensitive_checkbox.isChecked(),
                self.whole_word_checkbox.isChecked(),
            )
        except ValueError as exc:
            QMessageBox.warning(self, "Save Recipe", str(exc))
            return
        recipes = (*self._recipes, recipe)
        try:
            self._recipe_store.save(recipes)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Save Recipe", str(exc))
            return
        self._recipes = recipes
        self._refresh_recipe_combo()

    def _show_recipe_manager(self) -> None:
        if self._recipe_store is None:
            return
        from uniti.ui.find_replace_recipe_editor import FindReplaceRecipeEditor

        editor = FindReplaceRecipeEditor(self._recipes, self)
        if editor.exec():
            recipes = editor.recipes()
            self._recipe_store.save(recipes)
            self._recipes = recipes
            self._refresh_recipe_combo()

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
        self._reveal()
        self.find_input.setFocus()
        self.find_input.selectAll()

    def focus_replace(self) -> None:
        self._reveal()
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

    def set_document_provider(self, provider: Callable[[], object] | None) -> None:
        if provider is not None and not callable(provider):
            raise TypeError("document provider must be callable or None")
        self._document_provider = provider
        self._update_actions()

    def set_group_provider(self, provider: Callable[[object], object] | None) -> None:
        if provider is not None and not callable(provider):
            raise TypeError("group provider must be callable or None")
        self._group_provider = provider
        self._update_actions()

    def set_recipe_store(self, store: object | None) -> None:
        self._recipe_store = store
        self._recipes = tuple(store.load()) if store is not None else ()
        self._refresh_recipe_combo()

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
            visible=True if self._placement == "attached" else not self.isHidden(),
            geometry=self._detached_geometry,
            zoom_percent=self.zoom_percent,
            report_visible=self._report_open,
            last_target_view_id=last_target_view_id,
            placement=self._placement,
            find_wrap=self.find_wrap_button.isChecked(),
            replace_wrap=self.replace_wrap_button.isChecked(),
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
            self.find_wrap_button,
            self.replace_wrap_button,
        )
        blocked = tuple(widget.blockSignals(True) for widget in widgets)
        self._restoring_state = True
        try:
            if record.geometry is not None:
                self.set_detached_geometry(record.geometry)
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
            self.find_wrap_button.setChecked(record.find_wrap)
            self.replace_wrap_button.setChecked(record.replace_wrap)
            self._find_wrap_toggled(record.find_wrap)
            self._replace_wrap_toggled(record.replace_wrap)
            self._set_placement(record.placement)
            if record.placement != "attached":
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
        view = self._current_view()
        if view is not None and self._current_index is not None:
            self._request_capture_report(view, self._current_index)

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

    def _refresh_pattern_info_label(self) -> None:
        """Group-count info for the current pattern, shown under the Match
        Report rather than folded into `status_label`'s own busy/match/
        error messages (2026-09-20 request) -- it's a static property of
        the pattern, not a transient search-progress message, so it
        updates independently of `status_label` and of `self.busy`."""

        pattern = self._pattern_analysis
        if self.find_input.text() and pattern.state is AnalysisState.VALID:
            suffix = "group" if pattern.group_count == 1 else "groups"
            self.pattern_info_label.setText(
                f"valid pattern — {pattern.group_count:,} {suffix}"
            )
        else:
            self.pattern_info_label.setText("")

    def _refresh_analysis_status(self) -> None:
        self._refresh_pattern_info_label()
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
        if self._results_compiled is not None:
            # A search actually completed for this pattern and this
            # document state and found nothing -- distinct from having
            # never searched yet, which leaves status_label blank below
            # (a valid-but-unsearched pattern's group count is shown by
            # `pattern_info_label` instead, under the Match Report).
            self.status_label.setText("0 matches")
            return
        self.status_label.setText("")

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
        self.replace_and_next_button.setEnabled(
            idle and results_current and replacement_valid
        )
        self.replace_all_button.setEnabled(idle and replacement_valid)
        self.cancel_button.setEnabled(not idle)

    def _clear_results(self) -> None:
        self._cancel_capture_report(clear=True)
        if self._result_listener_remove is not None:
            self._result_listener_remove()
            self._result_listener_remove = None
        previous_view = self._results_view
        if previous_view is not None:
            previous_view.set_match_index(None)
        if isinstance(self._results, MatchStore):
            self._results.close()
        self._results = MatchIndex(())
        self._results_view = None
        self._results_region = None
        self._result_listener_remove = None
        self._current_index = None
        self._results_compiled = None
        self._update_actions()
        if previous_view is not None:
            self.matchPositionChanged.emit(previous_view.view_id, None)

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
        region = self._search_region(view)
        if self.selection_only_checkbox.isChecked() and region is None:
            self._record_dogfood(
                dogfood_operation,
                Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            return
        region_start, region_end = region if region is not None else (0, None)
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
                        options=SearchOptions(
                            timeout=0.5,
                            include_captures=False,
                            start=region_start,
                            end=region_end,
                        ),
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
            context=FindRequest(compiled, seal, direction, origin, region),
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
        if (
            len(self._results)
            and self._results_are_current(view)
            and self._results_region == self._search_region(view)
        ):
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

    def replace_current(self, *, advance: bool = False) -> None:
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
            context=(target_index, seal, advance),
            rejected_cleanup=snapshot.close,
        )

    def replace_and_find_next(self) -> None:
        """Step-through: confirm (replace) the current match, then advance.

        Per the BF-039 descope, this does not try to keep the old match list
        valid after a mutation — it replaces one match, then lets the normal
        `next_match` path re-search fresh from the post-replacement cursor
        position once the replace job completes.
        """

        self.replace_current(advance=True)

    def skip_current_match(self) -> None:
        """Step-through: leave the current match unchanged and advance."""

        self.next_match()

    def replace_scope(self) -> ReplaceScope:
        data = self.replace_scope_combo.currentData()
        return data if isinstance(data, ReplaceScope) else ReplaceScope.WHOLE_DOCUMENT

    def replace_all(self) -> None:
        scope = self.replace_scope()
        if scope is ReplaceScope.ALL_OPEN_DOCUMENTS:
            self._replace_all_open_documents()
            return
        if scope is ReplaceScope.CURRENT_GROUP:
            self._replace_all_in_group()
            return
        started_at = time.monotonic()
        view = self._current_view()
        compiled = self.compile_current()
        region = None if view is None else self._search_region(view)
        if (
            view is None
            or compiled is None
            or not self._replacement_is_current()
            or (self.selection_only_checkbox.isChecked() and region is None)
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
        if region is not None:
            search_start, search_end = region
        else:
            search_start = view.state.cursor if scope is ReplaceScope.CURSOR_TO_END else 0
            search_end = None
        snapshot = view.document.snapshot()

        def work(context: TaskContext):
            with snapshot:
                return collect_replacement_plan(
                    snapshot,
                    compiled,
                    replacement_text,
                    document_revision=revision,
                    options=SearchOptions(
                        timeout=0.5, start=search_start, end=search_end
                    ),
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

    def _replace_all_open_documents(self) -> None:
        self._replace_all_in_documents(
            provider=self._document_provider,
            provider_args=(),
        )

    def _replace_all_in_group(self) -> None:
        view = self._current_view()
        self._replace_all_in_documents(
            provider=self._group_provider,
            provider_args=(None if view is None else view.document,),
        )

    def _replace_all_in_documents(
        self,
        *,
        provider: Callable[..., object] | None,
        provider_args: tuple,
    ) -> None:
        started_at = time.monotonic()
        view = self._current_view()
        compiled = self.compile_current()
        if (
            view is None
            or compiled is None
            or not self._replacement_is_current()
            or provider is None
        ):
            self._record_dogfood(
                Operation.REPLACE_ALL,
                Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            return
        documents = list(provider(*provider_args))
        if not documents:
            self._record_dogfood(
                Operation.REPLACE_ALL,
                Outcome.UNAVAILABLE,
                started_at=started_at,
            )
            return
        self._cancel_capture_report(clear=True)
        replacement_text = self._replacement_expression()

        def work(context: TaskContext):
            results: list[tuple[object, ReplacementPlan]] = []
            try:
                for document in documents:
                    revision = document.revision
                    snapshot = document.snapshot()
                    with snapshot:
                        plan = collect_replacement_plan(
                            snapshot,
                            compiled,
                            replacement_text,
                            document_revision=revision,
                            options=SearchOptions(timeout=0.5),
                            cancelled=lambda: context.token.cancelled,
                        )
                    results.append((document, plan))
            except Exception:
                for _document, pending_plan in results:
                    pending_plan.close()
                raise
            return results

        self._start_job(
            "replace_all_documents",
            view,
            work,
            task_kind=TaskKind.REPLACE,
            dogfood_operation=Operation.REPLACE_ALL,
            started_at=started_at,
        )

    def cancel_search(self) -> None:
        if self._task_handle is not None:
            self._task_handle.cancel()
            self.status_label.setText("Cancelling…")

    def _poll_job(self) -> None:
        if self._shutdown:
            return
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
            elif kind == "replace_all_documents" and isinstance(payload, list):
                for _document, pending_plan in payload:
                    pending_plan.close()
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
                advance = (
                    isinstance(context, tuple)
                    and len(context) == 3
                    and bool(context[2])
                )
                applied = self._apply_current_replacement(
                    view,
                    payload,
                    context[:2] if isinstance(context, tuple) else context,
                )
                operation_outcome = Outcome.SUCCESS if applied else Outcome.UNAVAILABLE
                if applied and advance:
                    self.next_match()
            elif kind == "replace_all":
                operation_outcome = self._apply_replace_all(view, payload, context)
            elif kind == "replace_all_documents":
                operation_outcome = self._apply_replace_all_documents(payload)
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
        self._results_region = context.region
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

    def _apply_replace_all_documents(
        self,
        results: list[tuple[object, ReplacementPlan]],
    ) -> Outcome:
        memory_limit = max(
            1 << 20,
            min(256 << 20, self._resource_manager.status.available_memory // 4),
        )
        replaced_total = 0
        documents_changed = 0
        documents_skipped = 0
        for document, plan in results:
            try:
                count = document.apply_replacement_plan(
                    plan,
                    expected_revision=plan.document_revision,
                    memory_limit_bytes=memory_limit,
                )
            except Exception:
                documents_skipped += 1
                continue
            finally:
                plan.close()
            replaced_total += count
            if count:
                documents_changed += 1
        self._clear_results()
        if documents_skipped:
            self.status_label.setText(
                f"{replaced_total:,} replaced across {documents_changed:,} "
                f"document(s); {documents_skipped:,} skipped (changed during planning)"
            )
        else:
            self.status_label.setText(
                f"{replaced_total:,} replaced across {documents_changed:,} document(s)"
            )
        self._update_actions()
        if documents_skipped and documents_changed == 0:
            return Outcome.FAILED
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
        if (
            len(self._results)
            and self._results_are_current(view)
            and self._results_region == self._search_region(view)
        ):
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

    def _jump_to_report_row(self, index) -> None:
        match_index = index.data(CaptureReportModel.MatchIndexRole)
        if isinstance(match_index, int):
            self._navigate_to(match_index)

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
        self.matchPositionChanged.emit(
            view.view_id, f"Match {index + 1:,} of {len(self._results):,}"
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
        window = min(count, MAX_CAPTURE_REPORT_MATCHES)
        indices = tuple(
            dict.fromkeys((index + offset) % count for offset in range(window))
        )
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

        replacement_text = self._replacement_expression()

        def work(context: TaskContext) -> CaptureReport:
            with snapshot:
                return resolve_capture_report(
                    snapshot,
                    compiled,
                    request,
                    cancelled=lambda: context.token.cancelled,
                    replacement=replacement_text,
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
        # Deliberately never includes the triggering exception's own text:
        # that could leak internal detail (paths, snippets of document
        # content quoted in an error, memory addresses) into a report a
        # user might export or share. See
        # test_capture_failure_leaves_valid_match_navigation_intact.
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
        if self.busy:
            self.cancel_search()
        self._cancel_capture_report(clear=True)
        self.hide()

    def closeEvent(self, event) -> None:
        if self.busy:
            self.cancel_search()
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
