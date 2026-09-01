"""Application-owned text-format decisions for Open and Save As."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from uniti.core.encoding import EncodingAssessment
from uniti.core.eol import EOLReport
from uniti.core.text_format import (
    EOLPolicy,
    EncodingProfile,
    OutputFormat,
    encoding_profile,
    encoding_profiles,
)
from uniti.core.text_inspection import FormatPreview


@dataclass(frozen=True, slots=True)
class SaveAsSelection:
    destination: Path
    output_format: OutputFormat


def _eol_summary(report: EOLReport) -> str:
    if report.kind == "MIXED":
        return f"Mixed — LF {report.lf}, CRLF {report.crlf}, CR {report.cr}"
    return (
        f"{report.kind} — LF {report.lf}, "
        f"CRLF {report.crlf}, CR {report.cr}"
    )


class SaveAsFormatDialog(QDialog):
    """Cross-platform output path and exact format selection."""

    def __init__(
        self,
        *,
        initial_directory: str | Path,
        initial_name: str,
        initial_format: OutputFormat | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Save Text File As")
        self.setSizeGripEnabled(True)
        self.resize(620, 190)
        selected = initial_format or OutputFormat(
            encoding_profile("utf-8"),
            EOLPolicy.PRESERVE,
        )

        self.directory_edit = QLineEdit(str(Path(initial_directory)), self)
        self.directory_edit.setReadOnly(True)
        self.directory_edit.setObjectName("saveDirectoryEdit")
        browse_button = QPushButton("Browse…", self)
        browse_button.clicked.connect(self._browse_directory)
        directory_widget = QWidget(self)
        directory_row = QHBoxLayout(directory_widget)
        directory_row.setContentsMargins(0, 0, 0, 0)
        directory_row.addWidget(self.directory_edit, 1)
        directory_row.addWidget(browse_button)

        self.file_name_edit = QLineEdit(initial_name, self)
        self.file_name_edit.setObjectName("fileNameEdit")
        self.encoding_combo = QComboBox(self)
        self.encoding_combo.setObjectName("encodingCombo")
        for profile in encoding_profiles():
            self.encoding_combo.addItem(profile.label, profile)
        self.line_endings_combo = QComboBox(self)
        self.line_endings_combo.setObjectName("lineEndingsCombo")
        for policy, label in (
            (EOLPolicy.PRESERVE, "Preserve"),
            (EOLPolicy.LF, "LF"),
            (EOLPolicy.CRLF, "CRLF"),
            (EOLPolicy.CR, "CR"),
        ):
            self.line_endings_combo.addItem(label, policy)

        form = QFormLayout()
        form.addRow("Folder:", directory_widget)
        form.addRow("File name:", self.file_name_edit)
        form.addRow("Encoding:", self.encoding_combo)
        form.addRow("Line endings:", self.line_endings_combo)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        self.file_name_edit.textChanged.connect(self._update_save_enabled)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.buttons)
        self.select_encoding(selected.encoding)
        self.select_eol(selected.eol)
        self._update_save_enabled()

    def _update_save_enabled(self) -> None:
        button = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        button.setEnabled(bool(self.file_name_edit.text().strip()))

    def _browse_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self,
            "Select Save Folder",
            self.directory_edit.text(),
        )
        if selected:
            self.directory_edit.setText(selected)

    def select_encoding(self, profile: EncodingProfile) -> None:
        for index in range(self.encoding_combo.count()):
            if self.encoding_combo.itemData(index) == profile:
                self.encoding_combo.setCurrentIndex(index)
                return
        raise ValueError(f"encoding profile is not available: {profile.key}")

    def select_eol(self, policy: EOLPolicy) -> None:
        for index in range(self.line_endings_combo.count()):
            stored = self.line_endings_combo.itemData(index)
            if stored == policy or stored == policy.value:
                self.line_endings_combo.setCurrentIndex(index)
                return
        raise ValueError(f"EOL policy is not available: {policy}")

    def selection(self) -> SaveAsSelection:
        name = self.file_name_edit.text().strip()
        if not name:
            raise ValueError("file name cannot be empty")
        profile = self.encoding_combo.currentData()
        try:
            policy = EOLPolicy(self.line_endings_combo.currentData())
        except (TypeError, ValueError) as exc:
            raise ValueError("an exact output format must be selected") from exc
        if not isinstance(profile, EncodingProfile):
            raise ValueError("an exact output format must be selected")
        return SaveAsSelection(
            destination=Path(self.directory_edit.text()) / name,
            output_format=OutputFormat(profile, policy),
        )

    def result_selection(self) -> SaveAsSelection | None:
        if self.result() != QDialog.DialogCode.Accepted:
            return None
        return self.selection()


class OpenFormatDialog(QDialog):
    """Serious exact-input confirmation with a bounded live preview."""

    def __init__(
        self,
        assessment: EncodingAssessment,
        eol_report: EOLReport,
        *,
        preview_provider: Callable[[EncodingProfile], FormatPreview],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Confirm Text Encoding")
        self.setSizeGripEnabled(True)
        self.resize(720, 480)
        self._preview_provider = preview_provider

        warning = QLabel("Text encoding requires confirmation.", self)
        warning.setWordWrap(True)
        self.reason_label = QLabel("\n".join(assessment.reasons), self)
        self.reason_label.setWordWrap(True)
        confidence_label = QLabel(f"Confidence: {assessment.confidence:.0%}", self)

        self.encoding_combo = QComboBox(self)
        self.encoding_combo.setObjectName("encodingCombo")
        for profile in encoding_profiles():
            self.encoding_combo.addItem(profile.label, profile)
        self.preview_edit = QPlainTextEdit(self)
        self.preview_edit.setObjectName("formatPreview")
        self.preview_edit.setReadOnly(True)
        self.evidence_label = QLabel(self)
        self.evidence_label.setObjectName("formatEvidence")
        self.evidence_label.setWordWrap(True)
        self.eol_summary_label = QLabel(_eol_summary(eol_report), self)
        self.eol_summary_label.setObjectName("eolSummary")

        form = QFormLayout()
        form.addRow("Encoding:", self.encoding_combo)
        form.addRow("Line endings:", self.eol_summary_label)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Open
            | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(warning)
        layout.addWidget(self.reason_label)
        layout.addWidget(confidence_label)
        layout.addLayout(form)
        layout.addWidget(QLabel("Preview:", self))
        layout.addWidget(self.preview_edit, 1)
        layout.addWidget(self.evidence_label)
        layout.addWidget(self.buttons)

        self.select_encoding(assessment.suggested)
        self.encoding_combo.currentIndexChanged.connect(self._refresh_preview)
        self._refresh_preview()

    def select_encoding(self, profile: EncodingProfile) -> None:
        for index in range(self.encoding_combo.count()):
            if self.encoding_combo.itemData(index) == profile:
                self.encoding_combo.setCurrentIndex(index)
                self._refresh_preview()
                return
        raise ValueError(f"encoding profile is not available: {profile.key}")

    def selected_profile(self) -> EncodingProfile:
        profile = self.encoding_combo.currentData()
        if not isinstance(profile, EncodingProfile):
            raise ValueError("an exact input encoding must be selected")
        return profile

    def result_profile(self) -> EncodingProfile | None:
        if self.result() != QDialog.DialogCode.Accepted:
            return None
        return self.selected_profile()

    def _refresh_preview(self, _index: int | None = None) -> None:
        preview = self._preview_provider(self.selected_profile())
        self.preview_edit.setPlainText(preview.text)
        if preview.invalid_bytes:
            evidence = ", ".join(
                f"byte {error.byte_start}: {error.raw.hex(' ').upper()}"
                for error in preview.invalid_bytes
            )
            self.evidence_label.setText(f"Malformed preview bytes — {evidence}")
        else:
            self.evidence_label.setText("No malformed bytes in preview.")


class LineEndingReportDialog(QDialog):
    """Modeless mixed-line-ending report with explicit output choices."""

    policySelected = Signal(object)

    def __init__(self, report: EOLReport, parent=None) -> None:
        super().__init__(parent)
        self.setModal(False)
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setWindowTitle("Mixed Line Endings")
        self.summary_label = QLabel(_eol_summary(report), self)
        self.summary_label.setObjectName("eolSummary")

        button_row = QHBoxLayout()
        for label, policy in (
            ("Keep", EOLPolicy.PRESERVE),
            ("Convert to LF", EOLPolicy.LF),
            ("Convert to CRLF", EOLPolicy.CRLF),
            ("Convert to CR", EOLPolicy.CR),
        ):
            button = QPushButton(label, self)
            button.clicked.connect(
                lambda _checked=False, policy=policy: self.select_policy(policy)
            )
            button_row.addWidget(button)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("This file contains mixed line endings.", self))
        layout.addWidget(self.summary_label)
        layout.addLayout(button_row)

    def select_policy(self, policy: EOLPolicy) -> None:
        self.policySelected.emit(policy)
        self.hide()
