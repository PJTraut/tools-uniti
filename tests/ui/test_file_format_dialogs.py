from __future__ import annotations

import importlib.util
import os

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is not installed",
)


def application():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_save_as_format_rows_are_visible_in_required_order(tmp_path):
    from PySide6.QtWidgets import QLabel

    from uniti.ui.file_format_dialogs import SaveAsFormatDialog

    app = application()
    dialog = SaveAsFormatDialog(
        initial_directory=tmp_path,
        initial_name="aaa.txt",
    )
    labels = [label.text() for label in dialog.findChildren(QLabel)]
    assert labels.index("File name:") < labels.index("Encoding:")
    assert labels.index("Encoding:") < labels.index("Line endings:")
    assert dialog.file_name_edit.text() == "aaa.txt"
    assert dialog.file_name_edit.objectName() == "fileNameEdit"
    dialog.close()
    app.processEvents()


def test_save_as_selection_keeps_encoding_and_eol_independent(tmp_path):
    from uniti.core.text_format import EOLPolicy, encoding_profile
    from uniti.ui.file_format_dialogs import SaveAsFormatDialog

    app = application()
    dialog = SaveAsFormatDialog(
        initial_directory=tmp_path,
        initial_name="aaa.txt",
    )
    dialog.select_encoding(encoding_profile("utf-8"))
    dialog.select_eol(EOLPolicy.CRLF)
    dialog.accept()
    selection = dialog.result_selection()
    assert selection is not None
    assert selection.destination == tmp_path / "aaa.txt"
    assert selection.output_format.encoding.key == "utf-8"
    assert selection.output_format.eol is EOLPolicy.CRLF
    dialog.close()
    app.processEvents()


def test_save_as_lists_all_exact_profiles_in_canonical_order(tmp_path):
    from uniti.core.text_format import encoding_profiles
    from uniti.ui.file_format_dialogs import SaveAsFormatDialog

    app = application()
    dialog = SaveAsFormatDialog(
        initial_directory=tmp_path,
        initial_name="format.txt",
    )
    assert [
        dialog.encoding_combo.itemData(index).key
        for index in range(dialog.encoding_combo.count())
    ] == [profile.key for profile in encoding_profiles()]
    assert dialog.encoding_combo.objectName() == "encodingCombo"
    assert dialog.line_endings_combo.objectName() == "lineEndingsCombo"
    dialog.close()
    app.processEvents()


def test_cancelled_save_as_has_no_selection(tmp_path):
    from uniti.ui.file_format_dialogs import SaveAsFormatDialog

    app = application()
    dialog = SaveAsFormatDialog(
        initial_directory=tmp_path,
        initial_name="cancelled.txt",
    )
    dialog.reject()
    assert dialog.result_selection() is None
    dialog.close()
    app.processEvents()


def test_save_as_browse_changes_directory_without_changing_filename(
    tmp_path,
    monkeypatch,
):
    from PySide6.QtWidgets import QFileDialog

    from uniti.ui.file_format_dialogs import SaveAsFormatDialog

    app = application()
    selected_directory = tmp_path / "selected"
    monkeypatch.setattr(
        QFileDialog,
        "getExistingDirectory",
        lambda *_args, **_kwargs: str(selected_directory),
    )
    dialog = SaveAsFormatDialog(
        initial_directory=tmp_path,
        initial_name="kept.txt",
    )
    dialog._browse_directory()
    assert dialog.directory_edit.text() == str(selected_directory)
    assert dialog.file_name_edit.text() == "kept.txt"
    dialog.close()
    app.processEvents()


def test_open_profile_change_refreshes_preview_and_malformed_evidence():
    from uniti.core.decoder import DecodeError
    from uniti.core.encoding import EncodingAssessment
    from uniti.core.eol import EOLReport
    from uniti.core.text_format import encoding_profile
    from uniti.core.text_inspection import FormatPreview
    from uniti.ui.file_format_dialogs import OpenFormatDialog

    app = application()
    assessment = EncodingAssessment(
        suggested=encoding_profile("utf-8"),
        confidence=0.35,
        alternatives=(encoding_profile("windows-1252"),),
        reasons=("Encoding confidence 35% is below 75%.",),
        contradictory=False,
        malformed_preview=(),
        requires_confirmation=True,
    )
    calls = []

    def preview(profile):
        calls.append(profile.key)
        if profile.key == "utf-8":
            return FormatPreview(
                "A\ufffdZ",
                (DecodeError(1, 2, b"\xff"),),
                False,
            )
        return FormatPreview("AÿZ", (), False)

    dialog = OpenFormatDialog(
        assessment,
        EOLReport(lf=1, crlf=1, cr=0, kind="MIXED"),
        preview_provider=preview,
    )
    assert dialog.preview_edit.toPlainText() == "A\ufffdZ"
    assert "FF" in dialog.evidence_label.text()
    dialog.select_encoding(encoding_profile("windows-1252"))
    assert calls[-1] == "windows-1252"
    assert dialog.preview_edit.toPlainText() == "AÿZ"
    assert dialog.evidence_label.text() == "No malformed bytes in preview."
    assert "LF 1" in dialog.eol_summary_label.text()
    assert dialog.preview_edit.objectName() == "formatPreview"
    assert dialog.evidence_label.objectName() == "formatEvidence"
    dialog.close()
    app.processEvents()


def test_open_dialog_returns_profile_only_after_acceptance():
    from uniti.core.encoding import EncodingAssessment
    from uniti.core.eol import EOLReport
    from uniti.core.text_format import encoding_profile
    from uniti.core.text_inspection import FormatPreview
    from uniti.ui.file_format_dialogs import OpenFormatDialog

    app = application()
    selected = encoding_profile("utf-16-le")
    assessment = EncodingAssessment(
        suggested=selected,
        confidence=0.70,
        alternatives=(),
        reasons=("Confirmation required.",),
        contradictory=False,
        malformed_preview=(),
        requires_confirmation=True,
    )
    dialog = OpenFormatDialog(
        assessment,
        EOLReport(lf=1, crlf=0, cr=0, kind="LF"),
        preview_provider=lambda _profile: FormatPreview("text", (), False),
    )
    assert dialog.result_profile() is None
    dialog.accept()
    assert dialog.result_profile() == selected
    dialog.close()
    app.processEvents()


def test_line_ending_report_is_modeless_and_emits_explicit_policy():
    from uniti.core.eol import EOLReport
    from uniti.core.text_format import EOLPolicy
    from uniti.ui.file_format_dialogs import LineEndingReportDialog

    app = application()
    dialog = LineEndingReportDialog(
        EOLReport(lf=2, crlf=3, cr=1, kind="MIXED")
    )
    selected = []
    dialog.policySelected.connect(selected.append)
    assert dialog.isModal() is False
    assert "LF 2" in dialog.summary_label.text()
    assert "CRLF 3" in dialog.summary_label.text()
    dialog.select_policy(EOLPolicy.CR)
    assert selected == [EOLPolicy.CR]
    dialog.close()
    app.processEvents()
