"""Non-modal list of an environment's validation findings (ADR-0014).

The first UI consumer of `EnvironmentFinding` (ADR-0013 Phase E3 built the
seam with no consumer). Activating a row moves the caret to the finding.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from uniti.core.environment_findings import EnvironmentFinding

LineColumn = Callable[[int], tuple[int, int]]


class EnvironmentFindingsDialog(QDialog):
    def __init__(self, on_navigate: Callable[[int], None], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Environment Findings")
        self.setModal(False)
        self._on_navigate = on_navigate
        self.summary = QLabel(self)
        self.list = QListWidget(self)
        self.list.itemActivated.connect(self._activate)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.summary)
        layout.addWidget(self.list)
        layout.addWidget(buttons)
        self.resize(560, 320)

    def set_findings(
        self,
        title: str,
        document_name: str,
        findings: tuple[EnvironmentFinding, ...],
        line_column: LineColumn,
    ) -> None:
        self.setWindowTitle(f"{title} — {document_name}")
        self.list.clear()
        if not findings:
            self.summary.setText("No problems found.")
            return
        count = len(findings)
        self.summary.setText(f"{count} problem{'s' if count != 1 else ''} found.")
        for finding in findings:
            line, column = line_column(finding.start)
            item = QListWidgetItem(
                f"Line {line}, Col {column}  [{finding.severity.value}]  {finding.message}"
            )
            item.setData(Qt.ItemDataRole.UserRole, finding.start)
            self.list.addItem(item)

    def _activate(self, item: QListWidgetItem) -> None:
        offset = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(offset, int):
            self._on_navigate(offset)
