"""Minimal native UNITI desktop shell."""

from __future__ import annotations

from collections.abc import Mapping
from concurrent.futures import Future
from dataclasses import replace as dataclass_replace
from pathlib import Path
import weakref

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from uniti.app.diagnostics import diagnostics_snapshot
from uniti.app.editor_state import EditorState
from uniti.app.recovery_manager import RecoveryManager
from uniti.app.settings import Settings, SettingsStore
from uniti.core.byte_source import ByteSource
from uniti.core.document import Document
from uniti.core.eol import EOLReport, analyze_eol
from uniti.core.file_identity import ExternalFileChangedError
from uniti.resources import ResourceManager, WorkPriority
from uniti.ui.character_inspector import CharacterInspectorDialog
from uniti.ui.diagnostics_dialog import DiagnosticsDialog
from uniti.ui.find_replace import FindReplacePanel
from uniti.ui.status_bar import UNITIStatusBar
from uniti.ui.text_view import UNITITextView


_ENCODING_CHOICES = (
    ("UTF-8", "utf-8"),
    ("UTF-16 LE", "utf-16-le"),
    ("UTF-16 BE", "utf-16-be"),
    ("UTF-32 LE", "utf-32-le"),
    ("UTF-32 BE", "utf-32-be"),
    ("Windows-1252", "windows-1252"),
)


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
        self._owns_resources = resource_manager is None
        self._resources = resource_manager or ResourceManager()
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
        self._find_replace = FindReplacePanel(
            lambda: self.current_view, central, resource_manager=self._resources
        )
        self._find_replace.streamReplaceCommitted.connect(
            self._reload_after_stream_replace
        )
        self._find_replace.hide()
        central_layout.addWidget(self._find_replace, 0)
        self.setCentralWidget(central)
        self._status = UNITIStatusBar(self)
        self.setStatusBar(self._status)

        self._eol_pool = self._resources.workers
        self._eol_jobs: dict[Future, weakref.ReferenceType] = {}
        self._eol_reports: dict[int, EOLReport] = {}
        self._eol_timer = QTimer(self)
        self._eol_timer.setInterval(80)
        self._eol_timer.timeout.connect(self._poll_eol_jobs)
        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(1000)
        self._resource_timer.timeout.connect(self._observe_resource_pressure)
        self._resource_timer.start()
        self._build_menus()

    def _observe_resource_pressure(self) -> None:
        try:
            self._resources.observe_memory()
        except Exception:
            # Memory telemetry must never interfere with editing.
            return

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

    def _build_menus(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(
            self._action("Open…", QKeySequence.StandardKey.Open, self.open_dialog)
        )
        file_menu.addAction(
            self._action("Save", QKeySequence.StandardKey.Save, self.save_current)
        )
        file_menu.addAction(
            self._action("Save As…", QKeySequence.StandardKey.SaveAs, self.save_current_as)
        )
        file_menu.addAction(
            self._action(
                "Reload/Revert from Disk",
                QKeySequence("Ctrl+Shift+R"),
                self.reload_current,
            )
        )
        file_menu.addSeparator()
        file_menu.addAction(
            self._action("Close", QKeySequence.StandardKey.Close, self.close_current)
        )
        file_menu.addAction(
            self._action("Quit", QKeySequence.StandardKey.Quit, self.close)
        )

        edit_menu = self.menuBar().addMenu("&Edit")
        edit_menu.addAction(
            self._action("Undo", QKeySequence.StandardKey.Undo, self.undo_current)
        )
        edit_menu.addAction(
            self._action("Redo", QKeySequence.StandardKey.Redo, self.redo_current)
        )
        edit_menu.addSeparator()
        edit_menu.addAction(
            self._action("Cut", QKeySequence.StandardKey.Cut, self.cut_current)
        )
        edit_menu.addAction(
            self._action("Copy", QKeySequence.StandardKey.Copy, self.copy_current)
        )
        edit_menu.addAction(
            self._action("Paste", QKeySequence.StandardKey.Paste, self.paste_current)
        )
        edit_menu.addSeparator()
        edit_menu.addAction(
            self._action("Select All", QKeySequence.StandardKey.SelectAll, self.select_all)
        )

        navigation_menu = self.menuBar().addMenu("&Navigation")
        navigation_menu.addAction(
            self._action("Go to Line…", QKeySequence("Ctrl+L"), self.go_to_line_dialog)
        )

        search_menu = self.menuBar().addMenu("&Search")
        search_menu.addAction(
            self._action("Find", QKeySequence.StandardKey.Find, self.show_find)
        )
        search_menu.addAction(
            self._action("Replace", QKeySequence.StandardKey.Replace, self.show_replace)
        )
        search_menu.addAction(
            self._action("Find Next", QKeySequence("F3"), self._find_replace.next_match)
        )
        search_menu.addAction(
            self._action(
                "Find Previous",
                QKeySequence("Shift+F3"),
                self._find_replace.previous_match,
            )
        )

        view_menu = self.menuBar().addMenu("&View")
        view_menu.addAction(
            self._action("Zoom In", QKeySequence.StandardKey.ZoomIn, self.zoom_in_editor)
        )
        view_menu.addAction(
            self._action("Zoom Out", QKeySequence.StandardKey.ZoomOut, self.zoom_out_editor)
        )
        view_menu.addAction(
            self._action("Reset Zoom", QKeySequence("Ctrl+0"), self.reset_editor_zoom)
        )
        self._wrap_action = QAction("Soft Line Wrap", self)
        self._wrap_action.setCheckable(True)
        self._wrap_action.setChecked(self._settings.soft_wrap)
        self._wrap_action.toggled.connect(self.set_editor_wrap)
        view_menu.addAction(self._wrap_action)

        encoding_menu = self.menuBar().addMenu("&Encoding")
        reinterpret_menu = encoding_menu.addMenu("Reinterpret As")
        convert_menu = encoding_menu.addMenu("Convert on Save")
        for label, codec in _ENCODING_CHOICES:
            reinterpret_menu.addAction(
                self._action(label, None, lambda codec=codec: self.reinterpret_current(codec))
            )
            convert_menu.addAction(
                self._action(label, None, lambda codec=codec: self.set_output_encoding(codec))
            )

        eol_menu = self.menuBar().addMenu("&EOL")
        eol_menu.addAction(
            self._action("Keep Source", None, lambda: self.set_output_eol(None))
        )
        for eol in ("LF", "CRLF", "CR"):
            eol_menu.addAction(
                self._action(eol, None, lambda eol=eol: self.set_output_eol(eol))
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

    def _remember_directory(self, path: str | Path) -> None:
        directory = str(Path(path).parent)
        self._settings = dataclass_replace(self._settings, last_directory=directory)
        if self._settings_store is not None:
            try:
                self._settings_store.save(self._settings)
            except OSError:
                pass

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
        view.stateChanged.connect(lambda view=view: self._on_view_state_changed(view))
        view.cursorPositionChanged.connect(self._status.update_cursor)
        view.zoomChanged.connect(
            lambda percent, view=view: self._on_view_zoom_changed(view, percent)
        )
        view.wrapChanged.connect(
            lambda enabled, view=view: self._on_view_wrap_changed(view, enabled)
        )

    def _add_document(
        self,
        document: Document,
        *,
        attach_recovery: bool = True,
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
        self._set_status_document(view)
        self._status.update_cursor(0, 0)
        self._schedule_eol_analysis(view)
        view.setFocus()
        return view

    def open_path(self, path: str | Path) -> UNITITextView:
        document = Document.open(path, resource_manager=self._resources)
        try:
            view = self._add_document(document)
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
        if self._settings_store is not None:
            try:
                self._settings_store.save(self._settings)
            except OSError:
                pass

    def _on_view_wrap_changed(self, view: UNITITextView, enabled: bool) -> None:
        if view is self.current_view:
            self._status.update_view(view.zoom_percent, soft_wrap=enabled)
            if self._wrap_action.isChecked() != enabled:
                self._wrap_action.setChecked(enabled)
        self._settings = dataclass_replace(self._settings, soft_wrap=enabled)
        if self._settings_store is not None:
            try:
                self._settings_store.save(self._settings)
            except OSError:
                pass

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
    def _analyze_path_eol(path: Path, encoding: str) -> EOLReport:
        with ByteSource.open(path) as source:
            return analyze_eol(source, encoding=encoding)

    def _schedule_eol_analysis(self, view: UNITITextView) -> None:
        source_path = view.document.source.path
        encoding = view.document.encoding_info.detected
        future = self._eol_pool.submit(
            WorkPriority.INDEX,
            self._analyze_path_eol,
            source_path,
            encoding,
        )
        self._eol_jobs[future] = weakref.ref(view)
        self._eol_timer.start()

    def _poll_eol_jobs(self) -> None:
        for future, view_ref in tuple(self._eol_jobs.items()):
            if not future.done():
                continue
            self._eol_jobs.pop(future, None)
            view = view_ref()
            if view is None:
                continue
            try:
                report = future.result()
            except Exception:
                continue
            self._eol_reports[id(view)] = report
            view.document.set_source_eol_report(report)
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

    def set_output_eol(self, eol) -> None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        view.document.set_output_eol(eol)
        self._on_view_state_changed(view)

    def reinterpret_current(self, encoding: str) -> None:
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

        index = self._tabs.currentIndex()
        path = view.document.path
        try:
            document = Document.open(
                path, encoding=encoding, resource_manager=self._resources
            )
        except Exception as exc:
            QMessageBox.critical(self, "Reinterpret Failed", str(exc))
            return

        if self._recovery_manager is not None:
            self._recovery_manager.attach(document)
        replacement = UNITITextView(EditorState(document), self._tabs)
        self._connect_view(replacement)
        self._tabs.removeTab(index)
        self._tabs.insertTab(index, replacement, self._tab_label(replacement))
        self._tabs.setCurrentIndex(index)
        self._eol_reports.pop(id(view), None)
        if self._recovery_manager is not None:
            self._recovery_manager.detach(view.document, clean=True)
        view.document.close()
        view.deleteLater()
        self._set_status_document(replacement)
        self._schedule_eol_analysis(replacement)
        replacement.setFocus()

    def _reload_after_stream_replace(self, view, path: str, count: int) -> None:
        index = self._tabs.indexOf(view)
        if index < 0 or view.document.path != Path(path):
            return
        old_document = view.document
        try:
            replacement = Document.open(path, resource_manager=self._resources)
        except Exception as exc:
            QMessageBox.critical(
                self,
                "Reload After Replace Failed",
                f"The streamed file was written but could not be reopened:\n\n{exc}",
            )
            return
        try:
            if self._recovery_manager is not None:
                self._recovery_manager.detach(old_document, clean=True)
                self._recovery_manager.attach(replacement)
            view.state = EditorState(replacement)
            view.state.cursor = 0
            view.state.anchor = 0
            self._eol_reports.pop(id(view), None)
            old_document.close()
            view.set_match_index(None)
            view._max_seen_line_width = 0
            view._refresh_scrollbars(advance_index=False)
            view._state_changed()
            self._schedule_eol_analysis(view)
            self.statusBar().showMessage(
                f"Streamed Replace All committed {count:,} replacements",
                5000,
            )
        except Exception:
            replacement.close()
            raise

    def go_to_line(self, line_number: int) -> bool:
        view = self.current_view
        if view is None or not view.isEnabled() or line_number < 1:
            return False
        try:
            target = view.document.line_start(line_number - 1)
        except ValueError:
            return False
        view.state.move_to(target)
        view._state_changed()
        return True

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
    ) -> None:
        old_document = view.document
        if self._recovery_manager is not None:
            self._recovery_manager.attach(replacement)
            self._recovery_manager.detach(old_document, clean=True)
        view.state = EditorState(replacement)
        self._eol_reports.pop(id(view), None)
        old_document.close()
        view.set_match_index(None)
        view._max_seen_line_width = 0
        view._wrap_index = None
        view._wrap_signature = None
        view._refresh_scrollbars(advance_index=False)
        self._find_replace.document_changed()
        view._state_changed()
        self._schedule_eol_analysis(view)

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

        encoding = (
            view.document.encoding_info.detected
            if view.document.encoding_info.user_override
            else None
        )
        try:
            replacement = Document.open(
                view.document.path,
                encoding=encoding,
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

    def save_current(self) -> Path | None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return None
        try:
            result = view.document.save()
        except Exception as exc:
            self._show_save_error(exc)
            return None
        self._on_view_state_changed(view)
        return result

    def save_current_as(self, path: str | Path | None = None) -> Path | None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return None
        destination: str | Path | None = path
        if destination is None:
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "Save Text File As",
                str(view.document.path),
            )
            if not filename:
                return None
            destination = filename
        try:
            result = view.document.save(destination)
        except Exception as exc:
            self._show_save_error(exc)
            return None
        self._remember_directory(result)
        self._on_view_state_changed(view)
        self._on_current_changed(self._tabs.currentIndex())
        return result

    def undo_current(self) -> None:
        view = self.current_view
        if view is None or not view.isEnabled() or not view.document.can_undo:
            return
        view.state.undo()
        view._state_changed()

    def redo_current(self) -> None:
        view = self.current_view
        if view is None or not view.isEnabled() or not view.document.can_redo:
            return
        view.state.redo()
        view._state_changed()

    def copy_current(self) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.copy_selection()

    def cut_current(self) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.cut_selection()

    def paste_current(self) -> None:
        view = self.current_view
        if view is not None and view.isEnabled():
            view.paste_clipboard()

    def select_all(self) -> None:
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
            self._resource_timer.stop()
            self._find_replace.shutdown()
            if self._recovery_manager is not None:
                self._recovery_manager.shutdown()
            if self._owns_resources:
                self._resources.shutdown(wait=False)
            event.accept()
        else:
            event.ignore()
