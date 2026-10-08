"""Undefined markup report (field test round 2, R7; decision D4).

Pops up when an opened file uses markup no loaded definition covers (for
USFM: markers no stylesheet defines), and from **Check Undefined
Markers**. It can copy or save the report, jump to each use, and edit or
update the configuration file that should define the markers — the
project's `custom.sty`, or your own `uniti.sty` for a file outside a
project. Saving that file reloads the stylesheets and re-runs the check.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from uniti.core.environment_commands import ShowUndefinedMarkup
from uniti.core.environments.configuration import CUSTOM_STY_TEMPLATE, uniti_rules_template
from uniti.core.environments.sfm.paratext_project import project_for_file
from uniti.core.environments.sfm.references import ReferenceMap
from uniti.core.environments.sfm.undefined import definition_stubs, location_label, report_text
from uniti.core.environments.user_config import usfm_user_rules_path

if TYPE_CHECKING:
    from uniti.ui.main_window import UNITIMainWindow
    from uniti.ui.text_view import UNITITextView

_OFFSET_ROLE = Qt.ItemDataRole.UserRole
_MARKER_ROLE = Qt.ItemDataRole.UserRole + 1


class UndefinedMarkupDialog(QDialog):
    def __init__(self, window: "UNITIMainWindow", view: "UNITITextView", result: ShowUndefinedMarkup) -> None:
        super().__init__(window)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self._window = window
        self.view = view
        self.result = result
        self.document_name = view.document.path.name
        self.setWindowTitle(f"Undefined Markers — {self.document_name}")
        self.resize(640, 420)

        self.intro = QLabel(self)
        self.intro.setWordWrap(True)
        self.tree = QTreeWidget(self)
        self.tree.setHeaderLabels(["Marker / where", "Uses", "Note"])
        self.tree.itemActivated.connect(self._activated)
        self.copy_button = QPushButton("Copy Report", self)
        self.copy_button.clicked.connect(self.copy_report)
        self.save_button = QPushButton("Save Report…", self)
        self.save_button.clicked.connect(lambda: self.save_report())
        self.edit_button = QPushButton("Edit Stylesheet…", self)
        self.edit_button.clicked.connect(self.edit_stylesheet)
        self.add_button = QPushButton("Add Definitions", self)
        self.add_button.setToolTip("Append a starter definition for the selected markers (all, if none is selected) and open the stylesheet")
        self.add_button.clicked.connect(self.add_definitions)
        actions = QHBoxLayout()
        for button in (self.copy_button, self.save_button):
            actions.addWidget(button)
        actions.addStretch(1)
        for button in (self.edit_button, self.add_button):
            actions.addWidget(button)
        close = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        close.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(self.intro)
        layout.addWidget(self.tree, 1)
        layout.addLayout(actions)
        layout.addWidget(close)
        self._show_result(result)

    # --- content ------------------------------------------------------------------

    def _source(self) -> str:
        document = self.view.document
        return document.read(0, document.total_chars())

    def _show_result(self, result: ShowUndefinedMarkup) -> None:
        self.result = result
        markers = result.markers
        target = self.target_path()
        where = "" if target is None else f" Define them in {target.name} ({'the project' if self._in_project() else 'your rules'})."
        if markers:
            self.intro.setText(
                f"{len(markers)} marker{'s' if len(markers) != 1 else ''} in {self.document_name} "
                f"{'are' if len(markers) != 1 else 'is'} not defined in any loaded stylesheet "
                f"({' → '.join(result.layer_names) or 'none'}). Standard and Preview show "
                f"{'them' if len(markers) != 1 else 'it'} as tags.{where}"
            )
        else:
            self.intro.setText(f"Every marker in {self.document_name} is defined.")
        text = self._source()
        reference_map = ReferenceMap(text) if text else None
        self.tree.clear()
        for marker in markers:
            item = QTreeWidgetItem([marker.display, str(marker.count), marker.advice])
            item.setData(0, _MARKER_ROLE, marker.marker)
            for start in marker.starts[:200]:
                child = QTreeWidgetItem([location_label(reference_map, text, start), "", ""])
                child.setData(0, _OFFSET_ROLE, start)
                item.addChild(child)
            self.tree.addTopLevelItem(item)
        for column in range(3):
            self.tree.resizeColumnToContents(column)
        for button in (self.edit_button, self.add_button):
            button.setEnabled(bool(markers) and target is not None)

    def refresh(self) -> bool:
        """Re-run the check (after the stylesheets changed); whether any
        marker is still undefined."""

        result = self._window._environment.undefined_markup_for(self.view)
        if result is not None:
            self._show_result(result)
        return bool(self.result.markers)

    def report(self) -> str:
        return report_text(self.document_name, self.result.layer_names, self.result.markers, self._source())

    # --- actions -----------------------------------------------------------------------

    def copy_report(self) -> str:
        text = self.report()
        QApplication.clipboard().setText(text)
        return text

    def save_report(self, path: str | Path | None = None) -> Path | None:
        if path is None:
            suggested = self.view.document.path.with_name(f"{self.view.document.path.stem}-undefined-markers.txt")
            chosen, _filter = QFileDialog.getSaveFileName(self, "Save Report", str(suggested), "Text (*.txt);;All Files (*)")
            if not chosen:
                return None
            path = chosen
        path = Path(path)
        try:
            path.write_text(self.report(), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save Report", f"{path}\n\n{exc}")
            return None
        return path

    def _in_project(self) -> bool:
        return project_for_file(self.view.document.path) is not None

    def target_path(self) -> Path | None:
        """Where the definitions belong: the project's custom.sty, or your
        own uniti.sty for a file outside a Paratext project or in a
        read-only folder (round 3 T7)."""

        if self._in_project() and not self._read_only_folder():
            return self.view.document.path.parent / "custom.sty"
        return usfm_user_rules_path()

    def _read_only_folder(self) -> bool:
        from uniti.app.read_only import is_read_only_path

        window = self._window
        folders = () if window is None else window._settings.read_only_folders
        return is_read_only_path(self.view.document.path.parent / "custom.sty", folders)

    def _ensure_target(self) -> Path | None:
        target = self.target_path()
        if target is None:
            return None
        if not target.exists() and self._open_document(target) is None:
            template = CUSTOM_STY_TEMPLATE if target.name == "custom.sty" else uniti_rules_template("your own rules for every USFM file")
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(template, encoding="utf-8")
            except OSError as exc:
                QMessageBox.warning(self, "Edit Stylesheet", f"{target}\n\n{exc}")
                return None
        return target

    def _open_document(self, path: Path):
        service = self._window._service
        if service is not None:
            entry = service.documents.find_path(path)
            return None if entry is None else entry.document
        return next((view.document for view in self._window.views if view.document.path == path), None)

    def edit_stylesheet(self):
        target = self._ensure_target()
        return None if target is None else self._window.open_configuration_file(target)

    def add_definitions(self):
        """Append starter records for the selected markers (all, when none
        is selected) to the stylesheet, then open it to complete them."""

        selected = {item.data(0, _MARKER_ROLE) for item in self.tree.selectedItems() if item.data(0, _MARKER_ROLE)}
        markers = tuple(marker for marker in self.result.markers if not selected or marker.marker in selected)
        if not markers:
            return None
        target = self._ensure_target()
        if target is None:
            return None
        stubs = "\n" + definition_stubs(markers, self.document_name)
        document = self._open_document(target)
        if document is not None:
            # Open in UNITI (perhaps with unsaved changes): add to that copy.
            document.replace(document.total_chars(), document.total_chars(), stubs)
        else:
            try:
                with target.open("a", encoding="utf-8") as handle:
                    handle.write(stubs)
            except OSError as exc:
                QMessageBox.warning(self, "Add Definitions", f"{target}\n\n{exc}")
                return None
        return self._window.open_configuration_file(target)

    def _activated(self, item: QTreeWidgetItem, _column: int) -> None:
        offset = item.data(0, _OFFSET_ROLE)
        if offset is None and item.childCount():
            offset = item.child(0).data(0, _OFFSET_ROLE)
        if isinstance(offset, int):
            self._window._environment.navigate_view(self.view, offset)


__all__ = ["UndefinedMarkupDialog"]
