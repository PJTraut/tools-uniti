"""Minimal native UNITI desktop shell."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Future
from dataclasses import dataclass, replace as dataclass_replace
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from typing import TYPE_CHECKING
import uuid
import weakref

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QCloseEvent,
    QColor,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from uniti.app.diagnostics import diagnostics_snapshot
from uniti.app.dogfood import Operation, Outcome
from uniti.app.commands import (
    CommandCategory,
    CommandRegistry,
    CommandScope,
)
from uniti.app.editor_state import EditorState
from uniti.app.platform_policy import native_paths_equal, normalize_native_path
from uniti.app.recovery_manager import RecoveryHealth, RecoveryManager
from uniti.app.session import MAX_VIEWS
from uniti.app.settings import (
    MAX_EDITOR_TAB_WIDTH,
    MIN_EDITOR_TAB_WIDTH,
    Settings,
    SettingsStore,
)
from uniti.app.window_manager import ViewLocation
from uniti.core.byte_source import ByteSource
from uniti.core.document import Document
from uniti.core.durability import DurabilityLevel
from uniti.core.eol import EOLReport, analyze_eol
from uniti.core.file_identity import ExternalFileChangedError, FileIdentity
from uniti.core.reformatters import (
    MAX_REFORMAT_CHARS,
    ReformatFailure,
    reformatter_for_key,
)
from uniti.core.syntax_profiles import (
    MARKDOWN,
    PLAIN_TEXT,
    PROFILES,
    PROFILES_BY_KEY,
    profile_for_extension,
)
from uniti.core.index_jobs import (
    LineNavigationResult,
    build_line_index_batch,
    resolve_line_in_batch,
)
from uniti.core.text_format import (
    EOLPolicy,
    EncodingProfile,
    OutputFormat,
    encoding_profile,
    encoding_profiles,
    profile_from_codec,
)
from uniti.regex.replace import convert_document_eol, convert_document_tabs_to_spaces
from uniti.core.text_inspection import (
    TextFileInspection,
    inspect_source,
    preview_source,
)
from uniti.resources import (
    ResourceManager,
    ResourceSnapshot,
    ResourceState,
    TaskAdmissionError,
    TaskContext,
    TaskHandle,
    TaskKind,
    TaskSpec,
    WorkPriority,
)
from uniti.ui.character_inspector import CharacterInspectorDialog
from uniti.ui.compare_pane import (
    MAX_COMPARE_CHARS,
    CompareDocumentPickerDialog,
    ComparePane,
)
from uniti.ui.diagnostics_dialog import DiagnosticsDialog
from uniti.ui.file_format_dialogs import (
    LineEndingReportDialog,
    OpenFormatDialog,
    SaveAsFormatDialog,
)
from uniti.ui.file_operations import FileOperationController, FileOperationHandle
from uniti.ui.find_replace import FIND_REPLACE_VIEW_ID, FindReplaceWindow
from uniti.ui.hotkeys import HotkeysPopup
from uniti.ui.panes import EditorPaneTree
from uniti.ui.shortcut_policy import build_shortcut_policy
from uniti.ui.status_bar import UNITIStatusBar
from uniti.ui.text_view import UNITITextView
from uniti.ui.theme import (
    THEME_CONTRASTS,
    THEME_MODES,
    EditorThemeTokens,
    ThemeSpec,
    active_theme,
    apply_theme,
    apply_profile,
    preview_active,
    resolve_editor_tokens,
    resolve_profile_editor_tokens,
)
from uniti.ui.whitespace import WhitespaceMode, parse_whitespace_mode
from uniti.ui.unicode_inspection import unicode_inspection

if TYPE_CHECKING:
    from uniti.app.service import UNITIService


@dataclass(frozen=True, slots=True)
class _EOLJob:
    handle: TaskHandle[EOLReport]
    view_ref: weakref.ReferenceType
    document: Document
    identity: FileIdentity


@dataclass(frozen=True, slots=True)
class _NavigationJob:
    handle: TaskHandle[LineNavigationResult]
    view_ref: weakref.ReferenceType
    document: Document
    revision: int
    selecting: bool


@dataclass(frozen=True, slots=True)
class _SaveAsDecision:
    destination: Path
    output_format: OutputFormat
    target_view: UNITITextView | None
    expected_target_identity: FileIdentity | None
    in_place: bool


@dataclass(frozen=True, slots=True)
class _SaveJob:
    operation: FileOperationHandle
    view_ref: weakref.ReferenceType
    document: Document
    output_format: OutputFormat
    target_view_ref: weakref.ReferenceType | None
    target_document: Document | None


def _convert_and_set_output_eol(document: Document, eol: str | None) -> None:
    """Apply an EOL choice to a document's live content immediately (BF-023),
    then record it as the output policy too — shared by the Editor View menu
    (`UNITIMainWindow.set_output_eol`) and the mixed-EOL-on-open dialog
    (`_show_mixed_eol_report`), so both surfaces for choosing a document's
    EOL behave identically rather than one converting live and the other
    only deferring to save."""

    if eol is not None:
        convert_document_eol(document, eol)
        document.set_insertion_eol(eol)
    document.set_output_eol(eol)


class UNITIMainWindow(QMainWindow):
    def __init__(
        self,
        service: UNITIService | None = None,
        parent=None,
        *,
        window_id: str | None = None,
        recovery_manager: RecoveryManager | None = None,
        settings_store: SettingsStore | None = None,
        resource_manager: ResourceManager | None = None,
        startup_snapshot: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        if service is not None:
            self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.window_id = window_id or uuid.uuid4().hex
        if service is not None and any(
            item is not None
            for item in (recovery_manager, settings_store, resource_manager)
        ):
            raise ValueError(
                "service-owned windows cannot override process services"
            )
        self._recovery_manager = (
            service.recovery if service is not None else recovery_manager
        )
        self._settings_store = (
            service.settings if service is not None else settings_store
        )
        self._settings = (
            self._settings_store.load()
            if self._settings_store is not None
            else Settings()
        )
        from uniti.app.theme_profiles import ThemeProfileState
        self._theme_store = self._settings_store.theme_profiles if self._settings_store is not None else None
        self._theme_state = (self._theme_store.load(self._settings.theme_mode)
                             if self._theme_store is not None else ThemeProfileState(active_id=self._settings.theme_mode))
        from uniti.app.document_groups import default_groups
        self._group_store = (
            self._settings_store.document_groups
            if self._settings_store is not None
            else None
        )
        self._groups = (
            self._group_store.load() if self._group_store is not None else default_groups()
        )
        self._recent_files_store = (
            self._settings_store.recent_files
            if self._settings_store is not None
            else None
        )
        app = QApplication.instance()
        if isinstance(app, QApplication) and not preview_active(app):
            profile = self._theme_state.resolve()
            if profile is not None:
                apply_profile(app, profile, self._settings.theme_contrast)
            else:
                apply_theme(app, self._theme_state.active_id, self._settings.theme_contrast)
        shortcut_policy = build_shortcut_policy(
            self._settings.shortcut_overrides
        )
        unicode_inspection(QApplication.instance()).set_modifiers(
            self._settings.whitespace_inspect_modifiers
        )
        self.shortcut_notices = shortcut_policy.notices
        self.shortcut_warning_count = 0
        cleaned_overrides = dict(shortcut_policy.overrides)
        if cleaned_overrides != self._settings.shortcut_overrides:
            self._settings = dataclass_replace(
                self._settings,
                shortcut_overrides=cleaned_overrides,
            )
            self._save_settings()
        self._command_registry = CommandRegistry(
            shortcut_policy.definitions,
            overrides=shortcut_policy.overrides,
        )
        self._command_actions: dict[str, QAction] = {}
        self._find_replace_shortcuts: dict[str, QShortcut] = {}
        self._hotkeys_popup: HotkeysPopup | None = None
        self._command_registry.add_listener(self._on_command_binding_changed)
        self._owns_resources = service is None and resource_manager is None
        self._resources = (
            service.resources
            if service is not None
            else resource_manager or ResourceManager()
        )
        self._file_operations = FileOperationController(
            self._resources,
            self,
            dogfood_observer=(
                None if service is None else service.record_dogfood
            ),
        )
        self._file_operations.operationFinished.connect(
            self._finish_file_operation,
            Qt.ConnectionType.QueuedConnection,
        )
        self._save_jobs: dict[str, _SaveJob] = {}
        self._startup_snapshot = dict(startup_snapshot or {})
        self.setWindowTitle("UNITI")
        self.resize(1100, 760)
        self._panes = EditorPaneTree(self)
        self._tabs = self._panes.active_leaf.tabs
        self._panes.activeViewChanged.connect(self._on_pane_active)
        if service is not None:
            self._panes.viewSelected.connect(self._on_pane_view_selected)
        self._panes.viewCloseRequested.connect(self._close_view_id)
        self._panes.splitRequested.connect(self._split_pane)
        self._panes.assignmentRequested.connect(self._show_assignment_menu)
        self._panes.dockToggleRequested.connect(self._toggle_view_dock)
        self._panes.groupMenuRequested.connect(self._show_group_menu)
        if service is not None:
            self._panes.viewDetachRequested.connect(
                lambda view_id, _position: service.undock_view(view_id)
            )
        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        self._central_splitter = QSplitter(Qt.Orientation.Horizontal, central)
        self._central_splitter.addWidget(self._panes)
        central_layout.addWidget(self._central_splitter, 1)
        self._markdown_preview: MarkdownPreviewPane | None = None
        self._markdown_preview_target_view: UNITITextView | None = None
        # One generic tracker for every "toggle window" (2026-09-20
        # request: "one global function to manage toggle windows") --
        # Compare, Character Inspector, and any future one -- keyed by a
        # short window identifier. See `_toggle_window`/
        # `_on_toggle_window_closed` below; `_compare_pane`/
        # `_character_inspector_dialog` stay as read-only convenience
        # properties over this dict.
        self._toggle_windows: dict[str, QWidget] = {}
        self._markdown_preview_timer = QTimer(self)
        self._markdown_preview_timer.setSingleShot(True)
        self._markdown_preview_timer.setInterval(300)
        self._markdown_preview_timer.timeout.connect(self._refresh_markdown_preview_now)
        self._find_replace = (
            service.find_replace
            if service is not None
            else FindReplaceWindow(
                lambda: self.current_view,
                self,
                resource_manager=self._resources,
            )
        )
        for field in (
            self._find_replace.find_input,
            self._find_replace.replace_input,
        ):
            field.installEventFilter(self)
            field.viewport().installEventFilter(self)
        self._find_replace.matchPositionChanged.connect(self._on_match_position_changed)
        self._find_replace.attachedHeightChanged.connect(
            self._on_find_replace_attached_height_changed
        )
        if self._settings.find_replace_attached_height is not None:
            self._find_replace.set_attached_height(
                self._settings.find_replace_attached_height
            )
        if service is None:
            self._find_replace.hide()
            self._find_replace.set_zoom_percent(
                self._settings.find_replace_zoom_percent
            )
            self._find_replace.set_report_location(
                self._settings.find_replace_report_location
            )
            if self._settings.find_replace_geometry is not None:
                self._find_replace.set_detached_geometry(
                    self._settings.find_replace_geometry
                )
        self.setCentralWidget(central)
        self._status = UNITIStatusBar(self)
        self.setStatusBar(self._status)
        self._resource_notice_active = False
        self._recovery_notice_active = False
        self._recovery_notice_key: str | None = None
        self._recovery_notice_count = 0
        self._resource_notice_count = 0
        self._last_task_snapshot_generation = -1
        self._status.update_resources(self._resources.status)
        self._file_operations.taskSnapshotChanged.connect(
            self._apply_task_system_snapshot,
            Qt.ConnectionType.QueuedConnection,
        )

        self._eol_jobs: dict[str, _EOLJob] = {}
        self._eol_reports: dict[int, EOLReport] = {}
        self._eol_dialogs: dict[int, LineEndingReportDialog] = {}
        self._eol_timer = QTimer(self)
        self._eol_timer.setInterval(80)
        self._eol_timer.timeout.connect(self._poll_eol_jobs)
        self._navigation_jobs: dict[str, _NavigationJob] = {}
        self._navigation_timer = QTimer(self)
        self._navigation_timer.setInterval(20)
        self._navigation_timer.timeout.connect(self._poll_navigation_jobs)
        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(1000)
        self._resource_timer.timeout.connect(self._observe_resource_pressure)
        self._resource_probe_future: Future[ResourceSnapshot] | None = None
        self._resource_timer.start()
        self._build_menus()
        if self.shortcut_notices:
            self._show_shortcut_settings_warning()
        if service is not None:
            service.register_window(self.window_id, self)

    def _show_shortcut_settings_warning(self) -> None:
        self.shortcut_warning_count += 1
        count = len(self.shortcut_notices)
        message = (
            f"{count} saved shortcut setting"
            f"{' was' if count == 1 else 's were'} ignored because "
            f"the saved {'value was' if count == 1 else 'values were'} unknown, "
            "invalid, or conflicted with another command."
        )
        dialog = QMessageBox(
            QMessageBox.Icon.Warning,
            "Shortcut Settings Adjusted",
            message,
            QMessageBox.StandardButton.Ok,
            self,
        )
        dialog.setModal(False)
        dialog.open()
        self._shortcut_warning_dialog = dialog

    def _observe_resource_pressure(self) -> None:
        self._apply_recovery_status()
        future = self._resource_probe_future
        if future is None:
            self._resource_probe_future = self._resources.workers.submit(
                WorkPriority.PREFETCH,
                self._resources.sample_resources,
            )
            return
        if not future.done():
            return
        self._resource_probe_future = None
        try:
            self._resources.observe_resources(future.result())
            self._apply_resource_status(self._resources.status)
            self._apply_recovery_status()
        except Exception:
            # Memory telemetry must never interfere with editing.
            return

    def _apply_recovery_status(self) -> None:
        service = self._service
        message: str | None = None
        key: str | None = None
        if service is not None:
            recovery_health = getattr(service, "recovery_health", RecoveryHealth.OK)
            recovery_durability = getattr(
                service,
                "recovery_durability",
                DurabilityLevel.FULL,
            )
            session = getattr(service, "session_durability", None)
            session_durability = getattr(session, "level", DurabilityLevel.FULL)
            if (
                recovery_health is RecoveryHealth.DEGRADED
                or recovery_durability is DurabilityLevel.UNSAFE
            ):
                key = "recovery_unsafe"
                message = "New recovery is unavailable; existing durable evidence is retained."
            elif session_durability is DurabilityLevel.UNSAFE:
                key = "session_unsafe"
                message = "New session state is unavailable; the previous complete session is retained."
            elif (
                recovery_health is RecoveryHealth.REDUCED
                or recovery_durability is DurabilityLevel.FILE_SYNCED
                or session_durability is DurabilityLevel.FILE_SYNCED
            ):
                key = "reduced"
                message = "Persistence is file-synced, but power-loss durability is reduced."
            elif getattr(service, "recovery_degraded", False):
                key = "low_space"
                message = (
                    "Recovery degraded: saved edit history was reduced to protect free space."
                )
        if message is not None:
            if key != self._recovery_notice_key:
                self._recovery_notice_count += 1
            self._recovery_notice_key = key
            self._recovery_notice_active = True
            if self.statusBar().currentMessage() != message:
                self.statusBar().showMessage(message)
        elif self._recovery_notice_active:
            self._recovery_notice_active = False
            self._recovery_notice_key = None
            self.statusBar().clearMessage()

    def _apply_resource_status(self, status) -> None:
        self._status.update_resources(status)
        constrained = status.state in {
            ResourceState.CONSTRAINED,
            ResourceState.CRITICAL,
        }
        if constrained and not self._resource_notice_active:
            self._resource_notice_active = True
            self._resource_notice_count += 1
            self.statusBar().showMessage(
                f"System resources are {status.state.value}; background work reduced.",
                5000,
            )
        elif not constrained:
            self._resource_notice_active = False

    def _apply_task_system_snapshot(self) -> None:
        snapshot = self._resources.tasks.snapshot()
        if snapshot.generation <= self._last_task_snapshot_generation:
            return
        self._last_task_snapshot_generation = snapshot.generation
        visible = [
            task
            for task in snapshot.tasks
            if task.progress is not None and task.spec.foreground
        ]
        if not visible:
            visible = [task for task in snapshot.tasks if task.progress is not None]
        if visible:
            latest = max(
                visible,
                key=lambda task: task.progress.updated_at,  # type: ignore[union-attr]
            )
            assert latest.progress is not None
            self._status.update_task(latest.progress)
            return
        active = self._status.active_task
        if active is not None:
            self._status.clear_task(active.task_id)

    def _save_settings(self) -> None:
        if self._settings_store is not None:
            try:
                self._settings_store.save(self._settings)
            except OSError:
                pass

    def commit_theme_state(self, state) -> object:
        """Persist first; callers see errors and keep their draft on failure."""
        result = None
        if self._theme_store is not None:
            result = self._theme_store.save(state.profiles, state.active_id)
            if not result.replaced or not result.file_synced:
                raise OSError("Theme write did not reach durable publication")
        app = QApplication.instance()
        for window in app.topLevelWidgets() if isinstance(app, QApplication) else self._appearance_windows():
            if isinstance(window, UNITIMainWindow):
                window._theme_state = state
                window._refresh_theme_menu()
                window._refresh_editor_theme_menu()
        if isinstance(app, QApplication):
            profile = state.resolve()
            if profile is not None:
                apply_profile(app, profile, self._settings.theme_contrast)
            else:
                apply_theme(app, state.active_id, self._settings.theme_contrast)
        return result

    def set_theme(self, mode: str) -> None:
        from uniti.app.theme_profiles import BUILTIN_IDS, ThemeProfileState
        if mode not in (*BUILTIN_IDS, *(p.id for p in self._theme_state.profiles)):
            return
        app = QApplication.instance()
        editor = getattr(app, '_uniti_theme_editor', None)
        if editor is not None:
            editor.reject()
        try:
            self.commit_theme_state(ThemeProfileState(self._theme_state.profiles, mode))
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Theme could not be saved", str(exc))
            self._refresh_theme_menu()
            return
        if mode in THEME_MODES:
            for window in self._appearance_windows():
                window._settings = dataclass_replace(window._settings, theme_mode=mode)
            self._save_settings()

    def show_theme_editor(self) -> None:
        from uniti.ui.theme_editor import ThemeEditor
        app = QApplication.instance()
        editor = getattr(app, '_uniti_theme_editor', None)
        if editor is None:
            editor = ThemeEditor(self)
        editor.show()
        editor.raise_()
        editor.activateWindow()

    def _refresh_theme_menu(self) -> None:
        from uniti.app.theme_profiles import BUILTIN_IDS
        if not hasattr(self, '_theme_menu'):
            return
        for action in self._theme_actions.values():
            self._theme_menu.removeAction(action)
            self._theme_group.removeAction(action)
            action.deleteLater()
        self._theme_actions.clear()
        entries = [(name, name) for name in BUILTIN_IDS]
        entries.extend((p.id, p.name) for p in self._theme_state.profiles)
        for profile_id, name in entries:
            action = QAction(name, self)
            action.setCheckable(True)
            action.setChecked(profile_id == self._theme_state.active_id)
            action.triggered.connect(lambda _checked=False, mode=profile_id: self.set_theme(mode))
            self._theme_group.addAction(action)
            self._theme_menu.insertAction(self._theme_separator, action)
            self._theme_actions[profile_id] = action

    def set_theme_contrast(self, contrast: str) -> None:
        if contrast not in THEME_CONTRASTS:
            return
        app = QApplication.instance()
        spec = None
        if isinstance(app, QApplication):
            editor = getattr(app, '_uniti_theme_editor', None)
            if editor is not None:
                editor.reject()
            profile = self._theme_state.resolve()
            spec = (apply_profile(app, profile, contrast) if profile is not None
                    else apply_theme(app, self._theme_state.active_id, contrast))
        for window in self._appearance_windows():
            action = getattr(window, "_high_contrast_action", None)
            if action is not None:
                blocked = action.blockSignals(True)
                action.setChecked(contrast == "High Contrast")
                action.blockSignals(blocked)
            window._settings = dataclass_replace(
                window._settings,
                theme_contrast=contrast,
            )
        if spec is not None:
            self._propagate_theme_tokens(spec)
        self._save_settings()

    def _appearance_windows(self) -> tuple[UNITIMainWindow, ...]:
        if self._service is None:
            return (self,)
        return tuple(
            window
            for window in self._service.windows.windows
            if isinstance(window, UNITIMainWindow)
        )

    def _propagate_theme_tokens(self, spec: ThemeSpec) -> None:
        """Push an app-wide theme change to every view that is still
        following it — a view with its own `theme_choice_id` (View >
        Editor Theme) deliberately opted out and keeps its own tokens."""

        for window in self._appearance_windows():
            for view in window.views:
                if getattr(view, "theme_choice_id", None) is not None:
                    continue
                setter = getattr(view, "set_theme_tokens", None)
                if callable(setter):
                    setter(spec.editor)

    def set_whitespace_mode(self, mode: WhitespaceMode | str) -> None:
        """Per-view (View > Whitespace): applies only to the current view,
        like Wrap/Text Direction — not broadcast to every open view. Also
        becomes the default a newly opened view starts from."""

        selected = parse_whitespace_mode(mode)
        view = self.current_view
        if view is not None and view.isEnabled():
            view.set_whitespace_mode(selected)
        self._settings = dataclass_replace(self._settings, whitespace_mode=selected.value)
        self._save_settings()
        self._sync_whitespace_action(view)

    def _sync_whitespace_action(self, view: UNITITextView | None) -> None:
        selected = view.whitespace_mode if view is not None else parse_whitespace_mode(
            self._settings.whitespace_mode
        )
        action = getattr(self, "_whitespace_actions", {}).get(selected)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def set_tab_width(self, width: int) -> None:
        """Per-view (View > Tab Width): applies only to the current view —
        see `set_whitespace_mode` above for the same pattern."""

        width = max(
            MIN_EDITOR_TAB_WIDTH, min(MAX_EDITOR_TAB_WIDTH, int(width))
        )
        view = self.current_view
        if view is not None and view.isEnabled():
            view.set_tab_width(width)
        self._settings = dataclass_replace(self._settings, editor_tab_width=width)
        self._save_settings()
        self._sync_tab_width_action(view)

    def _sync_tab_width_action(self, view: UNITITextView | None) -> None:
        width = view.tab_width if view is not None else self._settings.editor_tab_width
        action = getattr(self, "_tab_width_actions", {}).get(width)
        if action is not None:
            if not action.isChecked():
                action.setChecked(True)
        elif getattr(self, "_custom_tab_width_action", None) is not None:
            if not self._custom_tab_width_action.isChecked():
                self._custom_tab_width_action.setChecked(True)

    def set_editor_theme_choice(self, choice_id: str | None) -> None:
        """Per-view editor-content theme (View > Editor Theme) — resolves
        `choice_id` into tokens and applies them to the current view only,
        leaving every other view's theme (and the app-wide chrome theme,
        `set_theme`/`set_theme_contrast` above) unchanged. `None` means
        "follow the app theme": resets to whatever `active_theme` is
        currently installed, and future app-wide theme changes apply to
        this view again (see `_propagate_theme_tokens`)."""

        view = self.current_view
        if view is not None and view.isEnabled():
            app = QApplication.instance()
            tokens = None
            if choice_id is not None:
                tokens = self._resolve_editor_theme_tokens(choice_id)
            elif isinstance(app, QApplication):
                tokens = active_theme(app).editor
            view.set_theme_choice(choice_id, tokens)
        self._sync_editor_theme_action(view)

    def _resolve_editor_theme_tokens(self, choice_id: str) -> EditorThemeTokens | None:
        from uniti.app.theme_profiles import BUILTIN_IDS
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return None
        if choice_id in BUILTIN_IDS:
            return resolve_editor_tokens(app, choice_id, self._settings.theme_contrast)
        for profile in self._theme_state.profiles:
            if profile.id == choice_id:
                return resolve_profile_editor_tokens(
                    app, profile, self._settings.theme_contrast
                )
        return None

    def _sync_editor_theme_action(self, view: UNITITextView | None) -> None:
        choice_id = view.theme_choice_id if view is not None else None
        action = getattr(self, "_editor_theme_actions", {}).get(choice_id)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _refresh_editor_theme_menu(self) -> None:
        """Rebuild the profile entries (System/Light/Dark plus every
        custom profile) to match `self._theme_state.profiles` — called
        whenever that list changes, mirroring `_refresh_theme_menu`'s own
        rebuild for the app-wide Theme menu."""

        if not hasattr(self, "_editor_theme_menu"):
            return
        from uniti.app.theme_profiles import BUILTIN_IDS
        follow_action = self._editor_theme_actions[None]
        for choice_id, action in list(self._editor_theme_actions.items()):
            if choice_id is None:
                continue
            self._editor_theme_menu.removeAction(action)
            self._editor_theme_group.removeAction(action)
            action.deleteLater()
        self._editor_theme_actions = {None: follow_action}
        entries = [(name, name) for name in BUILTIN_IDS]
        entries.extend((p.id, p.name) for p in self._theme_state.profiles)
        for choice_id, name in entries:
            action = QAction(name, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, choice_id=choice_id: self.set_editor_theme_choice(
                    choice_id
                )
            )
            self._editor_theme_group.addAction(action)
            self._editor_theme_menu.addAction(action)
            self._editor_theme_actions[choice_id] = action
        self._sync_editor_theme_action(self.current_view)

    def set_syntax_choice(self, choice_key: str | None) -> None:
        """Per-view syntax-profile override (View > Syntax Profile) —
        forces this one document to a specific profile regardless of what
        the extension→profile mapping (View > Text-Type Profiles…)
        would otherwise assign it. `None` returns to following the
        mapping."""

        view = self.current_view
        if view is not None and view.isEnabled():
            if choice_key is not None:
                profile = PROFILES_BY_KEY.get(choice_key, PLAIN_TEXT)
            else:
                profile = profile_for_extension(
                    view.document.path.suffix,
                    self._settings.syntax_extension_overrides,
                )
            view.set_syntax_choice(choice_key, profile)
        self._sync_syntax_choice_action(view)

    def _sync_syntax_choice_action(self, view: UNITITextView | None) -> None:
        choice_key = view.syntax_choice_key if view is not None else None
        action = getattr(self, "_syntax_choice_actions", {}).get(choice_key)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _prompt_custom_tab_width(self) -> None:
        view = self.current_view
        current_width = view.tab_width if view is not None else self._settings.editor_tab_width
        width, accepted = QInputDialog.getInt(
            self,
            "Tab Width",
            "Spaces per tab:",
            current_width,
            MIN_EDITOR_TAB_WIDTH,
            MAX_EDITOR_TAB_WIDTH,
        )
        if accepted:
            self.set_tab_width(width)
        else:
            # Restore the checked preset/custom action to match the
            # unchanged setting — the exclusive group already flipped to
            # "Custom…" when this action was triggered.
            self._sync_tab_width_action(view)

    def convert_tabs_to_spaces(self) -> None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        convert_document_tabs_to_spaces(view.document, view.tab_width)
        self._on_view_state_changed(view)

    def _on_command_binding_changed(self, command_id: str, shortcut: str) -> None:
        sequence = QKeySequence.fromString(
            shortcut,
            QKeySequence.SequenceFormat.PortableText,
        )
        action = self._command_actions.get(command_id)
        if action is not None:
            action.setShortcut(sequence)
        find_shortcut = self._find_replace_shortcuts.get(command_id)
        if find_shortcut is not None:
            find_shortcut.setKey(sequence)
        self._settings = dataclass_replace(
            self._settings,
            shortcut_overrides=self._command_registry.overrides,
        )
        self._save_settings()

    def set_inspection_modifiers(self, modifiers: str) -> None:
        controller = unicode_inspection(QApplication.instance())
        controller.set_modifiers(modifiers)
        for window in self._appearance_windows():
            window._settings = dataclass_replace(
                window._settings, whitespace_inspect_modifiers=controller.modifiers
            )
            if window._hotkeys_popup is not None:
                window._hotkeys_popup.set_inspection_modifiers(controller.modifiers)
        self._save_settings()

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and self._find_replace.focused_input() is not None
            and (
                self._service is None
                or self._service.most_recent_window is self
            )
        ):
            pressed = QKeySequence(event.keyCombination())
            for definition in self._command_registry.definitions(
                category=CommandCategory.EDITING
            ):
                shortcut = self._command_registry.current(definition.command_id)
                expected = QKeySequence.fromString(
                    shortcut,
                    QKeySequence.SequenceFormat.PortableText,
                )
                if shortcut and pressed.matches(expected) == (
                    QKeySequence.SequenceMatch.ExactMatch
                ):
                    self._command_actions[definition.command_id].trigger()
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    def event(self, event) -> bool:
        handled = super().event(event)
        service = getattr(self, "_service", None)
        if (
            event.type() == QEvent.Type.WindowActivate
            and service is not None
            and getattr(self, "window_id", None) in dict(service.windows.items)
        ):
            service.set_active_view(self.window_id, self.active_view_id)
        return handled

    @property
    def current_view(self) -> UNITITextView | None:
        widget = self._panes.active_view
        return widget if isinstance(widget, UNITITextView) else None

    @property
    def panes(self) -> EditorPaneTree:
        return self._panes

    @property
    def find_replace(self) -> FindReplaceWindow:
        return self._find_replace

    @property
    def _compare_pane(self) -> ComparePane | None:
        return self._toggle_windows.get("compare")

    @property
    def _character_inspector_dialog(self) -> CharacterInspectorDialog | None:
        return self._toggle_windows.get("character_inspector")

    @property
    def views(self) -> tuple[UNITITextView, ...]:
        found: list[UNITITextView] = []
        for view_id in self._panes.view_ids:
            leaf = self._panes.leaf_for_view(view_id)
            if leaf is None:
                continue
            widget = leaf.widget(leaf.index_of(view_id))
            if isinstance(widget, UNITITextView):
                found.append(widget)
        return tuple(found)

    @property
    def view_ids(self) -> tuple[str, ...]:
        return tuple(
            view_id
            for view_id in self._panes.view_ids
            if view_id != FIND_REPLACE_VIEW_ID
        )

    @property
    def active_view_id(self) -> str | None:
        view = self.current_view
        return None if view is None else view.view_id

    def view_for_id(self, view_id: str) -> UNITITextView | None:
        leaf = self._panes.leaf_for_view(view_id)
        if leaf is None:
            return None
        widget = leaf.widget(leaf.index_of(view_id))
        return widget if isinstance(widget, UNITITextView) else None

    def _contains_view(self, view: UNITITextView) -> bool:
        return self.view_for_id(view.view_id) is view

    def _on_match_position_changed(self, view_id: str, text: str | None) -> None:
        if self.view_for_id(view_id) is None:
            return
        if text is None:
            self._status.clear_match_position()
        else:
            self._status.update_match_position(text)

    def _select_view(self, view: UNITITextView) -> None:
        if not self._contains_view(view):
            raise ValueError("view does not belong to this window")
        self._panes.activate_view(view.view_id)

    def _on_pane_active(self, _view: object) -> None:
        self._tabs = self._panes.active_leaf.tabs
        self._on_current_changed(self._tabs.currentIndex())
        if self._service is not None:
            self._service.set_active_view(self.window_id, self.active_view_id)

    def _on_pane_view_selected(self, view_id: str) -> None:
        if (
            self._service is not None
            and view_id != FIND_REPLACE_VIEW_ID
            and self.view_for_id(view_id) is None
        ):
            self._service.promote_restore(view_id)

    def _action(self, text: str, shortcut, handler) -> QAction:
        action = QAction(text, self)
        if shortcut is not None:
            action.setShortcut(shortcut)
        action.triggered.connect(lambda _checked=False, handler=handler: handler())
        return action

    def _command_action(
        self,
        command_id: str,
        handler,
        *,
        checkable: bool = False,
    ) -> QAction:
        definition = self._command_registry.definition(command_id)
        action = QAction(definition.label, self)
        action.setCheckable(checkable)
        action.setShortcut(
            QKeySequence.fromString(
                self._command_registry.current(command_id),
                QKeySequence.SequenceFormat.PortableText,
            )
        )
        if definition.scope == CommandScope.WINDOW:
            action.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        else:
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        action.triggered.connect(
            lambda _checked=False, handler=handler: handler()
        )
        self._command_actions[command_id] = action
        return action

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(self._command_action("file.new", self.new_file))
        file_menu.addAction(
            self._command_action("window.new", self.new_window)
        )
        file_menu.addSeparator()
        file_menu.addAction(self._command_action("file.open", self.open_dialog))
        file_menu.addAction(
            self._command_action(
                "file.open_folder_by_type", self.open_folder_by_type
            )
        )
        self._recent_files_menu = file_menu.addMenu("Recent Files")
        self._recent_files_menu.aboutToShow.connect(self._populate_recent_files_menu)
        file_menu.addSeparator()
        file_menu.addAction(
            self._command_action("file.save", self.start_save_current)
        )
        file_menu.addAction(
            self._command_action("file.save_as", self.start_save_current_as)
        )
        file_menu.addAction(self._command_action("file.reload", self.reload_current))
        file_menu.addSeparator()
        file_menu.addAction(self._command_action("file.close", self.close_current))
        file_menu.addAction(
            self._command_action("file.close_all", self.close_all_documents)
        )
        file_menu.addAction(self._command_action("file.quit", self.request_quit))

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(self._command_action("editing.undo", self.undo_current))
        edit_menu.addAction(self._command_action("editing.redo", self.redo_current))
        edit_menu.addSeparator()
        edit_menu.addAction(self._command_action("editing.cut", self.cut_current))
        edit_menu.addAction(self._command_action("editing.copy", self.copy_current))
        edit_menu.addAction(self._command_action("editing.paste", self.paste_current))
        edit_menu.addSeparator()
        edit_menu.addAction(
            self._command_action("editing.select_all", self.select_all)
        )
        edit_menu.addAction(
            self._command_action(
                "editing.unicode_hex_toggle", self.toggle_unicode_hex
            )
        )

        edit_menu.addSeparator()
        edit_menu.addAction(
            self._command_action("find.open", self.toggle_find_replace_visibility)
        )
        edit_menu.addAction(self._command_action("find.replace", self.show_replace))
        edit_menu.addAction(
            self._command_action("find.next", self._find_replace.next_match)
        )
        edit_menu.addAction(
            self._command_action("find.previous", self._find_replace.previous_match)
        )

        edit_menu.addSeparator()
        edit_menu.addAction(
            self._command_action("navigation.go_to_line", self.go_to_line_dialog)
        )
        edit_menu.addAction(
            self._command_action("navigation.page_up", lambda: self._move_page(-1))
        )
        edit_menu.addAction(
            self._command_action("navigation.page_down", lambda: self._move_page(1))
        )
        edit_menu.addAction(
            self._command_action(
                "navigation.document_start",
                lambda: self._move_editor("move_document_start"),
            )
        )
        edit_menu.addAction(
            self._command_action(
                "navigation.document_end",
                lambda: self._move_editor("move_document_end"),
            )
        )
        edit_menu.addAction(
            self._command_action(
                "navigation.word_left",
                lambda: self._move_editor("move_visual_word_left"),
            )
        )
        edit_menu.addAction(
            self._command_action(
                "navigation.word_right",
                lambda: self._move_editor("move_visual_word_right"),
            )
        )

        format_menu = self.menuBar().addMenu("F&ormat")
        reinterpret_menu = format_menu.addMenu("Reinterpret As")
        convert_menu = format_menu.addMenu("Convert on Save")
        for profile in encoding_profiles():
            reinterpret_menu.addAction(
                self._action(
                    profile.label,
                    None,
                    lambda profile=profile: self.reinterpret_current(profile),
                )
            )
            convert_menu.addAction(
                self._action(
                    profile.label,
                    None,
                    lambda profile=profile: self.set_output_profile(profile),
                )
            )

        format_menu.addSeparator()
        format_menu.addAction(
            self._action("Keep Source", None, lambda: self.set_output_eol(None))
        )
        for eol in ("LF", "CRLF", "CR"):
            format_menu.addAction(
                self._action(eol, None, lambda eol=eol: self.set_output_eol(eol))
            )

        format_menu.addSeparator()
        self._format_document_action = self._action(
            "Format Document", None, self.format_current_document
        )
        self._minify_document_action = self._action(
            "Minify Document", None, self.minify_current_document
        )
        format_menu.addAction(self._format_document_action)
        format_menu.addAction(self._minify_document_action)
        self._refresh_reformat_actions()

        view_menu = self.menuBar().addMenu("&View")
        theme_menu = view_menu.addMenu("&Theme")
        theme_group = QActionGroup(self)
        theme_group.setExclusive(True)
        self._theme_actions: dict[str, QAction] = {}
        self._theme_group = theme_group
        self._theme_menu = theme_menu
        self._theme_separator = theme_menu.addSeparator()
        self._refresh_theme_menu()
        theme_menu.addAction("Edit Themes…", self.show_theme_editor)
        self._high_contrast_action = QAction("High Contrast", self)
        self._high_contrast_action.setCheckable(True)
        self._high_contrast_action.setChecked(
            self._settings.theme_contrast == "High Contrast"
        )
        self._high_contrast_action.toggled.connect(
            lambda enabled: self.set_theme_contrast(
                "High Contrast" if enabled else "Standard"
            )
        )
        theme_menu.addAction(self._high_contrast_action)
        view_menu.addAction("Document Groups…", self.show_document_group_editor)
        view_menu.addAction(
            "Text-Type Profiles…", self.show_extension_profile_editor
        )
        self._markdown_preview_action = QAction("Markdown Preview", self)
        self._markdown_preview_action.setCheckable(True)
        self._markdown_preview_action.triggered.connect(self.toggle_markdown_preview)
        view_menu.addAction(self._markdown_preview_action)
        self._refresh_markdown_preview_action()

        view_menu.addSeparator()
        view_menu.addAction(
            self._command_action("editor.zoom_in", self.zoom_in_editor)
        )
        view_menu.addAction(
            self._command_action("editor.zoom_out", self.zoom_out_editor)
        )
        view_menu.addAction(
            self._command_action("editor.zoom_reset", self.reset_editor_zoom)
        )
        view_menu.addAction(
            self._command_action(
                "editor.weight_increase", self.increase_editor_font_weight
            )
        )
        view_menu.addAction(
            self._command_action(
                "editor.weight_decrease", self.decrease_editor_font_weight
            )
        )
        view_menu.addAction(
            self._command_action(
                "editor.weight_reset", self.reset_editor_font_weight
            )
        )
        self._wrap_action = self._command_action(
            "editor.wrap",
            lambda: self.set_editor_wrap(self._wrap_action.isChecked()),
            checkable=True,
        )
        self._wrap_action.setChecked(self._settings.soft_wrap)
        view_menu.addAction(self._wrap_action)
        whitespace_menu = view_menu.addMenu("Whitespace")
        whitespace_group = QActionGroup(self)
        whitespace_group.setExclusive(True)
        whitespace_labels = {
            WhitespaceMode.OFF: "Off",
            WhitespaceMode.EOL: "EOL",
            WhitespaceMode.SPACES_TABS: "Spaces & Tabs",
            WhitespaceMode.INVISIBLE_UNICODE: "Invisible Unicode",
            WhitespaceMode.ALL: "All",
        }
        selected_whitespace = parse_whitespace_mode(
            self._settings.whitespace_mode
        )
        self._whitespace_actions: dict[WhitespaceMode, QAction] = {}
        for mode, label in whitespace_labels.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(mode is selected_whitespace)
            action.triggered.connect(
                lambda _checked=False, mode=mode: self.set_whitespace_mode(mode)
            )
            whitespace_group.addAction(action)
            whitespace_menu.addAction(action)
            self._whitespace_actions[mode] = action
        self._whitespace_group = whitespace_group
        direction_menu = view_menu.addMenu("Text Direction")
        direction_group = QActionGroup(self)
        direction_group.setExclusive(True)
        direction_labels = {
            "auto": "Auto",
            "ltr": "Left-to-Right",
            "rtl": "Right-to-Left",
        }
        self._text_direction_actions: dict[str, QAction] = {}
        for value, label in direction_labels.items():
            action = QAction(label, self)
            action.setCheckable(True)
            action.setChecked(value == "auto")
            action.triggered.connect(
                lambda _checked=False, value=value: self.set_editor_text_direction(
                    value
                )
            )
            direction_group.addAction(action)
            direction_menu.addAction(action)
            self._text_direction_actions[value] = action
        self._text_direction_group = direction_group
        tab_width_menu = view_menu.addMenu("Tab Width")
        tab_width_group = QActionGroup(self)
        tab_width_group.setExclusive(True)
        self._tab_width_actions: dict[int, QAction] = {}
        for width in (2, 4, 8):
            action = QAction(str(width), self)
            action.setCheckable(True)
            action.setChecked(width == self._settings.editor_tab_width)
            action.triggered.connect(
                lambda _checked=False, width=width: self.set_tab_width(width)
            )
            tab_width_group.addAction(action)
            tab_width_menu.addAction(action)
            self._tab_width_actions[width] = action
        tab_width_menu.addSeparator()
        custom_tab_width_action = QAction("Custom…", self)
        custom_tab_width_action.setCheckable(True)
        custom_tab_width_action.setChecked(
            self._settings.editor_tab_width not in self._tab_width_actions
        )
        custom_tab_width_action.triggered.connect(self._prompt_custom_tab_width)
        tab_width_group.addAction(custom_tab_width_action)
        tab_width_menu.addAction(custom_tab_width_action)
        self._custom_tab_width_action = custom_tab_width_action
        self._tab_width_group = tab_width_group
        editor_theme_menu = view_menu.addMenu("Editor Theme")
        editor_theme_group = QActionGroup(self)
        editor_theme_group.setExclusive(True)
        self._editor_theme_group = editor_theme_group
        self._editor_theme_menu = editor_theme_menu
        follow_theme_action = QAction("Follow App Theme", self)
        follow_theme_action.setCheckable(True)
        follow_theme_action.setChecked(True)
        follow_theme_action.triggered.connect(
            lambda _checked=False: self.set_editor_theme_choice(None)
        )
        editor_theme_group.addAction(follow_theme_action)
        editor_theme_menu.addAction(follow_theme_action)
        editor_theme_menu.addSeparator()
        self._editor_theme_actions: dict[str | None, QAction] = {None: follow_theme_action}
        self._refresh_editor_theme_menu()
        syntax_choice_menu = view_menu.addMenu("Syntax Profile")
        syntax_choice_group = QActionGroup(self)
        syntax_choice_group.setExclusive(True)
        self._syntax_choice_group = syntax_choice_group
        auto_syntax_action = QAction("Auto (by File Type)", self)
        auto_syntax_action.setCheckable(True)
        auto_syntax_action.setChecked(True)
        auto_syntax_action.triggered.connect(
            lambda _checked=False: self.set_syntax_choice(None)
        )
        syntax_choice_group.addAction(auto_syntax_action)
        syntax_choice_menu.addAction(auto_syntax_action)
        syntax_choice_menu.addSeparator()
        self._syntax_choice_actions: dict[str | None, QAction] = {
            None: auto_syntax_action
        }
        for profile in PROFILES:
            action = QAction(profile.label, self)
            action.setCheckable(True)
            action.triggered.connect(
                lambda _checked=False, key=profile.key: self.set_syntax_choice(key)
            )
            syntax_choice_group.addAction(action)
            syntax_choice_menu.addAction(action)
            self._syntax_choice_actions[profile.key] = action
        view_menu.addAction(
            "Convert Tabs to Spaces", self.convert_tabs_to_spaces
        )
        self._pause_background_action = self._command_action(
            "view.pause_background",
            lambda: self.set_pause_background(
                self._pause_background_action.isChecked()
            ),
            checkable=True,
        )
        self._pause_background_action.setChecked(
            self._resources.tasks.snapshot().background_paused
        )
        view_menu.addAction(self._pause_background_action)
        view_menu.addSeparator()
        view_menu.addAction(
            self._command_action("view.split_right", self.split_right)
        )
        view_menu.addAction(
            self._command_action("view.split_down", self.split_down)
        )
        view_menu.addAction(
            self._command_action("view.close_split", self.close_current_split)
        )
        view_menu.addAction(
            self._command_action(
                "view.move_new_window",
                self.move_current_to_new_window,
            )
        )

        view_menu.addSeparator()
        view_menu.addAction(
            self._command_action(
                "find.toggle_attachment",
                self.toggle_find_replace_attachment,
            )
        )
        view_menu.addAction(
            self._command_action("find.zoom_in", self._find_replace.zoom_in)
        )
        view_menu.addAction(
            self._command_action("find.zoom_out", self._find_replace.zoom_out)
        )
        view_menu.addAction(
            self._command_action("find.zoom_reset", self._find_replace.reset_zoom)
        )
        view_menu.addAction(
            self._command_action(
                "find.report_cycle",
                self._find_replace.toggle_report,
            )
        )

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(
            self._command_action(
                "tools.character_inspector", self.show_character_inspector
            )
        )
        tools_menu.addAction(self._command_action("tools.compare", self.show_compare))
        tools_menu.addAction(
            self._action(
                "Diagnostics…",
                None,
                self.show_diagnostics,
            )
        )
        tools_menu.addSeparator()
        self._export_dogfood_action = self._action(
            "Export Dogfood Evidence…",
            None,
            self.export_dogfood_evidence,
        )
        self._clear_dogfood_action = self._action(
            "Clear Dogfood Evidence…",
            None,
            self.clear_dogfood_evidence,
        )
        dogfood_available = (
            self._service is not None
            and self._service.dogfood_recorder is not None
        )
        self._export_dogfood_action.setEnabled(dogfood_available)
        self._clear_dogfood_action.setEnabled(dogfood_available)
        tools_menu.addAction(self._export_dogfood_action)
        tools_menu.addAction(self._clear_dogfood_action)

        self._hotkeys_action = self.menuBar().addAction("&Hotkeys")
        self._hotkeys_action.triggered.connect(self.show_hotkeys)
        for definition in self._command_registry.definitions():
            if definition.scope == CommandScope.FIND_REPLACE:
                self._find_replace.addAction(
                    self._command_actions[definition.command_id]
                )
            elif definition.category == CommandCategory.EDITING:
                action = self._command_actions[definition.command_id]
                shortcut = QShortcut(action.shortcut(), self._find_replace)
                shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
                shortcut.activated.connect(action.trigger)
                self._find_replace_shortcuts[definition.command_id] = shortcut

    def _remember_directory(self, path: str | Path) -> None:
        directory = str(Path(path).parent)
        self._settings = dataclass_replace(self._settings, last_directory=directory)
        self._save_settings()

    def _record_recent_file(self, path: str | Path) -> None:
        if self._recent_files_store is not None:
            self._recent_files_store.record_opened(str(Path(path)))

    def new_window(self):
        if self._service is None:
            return None
        window = self._service.new_window()
        window.show()
        return window

    _UNTITLED_NAME_PATTERN = re.compile(r"^Untitled(?: (\d+))?\.txt$")

    def _next_untitled_name(self) -> str:
        used = set()
        if self._service is not None:
            for entry in self._service.documents.entries:
                if not entry.is_untitled:
                    continue
                match = self._UNTITLED_NAME_PATTERN.match(entry.document.path.name)
                if match:
                    used.add(int(match.group(1) or "1"))
        number = 1
        while number in used:
            number += 1
        return "Untitled.txt" if number == 1 else f"Untitled {number}.txt"

    def _is_untitled_view(self, view: UNITITextView) -> bool:
        if self._service is None:
            return False
        entry = self._service.documents.entry_for_view(view.view_id)
        return entry is not None and entry.is_untitled

    def _save_as_initial_directory(self, view: UNITITextView) -> Path:
        if not self._is_untitled_view(view):
            return view.document.path.parent
        return Path(self._settings.last_directory or Path.home())

    def new_file(self) -> None:
        """Open a new, unsaved plain-text document in this window (Ctrl/Cmd+N)."""

        scratch_dir = Path(tempfile.mkdtemp(prefix="uniti-untitled-"))
        path = scratch_dir / self._next_untitled_name()
        try:
            path.touch()
            decision = self._inspect_open_path(path)
            if decision is None:
                shutil.rmtree(scratch_dir, ignore_errors=True)
                return
            selected, inspection = decision
            document = Document.open(
                path,
                profile=selected,
                resource_manager=self._resources,
            )
        except Exception:
            shutil.rmtree(scratch_dir, ignore_errors=True)
            raise
        try:
            self._add_document(
                document,
                attach_recovery=False,
                initial_eol_report=inspection.eol,
                initial_eol_complete=inspection.eol_complete,
                observe_document_open=False,
                is_untitled=True,
            )
        except Exception:
            document.close()
            shutil.rmtree(scratch_dir, ignore_errors=True)
            raise

    def _quit_choice(self, entry):
        from uniti.app.service import QuitChoice

        result = QMessageBox.warning(
            self,
            "Unsaved UNITI Document",
            f"Save changes to {entry.document.path.name}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Save:
            return QuitChoice.SAVE
        if result == QMessageBox.StandardButton.Discard:
            return QuitChoice.DISCARD
        return QuitChoice.CANCEL

    def request_quit(self) -> bool:
        if self._service is None:
            return self.close()
        try:
            return self._service.request_quit(self._quit_choice)
        except Exception as exc:
            self._show_save_error(exc)
            return False

    def _split_pane(
        self,
        pane_id: str,
        orientation: Qt.Orientation,
    ) -> UNITITextView | None:
        if self._service is None:
            return None
        source_leaf = self._panes.leaf(pane_id)
        view_id = source_leaf.selected_view_id
        view = None if view_id is None else self.view_for_id(view_id)
        if view is None:
            return None
        editor_snapshot = view.state.export_state()
        new_leaf = None
        try:
            new_leaf = self._panes.split_view(view.view_id, orientation)
            clone = self._add_document(
                view.document,
                attach_recovery=False,
                pane_id=new_leaf.pane_id,
            )
        except ValueError as exc:
            if new_leaf is not None:
                self._panes.close_leaf(new_leaf.pane_id)
            self.statusBar().showMessage(str(exc)[:256], 5000)
            return None
        clone.state.restore_state(editor_snapshot)
        clone._state_changed()
        return clone

    def split_current(self, orientation: Qt.Orientation) -> UNITITextView | None:
        return self._split_pane(self._panes.active_leaf.pane_id, orientation)

    def split_right(self) -> UNITITextView | None:
        return self.split_current(Qt.Orientation.Horizontal)

    def split_down(self) -> UNITITextView | None:
        return self.split_current(Qt.Orientation.Vertical)

    def close_current_split(self) -> bool:
        leaf = self._panes.active_leaf
        if self._panes.leaf_count == 1:
            return False
        for view_id in reversed(leaf.view_ids):
            if not self._close_view_id(view_id):
                return False
        try:
            return self._panes.close_leaf(leaf.pane_id)
        except KeyError:
            return True

    def move_current_to_new_window(self):
        view = self.current_view
        if view is None or self._service is None:
            return None
        return self._service.undock_view(view.view_id)

    def _toggle_view_dock(self, view_id: str) -> None:
        if self._service is None:
            return
        view = self.view_for_id(view_id)
        if view is None:
            return
        dock = getattr(self._service, "dock_view", None)
        if view.dock_return is not None and callable(dock):
            dock(view_id)
            return
        self._service.undock_view(view_id)

    _EDITOR_CONTEXT_MENU_GROUPS = (
        ("editing.undo", "editing.redo"),
        ("editing.cut", "editing.copy", "editing.paste"),
        ("editing.select_all",),
        ("find.open", "find.replace"),
        ("navigation.go_to_line",),
    )

    def _show_editor_context_menu(
        self, view: UNITITextView, global_position: QPoint
    ) -> None:
        if not view.isEnabled():
            return
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        for group in self._EDITOR_CONTEXT_MENU_GROUPS:
            if menu.actions():
                menu.addSeparator()
            for command_id in group:
                menu.addAction(self._command_actions[command_id])
        menu.popup(global_position)

    def _show_assignment_menu(self, pane_id: str, position: QPoint) -> None:
        if self._service is None:
            return
        entries = tuple(
            entry for entry in self._service.documents.entries if entry.view_ids
        )
        name_counts: dict[str, int] = {}
        for entry in entries:
            name = entry.canonical_path.name
            name_counts[name] = name_counts.get(name, 0) + 1
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        for entry in entries:
            name = entry.canonical_path.name
            label = (
                name
                if name_counts[name] == 1
                else f"{name} — {entry.canonical_path.parent}"
            )
            action = menu.addAction(label)
            action.triggered.connect(
                lambda _checked=False, document_id=entry.document_id: (
                    self.assign_document_to_pane(document_id, pane_id)
                )
            )
        if not entries:
            empty = menu.addAction("No Open Documents")
            empty.setEnabled(False)
        menu.popup(position)

    def assign_document_to_pane(
        self,
        document_id: str,
        pane_id: str,
    ) -> UNITITextView:
        if self._service is None:
            raise RuntimeError("document assignment requires the UNITI service")
        entry = self._service.documents.get(document_id)
        leaf = self._panes.leaf(pane_id)
        for view_id in leaf.view_ids:
            if self._service.documents.entry_for_view(view_id) is entry:
                leaf.select_view(view_id)
                view = self.view_for_id(view_id)
                if view is None:
                    raise RuntimeError("assigned document view is unavailable")
                return view
        try:
            return self._add_document(
                entry.document,
                attach_recovery=False,
                pane_id=pane_id,
            )
        except ValueError as exc:
            self.statusBar().showMessage(str(exc)[:256], 5000)
            raise

    @staticmethod
    def _group_swatch_icon(color: str) -> QIcon:
        size = 12
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        try:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QColor(color))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(1, 1, size - 2, size - 2)
        finally:
            painter.end()
        return QIcon(pixmap)

    def _refresh_group_indicator(self, view_id: str) -> None:
        if self._service is None:
            return
        leaf = self._panes.leaf_for_view(view_id)
        if leaf is None:
            return
        index = leaf.index_of(view_id)
        if index < 0:
            return
        entry = self._service.documents.entry_for_view(view_id)
        group = next(
            (g for g in self._groups if entry is not None and g.id == entry.group_id),
            None,
        )
        leaf.tabs.setTabIcon(
            index, self._group_swatch_icon(group.color) if group is not None else QIcon()
        )

    def _refresh_all_group_indicators(self) -> None:
        for view_id in self._panes.view_ids:
            self._refresh_group_indicator(view_id)

    def _set_document_group(self, document_id: str, group_id: str | None) -> None:
        if self._service is None:
            return
        self._service.documents.set_group(document_id, group_id)
        entry = self._service.documents.get(document_id)
        for view_id in entry.view_ids:
            self._refresh_group_indicator(view_id)

    def _show_group_menu(self, view_id: str, position: QPoint) -> None:
        if self._service is None:
            return
        entry = self._service.documents.entry_for_view(view_id)
        if entry is None:
            return
        menu = QMenu(self)
        menu.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        none_action = menu.addAction("No Group")
        none_action.setCheckable(True)
        none_action.setChecked(entry.group_id is None)
        none_action.triggered.connect(
            lambda _checked=False, document_id=entry.document_id: (
                self._set_document_group(document_id, None)
            )
        )
        if self._groups:
            menu.addSeparator()
        for group in self._groups:
            action = menu.addAction(self._group_swatch_icon(group.color), group.name)
            action.setCheckable(True)
            action.setChecked(entry.group_id == group.id)
            action.triggered.connect(
                lambda _checked=False,
                document_id=entry.document_id,
                group_id=group.id: self._set_document_group(document_id, group_id)
            )
        menu.addSeparator()
        manage_action = menu.addAction("Manage Groups…")
        manage_action.triggered.connect(self.show_document_group_editor)
        menu.popup(position)

    def show_document_group_editor(self) -> None:
        from uniti.ui.document_group_editor import DocumentGroupEditor

        editor = DocumentGroupEditor(self._groups, self)
        if editor.exec() and self._group_store is not None:
            groups = editor.groups()
            self._group_store.save(groups)
            removed_ids = {g.id for g in self._groups} - {g.id for g in groups}
            self._groups = groups
            if self._service is not None and removed_ids:
                for entry in self._service.documents.entries:
                    if entry.group_id in removed_ids:
                        self._service.documents.set_group(entry.document_id, None)
            self._refresh_all_group_indicators()

    def show_extension_profile_editor(self) -> None:
        from uniti.ui.extension_profile_editor import ExtensionProfileEditor

        editor = ExtensionProfileEditor(self._settings.syntax_extension_overrides, self)
        if editor.exec():
            overrides = editor.overrides()
            self._settings = dataclass_replace(
                self._settings, syntax_extension_overrides=overrides
            )
            self._save_settings()
            self._refresh_all_syntax_profiles()

    def _refresh_all_syntax_profiles(self) -> None:
        """Re-resolve every view's syntax profile from the (possibly just
        changed) extension→profile mapping — except a view with its own
        per-view override (View > Syntax Profile), which deliberately
        doesn't follow the mapping."""

        for view_id in self._panes.view_ids:
            view = self.view_for_id(view_id)
            if view is None or view.syntax_choice_key is not None:
                continue
            view.set_syntax_profile(
                profile_for_extension(
                    view.document.path.suffix,
                    self._settings.syntax_extension_overrides,
                )
            )

    def _disconnect_view(self, view: UNITITextView) -> None:
        for signal in (
            view.stateChanged,
            view.cursorPositionChanged,
            view.zoomChanged,
            view.fontWeightChanged,
            view.wrapChanged,
            view.navigationRequested,
        ):
            try:
                signal.disconnect()
            except RuntimeError:
                pass
        for action in self._command_actions.values():
            view.removeAction(action)

    def view_location(self, view_id: str) -> ViewLocation:
        leaf = self._panes.leaf_for_view(view_id)
        if leaf is None:
            raise KeyError(view_id)
        return ViewLocation(
            self.window_id,
            leaf.pane_id,
            leaf.index_of(view_id),
        )

    def validate_transfer_destination(self, pane_id: str | None = None) -> str:
        leaf = self._panes.active_leaf if pane_id is None else self._panes.leaf(pane_id)
        if len(self._panes.view_ids) >= MAX_VIEWS:
            raise ValueError(f"pane tree cannot exceed {MAX_VIEWS} views")
        return leaf.pane_id

    def take_view_for_transfer(self, view_id: str) -> UNITITextView:
        view = self.view_for_id(view_id)
        if view is None:
            raise KeyError(view_id)
        self._cancel_navigation(view)
        self._cancel_eol_analysis(view)
        self._dismiss_eol_dialog(view)
        self._eol_reports.pop(id(view), None)
        leaf = self._panes.leaf_for_view(view_id)
        assert leaf is not None
        leaf.take_view(view_id)
        self._disconnect_view(view)
        return view

    def accept_transferred_view(
        self,
        view: UNITITextView,
        *,
        pane_id: str | None = None,
        index: int | None = None,
    ) -> UNITITextView:
        if not isinstance(view, UNITITextView):
            raise TypeError("view must be a UNITITextView")
        selected_pane_id = self.validate_transfer_destination(pane_id)
        if index is not None and (type(index) is not int or index < 0):
            raise ValueError("tab index must be a nonnegative integer or None")
        leaf = self._panes.leaf(selected_pane_id)
        selected_index = None if index is None else min(index, leaf.count())
        leaf = self._panes.add_view(
            view,
            pane_id=selected_pane_id,
            index=selected_index,
        )
        self._connect_view(view)
        self._panes.set_dock_mode(
            view.view_id,
            "dock" if view.dock_return is not None else "undock",
        )
        self._tabs = leaf.tabs
        self._schedule_eol_analysis(view)
        view.setFocus()
        return view

    def restore_window_record(self, record) -> None:
        from uniti.app.session import WindowRecord

        if not isinstance(record, WindowRecord):
            raise TypeError("record must be a WindowRecord")
        if record.window_id != self.window_id:
            raise ValueError("window record ID does not match the window")
        self.setGeometry(*record.geometry)
        self._panes.restore_shell(record.root)
        self._tabs = self._panes.active_leaf.tabs
        if record.window_state == "maximized":
            self.showMaximized()
        elif record.window_state == "fullscreen":
            self.showFullScreen()
        elif record.window_state == "minimized":
            self.showMinimized()

    def restore_document_view(self, document: Document, record) -> UNITITextView:
        """Replace one shell placeholder with its sealed live text view."""

        from uniti.app.session import ViewRecord

        if not isinstance(record, ViewRecord):
            raise TypeError("record must be a ViewRecord")
        if record.view_id not in self._panes.view_ids:
            raise ValueError("restored view has no matching placeholder")
        return self._add_document(
            document,
            attach_recovery=False,
            view_id=record.view_id,
            restore_record=record,
            select=False,
        )

    def discard_session_placeholder(self, view_id: str) -> None:
        """Remove one unresolved view after explicit evidence discard."""

        if self.view_for_id(view_id) is not None:
            raise ValueError("cannot discard a restored live view as a placeholder")
        self._panes.remove_shell_view(view_id)

    def export_window_record(self):
        """Return this window's immutable geometry and pane-tree state."""

        from uniti.app.session import WindowRecord

        geometry = self.geometry()
        if self.isFullScreen():
            state = "fullscreen"
        elif self.isMaximized():
            state = "maximized"
        elif self.isMinimized():
            state = "minimized"
        else:
            state = "normal"
        return WindowRecord(
            self.window_id,
            (geometry.x(), geometry.y(), geometry.width(), geometry.height()),
            state,
            self._panes.export_state(),
        )

    def open_dialog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Open Text File",
            self._settings.last_directory or "",
        )
        if filename:
            try:
                self.open_path(filename)
            except Exception as exc:
                QMessageBox.critical(
                    self,
                    "Open Failed",
                    f"{filename}\n\n{exc}",
                )

    def _populate_recent_files_menu(self) -> None:
        menu = self._recent_files_menu
        menu.clear()
        paths = (
            self._recent_files_store.load()
            if self._recent_files_store is not None
            else ()
        )
        if not paths:
            empty_action = menu.addAction("(No Recent Files)")
            empty_action.setEnabled(False)
            return
        names = [Path(path).name for path in paths]
        duplicated_names = {name for name in names if names.count(name) > 1}
        for path, name in zip(paths, names):
            label = (
                f"{name}  ({Path(path).parent})" if name in duplicated_names else name
            )
            action = menu.addAction(label)
            action.setToolTip(path)
            action.triggered.connect(
                lambda _checked=False, path=path: self._open_recent_file(path)
            )
        menu.addSeparator()
        menu.addAction("Clear Recent Files", self._clear_recent_files)

    def _open_recent_file(self, path: str) -> None:
        try:
            self.open_path(path)
        except Exception as exc:
            QMessageBox.critical(self, "Open Failed", f"{path}\n\n{exc}")

    def _clear_recent_files(self) -> None:
        if self._recent_files_store is not None:
            self._recent_files_store.clear()

    _OPEN_FOLDER_WARN_THRESHOLD = 100

    _OPEN_FOLDER_GROUP_PALETTE = (
        "#e06c75",
        "#61afef",
        "#98c379",
        "#e5c07b",
        "#c678dd",
        "#56b6c2",
        "#d19a66",
    )

    def _next_group_color(self) -> str:
        used = {group.color for group in self._groups}
        for color in self._OPEN_FOLDER_GROUP_PALETTE:
            if color not in used:
                return color
        return self._OPEN_FOLDER_GROUP_PALETTE[
            len(self._groups) % len(self._OPEN_FOLDER_GROUP_PALETTE)
        ]

    def _unique_group_id(self, name: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", name).strip("-")[:64] or "group"
        existing = {group.id for group in self._groups}
        candidate = base
        suffix = 2
        while candidate in existing:
            candidate = f"{base}-{suffix}"[:64]
            suffix += 1
        return candidate

    def open_folder_by_type(self) -> None:
        """BF-029/ADR-0009: open every file of one chosen type from a folder
        (non-recursive, top-level files only) as independent documents,
        optionally assigned to one document group. This is a one-shot batch
        convenience over the existing per-file open pipeline — UNITI does
        not retain the folder as project/workspace state afterward."""

        folder = QFileDialog.getExistingDirectory(
            self,
            "Open Folder by Type",
            self._settings.last_directory or "",
        )
        if not folder:
            return
        folder_path = Path(folder)
        try:
            entries = [entry for entry in folder_path.iterdir() if entry.is_file()]
        except OSError as exc:
            QMessageBox.critical(self, "Open Folder Failed", f"{folder}\n\n{exc}")
            return
        if not entries:
            QMessageBox.information(
                self, "Open Folder by Type", "This folder has no files."
            )
            return

        counts: dict[str, int] = {}
        for entry in entries:
            extension = entry.suffix.lower() or "(no extension)"
            counts[extension] = counts.get(extension, 0) + 1
        ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
        labels = [
            f"{extension} — {count} file{'s' if count != 1 else ''}"
            for extension, count in ordered
        ]
        label, accepted = QInputDialog.getItem(
            self, "Open Folder by Type", "File type:", labels, editable=False
        )
        if not accepted or not label:
            return
        chosen_extension = ordered[labels.index(label)][0]
        matching = sorted(
            entry
            for entry in entries
            if (entry.suffix.lower() or "(no extension)") == chosen_extension
        )

        if len(matching) > self._OPEN_FOLDER_WARN_THRESHOLD:
            proceed = QMessageBox.question(
                self,
                "Open Many Files",
                f"This opens {len(matching)} files at once. Concurrent-document "
                "performance at this scale is not yet benchmarked (BF-030). "
                "Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if proceed != QMessageBox.StandardButton.Yes:
                return

        group_id: str | None = None
        if self._service is not None:
            no_group_label = "No Group"
            new_group_label = "New Group…"
            options = (
                [no_group_label]
                + [group.name for group in self._groups]
                + [new_group_label]
            )
            choice, accepted = QInputDialog.getItem(
                self,
                "Assign to Group",
                "Assign the opened documents to a group:",
                options,
                editable=False,
            )
            if accepted and choice == new_group_label:
                name, name_accepted = QInputDialog.getText(
                    self, "New Group", "Group name:"
                )
                name = name.strip() if name_accepted else ""
                if name:
                    from uniti.app.document_groups import DocumentGroup

                    new_group = DocumentGroup(
                        self._unique_group_id(name), name, self._next_group_color()
                    )
                    self._groups = self._groups + (new_group,)
                    if self._group_store is not None:
                        self._group_store.save(self._groups)
                    group_id = new_group.id
            elif accepted and choice != no_group_label:
                existing_group = next(
                    (group for group in self._groups if group.name == choice), None
                )
                if existing_group is not None:
                    group_id = existing_group.id

        opened = 0
        failures: list[str] = []
        for path in matching:
            try:
                view = self.open_path(path)
            except Exception as exc:
                failures.append(f"{path.name}: {exc}")
                continue
            if view is None:
                continue
            opened += 1
            if group_id is not None and self._service is not None:
                entry = self._service.documents.entry_for_view(view.view_id)
                if entry is not None:
                    self._set_document_group(entry.document_id, group_id)

        if failures:
            QMessageBox.warning(
                self,
                "Some Files Did Not Open",
                f"Opened {opened} of {len(matching)} files.\n\n"
                + "\n".join(failures[:20]),
            )

    def _connect_view(self, view: UNITITextView) -> None:
        view.set_progressive_navigation(True)
        view.stateChanged.connect(lambda view=view: self._on_view_state_changed(view))
        view.cursorPositionChanged.connect(self._status.update_cursor)
        view.zoomChanged.connect(
            lambda percent, view=view: self._on_view_zoom_changed(view, percent)
        )
        view.fontWeightChanged.connect(
            lambda weight, view=view: self._on_view_font_weight_changed(view, weight)
        )
        view.wrapChanged.connect(
            lambda enabled, view=view: self._on_view_wrap_changed(view, enabled)
        )
        view.navigationRequested.connect(
            lambda operation, selecting, view=view: self._on_navigation_requested(
                view,
                operation,
                selecting,
            )
        )
        view.contextMenuRequested.connect(
            lambda global_position, view=view: self._show_editor_context_menu(
                view, global_position
            )
        )
        for definition in self._command_registry.definitions():
            if definition.scope == CommandScope.EDITOR:
                view.addAction(self._command_actions[definition.command_id])

    def _move_editor(self, method_name: str) -> None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        if method_name == "move_document_end":
            self.go_to_document_end()
            return
        getattr(view.state, method_name)()
        view._state_changed()

    def _move_page(self, direction: int) -> None:
        view = self.current_view
        if view is None or not view.isEnabled() or direction == 0:
            return
        page = max(1, view._visible_line_capacity() - 1)
        view.state.move_page(page if direction > 0 else -page)
        view._state_changed()

    def show_hotkeys(self) -> HotkeysPopup:
        if self._hotkeys_popup is None:
            self._hotkeys_popup = HotkeysPopup(self._command_registry, self)
            self._hotkeys_popup.set_inspection_modifiers(
                self._settings.whitespace_inspect_modifiers
            )
            self._hotkeys_popup.inspectionShortcutChanged.connect(self.set_inspection_modifiers)
        self._hotkeys_popup.show_below(self.menuBar())
        return self._hotkeys_popup

    def _add_document(
        self,
        document: Document,
        *,
        attach_recovery: bool = True,
        initial_eol_report: EOLReport | None = None,
        initial_eol_complete: bool = True,
        pane_id: str | None = None,
        view_id: str | None = None,
        restore_record=None,
        select: bool = True,
        observe_document_open: bool = True,
        is_untitled: bool = False,
    ) -> UNITITextView:
        entry = None
        adopted = False
        if self._service is not None:
            entry = self._service.documents.find_path(document.path)
            if entry is None:
                entry = self._service.documents.adopt(
                    document, is_untitled=is_untitled
                )
                adopted = True
            elif entry.document is not document:
                raise ValueError("document path already has another authority")
            if adopted and attach_recovery and self._recovery_manager is not None:
                self._recovery_manager.attach(document)
            if adopted and not is_untitled:
                self._service.track_document(
                    entry,
                    observe_open=observe_document_open,
                )
        elif attach_recovery and self._recovery_manager is not None:
            self._recovery_manager.attach(document)
        state = EditorState(document)
        view = UNITITextView(state, view_id=view_id)
        view.set_zoom_percent(self._settings.editor_zoom_percent)
        view.set_font_weight(self._settings.editor_font_weight)
        view.set_soft_wrap(self._settings.soft_wrap)
        view.set_whitespace_mode(self._settings.whitespace_mode)
        view.set_tab_width(self._settings.editor_tab_width)
        view.set_syntax_profile(
            profile_for_extension(
                document.path.suffix, self._settings.syntax_extension_overrides
            )
        )
        app = QApplication.instance()
        if isinstance(app, QApplication):
            view.set_theme_tokens(active_theme(app).editor)
        self._connect_view(view)
        leaf = self._panes.add_view(view, pane_id=pane_id, select=select)
        self._tabs = leaf.tabs
        if entry is not None:
            self._service.documents.bind_view(entry.document_id, view.view_id)
            self._refresh_group_indicator(view.view_id)
        if initial_eol_report is not None:
            document.set_source_eol_report(initial_eol_report)
            if initial_eol_complete:
                self._eol_reports[id(view)] = initial_eol_report
        self._set_status_document(view)
        self._status.update_cursor(0, 0)
        if initial_eol_report is None or not initial_eol_complete:
            self._schedule_eol_analysis(view)
        elif initial_eol_report.kind == "MIXED":
            self._show_mixed_eol_report(view, initial_eol_report)
        if restore_record is not None:
            view.restore_state(restore_record)
            self._panes.set_dock_mode(
                view.view_id,
                "dock" if view.dock_return is not None else "undock",
            )
            if view.theme_choice_id is not None:
                # `restore_state` can only remember the choice id (no
                # access to the theme/profile store from `text_view.py`);
                # resolve it into concrete tokens now that the view exists.
                tokens = self._resolve_editor_theme_tokens(view.theme_choice_id)
                if tokens is not None:
                    view.set_theme_choice(view.theme_choice_id, tokens)
        if select:
            view.setFocus()
        return view

    def open_existing_document(self, document: Document) -> UNITITextView:
        if not isinstance(document, Document):
            raise TypeError("document must be a Document")
        return self._add_document(document)

    def _inspect_open_path(
        self,
        path: str | Path,
        *,
        profile: EncodingProfile | None = None,
    ) -> tuple[EncodingProfile | None, TextFileInspection] | None:
        with ByteSource.open(path) as source:
            inspection = inspect_source(
                source,
                override=profile,
                eol_max_bytes=65_536,
            )
            selected = profile
            if inspection.encoding.requires_confirmation:
                dialog = OpenFormatDialog(
                    inspection.encoding,
                    inspection.eol,
                    preview_provider=lambda candidate: preview_source(source, candidate),
                    parent=self,
                )
                if dialog.exec() != QDialog.DialogCode.Accepted:
                    return None
                selected = dialog.selected_profile()
                inspection = inspect_source(
                    source,
                    override=selected,
                    eol_max_bytes=65_536,
                )
        return selected, inspection

    def open_path(
        self,
        path: str | Path,
        *,
        profile: EncodingProfile | None = None,
    ) -> UNITITextView | None:
        started_at = time.monotonic()
        if self._service is not None:
            existing = self._service.documents.find_path(Path(path))
            if existing is not None:
                focused = self._service.focus_document(existing.document_id)
                if isinstance(focused, UNITITextView):
                    self._record_recent_file(path)
                    self._service.record_dogfood(
                        Operation.DOCUMENT_OPEN,
                        Outcome.SUCCESS,
                        elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                    )
                    return focused
                reopened = self.open_existing_document(existing.document)
                self._record_recent_file(path)
                self._service.record_dogfood(
                    Operation.DOCUMENT_OPEN,
                    Outcome.SUCCESS,
                    elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                )
                return reopened
        decision = self._inspect_open_path(path, profile=profile)
        if decision is None:
            if self._service is not None:
                self._service.record_dogfood(
                    Operation.DOCUMENT_OPEN,
                    Outcome.CANCELLED,
                    elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                )
            return None
        selected, inspection = decision
        try:
            document = Document.open(
                path,
                profile=selected,
                resource_manager=self._resources,
            )
        except Exception:
            if self._service is not None:
                self._service.record_dogfood(
                    Operation.DOCUMENT_OPEN,
                    Outcome.FAILED,
                    elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                )
            raise
        try:
            view = self._add_document(
                document,
                initial_eol_report=inspection.eol,
                initial_eol_complete=inspection.eol_complete,
                observe_document_open=False,
            )
        except Exception:
            document.close()
            if self._service is not None:
                self._service.record_dogfood(
                    Operation.DOCUMENT_OPEN,
                    Outcome.FAILED,
                    elapsed_ms=(time.monotonic() - started_at) * 1000.0,
                )
            raise
        self._remember_directory(path)
        self._record_recent_file(path)
        if self._service is not None:
            self._service.record_dogfood(
                Operation.DOCUMENT_OPEN,
                Outcome.SUCCESS,
                elapsed_ms=(time.monotonic() - started_at) * 1000.0,
            )
        return view

    def _tab_label(self, view: UNITITextView) -> str:
        marker = "*" if view.document.modified else ""
        return f"{view.document.path.name}{marker}"

    def _set_status_document(self, view: UNITITextView) -> None:
        report = self._eol_reports.get(id(view))
        self._status.update_eol_report(report)
        self._status.update_document(view.document, report)
        self._status.update_view(view.zoom_percent, soft_wrap=view.soft_wrap)

    def _on_view_zoom_changed(self, view: UNITITextView, percent: int) -> None:
        if view is self.current_view:
            self._status.update_view(percent, soft_wrap=view.soft_wrap)
        self._settings = dataclass_replace(
            self._settings,
            editor_zoom_percent=percent,
        )
        self._save_settings()

    def _on_view_font_weight_changed(self, view: UNITITextView, weight: int) -> None:
        self._settings = dataclass_replace(
            self._settings,
            editor_font_weight=weight,
        )
        self._save_settings()

    def _on_find_replace_attached_height_changed(self, height: int) -> None:
        self._settings = dataclass_replace(
            self._settings, find_replace_attached_height=height
        )
        self._save_settings()

    def _on_view_wrap_changed(self, view: UNITITextView, enabled: bool) -> None:
        if view is self.current_view:
            self._status.update_view(view.zoom_percent, soft_wrap=enabled)
            if self._wrap_action.isChecked() != enabled:
                self._wrap_action.setChecked(enabled)
        self._settings = dataclass_replace(self._settings, soft_wrap=enabled)
        self._save_settings()

    def zoom_in_editor(self) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.zoom_in()

    def zoom_out_editor(self) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.zoom_out()

    def reset_editor_zoom(self) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.reset_zoom()

    def increase_editor_font_weight(self) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.increase_font_weight()

    def decrease_editor_font_weight(self) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.decrease_font_weight()

    def reset_editor_font_weight(self) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.reset_font_weight()

    def set_editor_wrap(self, enabled: bool) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.set_soft_wrap(enabled)

    def set_editor_text_direction(self, value: str) -> None:
        """Per-view "primary direction" override (Auto/LTR/RTL), like
        Whitespace/Tab Width/Editor Theme/Syntax Profile above and below:
        each view keeps its own choice, persisted in its own
        `ViewRecord.extra` (see `UNITITextView.set_text_direction_override`).
        Unlike those, "Auto" has no equivalent global default setting to
        feed back into — it's the sensible default for every new view."""

        view = self.current_view
        if view is not None and view.isEnabled():
            view.set_text_direction_override(value)
        self._sync_text_direction_action(view)

    def _sync_text_direction_action(self, view: UNITITextView | None) -> None:
        value = view.text_direction_override if view is not None else "auto"
        action = getattr(self, "_text_direction_actions", {}).get(value)
        if action is not None and not action.isChecked():
            action.setChecked(True)

    def _on_view_state_changed(self, view: UNITITextView) -> None:
        if any(
            job.view_ref() is view and job.revision != view.document.revision
            for job in self._navigation_jobs.values()
        ):
            self._cancel_navigation(view)
        leaf = self._panes.leaf_for_view(view.view_id)
        if leaf is not None:
            leaf.setTabText(leaf.index_of(view.view_id), self._tab_label(view))
        if view is self.current_view:
            self._set_status_document(view)
        if view is self._markdown_preview_target_view:
            self._markdown_preview_timer.start()

    def _on_current_changed(self, _index: int) -> None:
        self._find_replace.document_changed()
        view = self.current_view
        for widget in self.views:
            widget.document.set_resource_active(widget is view)
        self._refresh_reformat_actions()
        if self._markdown_preview is not None:
            target = self._markdown_preview_target_view
            if target is not None and not self._contains_view(target):
                # The tab this preview was tracking got closed elsewhere.
                self._close_markdown_preview()
            elif (
                view is not None
                and view.syntax_profile is MARKDOWN
                and view is not target
            ):
                self._markdown_preview_target_view = view
                self._refresh_markdown_preview_now()
        self._refresh_markdown_preview_action()
        self._sync_text_direction_action(view)
        self._sync_whitespace_action(view)
        self._sync_tab_width_action(view)
        self._sync_editor_theme_action(view)
        self._sync_syntax_choice_action(view)
        if view is None:
            # The active pane may be a non-document view (e.g. the attached
            # Find/Replace pane) while other document tabs are still open
            # elsewhere in this window; only reset to the empty-window
            # title/status when no documents remain at all.
            if not self.views:
                self._status.clear_document()
                self.setWindowTitle("UNITI")
            return
        self._set_status_document(view)
        line = view.document.line_for_char(view.state.cursor)
        column = view.state.cursor - view.document.line_start(line)
        self._status.update_cursor(line, column)
        self.setWindowTitle(f"UNITI — {view.document.path.name}")

    @staticmethod
    def _analyze_path_eol(
        path: Path,
        encoding: str,
        expected_identity: FileIdentity,
        context: TaskContext,
    ) -> EOLReport:
        if FileIdentity.from_path(path) != expected_identity:
            raise RuntimeError("source identity changed before EOL analysis")
        with ByteSource.open(path, prefer_mmap=False) as source:
            report = analyze_eol(
                source,
                encoding=encoding,
                cancelled=lambda: context.token.cancelled,
                progress=lambda completed, total: context.report(
                    "Analyzing line endings",
                    completed,
                    total,
                ),
            )
        context.check_cancelled()
        if FileIdentity.from_path(path) != expected_identity:
            raise RuntimeError("source identity changed during EOL analysis")
        return report

    def _schedule_eol_analysis(self, view: UNITITextView) -> None:
        source_path = view.document.source.path
        encoding = view.document.encoding_info.detected
        identity = view.document.disk_identity
        spec = TaskSpec.create(
            TaskKind.EOL,
            foreground=False,
            document_key=str(id(view.document)),
            revision=view.document.revision,
            estimated_memory_bytes=2 << 20,
        )
        handle = self._resources.tasks.submit(
            spec,
            lambda context: self._analyze_path_eol(
                source_path,
                encoding,
                identity,
                context,
            ),
        )
        self._eol_jobs[spec.task_id] = _EOLJob(
            handle,
            weakref.ref(view),
            view.document,
            identity,
        )
        self._eol_timer.start()

    def _cancel_eol_analysis(self, view: UNITITextView) -> None:
        for task_id, job in tuple(self._eol_jobs.items()):
            if job.view_ref() is not view:
                continue
            self._eol_jobs.pop(task_id, None)
            job.handle.cancel()
        if not self._eol_jobs:
            self._eol_timer.stop()

    def _dismiss_eol_dialog(self, view: UNITITextView) -> None:
        dialog = self._eol_dialogs.pop(id(view), None)
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()

    def _show_mixed_eol_report(
        self,
        view: UNITITextView,
        report: EOLReport,
    ) -> None:
        self._dismiss_eol_dialog(view)
        dialog = LineEndingReportDialog(report, self)

        def apply_policy(policy: EOLPolicy) -> None:
            if not self._contains_view(view):
                return
            eol = None if policy is EOLPolicy.PRESERVE else policy.value
            _convert_and_set_output_eol(view.document, eol)
            self._on_view_state_changed(view)

        dialog.policySelected.connect(apply_policy)
        self._eol_dialogs[id(view)] = dialog
        dialog.show()

    def _poll_eol_jobs(self) -> None:
        for task_id, job in tuple(self._eol_jobs.items()):
            if not job.handle.done:
                continue
            self._eol_jobs.pop(task_id, None)
            view = job.view_ref()
            if (
                view is None
                or not self._contains_view(view)
                or view.document is not job.document
            ):
                continue
            try:
                report = job.handle.future.result()
                if FileIdentity.from_path(job.document.path) != job.identity:
                    continue
            except (Exception, OSError):
                continue
            self._eol_reports[id(view)] = report
            view.document.set_source_eol_report(report)
            if report.kind == "MIXED":
                self._show_mixed_eol_report(view, report)
            if view is self.current_view:
                self._set_status_document(view)
        if not self._eol_jobs:
            self._eol_timer.stop()

    def set_output_encoding(self, encoding: str) -> None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        view.document.set_output_encoding(encoding)
        self._on_view_state_changed(view)

    def set_output_profile(self, profile: EncodingProfile) -> None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        view.document.set_output_format(
            OutputFormat(profile, view.document.output_format.eol)
        )
        self._on_view_state_changed(view)

    def set_output_eol(self, eol) -> None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        _convert_and_set_output_eol(view.document, eol)
        self._on_view_state_changed(view)

    def _refresh_reformat_actions(self) -> None:
        format_action = getattr(self, "_format_document_action", None)
        if format_action is None:
            # Menus (and these actions) are built after the pane tree, whose
            # construction can synchronously fire the active-view-changed
            # signal that reaches this method first.
            return
        view = self.current_view
        reformatter = (
            None if view is None else reformatter_for_key(view.syntax_profile.key)
        )
        format_action.setEnabled(reformatter is not None)
        self._minify_document_action.setEnabled(
            reformatter is not None and reformatter.can_minify
        )

    def toggle_markdown_preview(self) -> None:
        """BF-062: open/close a read-only Markdown preview split beside the
        editor, tracking whichever Markdown tab is active."""

        if self._markdown_preview is not None:
            self._close_markdown_preview()
            return
        view = self.current_view
        if view is None or view.syntax_profile is not MARKDOWN:
            return
        from uniti.ui.markdown_preview import MarkdownPreviewPane

        self._markdown_preview = MarkdownPreviewPane(self._central_splitter)
        self._central_splitter.addWidget(self._markdown_preview)
        # Literal starting sizes (not proportions), same trick as BF-059's
        # attached Find/Replace split: gives an even side-by-side split
        # regardless of the splitter's not-yet-laid-out current width.
        self._central_splitter.setSizes([1, 1])
        self._markdown_preview_target_view = view
        self._refresh_markdown_preview_now()
        self._refresh_markdown_preview_action()

    def _close_markdown_preview(self) -> None:
        if self._markdown_preview is None:
            return
        self._markdown_preview_timer.stop()
        self._markdown_preview.setParent(None)
        self._markdown_preview.deleteLater()
        self._markdown_preview = None
        self._markdown_preview_target_view = None
        self._refresh_markdown_preview_action()

    def _refresh_markdown_preview_now(self) -> None:
        view = self._markdown_preview_target_view
        if view is None or self._markdown_preview is None:
            return
        text = view.document.read(0, view.document.total_chars())
        self._markdown_preview.set_text(text)

    def _refresh_markdown_preview_action(self) -> None:
        action = getattr(self, "_markdown_preview_action", None)
        if action is None:
            return
        view = self.current_view
        is_markdown = view is not None and view.syntax_profile is MARKDOWN
        action.setEnabled(is_markdown or self._markdown_preview is not None)
        action.setChecked(self._markdown_preview is not None)

    def _reformat_current_document(self, *, minify: bool) -> None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        reformatter = reformatter_for_key(view.syntax_profile.key)
        if reformatter is None or (minify and not reformatter.can_minify):
            return
        document = view.document
        total_chars = document.total_chars()
        if total_chars > MAX_REFORMAT_CHARS:
            QMessageBox.warning(
                self,
                "Document Too Large",
                "This document is larger than "
                f"{MAX_REFORMAT_CHARS:,} characters. Formatting requires "
                "reading the whole document into memory, so it is not "
                "offered above that size.",
            )
            return
        text = document.read(0, total_chars)
        action = reformatter.minify if minify else reformatter.format
        try:
            formatted = action(text)
        except ReformatFailure as exc:
            error = exc.error
            location = (
                f" (line {error.line}, column {error.column})"
                if error.line is not None
                else ""
            )
            QMessageBox.critical(
                self,
                "Minify Failed" if minify else "Format Failed",
                f"{error.message}{location}",
            )
            return
        document.replace(0, total_chars, formatted)

    def format_current_document(self) -> None:
        self._reformat_current_document(minify=False)

    def minify_current_document(self) -> None:
        self._reformat_current_document(minify=True)

    @staticmethod
    def _exact_profile(profile: EncodingProfile | str) -> EncodingProfile:
        if isinstance(profile, EncodingProfile):
            return profile
        try:
            return encoding_profile(profile)
        except ValueError:
            return profile_from_codec(profile)

    def reinterpret_current(self, profile: EncodingProfile | str) -> None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        if view.document.modified:
            QMessageBox.information(
                self,
                "Reinterpret Encoding",
                "Save or discard current changes before reinterpreting the source bytes.",
            )
            return

        path = view.document.path
        exact_profile = self._exact_profile(profile)
        decision = self._inspect_open_path(path, profile=exact_profile)
        if decision is None:
            return
        selected, inspection = decision
        try:
            document = Document.open(
                path,
                profile=selected,
                resource_manager=self._resources,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Reinterpret Failed", str(exc))
            return

        try:
            self._replace_view_document(
                view,
                document,
                initial_eol_report=inspection.eol,
                initial_eol_complete=inspection.eol_complete,
            )
        except Exception:
            document.close()
            raise
        view.setFocus()

    @staticmethod
    def _build_navigation_result(
        snapshot,
        target_line: int | None,
        context: TaskContext,
    ) -> LineNavigationResult:
        try:
            batch = build_line_index_batch(
                snapshot,
                start_char=0,
                max_chars=sys.maxsize,
                context=context,
            )
            if target_line is not None:
                result = resolve_line_in_batch(snapshot, batch, target_line)
            elif not batch.complete:
                result = LineNavigationResult(batch, None)
            else:
                total_lines = 1
                if batch.summaries:
                    final = batch.summaries[-1]
                    total_lines += (
                        final.line_count_before + final.line_starts_in_chunk
                    )
                seeded = resolve_line_in_batch(snapshot, batch, total_lines - 1)
                result = LineNavigationResult(
                    seeded.batch,
                    batch.indexed_char_end,
                )
            return dataclass_replace(
                result,
                source_checkpoints=snapshot.piece_table.offset_checkpoints,
                source_mapping_complete=snapshot.piece_table.offset_mapping_complete,
            )
        finally:
            snapshot.close()

    def _schedule_navigation(
        self,
        view: UNITITextView,
        *,
        target_line: int | None,
        selecting: bool = False,
    ) -> bool:
        self._cancel_navigation(view)
        snapshot = view.document.snapshot()
        revision = view.document.revision
        spec = TaskSpec.create(
            TaskKind.NAVIGATION,
            foreground=True,
            document_key=str(id(view.document)),
            revision=revision,
            estimated_memory_bytes=4 << 20,
        )
        try:
            handle = self._resources.tasks.submit(
                spec,
                lambda context: self._build_navigation_result(
                    snapshot,
                    target_line,
                    context,
                ),
            )
        except TaskAdmissionError:
            snapshot.close()
            return False
        handle.future.add_done_callback(lambda _future: snapshot.close())
        self._navigation_jobs[spec.task_id] = _NavigationJob(
            handle,
            weakref.ref(view),
            view.document,
            revision,
            selecting,
        )
        self._navigation_timer.start()
        return True

    def _cancel_navigation(self, view: UNITITextView) -> None:
        for task_id, job in tuple(self._navigation_jobs.items()):
            if job.view_ref() is not view:
                continue
            self._navigation_jobs.pop(task_id, None)
            job.handle.cancel()
        if not self._navigation_jobs:
            self._navigation_timer.stop()

    def _poll_navigation_jobs(self) -> None:
        for task_id, job in tuple(self._navigation_jobs.items()):
            if not job.handle.done:
                continue
            self._navigation_jobs.pop(task_id, None)
            view = job.view_ref()
            if (
                view is None
                or not self._contains_view(view)
                or view.document is not job.document
                or view.document.revision != job.revision
            ):
                continue
            try:
                result = job.handle.future.result()
            except Exception:
                continue
            if result.target_char is None:
                continue
            if result.source_checkpoints:
                view.document.offset_mapper.publish_progress(
                    result.source_checkpoints,
                    complete=result.source_mapping_complete,
                )
            if not view.document.document_line_index.publish(
                result.batch,
                expected_revision=job.revision,
            ):
                continue
            view.document.break_history_coalescing()
            if not job.selecting:
                view.state.anchor = result.target_char
            view.state.cursor = result.target_char
            view.state._preferred_column = None
            view._state_changed()
        if not self._navigation_jobs:
            self._navigation_timer.stop()

    def _on_navigation_requested(
        self,
        view: UNITITextView,
        operation: str,
        selecting: bool,
    ) -> None:
        if view is not self.current_view or not view.isEnabled():
            return
        if operation == "document_end":
            self.go_to_document_end(selecting=selecting)

    def go_to_document_end(self, *, selecting: bool = False) -> bool:
        view = self.current_view
        if view is None or not view.isEnabled():
            return False
        index = view.document.document_line_index
        if index.complete or view.document.source.size <= 1 << 20:
            view.state.move_document_end(selecting=selecting)
            view._state_changed()
            return True
        return self._schedule_navigation(
            view,
            target_line=None,
            selecting=selecting,
        )

    def go_to_line(self, line_number: int) -> bool:
        view = self.current_view
        if view is None or not view.isEnabled() or line_number < 1:
            return False
        target_line = line_number - 1
        index = view.document.document_line_index
        if (
            target_line < index.indexed_line_count
            or view.document.source.size <= 1 << 20
        ):
            try:
                target = view.document.line_start(target_line)
            except ValueError:
                return False
            view.state.move_to(target)
            view._state_changed()
            return True
        if index.complete:
            return False
        return self._schedule_navigation(view, target_line=target_line)

    def go_to_line_dialog(self) -> bool:
        view = self.current_view
        if view is None or not view.isEnabled():
            return False
        current_line = view.document.line_for_char(view.state.cursor) + 1
        line_number, accepted = QInputDialog.getInt(
            self,
            "Go to Line",
            "Line:",
            current_line,
            1,
            2_147_483_647,
        )
        return accepted and self.go_to_line(line_number)

    def _replace_view_document(
        self,
        view: UNITITextView,
        replacement: Document,
        *,
        initial_eol_report: EOLReport | None = None,
        initial_eol_complete: bool = True,
        allow_path_change: bool = False,
    ) -> None:
        old_document = view.document
        if self._service is not None:
            entry = self._service.documents.entry_for_view(view.view_id)
            if entry is None or entry.document is not old_document:
                raise ValueError("view is not bound to its document authority")
            affected: list[tuple[UNITIMainWindow, UNITITextView]] = []
            for view_id in entry.view_ids:
                owner = self._service.windows.window_for_view(view_id)
                candidate = (
                    None
                    if owner is None
                    else getattr(owner, "view_for_id", lambda _value: None)(view_id)
                )
                if not isinstance(owner, UNITIMainWindow) or not isinstance(
                    candidate, UNITITextView
                ):
                    raise ValueError("document authority has an unavailable view")
                owner._prepare_view_document_replacement(candidate)
                affected.append((owner, candidate))
            if self._recovery_manager is not None:
                self._recovery_manager.attach(replacement)
                self._recovery_manager.detach(old_document, clean=True)
            self._service.documents.replace_document(
                entry.document_id,
                replacement,
                allow_path_change=allow_path_change,
            )
            self._service.track_document(entry)
            if initial_eol_report is not None:
                replacement.set_source_eol_report(initial_eol_report)
            for owner, candidate in affected:
                owner._install_view_document_replacement(
                    candidate,
                    replacement,
                    initial_eol_report=initial_eol_report,
                    initial_eol_complete=initial_eol_complete,
                )
            self._find_replace.document_changed()
            return

        self._prepare_view_document_replacement(view)
        if self._recovery_manager is not None:
            self._recovery_manager.attach(replacement)
            self._recovery_manager.detach(old_document, clean=True)
        if initial_eol_report is not None:
            replacement.set_source_eol_report(initial_eol_report)
        self._install_view_document_replacement(
            view,
            replacement,
            initial_eol_report=initial_eol_report,
            initial_eol_complete=initial_eol_complete,
        )
        old_document.close()
        self._find_replace.document_changed()

    def _prepare_view_document_replacement(self, view: UNITITextView) -> None:
        self._cancel_navigation(view)
        self._cancel_eol_analysis(view)
        self._dismiss_eol_dialog(view)
        self._eol_reports.pop(id(view), None)

    def _install_view_document_replacement(
        self,
        view: UNITITextView,
        replacement: Document,
        *,
        initial_eol_report: EOLReport | None,
        initial_eol_complete: bool,
    ) -> None:
        view.replace_state(EditorState(replacement))
        if initial_eol_report is not None and initial_eol_complete:
            self._eol_reports[id(view)] = initial_eol_report
        view.set_match_index(None)
        view._max_seen_line_width = 0
        view._wrap_index = None
        view._wrap_signature = None
        view._refresh_scrollbars(advance_index=False)
        view._state_changed()
        if initial_eol_report is None or not initial_eol_complete:
            self._schedule_eol_analysis(view)
        elif initial_eol_report.kind == "MIXED":
            self._show_mixed_eol_report(view, initial_eol_report)

    def reload_current(self) -> bool:
        view = self.current_view
        if view is None or not view.isEnabled():
            return False
        if view.document.modified:
            choice = QMessageBox.warning(
                self,
                "Reload/Revert from Disk",
                "Discard all unsaved changes and reload this document from disk?",
                QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Cancel,
            )
            if choice != QMessageBox.StandardButton.Discard:
                return False

        profile = (
            view.document.source_profile
            if view.document.encoding_info.user_override
            else None
        )
        try:
            replacement = Document.open(
                view.document.path,
                profile=profile,
                resource_manager=self._resources,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Reload Failed", str(exc))
            return False
        try:
            self._replace_view_document(view, replacement)
        except Exception:
            replacement.close()
            raise
        return True

    def show_character_inspector(self) -> None:
        """The hotkey toggles like Find does (2026-09-20 request):
        pressing it again while the dialog is open closes it instead of
        opening a second one -- via the generic `_toggle_window` manager
        below, which is also why the dialog itself is non-modal (`show()`,
        not `exec()`)."""

        self._toggle_window("character_inspector", self._build_character_inspector)

    def _build_character_inspector(
        self, zoom_percent: int, geometry: tuple[int, int, int, int] | None
    ) -> CharacterInspectorDialog | None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return None
        selection = view.state.selection
        if selection is not None and selection[1] - selection[0] > 1:
            return self._build_inspect_selection(view, selection, zoom_percent, geometry)
        payload = self._character_inspector_single_payload(view, selection)
        if payload is None:
            QMessageBox.information(self, "Character Inspector", "No character at cursor.")
            return None
        character, output_encoding, invalid_bytes = payload
        return CharacterInspectorDialog(
            character,
            output_encoding=output_encoding,
            invalid_bytes=invalid_bytes,
            initial_zoom_percent=zoom_percent,
            initial_geometry=geometry,
            on_refresh=self._refresh_character_inspector,
            parent=self,
        )

    def _character_inspector_single_payload(
        self, view: UNITITextView, selection: tuple[int, int] | None
    ) -> tuple[str, str, bytes | None] | None:
        position = selection[0] if selection is not None else view.state.cursor
        invalid_bytes = None
        try:
            annotated = view.document.read_with_annotations(position, position + 1)
            character = annotated.text
            if annotated.invalid_bytes:
                invalid_bytes = annotated.invalid_bytes[0].raw
        except ValueError:
            character = ""
        if not character and position > 0:
            try:
                annotated = view.document.read_with_annotations(position - 1, position)
                character = annotated.text
                if annotated.invalid_bytes:
                    invalid_bytes = annotated.invalid_bytes[0].raw
            except ValueError:
                character = ""
        if not character:
            return None
        return character[0], view.document.output_encoding, invalid_bytes

    def _character_inspector_selection_payload(
        self, view: UNITITextView, selection: tuple[int, int]
    ) -> tuple[str, str, None] | None:
        from uniti.ui.character_inspector import MAX_INSPECT_SELECTION_CHARACTERS

        start, end = selection
        bounded_end = min(end, start + MAX_INSPECT_SELECTION_CHARACTERS)
        try:
            text = view.document.read(start, bounded_end)
        except ValueError:
            text = ""
        if not text:
            return None
        return text, view.document.output_encoding, None

    def _build_inspect_selection(
        self,
        view: UNITITextView,
        selection: tuple[int, int],
        zoom_percent: int,
        geometry: tuple[int, int, int, int] | None,
    ) -> CharacterInspectorDialog | None:
        """BF-065: the whole-selection counterpart to the single-character
        inspector above — same dialog class, a per-character list+detail
        view instead of one character's form."""

        payload = self._character_inspector_selection_payload(view, selection)
        if payload is None:
            QMessageBox.information(
                self, "Character Inspector", "No characters in selection."
            )
            return None
        text, output_encoding, _ = payload
        return CharacterInspectorDialog(
            text,
            output_encoding=output_encoding,
            initial_zoom_percent=zoom_percent,
            initial_geometry=geometry,
            on_refresh=self._refresh_character_inspector,
            parent=self,
        )

    def _refresh_character_inspector(self) -> None:
        """BF-076: re-reads the current view's selection/cursor and
        repaints the already-open Character Inspector in place, rather
        than requiring the user to close and reopen it to see a newer
        selection. Wired as the dialog's `on_refresh` callback."""

        dialog = self._toggle_windows.get("character_inspector")
        if dialog is None:
            return
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        selection = view.state.selection
        if selection is not None and selection[1] - selection[0] > 1:
            payload = self._character_inspector_selection_payload(view, selection)
            message = "No characters in selection."
        else:
            payload = self._character_inspector_single_payload(view, selection)
            message = "No character at cursor."
        if payload is None:
            QMessageBox.information(self, "Character Inspector", message)
            return
        text, output_encoding, invalid_bytes = payload
        dialog.refresh(text, output_encoding=output_encoding, invalid_bytes=invalid_bytes)

    def _toggle_window(self, key: str, factory) -> QWidget | None:
        """One generic open/close/geometry-and-zoom-persistence manager
        for every "toggle window" (2026-09-20 request: "one global
        function to manage toggle windows") -- Compare, Character
        Inspector, and any future one. A call while `key`'s window is
        already open closes it instead of opening another (matching Find:
        the hotkey toggles). `factory(zoom_percent, geometry)` builds a
        new window using the last-persisted values for `key` (or the
        defaults if none exist yet), or returns `None` to decline opening
        at all -- e.g. the user cancelled a document/file picker, or
        there was nothing to inspect -- in which case nothing is shown or
        tracked. Whatever closes the window (this method again, its own
        Close action, Escape, or window chrome) is caught via its
        `closeRequested` signal if it has one (`ComparePane`), else
        `QDialog`'s own `finished` (`CharacterInspectorDialog`), and
        persists its final geometry (always) and `zoom_percent` (if the
        window exposes that property) back to `Settings`."""

        existing = self._toggle_windows.get(key)
        if existing is not None:
            existing.close()
            return None
        zoom_percent = self._settings.toggle_window_zoom_percent.get(key, 100)
        geometry = self._settings.toggle_window_geometry.get(key)
        window = factory(zoom_percent, geometry)
        if window is None:
            return None
        self._toggle_windows[key] = window
        close_signal = getattr(window, "closeRequested", None)
        if close_signal is None:
            close_signal = window.finished
        close_signal.connect(
            lambda *_args, key=key, window=window: self._on_toggle_window_closed(
                key, window
            )
        )
        window.show()
        window.raise_()
        window.activateWindow()
        return window

    def _on_toggle_window_closed(self, key: str, window: QWidget) -> None:
        if self._toggle_windows.get(key) is not window:
            return
        del self._toggle_windows[key]
        geometry = window.geometry()
        geometries = dict(self._settings.toggle_window_geometry)
        geometries[key] = (
            geometry.x(),
            geometry.y(),
            geometry.width(),
            geometry.height(),
        )
        updates: dict[str, object] = {"toggle_window_geometry": geometries}
        zoom_percent = getattr(window, "zoom_percent", None)
        if isinstance(zoom_percent, int):
            zoom_percents = dict(self._settings.toggle_window_zoom_percent)
            zoom_percents[key] = zoom_percent
            updates["toggle_window_zoom_percent"] = zoom_percents
        self._settings = dataclass_replace(self._settings, **updates)
        self._save_settings()
        window.deleteLater()

    def show_diagnostics(self) -> None:
        documents = list(dict.fromkeys(view.document for view in self.views))
        dialog = DiagnosticsDialog(
            diagnostics_snapshot(
                documents,
                startup_snapshot=self._startup_snapshot,
                resource_manager=self._resources,
                dogfood_status=(
                    None
                    if self._service is None
                    else self._service.dogfood_status
                ),
            ),
            self,
        )
        dialog.exec()

    def _compare_candidates(self) -> list[tuple[str, Document]]:
        documents = list(dict.fromkeys(view.document for view in self.views))
        return [
            (f"{document.path.name}{'*' if document.modified else ''}", document)
            for document in documents
        ]

    def show_compare(self) -> None:
        """The hotkey/menu command toggles like Find and Character
        Inspector do (2026-09-20 request), via the generic
        `_toggle_window` manager below."""

        self._toggle_window("compare", self._build_compare_pane)

    def _build_compare_pane(
        self, zoom_percent: int, geometry: tuple[int, int, int, int] | None
    ) -> ComparePane | None:
        candidates = self._compare_candidates()
        if not candidates:
            # "ask for files if nothing OPEN" (2026-09-20 request): with
            # no documents open at all, the usual picker has nothing to
            # offer -- prompt for exactly two files directly instead of
            # just reporting an error, and compare those two once opened.
            paths, _filter = QFileDialog.getOpenFileNames(
                self,
                "Choose Two Files to Compare",
                self._settings.last_directory or "",
            )
            if not paths:
                return None
            if len(paths) != 2:
                QMessageBox.information(
                    self, "Compare", "Choose exactly two files to compare."
                )
                return None
            documents = []
            for path in paths:
                opened = self.open_path(path)
                if opened is None:
                    return None
                documents.append(opened.document)
            left_label, right_label = (Path(path).name for path in paths)
            left_document, right_document = documents
        else:
            if len(candidates) < 2:
                QMessageBox.information(
                    self, "Compare", "Open at least two documents to compare."
                )
                return None
            dialog = CompareDocumentPickerDialog(candidates, parent=self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            left_label, left_document = dialog.left_choice()
            right_label, right_document = dialog.right_choice()
            if left_document is right_document:
                QMessageBox.warning(
                    self, "Compare", "Choose two different documents to compare."
                )
                return None
        for label, document in (
            (left_label, left_document),
            (right_label, right_document),
        ):
            if document.total_chars() > MAX_COMPARE_CHARS:
                QMessageBox.warning(
                    self,
                    "Compare",
                    f'"{label}" is larger than {MAX_COMPARE_CHARS:,} '
                    "characters and cannot be compared.",
                )
                return None
        pane = ComparePane(left_document, left_label, right_document, right_label, self)
        pane.apply_view_defaults(
            whitespace_mode=self._settings.whitespace_mode,
            tab_width=self._settings.editor_tab_width,
            syntax_extension_overrides=self._settings.syntax_extension_overrides,
        )
        pane.set_zoom_percent(zoom_percent)
        if geometry is not None:
            pane.setGeometry(*geometry)
        else:
            pane.resize(900, 600)
        return pane

    def export_dogfood_evidence(self):
        if self._service is None:
            return None
        initial = (
            Path(self._settings.last_directory or "")
            / "uniti-dogfood-evidence.json"
        )
        selected, _filter = QFileDialog.getSaveFileName(
            self,
            "Export Dogfood Evidence",
            str(initial),
            "JSON Files (*.json)",
        )
        if not selected:
            return None
        try:
            handle = self._service.export_dogfood_evidence(Path(selected))
        except (RuntimeError, ValueError):
            QMessageBox.warning(
                self,
                "Dogfood Evidence Unavailable",
                "UNITI could not start the evidence export.",
            )
            return None
        self.statusBar().showMessage("Dogfood evidence export started.", 5000)
        return handle

    def clear_dogfood_evidence(self):
        if self._service is None:
            return None
        answer = QMessageBox.question(
            self,
            "Clear Dogfood Evidence",
            "Clear all locally stored UNITI dogfood evidence?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        try:
            handle = self._service.clear_dogfood_evidence()
        except RuntimeError:
            QMessageBox.warning(
                self,
                "Dogfood Evidence Unavailable",
                "UNITI could not start clearing the evidence.",
            )
            return None
        self.statusBar().showMessage("Clearing dogfood evidence…", 5000)
        return handle

    def set_pause_background(self, paused: bool) -> None:
        self._resources.pause_background(bool(paused))
        if self._pause_background_action.isChecked() != bool(paused):
            self._pause_background_action.setChecked(bool(paused))
        self._apply_resource_status(self._resources.status)

    def set_startup_snapshot(self, snapshot: Mapping[str, object]) -> None:
        self._startup_snapshot = dict(snapshot)

    def _show_save_error(self, exc: Exception) -> None:
        if isinstance(exc, ExternalFileChangedError):
            QMessageBox.warning(
                self,
                "File Changed on Disk",
                f"{exc}\n\nUNITI did not overwrite the file. Reload/inspect it, or use Save As when safe.",
            )
            return
        QMessageBox.critical(self, "Save Failed", str(exc))

    def _view_for_path(
        self,
        path: str | Path,
        *,
        excluding: UNITITextView | None = None,
    ) -> UNITITextView | None:
        windows = (
            tuple(window for _window_id, window in self._service.windows.items)
            if self._service is not None
            else (self,)
        )
        for window in windows:
            for candidate in getattr(window, "views", ()):
                if candidate is excluding:
                    continue
                if native_paths_equal(candidate.document.path, path):
                    return candidate
        return None

    def _confirm_encoding_change(
        self,
        path: Path,
        before: EncodingProfile,
        after: EncodingProfile,
    ) -> bool:
        if before == after:
            return True
        result = QMessageBox.warning(
            self,
            "Change Text Encoding",
            (
                f"{path}\n\n"
                f"Encoding will change: {before.label} -> {after.label}\n\n"
                "This changes the file's byte representation. Continue?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Yes

    def _confirm_existing_replacement(
        self,
        path: Path,
        output_format: OutputFormat,
        inspection: TextFileInspection,
    ) -> bool:
        output_eol = (
            "Preserve source structure"
            if output_format.eol is EOLPolicy.PRESERVE
            else output_format.eol.value
        )
        result = QMessageBox.warning(
            self,
            "Replace Existing File",
            (
                f"Replace the existing file?\n\n{path}\n\n"
                f"Current line endings: {inspection.eol.kind}\n"
                f"Output line endings: {output_eol}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Yes

    def _confirm_open_replacement(self, path: Path) -> bool:
        result = QMessageBox.warning(
            self,
            "Replace Open Document",
            (
                f"{path} is already open in UNITI.\n\n"
                "Replace it on disk, reload its open tab, and discard that tab's "
                "current undo history?"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        return result == QMessageBox.StandardButton.Yes

    @staticmethod
    def _inspect_known_output(
        path: str | Path,
        profile: EncodingProfile,
    ) -> TextFileInspection:
        with ByteSource.open(path) as source:
            return inspect_source(
                source,
                override=profile,
                eol_max_bytes=65_536,
            )

    def _refresh_saved_format(
        self,
        view: UNITITextView,
        profile: EncodingProfile,
    ) -> None:
        inspection = self._inspect_known_output(view.document.path, profile)
        view.document.set_source_eol_report(inspection.eol)
        for owner in self._appearance_windows():
            for candidate in owner.views:
                if candidate.document is not view.document:
                    continue
                owner._cancel_eol_analysis(candidate)
                owner._dismiss_eol_dialog(candidate)
                if inspection.eol_complete:
                    owner._eol_reports[id(candidate)] = inspection.eol
                else:
                    owner._eol_reports.pop(id(candidate), None)
                if inspection.eol_complete and inspection.eol.kind == "MIXED":
                    owner._show_mixed_eol_report(candidate, inspection.eol)
                owner._on_view_state_changed(candidate)
                candidate.viewport().update()
                if not inspection.eol_complete:
                    owner._schedule_eol_analysis(candidate)

    def _open_verified_export(
        self,
        path: Path,
        output_format: OutputFormat,
        *,
        existing_view: UNITITextView | None,
    ) -> UNITITextView:
        inspection = self._inspect_known_output(path, output_format.encoding)
        document = Document.open(
            path,
            profile=output_format.encoding,
            resource_manager=self._resources,
        )
        if existing_view is None:
            try:
                return self._add_document(
                    document,
                    initial_eol_report=inspection.eol,
                    initial_eol_complete=inspection.eol_complete,
                )
            except Exception:
                document.close()
                raise
        was_untitled = self._is_untitled_view(existing_view)
        old_scratch_dir = existing_view.document.path.parent if was_untitled else None
        try:
            self._replace_view_document(
                existing_view,
                document,
                initial_eol_report=inspection.eol,
                initial_eol_complete=inspection.eol_complete,
                allow_path_change=was_untitled,
            )
        except Exception:
            document.close()
            raise
        if old_scratch_dir is not None:
            shutil.rmtree(old_scratch_dir, ignore_errors=True)
        owner = (
            self._service.windows.window_for_view(existing_view.view_id)
            if self._service is not None
            else self
        )
        if owner is not None:
            owner._select_view(existing_view)
        return existing_view

    def _resolve_save_as_decision(
        self,
        view: UNITITextView,
        path: str | Path | None,
        output_format: OutputFormat | None,
    ) -> _SaveAsDecision | None:
        destination = Path(path).expanduser() if path is not None else None
        selected = output_format or view.document.output_format
        if not isinstance(selected, OutputFormat):
            raise TypeError("output_format must be an OutputFormat")

        if destination is None:
            dialog = SaveAsFormatDialog(
                initial_directory=self._save_as_initial_directory(view),
                initial_name=view.document.path.name,
                initial_format=selected,
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            selection = dialog.result_selection()
            if selection is None:
                return None
            destination = selection.destination.expanduser()
            selected = selection.output_format

        destination = normalize_native_path(destination).path
        if native_paths_equal(destination, view.document.path):
            if not self._confirm_encoding_change(
                view.document.path,
                view.document.saved_output_format.encoding,
                selected.encoding,
            ):
                return None
            return _SaveAsDecision(
                destination,
                selected,
                None,
                view.document.disk_identity,
                True,
            )

        target_view = self._view_for_path(destination, excluding=view)
        if target_view is not None and (
            target_view.document.modified or not target_view.isEnabled()
        ):
            QMessageBox.warning(
                self,
                "Target Has Unsaved Changes",
                (
                    f"{destination} is already open with unsaved changes or an "
                    "active operation. Save or close that tab before replacing it."
                ),
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Ok,
            )
            return None

        expected_target_identity: FileIdentity | None = None
        if destination.exists():
            try:
                expected_target_identity = FileIdentity.from_path(destination)
            except OSError:
                expected_target_identity = None
            decision = self._inspect_open_path(destination)
            if decision is None:
                return None
            confirmed_profile, target_inspection = decision
            target_profile = (
                confirmed_profile or target_inspection.encoding.suggested
            )
            if not self._confirm_existing_replacement(
                destination,
                selected,
                target_inspection,
            ):
                return None
            if not self._confirm_encoding_change(
                destination,
                target_profile,
                selected.encoding,
            ):
                return None
            if target_view is not None and not self._confirm_open_replacement(
                destination
            ):
                return None

        if target_view is not None and (
            target_view.document.modified or not target_view.isEnabled()
        ):
            QMessageBox.warning(
                self,
                "Target Has Unsaved Changes",
                f"{destination} changed while replacement was being confirmed.",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Ok,
            )
            return None
        return _SaveAsDecision(
            destination,
            selected,
            target_view,
            expected_target_identity,
            False,
        )

    def _begin_file_operation(
        self,
        view: UNITITextView,
        decision: _SaveAsDecision,
    ) -> FileOperationHandle | None:
        try:
            operation = self._file_operations.start(
                view.document,
                decision.destination,
                decision.output_format,
                expected_destination_identity=decision.expected_target_identity,
            )
        except Exception as exc:
            self._show_save_error(exc)
            return None
        target_document = (
            None if decision.target_view is None else decision.target_view.document
        )
        self._save_jobs[operation.task_id] = _SaveJob(
            operation,
            weakref.ref(view),
            view.document,
            decision.output_format,
            (
                None
                if decision.target_view is None
                else weakref.ref(decision.target_view)
            ),
            target_document,
        )
        view.setEnabled(False)
        self.statusBar().showMessage("Saving…")
        return operation

    def start_save_current(self) -> FileOperationHandle | None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return None
        if self._is_untitled_view(view):
            return self.start_save_current_as()
        selected = view.document.output_format
        if not self._confirm_encoding_change(
            view.document.path,
            view.document.saved_output_format.encoding,
            selected.encoding,
        ):
            return None
        return self._begin_file_operation(
            view,
            _SaveAsDecision(
                view.document.path,
                selected,
                None,
                view.document.disk_identity,
                True,
            ),
        )

    def start_save_current_as(
        self,
        path: str | Path | None = None,
        output_format: OutputFormat | None = None,
    ) -> FileOperationHandle | None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return None
        decision = self._resolve_save_as_decision(view, path, output_format)
        if decision is None:
            return None
        return self._begin_file_operation(view, decision)

    def _finish_file_operation(self, operation: FileOperationHandle) -> None:
        job = self._save_jobs.pop(operation.task_id, None)
        if job is None:
            return
        view = job.view_ref()
        prepared = None
        try:
            prepared = operation.task.future.result()
            if operation.task.token.cancelled:
                self.statusBar().showMessage("Save cancelled", 3000)
                self._file_operations.record_completion(
                    operation,
                    cancelled=True,
                )
                return
            if view is None or view.document is not job.document:
                self._file_operations.record_completion(
                    operation,
                    unavailable=True,
                )
                return
            if job.target_view_ref is not None:
                target_view = job.target_view_ref()
                if (
                    target_view is None
                    or target_view.document is not job.target_document
                    or target_view.document.modified
                    or not target_view.isEnabled()
                ):
                    QMessageBox.warning(
                        self,
                        "Target Has Unsaved Changes",
                        (
                            f"{operation.request.destination} changed while the "
                            "save was being prepared. UNITI did not overwrite it."
                        ),
                        QMessageBox.StandardButton.Ok,
                        QMessageBox.StandardButton.Ok,
                    )
                    self._file_operations.record_completion(
                        operation,
                        unavailable=True,
                    )
                    return
            if operation.request.in_place:
                result = job.document.commit_prepared_save(prepared)
                view.setEnabled(True)
                self._refresh_saved_format(view, job.output_format.encoding)
            else:
                result = job.document.commit_prepared_export(prepared)
                view.setEnabled(True)
                target_view = (
                    None
                    if job.target_view_ref is None
                    else job.target_view_ref()
                )
                if target_view is None and self._is_untitled_view(view):
                    target_view = view
                self._open_verified_export(
                    result,
                    job.output_format,
                    existing_view=target_view,
                )
                self._remember_directory(result)
                self._on_view_state_changed(view)
                self._on_current_changed(self._tabs.currentIndex())
            self._file_operations.record_completion(
                operation,
                durability_result=prepared.staged.commit_durability,
            )
            self.statusBar().showMessage(f"Saved {result}", 3000)
        except Exception as exc:
            self._file_operations.record_completion(
                operation,
                error=exc,
                cancelled=operation.task.token.cancelled,
            )
            if operation.task.token.cancelled:
                self.statusBar().showMessage("Save cancelled", 3000)
            else:
                self._show_save_error(exc)
        finally:
            if prepared is not None:
                prepared.discard()
            if view is not None and view.document is job.document:
                view.setEnabled(True)

    def cancel_active_operation(self) -> None:
        view = self.current_view
        for job in reversed(tuple(self._save_jobs.values())):
            if view is None or job.view_ref() is view:
                job.operation.cancel()
                return

    def save_current(self) -> Path | None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return None
        if self._is_untitled_view(view):
            return self.save_current_as()
        selected = view.document.output_format
        if not self._confirm_encoding_change(
            view.document.path,
            view.document.saved_output_format.encoding,
            selected.encoding,
        ):
            return None
        try:
            result = view.document.save(output_format=selected)
        except Exception as exc:
            self._show_save_error(exc)
            return None
        self._refresh_saved_format(view, selected.encoding)
        return result

    def save_current_as(
        self,
        path: str | Path | None = None,
        output_format: OutputFormat | None = None,
    ) -> Path | None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return None
        destination = Path(path).expanduser() if path is not None else None
        selected = output_format or view.document.output_format
        if not isinstance(selected, OutputFormat):
            raise TypeError("output_format must be an OutputFormat")

        if destination is None:
            dialog = SaveAsFormatDialog(
                initial_directory=self._save_as_initial_directory(view),
                initial_name=view.document.path.name,
                initial_format=selected,
                parent=self,
            )
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return None
            selection = dialog.result_selection()
            if selection is None:
                return None
            destination = selection.destination.expanduser()
            selected = selection.output_format

        destination = normalize_native_path(destination).path
        if native_paths_equal(destination, view.document.path):
            if not self._confirm_encoding_change(
                view.document.path,
                view.document.saved_output_format.encoding,
                selected.encoding,
            ):
                return None
            try:
                result = view.document.save(output_format=selected)
            except Exception as exc:
                self._show_save_error(exc)
                return None
            self._refresh_saved_format(view, selected.encoding)
            return result

        target_view = self._view_for_path(destination, excluding=view)
        if target_view is not None and (
            target_view.document.modified or not target_view.isEnabled()
        ):
            QMessageBox.warning(
                self,
                "Target Has Unsaved Changes",
                (
                    f"{destination} is already open with unsaved changes or an "
                    "active operation. Save or close that tab before replacing it."
                ),
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Ok,
            )
            return None

        target_inspection: TextFileInspection | None = None
        target_profile: EncodingProfile | None = None
        expected_target_identity: FileIdentity | None = None
        if destination.exists():
            try:
                expected_target_identity = FileIdentity.from_path(destination)
            except OSError:
                expected_target_identity = None
            decision = self._inspect_open_path(destination)
            if decision is None:
                return None
            confirmed_profile, target_inspection = decision
            target_profile = confirmed_profile or target_inspection.encoding.suggested
            if not self._confirm_existing_replacement(
                destination,
                selected,
                target_inspection,
            ):
                return None
            if not self._confirm_encoding_change(
                destination,
                target_profile,
                selected.encoding,
            ):
                return None
            if target_view is not None and not self._confirm_open_replacement(
                destination
            ):
                return None

        if target_view is not None and (
            target_view.document.modified or not target_view.isEnabled()
        ):
            QMessageBox.warning(
                self,
                "Target Has Unsaved Changes",
                f"{destination} changed while replacement was being confirmed.",
                QMessageBox.StandardButton.Ok,
                QMessageBox.StandardButton.Ok,
            )
            return None

        try:
            result = view.document.export_copy(
                destination,
                output_format=selected,
                expected_destination_identity=expected_target_identity,
            )
        except Exception as exc:
            self._show_save_error(exc)
            return None
        if target_view is None and self._is_untitled_view(view):
            target_view = view
        try:
            self._open_verified_export(
                result,
                selected,
                existing_view=target_view,
            )
        except Exception as exc:
            self._show_save_error(exc)
            return None
        self._remember_directory(result)
        self._on_view_state_changed(view)
        self._on_current_changed(self._tabs.currentIndex())
        return result

    def undo_current(self) -> None:
        if self._find_replace.undo_focused_input():
            return
        view = self.current_view
        if view is None or not view.isEnabled() or not view.document.can_undo:
            return
        view.state.undo()
        view._state_changed()

    def redo_current(self) -> None:
        if self._find_replace.redo_focused_input():
            return
        view = self.current_view
        if view is None or not view.isEnabled() or not view.document.can_redo:
            return
        view.state.redo()
        view._state_changed()

    def copy_current(self) -> None:
        field = self._find_replace.focused_input()
        if field is not None:
            field.copy()
            return
        view = self.current_view
        if view is not None and view.isEnabled():
            view.copy_selection()

    def cut_current(self) -> None:
        field = self._find_replace.focused_input()
        if field is not None:
            field.cut()
            return
        view = self.current_view
        if view is not None and view.isEnabled():
            view.cut_selection()

    def paste_current(self) -> None:
        field = self._find_replace.focused_input()
        if field is not None:
            field.paste()
            return
        view = self.current_view
        if view is not None and view.isEnabled():
            view.paste_clipboard()

    def select_all(self) -> None:
        field = self._find_replace.focused_input()
        if field is not None:
            field.selectAll()
            return
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        view.state.select_all()
        view._state_changed()

    def toggle_unicode_hex(self) -> None:
        """BF-053: convert a hex codepoint run before the cursor into its
        character, or reverse a character back into hex notation."""

        view = self.current_view
        if view is None or not view.isEnabled():
            return
        if view.state.toggle_unicode_hex():
            view._state_changed()

    def _confirm_close(self, view: UNITITextView) -> bool:
        if not view.document.modified:
            return True
        untitled = self._is_untitled_view(view)
        result = QMessageBox.warning(
            self,
            "Unsaved UNITI Document",
            f"Save changes to {view.document.path.name}?",
            QMessageBox.StandardButton.Save
            | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if result == QMessageBox.StandardButton.Cancel:
            return False
        if result == QMessageBox.StandardButton.Save:
            if untitled:
                self._select_view(view)
                if self.save_current_as() is None:
                    return False
            else:
                try:
                    view.document.save()
                except Exception as exc:
                    self._show_save_error(exc)
                    return False
        return True

    def _close_tab(self, index: int, *, force: bool = False) -> bool:
        widget = self._tabs.widget(index)
        if widget is self._find_replace.content:
            self._find_replace.close_attached_tab()
            return True
        if not isinstance(widget, UNITITextView):
            return True
        if self._service is not None:
            return self._close_service_view(widget, force=force)
        self._tabs.setCurrentIndex(index)
        if not force and not widget.isEnabled():
            QMessageBox.information(
                self,
                "UNITI Operation in Progress",
                "Cancel the active Find/Replace operation before closing this document.",
            )
            return False
        if not force and not self._confirm_close(widget):
            return False
        self._cancel_navigation(widget)
        self._cancel_eol_analysis(widget)
        self._dismiss_eol_dialog(widget)
        self._eol_reports.pop(id(widget), None)
        if self._recovery_manager is not None:
            self._recovery_manager.detach(widget.document, clean=True)
        widget.document.close()
        self._tabs.removeTab(index)
        widget.dispose()
        widget.deleteLater()
        return True

    def _close_service_view(
        self,
        view: UNITITextView,
        *,
        force: bool = False,
    ) -> bool:
        entry = self._service.documents.entry_for_view(view.view_id)
        if entry is None:
            return False
        if not force and not view.isEnabled():
            QMessageBox.information(
                self,
                "UNITI Operation in Progress",
                "Cancel the active Find/Replace operation before closing this document.",
            )
            return False
        final_view = len(entry.view_ids) == 1
        if final_view and not force and not self._confirm_close(view):
            return False
        discarded = final_view and entry.document.modified
        self._cancel_navigation(view)
        self._cancel_eol_analysis(view)
        self._dismiss_eol_dialog(view)
        self._eol_reports.pop(id(view), None)
        leaf = self._panes.leaf_for_view(view.view_id)
        if leaf is None:
            return False
        leaf.take_view(view.view_id)
        self._service.documents.release_view(view.view_id)
        view.dispose()
        view.deleteLater()
        if leaf.count() == 0 and self._panes.leaf_count > 1:
            self._panes.close_leaf(leaf.pane_id)
        if final_view:
            if (
                self._recovery_manager is not None
                and not getattr(self, "_service_close_requested", False)
            ):
                self._recovery_manager.detach(entry.document, clean=True)
            if discarded:
                self._service.documents.retire(entry.document_id)
            if not self._service.is_quitting:
                if discarded:
                    self._service.record_dogfood(
                        Operation.DISCARD,
                        Outcome.DISCARDED,
                    )
                self._service.record_dogfood(
                    Operation.DOCUMENT_CLOSE,
                    Outcome.SUCCESS,
                )
        return True

    def _close_view_id(self, view_id: str, *, force: bool = False) -> bool:
        if view_id == FIND_REPLACE_VIEW_ID:
            self._find_replace.close_attached_tab()
            return True
        view = self.view_for_id(view_id)
        return view is None or self._close_service_view(view, force=force)

    def close_current(self) -> bool:
        index = self._tabs.currentIndex()
        if index < 0:
            return True
        return self._close_tab(index)

    def close_all_documents(self, *, force: bool = False) -> bool:
        if self._service is not None:
            for view_id in reversed(self.view_ids):
                if not self._close_view_id(view_id, force=force):
                    return False
            return True
        while self._tabs.count():
            before = self._tabs.count()
            if not self._close_tab(before - 1, force=force):
                return False
            if self._tabs.count() >= before:
                raise RuntimeError(
                    "close_all_documents made no progress on a tab it could not close"
                )
        return True

    def show_find(self) -> None:
        if self._service is not None:
            self._service.focus_find()
        else:
            self._find_replace.focus_find()

    def show_replace(self) -> None:
        if self._service is not None:
            self._service.focus_replace()
        else:
            self._find_replace.focus_replace()

    def toggle_find_replace_attachment(self) -> None:
        if self._service is not None:
            self._service.toggle_find_replace_attachment()
        elif self._find_replace.placement == "attached":
            self._find_replace.detach()
        else:
            self._find_replace.attach_to(self)

    def toggle_find_replace_visibility(self) -> None:
        if self._service is not None:
            self._service.toggle_find_replace_visibility()
            return
        panel = self._find_replace
        if panel.is_visible():
            if panel.placement == "attached":
                panel.close_attached_tab()
            else:
                panel.reject()
        else:
            if panel.placement == "attached":
                # Standalone mode has no service-level `_sync_find_replace_host`
                # to re-insert a closed attached tab before `focus_find`'s
                # `_reveal()` looks for it; do that step directly here.
                panel.attach_to(self)
            self.show_find()

    def host_find_replace(self, panel: FindReplaceWindow) -> None:
        if not isinstance(panel, FindReplaceWindow):
            raise TypeError("panel must be a FindReplaceWindow")
        panel.attach_to(self)

    def release_find_replace(self, panel: FindReplaceWindow) -> None:
        if not isinstance(panel, FindReplaceWindow):
            raise TypeError("panel must be a FindReplaceWindow")
        panel.release_from(self)

    def closeEvent(self, event: QCloseEvent) -> None:
        editor = getattr(QApplication.instance(), '_uniti_theme_editor', None)
        if editor is not None and editor.owner is self:
            editor.reject()
        if self._service is not None:
            force = bool(getattr(self, "_service_close_requested", False))
            if force:
                accepted = self.close_all_documents(force=True)
            else:
                accepted = self._close_service_window_views()
            if not accepted:
                event.ignore()
                return
            if (
                not force
                and not self._service.is_quitting
                and self._service.window_count == 1
            ):
                # Keep a visible way to open files and Quit while the service
                # is alive; only explicit Quit tears down the last window.
                event.ignore()
                self._service.set_active_view(self.window_id, None)
                self.show()
                try:
                    self._service.schedule_publication(clean_shutdown=False)
                except RuntimeError:
                    pass
                return
            self._navigation_timer.stop()
            self._resource_timer.stop()
            if self._resource_probe_future is not None:
                self._resource_probe_future.cancel()
                self._resource_probe_future = None
            self._file_operations.shutdown()
            self._detach_global_panel_bindings()
            if self.window_id in dict(self._service.windows.items):
                self._service.unregister_window(self.window_id)
                if not self._service.is_quitting:
                    try:
                        self._service.schedule_publication(clean_shutdown=False)
                    except RuntimeError:
                        pass
            event.accept()
            return
        if self.close_all_documents(force=False):
            self._navigation_timer.stop()
            self._resource_timer.stop()
            if self._resource_probe_future is not None:
                self._resource_probe_future.cancel()
                self._resource_probe_future = None
            self._file_operations.shutdown()
            self._find_replace.shutdown()
            if self._recovery_manager is not None:
                self._recovery_manager.shutdown()
            if self._owns_resources:
                self._resources.shutdown(wait=False)
            event.accept()
        else:
            event.ignore()

    def _close_service_window_views(self) -> bool:
        if any(self.view_for_id(view_id) is None for view_id in self.view_ids):
            QMessageBox.information(
                self,
                "UNITI Session Restore Pending",
                "Finish or resolve pending session restoration before closing this window.",
            )
            return False
        views = self.views
        if any(not view.isEnabled() for view in views):
            QMessageBox.information(
                self,
                "UNITI Operation in Progress",
                "Cancel active operations before closing this window.",
            )
            return False
        local_view_ids = set(self.view_ids)
        decisions: dict[str, QMessageBox.StandardButton] = {}
        for view in views:
            entry = self._service.documents.entry_for_view(view.view_id)
            if (
                entry is None
                or entry.document_id in decisions
                or not entry.document.modified
                or not set(entry.view_ids).issubset(local_view_ids)
            ):
                continue
            result = QMessageBox.warning(
                self,
                "Unsaved UNITI Document",
                f"Save changes to {entry.document.path.name}?",
                QMessageBox.StandardButton.Save
                | QMessageBox.StandardButton.Discard
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if result == QMessageBox.StandardButton.Cancel:
                return False
            decisions[entry.document_id] = result
        for document_id, decision in decisions.items():
            if decision != QMessageBox.StandardButton.Save:
                continue
            try:
                self._service.documents.get(document_id).document.save()
            except Exception as exc:
                self._show_save_error(exc)
                return False
        return self.close_all_documents(force=True)

    def close_for_service(self) -> None:
        self._service_close_requested = True
        self.close()

    def _detach_global_panel_bindings(self) -> None:
        if self._service is None:
            return
        for field in (
            self._find_replace.find_input,
            self._find_replace.replace_input,
        ):
            field.removeEventFilter(self)
            field.viewport().removeEventFilter(self)
        for shortcut in self._find_replace_shortcuts.values():
            shortcut.setEnabled(False)
            shortcut.deleteLater()
        self._find_replace_shortcuts.clear()
        for definition in self._command_registry.definitions():
            if definition.scope == CommandScope.FIND_REPLACE:
                action = self._command_actions.get(definition.command_id)
                if action is not None:
                    self._find_replace.removeAction(action)

    def set_global_panel_bindings_enabled(self, enabled: bool) -> None:
        if self._service is None:
            return
        for definition in self._command_registry.definitions():
            if definition.scope == CommandScope.FIND_REPLACE:
                action = self._command_actions.get(definition.command_id)
                if action is not None:
                    action.setEnabled(bool(enabled))
        for shortcut in self._find_replace_shortcuts.values():
            shortcut.setEnabled(bool(enabled))

    def set_service_window_active(self, enabled: bool) -> None:
        current = self.current_view if enabled else None
        for view in self.views:
            view.document.set_resource_active(view is current)
