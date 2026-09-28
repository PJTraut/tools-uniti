"""Dogfood evidence export/clear, composed onto UNITIMainWindow.

First slice pulled out of main_window.py's god-object (an architecture
review flagged the file's size/mixed responsibilities): the narrowest,
most self-contained cluster there -- two methods, no writes to any state
shared with the rest of the window, only two call-sites (both from
`_build_menus`'s dogfood action wiring). Extracted first to prove the
"compose a controller object" pattern (mirroring `theme_editor.py`,
`compare_pane.py`, `whitespace_legend.py`) before attempting a riskier,
more entangled cluster.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QFileDialog, QMessageBox


class DogfoodEvidenceController:
    """Owns the Export/Clear Dogfood Evidence flows for one main window.

    `owner` is the `UNITIMainWindow` this controller acts on behalf of --
    used only as a Qt dialog parent, for `owner._service`, and for
    `owner._settings.last_directory`/`owner.statusBar()`, exactly the
    same state these two methods touched before the move."""

    def __init__(self, owner) -> None:
        self._owner = owner

    def export_dogfood_evidence(self):
        owner = self._owner
        if owner._service is None:
            return None
        initial = (
            Path(owner._settings.last_directory or "")
            / "uniti-dogfood-evidence.json"
        )
        selected, _filter = QFileDialog.getSaveFileName(
            owner,
            "Export Dogfood Evidence",
            str(initial),
            "JSON Files (*.json)",
        )
        if not selected:
            return None
        try:
            handle = owner._service.export_dogfood_evidence(Path(selected))
        except (RuntimeError, ValueError):
            QMessageBox.warning(
                owner,
                "Dogfood Evidence Unavailable",
                "UNITI could not start the evidence export.",
            )
            return None
        owner.statusBar().showMessage("Dogfood evidence export started.", 5000)
        return handle

    def clear_dogfood_evidence(self):
        owner = self._owner
        if owner._service is None:
            return None
        answer = QMessageBox.question(
            owner,
            "Clear Dogfood Evidence",
            "Clear all locally stored UNITI dogfood evidence?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return None
        try:
            handle = owner._service.clear_dogfood_evidence()
        except RuntimeError:
            QMessageBox.warning(
                owner,
                "Dogfood Evidence Unavailable",
                "UNITI could not start clearing the evidence.",
            )
            return None
        owner.statusBar().showMessage("Clearing dogfood evidence…", 5000)
        return handle


__all__ = ["DogfoodEvidenceController"]
