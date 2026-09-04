from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is not installed",
)


@pytest.fixture
def app():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app):
    from uniti.ui.main_window import UNITIMainWindow

    instance = UNITIMainWindow()
    yield instance
    instance.close_all_documents(force=True)
    instance.close()
    app.processEvents()


def _open(window, path: Path, text: str):
    path.write_text(text, encoding="utf-8", newline="")
    view = window.open_path(path)
    assert view is not None
    return view


def _document_state(document) -> tuple:
    return (
        document.path,
        document.disk_identity,
        document.revision,
        document.can_undo,
        document.can_redo,
        document.modified,
        document.output_format,
        document.saved_output_format,
        document.read(0, document.total_chars()),
    )


def _warning_responses(monkeypatch, responses):
    from PySide6.QtWidgets import QMessageBox

    calls: list[tuple[str, str]] = []
    pending = list(responses)

    def warning(_parent, title, text, *args, **kwargs):
        calls.append((title, text))
        if not pending:
            raise AssertionError(f"unexpected warning: {title}")
        return pending.pop(0)

    monkeypatch.setattr(QMessageBox, "warning", warning)
    return calls


def test_new_destination_opens_export_without_mutating_source_tab(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile

    source_path = tmp_path / "source.txt"
    target = tmp_path / "target.txt"
    source_view = _open(window, source_path, "body\n")
    source_view.state.move_to(0)
    source_view.state.insert_text("edited ")
    before = _document_state(source_view.document)
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("a new destination must not warn")
        ),
    )
    output_format = OutputFormat(
        encoding_profile("utf-16-le-bom"), EOLPolicy.CRLF
    )

    result = window.save_current_as(target, output_format)

    assert result == target
    assert _document_state(source_view.document) == before
    assert window.panes.active_leaf.tabs.count() == 2
    assert window.current_view is not source_view
    assert window.current_view.document.path == target
    assert window.current_view.document.source_profile.key == "utf-16-le-bom"
    assert window.current_view.document.read(
        0, window.current_view.document.total_chars()
    ) == "edited body\r\n"
    assert target.read_bytes().startswith(b"\xff\xfe")


def test_dirty_open_target_blocks_before_any_write_or_confirmation(
    window, tmp_path: Path, monkeypatch
):
    source = _open(window, tmp_path / "source.txt", "source\n")
    target = _open(window, tmp_path / "target.txt", "target\n")
    target.state.move_document_end()
    target.state.insert_text("dirty")
    target_bytes = target.document.path.read_bytes()
    target_document = target.document
    window.panes.active_leaf.tabs.setCurrentWidget(source)
    calls = _warning_responses(monkeypatch, [None])

    assert (
        window.save_current_as(target.document.path, source.document.output_format)
        is None
    )

    assert [title for title, _text in calls] == ["Target Has Unsaved Changes"]
    assert target.document.path.read_bytes() == target_bytes
    assert target.document is target_document
    assert window.panes.active_leaf.tabs.count() == 2


def test_existing_closed_target_requires_one_normal_overwrite_confirmation(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    source = _open(window, tmp_path / "source.txt", "replacement\n")
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    calls = _warning_responses(monkeypatch, [QMessageBox.StandardButton.Yes])

    assert window.save_current_as(target, source.document.output_format) == target

    assert [title for title, _text in calls] == ["Replace Existing File"]
    assert target.read_text(encoding="utf-8") == "replacement\n"
    assert window.current_view.document.path == target


def test_existing_target_encoding_change_has_exact_separate_warning(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile

    _open(window, tmp_path / "source.txt", "replacement\n")
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    calls = _warning_responses(
        monkeypatch,
        [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Yes],
    )
    selected = OutputFormat(
        encoding_profile("utf-16-be-bom"), EOLPolicy.CRLF
    )

    assert window.save_current_as(target, selected) == target

    assert [title for title, _text in calls] == [
        "Replace Existing File",
        "Change Text Encoding",
    ]
    assert "UTF-8 -> UTF-16 BE BOM" in calls[1][1]
    assert target.read_bytes().startswith(b"\xfe\xff")


def test_target_changed_after_confirmation_is_not_overwritten(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    source = _open(window, tmp_path / "source.txt", "replacement\n")
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    calls: list[str] = []

    def warning(_parent, title, text, *args, **kwargs):
        calls.append(title)
        if title == "Replace Existing File":
            target.write_text("external change\n", encoding="utf-8")
            return QMessageBox.StandardButton.Yes
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", warning)

    assert window.save_current_as(target, source.document.output_format) is None
    assert target.read_text(encoding="utf-8") == "external change\n"
    assert calls == ["Replace Existing File", "File Changed on Disk"]
    assert window.panes.active_leaf.tabs.count() == 1


@pytest.mark.parametrize("refused_warning", [0, 1])
def test_refusing_an_existing_target_warning_leaves_disk_and_tabs_unchanged(
    window, tmp_path: Path, monkeypatch, refused_warning: int
):
    from PySide6.QtWidgets import QMessageBox

    from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile

    source = _open(window, tmp_path / "source.txt", "new\n")
    target = tmp_path / "target.txt"
    target.write_text("old\n", encoding="utf-8")
    before = target.read_bytes()
    responses = [QMessageBox.StandardButton.Yes] * refused_warning
    responses.append(QMessageBox.StandardButton.Cancel)
    calls = _warning_responses(monkeypatch, responses)
    selected = OutputFormat(encoding_profile("utf-16-le"), EOLPolicy.LF)

    assert window.save_current_as(target, selected) is None

    assert target.read_bytes() == before
    assert window.panes.active_leaf.tabs.count() == 1
    assert window.current_view is source
    assert len(calls) == refused_warning + 1


def test_clean_open_target_requires_two_overwrite_confirmations_and_reuses_tab(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    source = _open(window, tmp_path / "source.txt", "replacement\n")
    target = _open(window, tmp_path / "target.txt", "old\n")
    old_target_document = target.document
    window.panes.active_leaf.tabs.setCurrentWidget(source)
    calls = _warning_responses(
        monkeypatch,
        [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Yes],
    )

    result = window.save_current_as(
        target.document.path,
        source.document.output_format,
    )

    assert result == target.document.path
    assert [title for title, _text in calls] == [
        "Replace Existing File",
        "Replace Open Document",
    ]
    assert window.panes.active_leaf.tabs.count() == 2
    assert window.current_view is target
    assert target.document is not old_target_document
    assert target.document.read(0, target.document.total_chars()) == "replacement\n"
    assert source.document.path == tmp_path / "source.txt"


def test_refusing_open_tab_replacement_leaves_disk_and_documents_unchanged(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    source = _open(window, tmp_path / "source.txt", "replacement\n")
    target = _open(window, tmp_path / "target.txt", "old\n")
    old_target_document = target.document
    before = target.document.path.read_bytes()
    window.panes.active_leaf.tabs.setCurrentWidget(source)
    calls = _warning_responses(
        monkeypatch,
        [QMessageBox.StandardButton.Yes, QMessageBox.StandardButton.Cancel],
    )

    assert (
        window.save_current_as(target.document.path, source.document.output_format)
        is None
    )

    assert [title for title, _text in calls] == [
        "Replace Existing File",
        "Replace Open Document",
    ]
    assert target.document.path.read_bytes() == before
    assert target.document is old_target_document
    assert window.current_view is source


def test_save_warns_once_for_encoding_change_but_not_for_later_unchanged_save(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile

    view = _open(window, tmp_path / "source.txt", "hello\n")
    view.document.set_output_format(
        OutputFormat(encoding_profile("utf-8-bom"), EOLPolicy.PRESERVE)
    )
    calls = _warning_responses(monkeypatch, [QMessageBox.StandardButton.Yes])

    assert window.save_current() == view.document.path
    assert window.save_current() == view.document.path

    assert [title for title, _text in calls] == ["Change Text Encoding"]
    assert "UTF-8 -> UTF-8 BOM" in calls[0][1]
    assert view.document.modified is False
    assert view.document.saved_output_format.encoding.key == "utf-8-bom"


def test_save_with_only_line_ending_conversion_has_no_serious_warning(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from uniti.core.text_format import EOLPolicy, OutputFormat

    view = _open(window, tmp_path / "source.txt", "one\ntwo\n")
    view.document.set_output_format(
        OutputFormat(view.document.output_format.encoding, EOLPolicy.CRLF)
    )
    monkeypatch.setattr(
        QMessageBox,
        "warning",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("line-ending conversion is not a serious encoding warning")
        ),
    )

    assert window.save_current() == view.document.path
    assert view.document.path.read_bytes() == b"one\r\ntwo\r\n"


def test_low_confidence_existing_target_requires_explicit_target_profile(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QDialog, QMessageBox

    from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile
    import uniti.ui.main_window as main_window

    _open(window, tmp_path / "source.txt", "Price - 10\n")
    target = tmp_path / "legacy.txt"
    target.write_bytes(b"Price \x96 10\r\n")
    seen = {}

    class AcceptedTargetProfile:
        def __init__(self, assessment, eol_report, *, preview_provider, parent=None):
            seen["assessment"] = assessment

        def exec(self):
            return QDialog.DialogCode.Accepted

        def selected_profile(self):
            return encoding_profile("windows-1252")

    monkeypatch.setattr(main_window, "OpenFormatDialog", AcceptedTargetProfile)
    calls = _warning_responses(monkeypatch, [QMessageBox.StandardButton.Yes])
    selected = OutputFormat(encoding_profile("windows-1252"), EOLPolicy.CRLF)

    assert window.save_current_as(target, selected) == target

    assert seen["assessment"].confidence < 0.75
    assert [title for title, _text in calls] == ["Replace Existing File"]
    assert target.read_bytes() == b"Price - 10\r\n"


def test_same_destination_save_as_updates_current_tab_without_generic_overwrite(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QMessageBox

    from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile

    view = _open(window, tmp_path / "same.txt", "same\n")
    selected = OutputFormat(encoding_profile("utf-16-le-bom"), EOLPolicy.LF)
    calls = _warning_responses(monkeypatch, [QMessageBox.StandardButton.Yes])

    assert window.save_current_as(view.document.path, selected) == view.document.path

    assert [title for title, _text in calls] == ["Change Text Encoding"]
    assert window.panes.active_leaf.tabs.count() == 1
    assert window.current_view is view
    assert view.document.source_profile.key == "utf-16-le-bom"


def test_dialog_save_as_uses_selected_filename_and_format(
    window, tmp_path: Path, monkeypatch
):
    from PySide6.QtWidgets import QDialog

    from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile
    from uniti.ui.file_format_dialogs import SaveAsSelection
    import uniti.ui.main_window as main_window

    _open(window, tmp_path / "source.txt", "dialog\n")
    target = tmp_path / "chosen.txt"
    selected = OutputFormat(encoding_profile("utf-8-bom"), EOLPolicy.CRLF)

    class AcceptedSaveAsDialog:
        def __init__(self, **kwargs):
            assert kwargs["initial_name"] == "source.txt"

        def exec(self):
            return QDialog.DialogCode.Accepted

        def result_selection(self):
            return SaveAsSelection(target, selected)

    monkeypatch.setattr(main_window, "SaveAsFormatDialog", AcceptedSaveAsDialog)

    assert window.save_current_as() == target
    assert window.current_view.document.path == target
    assert window.current_view.document.source_profile.key == "utf-8-bom"
