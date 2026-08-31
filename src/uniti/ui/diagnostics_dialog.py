"""Copyable diagnostics view; never used as UNITI document storage."""

from __future__ import annotations

import json

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QPlainTextEdit, QVBoxLayout


class DiagnosticsDialog(QDialog):
    def __init__(self, snapshot: dict[str, object], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("UNITI Diagnostics")
        self.resize(720, 520)
        text = QPlainTextEdit(self)
        text.setReadOnly(True)
        text.setPlainText(json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True))
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(text, 1)
        layout.addWidget(buttons)
