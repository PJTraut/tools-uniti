"""Minimal native UNITI desktop shell."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QAction, QCloseEvent, QKeySequence
from PySide6.QtWidgets import (
    QFileDialog,
    QMainWindow,
    QMessageBox,
    QTabWidget,
)

from uniti.app.editor_state import EditorState
from uniti.core.document import Document
from uniti.ui.status_bar import UNITIStatusBar
from uniti.ui.text_view import UNITITextView


class UNITIMainWindow(QMainWindow):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("UNITI")
        self.resize(1100, 760)
        self._tabs = QTabWidget(self)
        self._tabs.setTabsClosable(True)
        self._tabs.setMovable(True)
        self._tabs.tabCloseRequested.connect(self._close_tab)
        self._tabs.currentChanged.connect(self._on_current_changed)
        self.setCentralWidget(self._tabs)
        self._status = UNITIStatusBar(self)
        self.setStatusBar(self._status)
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

        self.menuBar().addMenu("&Search")
        self.menuBar().addMenu("&View")
        self.menuBar().addMenu("&Encoding")
        self.menuBar().addMenu("&EOL")

    def open_dialog(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(self, "Open Text File")
        if filename:
            self.open_path(filename)

    def open_path(self, path: str | Path) -> UNITITextView:
        document = Document.open(path)
        state = EditorState(document)
        view = UNITITextView(state, self._tabs)
        index = self._tabs.addTab(view, self._tab_label(view))
        self._tabs.setCurrentIndex(index)
        view.stateChanged.connect(lambda view=view: self._on_view_state_changed(view))
        view.cursorPositionChanged.connect(self._status.update_cursor)
        self._status.update_document(document)
        self._status.update_cursor(0, 0)
        view.setFocus()
        return view

    def _tab_label(self, view: UNITITextView) -> str:
        marker = "*" if view.document.modified else ""
        return f"{view.document.path.name}{marker}"

    def _on_view_state_changed(self, view: UNITITextView) -> None:
        index = self._tabs.indexOf(view)
        if index >= 0:
            self._tabs.setTabText(index, self._tab_label(view))
        if view is self.current_view:
            self._status.update_document(view.document)

    def _on_current_changed(self, _index: int) -> None:
        view = self.current_view
        if view is None:
            self._status.clear_document()
            self.setWindowTitle("UNITI")
            return
        self._status.update_document(view.document)
        line = view.document.line_for_char(view.state.cursor)
        column = view.state.cursor - view.document.line_start(line)
        self._status.update_cursor(line, column)
        self.setWindowTitle(f"UNITI — {view.document.path.name}")

    def save_current(self) -> Path | None:
        view = self.current_view
        if view is None:
            return None
        result = view.document.save()
        self._on_view_state_changed(view)
        return result

    def save_current_as(self, path: str | Path | None = None) -> Path | None:
        view = self.current_view
        if view is None:
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
        if view is None or not view.document.can_undo:
            return
        view.state.undo()
        view._state_changed()

    def redo_current(self) -> None:
        view = self.current_view
        if view is None or not view.document.can_redo:
            return
        view.state.redo()
        view._state_changed()

    def select_all(self) -> None:
        view = self.current_view
        if view is None:
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
        if not force and not self._confirm_close(widget):
            return False
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

    def closeEvent(self, event: QCloseEvent) -> None:
        if self.close_all_documents(force=False):
            event.accept()
        else:
            event.ignore()
