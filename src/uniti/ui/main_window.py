"""Minimal native UNITI desktop shell."""

from __future__ import annotations

from concurrent.futures import Future
from pathlib import Path
import weakref

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from uniti.app.editor_state import EditorState
from uniti.app.recovery_manager import RecoveryManager
from uniti.core.byte_source import ByteSource
from uniti.core.document import Document
from uniti.core.eol import EOLReport, analyze_eol
from uniti.resources import PriorityWorkerPool, WorkPriority
from uniti.ui.character_inspector import CharacterInspectorDialog
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
    ) -> None:
        super().__init__(parent)
        self._recovery_manager = recovery_manager
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
        self._find_replace = FindReplacePanel(lambda: self.current_view, central)
        self._find_replace.hide()
        central_layout.addWidget(self._find_replace, 0)
        self.setCentralWidget(central)
        self._status = UNITIStatusBar(self)
        self.setStatusBar(self._status)

        self._eol_pool = PriorityWorkerPool(
            max_workers=1,
            thread_name_prefix="uniti-eol",
        )
        self._eol_jobs: dict[Future, weakref.ReferenceType] = {}
        self._eol_reports: dict[int, EOLReport] = {}
        self._eol_timer = QTimer(self)
        self._eol_timer.setInterval(80)
        self._eol_timer.timeout.connect(self._poll_eol_jobs)
        self._build_menus()

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
            self._action("Select All", QKeySequence.StandardKey.SelectAll, self.select_all)
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

        self.menuBar().addMenu("&View")

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

    def open_dialog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open Text File")
        if filename:
            self.open_path(filename)

    def _connect_view(self, view: UNITITextView) -> None:
        view.stateChanged.connect(lambda view=view: self._on_view_state_changed(view))
        view.cursorPositionChanged.connect(self._status.update_cursor)

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
        self._connect_view(view)
        index = self._tabs.addTab(view, self._tab_label(view))
        self._tabs.setCurrentIndex(index)
        self._set_status_document(view)
        self._status.update_cursor(0, 0)
        self._schedule_eol_analysis(view)
        view.setFocus()
        return view

    def open_path(self, path: str | Path) -> UNITITextView:
        document = Document.open(path)
        try:
            return self._add_document(document)
        except Exception:
            document.close()
            raise

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

    def _on_view_state_changed(self, view: UNITITextView) -> None:
        index = self._tabs.indexOf(view)
        if index >= 0:
            self._tabs.setTabText(index, self._tab_label(view))
        if view is self.current_view:
            self._set_status_document(view)

    def _on_current_changed(self, _index: int) -> None:
        self._find_replace.document_changed()
        view = self.current_view
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
        path = view.document.source.path
        try:
            document = Document.open(path, encoding=encoding)
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

    def show_character_inspector(self) -> None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return
        selection = view.state.selection
        position = selection[0] if selection is not None else view.state.cursor
        try:
            character = view.document.read(position, position + 1)
        except ValueError:
            character = ""
        if not character and position > 0:
            try:
                character = view.document.read(position - 1, position)
            except ValueError:
                character = ""
        if not character:
            QMessageBox.information(self, "Character Inspector", "No character at cursor.")
            return
        dialog = CharacterInspectorDialog(
            character[0],
            output_encoding=view.document.output_encoding,
            parent=self,
        )
        dialog.exec()

    def save_current(self) -> Path | None:
        view = self.current_view
        if view is None or not view.isEnabled():
            return None
        result = view.document.save()
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
        result = view.document.save(destination)
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
                QMessageBox.critical(self, "Save Failed", str(exc))
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
            self._find_replace.shutdown()
            self._eol_pool.shutdown(wait=False, cancel_pending=True)
            event.accept()
        else:
            event.ignore()
