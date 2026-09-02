"""Minimal native UNITI desktop shell."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Future
from dataclasses import dataclass, replace as dataclass_replace
import os
from pathlib import Path
import sys
import weakref

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from uniti.app.diagnostics import diagnostics_snapshot
from uniti.app.commands import (
    CommandCategory,
    CommandDefinition,
    CommandRegistry,
    CommandScope,
)
from uniti.app.editor_state import EditorState
from uniti.app.recovery_manager import RecoveryManager
from uniti.app.settings import Settings, SettingsStore
from uniti.core.byte_source import ByteSource
from uniti.core.document import Document
from uniti.core.eol import EOLReport, analyze_eol
from uniti.core.file_identity import ExternalFileChangedError, FileIdentity
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
from uniti.core.text_inspection import (
    TextFileInspection,
    inspect_source,
    preview_source,
)
from uniti.resources import (
    MemorySnapshot,
    ResourceManager,
    TaskAdmissionError,
    TaskContext,
    TaskHandle,
    TaskKind,
    TaskSpec,
    WorkPriority,
    probe_memory,
)
from uniti.ui.character_inspector import CharacterInspectorDialog
from uniti.ui.diagnostics_dialog import DiagnosticsDialog
from uniti.ui.file_format_dialogs import (
    LineEndingReportDialog,
    OpenFormatDialog,
    SaveAsFormatDialog,
)
from uniti.ui.file_operations import FileOperationController, FileOperationHandle
from uniti.ui.find_replace import FindReplaceWindow
from uniti.ui.hotkeys import HotkeysPopup
from uniti.ui.status_bar import UNITIStatusBar
from uniti.ui.text_view import UNITITextView


def _standard_shortcut(key: QKeySequence.StandardKey, fallback: str = "") -> str:
    shortcut = QKeySequence(key).toString(QKeySequence.SequenceFormat.PortableText)
    return shortcut or fallback


def _command_definitions() -> tuple[CommandDefinition, ...]:
    # Qt's portable "Ctrl" token maps to the native primary modifier on each
    # platform (Command on macOS, Control on Windows/Linux).
    primary = "Ctrl"
    return (
        CommandDefinition("file.open", "Open…", CommandCategory.FILE, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Open)),
        CommandDefinition("file.save", "Save", CommandCategory.FILE, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Save)),
        CommandDefinition("file.save_as", "Save As…", CommandCategory.FILE, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.SaveAs)),
        CommandDefinition("file.reload", "Reload/Revert from Disk", CommandCategory.FILE, CommandScope.WINDOW, f"{primary}+Shift+R"),
        CommandDefinition("file.close", "Close", CommandCategory.FILE, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Close)),
        CommandDefinition("file.quit", "Quit", CommandCategory.FILE, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Quit, f"{primary}+Q")),
        CommandDefinition("editing.undo", "Undo", CommandCategory.EDITING, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Undo)),
        CommandDefinition("editing.redo", "Redo", CommandCategory.EDITING, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Redo)),
        CommandDefinition("editing.cut", "Cut", CommandCategory.EDITING, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Cut)),
        CommandDefinition("editing.copy", "Copy", CommandCategory.EDITING, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Copy)),
        CommandDefinition("editing.paste", "Paste", CommandCategory.EDITING, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Paste)),
        CommandDefinition("editing.select_all", "Select All", CommandCategory.EDITING, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.SelectAll)),
        CommandDefinition("navigation.go_to_line", "Go to Line…", CommandCategory.NAVIGATION, CommandScope.EDITOR, f"{primary}+L"),
        CommandDefinition("navigation.page_up", "Page Up", CommandCategory.NAVIGATION, CommandScope.EDITOR, "PageUp"),
        CommandDefinition("navigation.page_down", "Page Down", CommandCategory.NAVIGATION, CommandScope.EDITOR, "PageDown"),
        CommandDefinition("navigation.document_start", "Document Start", CommandCategory.NAVIGATION, CommandScope.EDITOR, f"{primary}+Home"),
        CommandDefinition("navigation.document_end", "Document End", CommandCategory.NAVIGATION, CommandScope.EDITOR, f"{primary}+End"),
        CommandDefinition("navigation.word_left", "Word Left", CommandCategory.NAVIGATION, CommandScope.EDITOR, f"{primary}+Left"),
        CommandDefinition("navigation.word_right", "Word Right", CommandCategory.NAVIGATION, CommandScope.EDITOR, f"{primary}+Right"),
        CommandDefinition("find.open", "Find", CommandCategory.FIND_REPLACE, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Find)),
        CommandDefinition("find.replace", "Replace", CommandCategory.FIND_REPLACE, CommandScope.WINDOW, _standard_shortcut(QKeySequence.StandardKey.Replace)),
        CommandDefinition("find.next", "Find Next", CommandCategory.FIND_REPLACE, CommandScope.WINDOW, "F3"),
        CommandDefinition("find.previous", "Find Previous", CommandCategory.FIND_REPLACE, CommandScope.WINDOW, "Shift+F3"),
        CommandDefinition("editor.zoom_in", "Zoom In", CommandCategory.EDITOR_VIEW, CommandScope.EDITOR, _standard_shortcut(QKeySequence.StandardKey.ZoomIn)),
        CommandDefinition("editor.zoom_out", "Zoom Out", CommandCategory.EDITOR_VIEW, CommandScope.EDITOR, _standard_shortcut(QKeySequence.StandardKey.ZoomOut)),
        CommandDefinition("editor.zoom_reset", "Reset Zoom", CommandCategory.EDITOR_VIEW, CommandScope.EDITOR, f"{primary}+0"),
        CommandDefinition("editor.wrap", "Soft Line Wrap", CommandCategory.EDITOR_VIEW, CommandScope.EDITOR, f"{primary}+Alt+W"),
        CommandDefinition("find.zoom_in", "Zoom In", CommandCategory.FIND_REPLACE_VIEW, CommandScope.FIND_REPLACE, _standard_shortcut(QKeySequence.StandardKey.ZoomIn)),
        CommandDefinition("find.zoom_out", "Zoom Out", CommandCategory.FIND_REPLACE_VIEW, CommandScope.FIND_REPLACE, _standard_shortcut(QKeySequence.StandardKey.ZoomOut)),
        CommandDefinition("find.zoom_reset", "Reset Zoom", CommandCategory.FIND_REPLACE_VIEW, CommandScope.FIND_REPLACE, f"{primary}+0"),
        CommandDefinition("find.report_cycle", "Cycle Report Position", CommandCategory.FIND_REPLACE_VIEW, CommandScope.FIND_REPLACE, f"{primary}+Alt+R"),
    )


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


class UNITIMainWindow(QMainWindow):
    def __init__(
        self,
        parent=None,
        *,
        recovery_manager: RecoveryManager | None = None,
        settings_store: SettingsStore | None = None,
        resource_manager: ResourceManager | None = None,
        startup_snapshot: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(parent)
        self._recovery_manager = recovery_manager
        self._settings_store = settings_store
        self._settings = settings_store.load() if settings_store is not None else Settings()
        self._command_registry = CommandRegistry(
            _command_definitions(),
            overrides=self._settings.shortcut_overrides,
        )
        self._command_actions: dict[str, QAction] = {}
        self._find_replace_shortcuts: dict[str, QShortcut] = {}
        self._hotkeys_popup: HotkeysPopup | None = None
        self._command_registry.add_listener(self._on_command_binding_changed)
        self._owns_resources = resource_manager is None
        self._resources = resource_manager or ResourceManager()
        self._file_operations = FileOperationController(self._resources, self)
        self._file_operations.operationFinished.connect(
            self._finish_file_operation,
            Qt.ConnectionType.QueuedConnection,
        )
        self._save_jobs: dict[str, _SaveJob] = {}
        self._startup_snapshot = dict(startup_snapshot or {})
        self.setWindowTitle("UNITI")
        self.resize(1100, 760)
        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_current_changed)
        central = QWidget(self)
        central_layout = QVBoxLayout(central)
        central_layout.setContentsMargins(0, 0, 0, 0)
        central_layout.setSpacing(0)
        central_layout.addWidget(self._tabs, 1)
        self._find_replace = FindReplaceWindow(
            lambda: self.current_view, self, resource_manager=self._resources
        )
        for field in (
            self._find_replace.find_input,
            self._find_replace.replace_input,
        ):
            field.installEventFilter(self)
            field.viewport().installEventFilter(self)
        self._find_replace.hide()
        self._find_replace.set_zoom_percent(
            self._settings.find_replace_zoom_percent
        )
        self._find_replace.set_report_location(
            self._settings.find_replace_report_location
        )
        if self._settings.find_replace_geometry is not None:
            self._find_replace.setGeometry(*self._settings.find_replace_geometry)
        self._find_replace.zoomChanged.connect(self._on_find_replace_zoom_changed)
        self._find_replace.reportLocationChanged.connect(
            self._on_find_replace_report_location_changed
        )
        self._find_replace.geometryChanged.connect(
            self._on_find_replace_geometry_changed
        )
        self.setCentralWidget(central)
        self._status = UNITIStatusBar(self)
        self.setStatusBar(self._status)

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
        self._resource_probe_future: Future[MemorySnapshot] | None = None
        self._resource_timer.start()
        self._build_menus()

    def _observe_resource_pressure(self) -> None:
        future = self._resource_probe_future
        if future is None:
            self._resource_probe_future = self._resources.workers.submit(
                WorkPriority.PREFETCH,
                probe_memory,
            )
            return
        if not future.done():
            return
        self._resource_probe_future = None
        try:
            self._resources.observe_memory(future.result())
        except Exception:
            # Memory telemetry must never interfere with editing.
            return

    def _save_settings(self) -> None:
        if self._settings_store is not None:
            try:
                self._settings_store.save(self._settings)
            except OSError:
                pass

    def _on_find_replace_zoom_changed(self, percent: int) -> None:
        self._settings = dataclass_replace(
            self._settings,
            find_replace_zoom_percent=percent,
        )
        self._save_settings()

    def _on_find_replace_report_location_changed(self, location: str) -> None:
        self._settings = dataclass_replace(
            self._settings,
            find_replace_report_location=location,
        )
        self._save_settings()

    def _on_find_replace_geometry_changed(
        self,
        geometry: tuple[int, int, int, int],
    ) -> None:
        self._settings = dataclass_replace(
            self._settings,
            find_replace_geometry=geometry,
        )
        self._save_settings()

    def _on_command_binding_changed(self, command_id: str, shortcut: str) -> None:
        action = self._command_actions.get(command_id)
        if action is not None:
            action.setShortcut(QKeySequence(shortcut))
        find_shortcut = self._find_replace_shortcuts.get(command_id)
        if find_shortcut is not None:
            find_shortcut.setKey(QKeySequence(shortcut))
        self._settings = dataclass_replace(
            self._settings,
            shortcut_overrides=self._command_registry.overrides,
        )
        self._save_settings()

    def eventFilter(self, watched, event) -> bool:
        if (
            event.type() == QEvent.Type.KeyPress
            and self._find_replace.focused_input() is not None
        ):
            pressed = QKeySequence(event.keyCombination())
            for definition in self._command_registry.definitions(
                category=CommandCategory.EDITING
            ):
                shortcut = self._command_registry.current(definition.command_id)
                if shortcut and pressed.matches(QKeySequence(shortcut)) == (
                    QKeySequence.SequenceMatch.ExactMatch
                ):
                    self._command_actions[definition.command_id].trigger()
                    event.accept()
                    return True
        return super().eventFilter(watched, event)

    @property
    def current_view(self) -> UNITITextView | None:
        widget = self._tabs.currentWidget()
        return widget if isinstance(widget, UNITITextView) else None

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
        action.setShortcut(QKeySequence(self._command_registry.current(command_id)))
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
        file_menu.addAction(self._command_action("file.open", self.open_dialog))
        file_menu.addAction(
            self._command_action("file.save", self.start_save_current)
        )
        file_menu.addAction(
            self._command_action("file.save_as", self.start_save_current_as)
        )
        file_menu.addAction(self._command_action("file.reload", self.reload_current))
        file_menu.addSeparator()
        file_menu.addAction(self._command_action("file.close", self.close_current))
        file_menu.addAction(self._command_action("file.quit", self.close))

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

        edit_menu.addSeparator()
        navigation_menu = edit_menu.addMenu("&Navigation")
        navigation_menu.addAction(
            self._command_action("navigation.go_to_line", self.go_to_line_dialog)
        )
        navigation_menu.addAction(
            self._command_action("navigation.page_up", lambda: self._move_page(-1))
        )
        navigation_menu.addAction(
            self._command_action("navigation.page_down", lambda: self._move_page(1))
        )
        navigation_menu.addAction(
            self._command_action(
                "navigation.document_start",
                lambda: self._move_editor("move_document_start"),
            )
        )
        navigation_menu.addAction(
            self._command_action(
                "navigation.document_end",
                lambda: self._move_editor("move_document_end"),
            )
        )
        navigation_menu.addAction(
            self._command_action(
                "navigation.word_left",
                lambda: self._move_editor("move_word_left"),
            )
        )
        navigation_menu.addAction(
            self._command_action(
                "navigation.word_right",
                lambda: self._move_editor("move_word_right"),
            )
        )

        format_menu = self.menuBar().addMenu("F&ormat")
        encoding_menu = format_menu.addMenu("&Encoding")
        reinterpret_menu = encoding_menu.addMenu("Reinterpret As")
        convert_menu = encoding_menu.addMenu("Convert on Save")
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

        eol_menu = format_menu.addMenu("&Line Endings")
        eol_menu.addAction(
            self._action("Keep Source", None, lambda: self.set_output_eol(None))
        )
        for eol in ("LF", "CRLF", "CR"):
            eol_menu.addAction(
                self._action(eol, None, lambda eol=eol: self.set_output_eol(eol))
            )

        view_menu = self.menuBar().addMenu("&View")
        editor_view_menu = view_menu.addMenu("&Editor View")
        editor_view_menu.addAction(
            self._command_action("editor.zoom_in", self.zoom_in_editor)
        )
        editor_view_menu.addAction(
            self._command_action("editor.zoom_out", self.zoom_out_editor)
        )
        editor_view_menu.addAction(
            self._command_action("editor.zoom_reset", self.reset_editor_zoom)
        )
        self._wrap_action = self._command_action(
            "editor.wrap",
            lambda: self.set_editor_wrap(self._wrap_action.isChecked()),
            checkable=True,
        )
        self._wrap_action.setChecked(self._settings.soft_wrap)
        editor_view_menu.addAction(self._wrap_action)

        find_view_menu = view_menu.addMenu("F/R &View")
        find_view_menu.addAction(
            self._command_action("find.zoom_in", self._find_replace.zoom_in)
        )
        find_view_menu.addAction(
            self._command_action("find.zoom_out", self._find_replace.zoom_out)
        )
        find_view_menu.addAction(
            self._command_action("find.zoom_reset", self._find_replace.reset_zoom)
        )
        find_view_menu.addSeparator()
        find_view_menu.addAction(
            self._command_action(
                "find.report_cycle",
                self._find_replace.cycle_report_location,
            )
        )

        find_menu = self.menuBar().addMenu("&Find")
        find_menu.addAction(self._command_action("find.open", self.show_find))
        find_menu.addAction(self._command_action("find.replace", self.show_replace))
        find_menu.addAction(
            self._command_action("find.next", self._find_replace.next_match)
        )
        find_menu.addAction(
            self._command_action("find.previous", self._find_replace.previous_match)
        )

        tools_menu = self.menuBar().addMenu("&Tools")
        tools_menu.addAction(
            self._action(
                "Character Inspector…",
                None,
                self.show_character_inspector,
            )
        )
        tools_menu.addAction(
            self._action(
                "Diagnostics…",
                None,
                self.show_diagnostics,
            )
        )

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

    def _connect_view(self, view: UNITITextView) -> None:
        view.set_progressive_navigation(True)
        view.stateChanged.connect(lambda view=view: self._on_view_state_changed(view))
        view.cursorPositionChanged.connect(self._status.update_cursor)
        view.zoomChanged.connect(
            lambda percent, view=view: self._on_view_zoom_changed(view, percent)
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
        self._hotkeys_popup.show_below(self.menuBar())
        return self._hotkeys_popup

    def _add_document(
        self,
        document: Document,
        *,
        attach_recovery: bool = True,
        initial_eol_report: EOLReport | None = None,
        initial_eol_complete: bool = True,
    ) -> UNITITextView:
        if attach_recovery and self._recovery_manager is not None:
            self._recovery_manager.attach(document)
        state = EditorState(document)
        view = UNITITextView(state, self._tabs)
        view.set_zoom_percent(self._settings.editor_zoom_percent)
        view.set_soft_wrap(self._settings.soft_wrap)
        self._connect_view(view)
        index = self._tabs.addTab(view, self._tab_label(view))
        self._tabs.setCurrentIndex(index)
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
        view.setFocus()
        return view

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
        decision = self._inspect_open_path(path, profile=profile)
        if decision is None:
            return None
        selected, inspection = decision
        document = Document.open(
            path,
            profile=selected,
            resource_manager=self._resources,
        )
        try:
            view = self._add_document(
                document,
                initial_eol_report=inspection.eol,
                initial_eol_complete=inspection.eol_complete,
            )
        except Exception:
            document.close()
            raise
        self._remember_directory(path)
        return view

    def recover_startup_sessions(self) -> int:
        if self._recovery_manager is None:
            return 0
        recovered = 0
        for candidate in self._recovery_manager.discover():
            choice = QMessageBox.question(
                self,
                "Recover UNITI Document",
                f"Recover unsaved changes to {candidate.session.source_path}?",
                QMessageBox.StandardButton.Yes
                | QMessageBox.StandardButton.No
                | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            if choice == QMessageBox.StandardButton.Cancel:
                break
            if choice == QMessageBox.StandardButton.No:
                self._recovery_manager.discard(candidate)
                continue
            try:
                document = self._recovery_manager.recover(candidate)
                self._add_document(document, attach_recovery=False)
            except Exception as exc:
                QMessageBox.warning(
                    self,
                    "Recovery Failed",
                    f"Could not recover {candidate.session.source_path}:\n\n{exc}",
                )
                continue
            recovered += 1
        return recovered

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

    def set_editor_wrap(self, enabled: bool) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.set_soft_wrap(enabled)

    def _on_view_state_changed(self, view: UNITITextView) -> None:
        if any(
            job.view_ref() is view and job.revision != view.document.revision
            for job in self._navigation_jobs.values()
        ):
            self._cancel_navigation(view)
        index = self._tabs.indexOf(view)
        if index >= 0:
            self._tabs.setTabText(index, self._tab_label(view))
        if view is self.current_view:
            self._set_status_document(view)

    def _on_current_changed(self, _index: int) -> None:
        self._find_replace.document_changed()
        view = self.current_view
        for index in range(self._tabs.count()):
            widget = self._tabs.widget(index)
            if isinstance(widget, UNITITextView):
                widget.document.set_resource_active(widget is view)
        if view is None:
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
            if self._tabs.indexOf(view) < 0:
                return
            current = view.document.output_format
            view.document.set_output_format(OutputFormat(current.encoding, policy))
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
                or self._tabs.indexOf(view) < 0
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
        view.document.set_output_eol(eol)
        self._on_view_state_changed(view)

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
                or self._tabs.indexOf(view) < 0
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
    ) -> None:
        old_document = view.document
        self._cancel_navigation(view)
        self._cancel_eol_analysis(view)
        self._dismiss_eol_dialog(view)
        if self._recovery_manager is not None:
            self._recovery_manager.attach(replacement)
            self._recovery_manager.detach(old_document, clean=True)
        view.state = EditorState(replacement)
        self._eol_reports.pop(id(view), None)
        if initial_eol_report is not None:
            replacement.set_source_eol_report(initial_eol_report)
            if initial_eol_complete:
                self._eol_reports[id(view)] = initial_eol_report
        old_document.close()
        view.set_match_index(None)
        view._max_seen_line_width = 0
        view._wrap_index = None
        view._wrap_signature = None
        view._refresh_scrollbars(advance_index=False)
        self._find_replace.document_changed()
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
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        selection = view.state.selection
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
            QMessageBox.information(self, "Character Inspector", "No character at cursor.")
            return
        dialog = CharacterInspectorDialog(
            character[0],
            output_encoding=view.document.output_encoding,
            invalid_bytes=invalid_bytes,
            parent=self,
        )
        dialog.exec()

    def show_diagnostics(self) -> None:
        documents = []
        for index in range(self._tabs.count()):
            widget = self._tabs.widget(index)
            if isinstance(widget, UNITITextView):
                documents.append(widget.document)
        dialog = DiagnosticsDialog(
            diagnostics_snapshot(documents, startup_snapshot=self._startup_snapshot), self
        )
        dialog.exec()

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

    @staticmethod
    def _same_resolved_path(left: str | Path, right: str | Path) -> bool:
        left_path = Path(left).expanduser()
        right_path = Path(right).expanduser()
        if left_path.resolve(strict=False) == right_path.resolve(strict=False):
            return True
        try:
            return os.path.samefile(left_path, right_path)
        except OSError:
            return False

    def _view_for_path(
        self,
        path: str | Path,
        *,
        excluding: UNITITextView | None = None,
    ) -> UNITITextView | None:
        for index in range(self._tabs.count()):
            candidate = self._tabs.widget(index)
            if not isinstance(candidate, UNITITextView) or candidate is excluding:
                continue
            if self._same_resolved_path(candidate.document.path, path):
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
        self._dismiss_eol_dialog(view)
        if inspection.eol_complete:
            self._eol_reports[id(view)] = inspection.eol
        else:
            self._eol_reports.pop(id(view), None)
        if inspection.eol_complete and inspection.eol.kind == "MIXED":
            self._show_mixed_eol_report(view, inspection.eol)
        self._on_view_state_changed(view)
        if not inspection.eol_complete:
            self._schedule_eol_analysis(view)

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
        try:
            self._replace_view_document(
                existing_view,
                document,
                initial_eol_report=inspection.eol,
                initial_eol_complete=inspection.eol_complete,
            )
        except Exception:
            document.close()
            raise
        self._tabs.setCurrentWidget(existing_view)
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
                initial_directory=view.document.path.parent,
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

        destination = destination.resolve(strict=False)
        if self._same_resolved_path(destination, view.document.path):
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
                return
            if view is None or view.document is not job.document:
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
                self._open_verified_export(
                    result,
                    job.output_format,
                    existing_view=target_view,
                )
                self._remember_directory(result)
                self._on_view_state_changed(view)
                self._on_current_changed(self._tabs.currentIndex())
            self.statusBar().showMessage(f"Saved {result}", 3000)
        except Exception as exc:
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
                initial_directory=view.document.path.parent,
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

        destination = destination.resolve(strict=False)
        if self._same_resolved_path(destination, view.document.path):
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

    def _confirm_close(self, view: UNITITextView) -> bool:
        if not view.document.modified:
            return True
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
            try:
                view.document.save()
            except Exception as exc:
                self._show_save_error(exc)
                return False
        return True

    def _close_tab(self, index: int, *, force: bool = False) -> bool:
        widget = self._tabs.widget(index)
        if not isinstance(widget, UNITITextView):
            return True
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
        widget.deleteLater()
        return True

    def close_current(self) -> bool:
        index = self._tabs.currentIndex()
        if index < 0:
            return True
        return self._close_tab(index)

    def close_all_documents(self, *, force: bool = False) -> bool:
        while self._tabs.count():
            if not self._close_tab(self._tabs.count() - 1, force=force):
                return False
        return True

    def show_find(self) -> None:
        self._find_replace.focus_find()

    def show_replace(self) -> None:
        self._find_replace.focus_replace()

    def closeEvent(self, event: QCloseEvent) -> None:
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
