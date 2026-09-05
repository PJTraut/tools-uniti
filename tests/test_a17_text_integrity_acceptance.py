from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import tomllib

import pytest

from uniti.core.byte_source import ByteSource
from uniti.core.document import Document
from uniti.core.save import (
    SaveVerificationError,
    UnrepresentableCharacterError,
    UnresolvedMalformedBytesError,
)
from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile
from uniti.core.text_inspection import inspect_source


def test_a17_or_later_release_metadata_remains_coherent():
    import uniti

    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    display = Path("VERSION").read_text(encoding="utf-8").strip()
    assert display == uniti.__display_version__
    assert project["project"]["version"] == uniti.__version__
    assert display.startswith("v0.001a")
    assert uniti.__version__.startswith("0.1a")
    assert int(display.removeprefix("v0.001a")) >= 17


PROFILE_KEYS = (
    "utf-8",
    "utf-8-bom",
    "windows-1252",
    "utf-16-le",
    "utf-16-le-bom",
    "utf-16-be",
    "utf-16-be-bom",
    "utf-32-le",
    "utf-32-le-bom",
    "utf-32-be",
    "utf-32-be-bom",
)


@pytest.mark.parametrize("profile_key", PROFILE_KEYS)
@pytest.mark.parametrize(
    ("policy", "ending"),
    (
        (EOLPolicy.LF, "\n"),
        (EOLPolicy.CRLF, "\r\n"),
        (EOLPolicy.CR, "\r"),
    ),
)
def test_a17_exact_profile_edit_save_reopen_and_bytes(
    tmp_path: Path,
    profile_key: str,
    policy: EOLPolicy,
    ending: str,
):
    profile = encoding_profile(profile_key)
    if profile_key == "windows-1252":
        first_line = "Alpha café –"
    else:
        first_line = "Alpha café Привет Ω"
    initial_text = f"{first_line}\n"
    path = tmp_path / f"{profile_key}-{policy.value}.txt"
    path.write_bytes(profile.bom + initial_text.encode(profile.codec))

    with Document.open(path, profile=profile) as document:
        document.insert(document.total_chars(), "Edited\n")
        selected = OutputFormat(profile, policy)
        document.set_output_format(selected)
        assert document.save() == path
        assert document.source_profile == profile
        assert document.saved_output_format == selected
        assert document.output_format == selected
        assert document.modified is False

    expected_text = f"{first_line}{ending}Edited{ending}"
    expected_bytes = profile.bom + expected_text.encode(profile.codec)
    assert path.read_bytes() == expected_bytes
    with Document.open(path, profile=profile) as reopened:
        assert reopened.read(0, reopened.total_chars()) == expected_text
        assert reopened.source_profile == profile


def test_a17_mixed_eol_preserve_keeps_each_original_ending(tmp_path: Path):
    path = tmp_path / "mixed.txt"
    path.write_bytes(b"one\r\ntwo\nthree\r")

    with Document.open(path, profile=encoding_profile("utf-8")) as document:
        document.insert(0, "X")
        document.save()
        assert document.source_eol_report.kind == "MIXED"

    assert path.read_bytes() == b"Xone\r\ntwo\nthree\r"


def test_whitespace_modes_do_not_change_offsets_clipboard_or_saved_bytes(
    tmp_path: Path,
):
    if importlib.util.find_spec("PySide6") is None:
        pytest.skip("PySide6 is not installed")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from uniti.app.editor_state import EditorState
    from uniti.ui.text_view import UNITITextView
    from uniti.ui.whitespace import WhitespaceMode

    source = tmp_path / "whitespace-exact.txt"
    original = "a b\t\u00a0\u200b\r\n"
    encoded = original.encode("utf-8")
    source.write_bytes(encoded)
    app = QApplication.instance() or QApplication([])
    with Document.open(source, encoding="utf-8") as document:
        view = UNITITextView(EditorState(document, cursor=5, anchor=1))
        before = (document.revision, document.modified, view.state.selection)
        view.resize(480, 80)
        view.set_whitespace_mode(WhitespaceMode.ALL)
        view.show()
        view.viewport().repaint()
        app.processEvents()

        assert (document.revision, document.modified, view.state.selection) == before
        assert view.copy_selection() == document.read(1, 5)
        assert document.save() == source
        view.close()
    assert source.read_bytes() == encoded


def test_a17_malformed_utf8_same_profile_preserve_is_byte_exact(tmp_path: Path):
    path = tmp_path / "malformed.txt"
    path.write_bytes(b"A\xffB\r\n")

    with Document.open(path, profile=encoding_profile("utf-8")) as document:
        document.insert(1, "X")
        document.save()

    assert path.read_bytes() == b"AX\xffB\r\n"


def test_a17_malformed_conversion_is_blocked_without_touching_disk(tmp_path: Path):
    path = tmp_path / "malformed.txt"
    original = b"A\xffB\n"
    path.write_bytes(original)

    with Document.open(path, profile=encoding_profile("utf-8")) as document:
        document.set_output_format(
            OutputFormat(encoding_profile("utf-16-le-bom"), EOLPolicy.CRLF)
        )
        with pytest.raises(UnresolvedMalformedBytesError):
            document.save()

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".malformed.txt.*.uniti-tmp")) == []


def test_a17_windows_1252_rejects_cyrillic_without_touching_disk(tmp_path: Path):
    path = tmp_path / "cyrillic.txt"
    original = "Привет\n".encode("utf-8")
    path.write_bytes(original)

    with Document.open(path, profile=encoding_profile("utf-8")) as document:
        document.set_output_format(
            OutputFormat(encoding_profile("windows-1252"), EOLPolicy.PRESERVE)
        )
        with pytest.raises(UnrepresentableCharacterError) as exc_info:
            document.save()
        assert exc_info.value.character == "П"

    assert path.read_bytes() == original


def test_a17_low_confidence_override_is_explicit_and_exact(tmp_path: Path):
    path = tmp_path / "legacy.txt"
    path.write_bytes(b"Price \x96 10\r\n")
    with ByteSource.open(path) as source:
        automatic = inspect_source(source)
        explicit = inspect_source(
            source,
            override=encoding_profile("windows-1252"),
        )

    assert automatic.encoding.requires_confirmation is True
    assert automatic.encoding.confidence < 0.75
    assert explicit.encoding.suggested.key == "windows-1252"
    with Document.open(
        path,
        profile=encoding_profile("windows-1252"),
    ) as document:
        assert document.read(0, document.total_chars()) == "Price – 10\r\n"


@pytest.mark.parametrize(
    ("patched_name", "error"),
    (
        ("verify_staged_document", SaveVerificationError("injected refusal")),
        ("commit_staged_document", OSError("injected replace refusal")),
    ),
)
def test_a17_failed_verification_or_replacement_preserves_bytes_and_state(
    tmp_path: Path,
    monkeypatch,
    patched_name: str,
    error: Exception,
):
    path = tmp_path / "failure.txt"
    original = b"alpha\n"
    path.write_bytes(original)
    document = Document.open(path)
    try:
        document.insert(document.total_chars(), "beta\n")
        before = (
            document.path,
            document.disk_identity,
            document.revision,
            document.modified,
            document.output_format,
            document.saved_output_format,
            document.can_undo,
            document.can_redo,
        )

        def refuse(*args, **kwargs):
            raise error

        monkeypatch.setattr(f"uniti.core.document.{patched_name}", refuse)
        with pytest.raises(type(error), match="injected"):
            document.save()
        after = (
            document.path,
            document.disk_identity,
            document.revision,
            document.modified,
            document.output_format,
            document.saved_output_format,
            document.can_undo,
            document.can_redo,
        )
        assert after == before
    finally:
        document.close()

    assert path.read_bytes() == original
    assert list(tmp_path.glob(".failure.txt.*.uniti-tmp")) == []


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is not installed",
)
def test_a17_save_as_replaces_clean_open_target_without_duplicate_tab(
    tmp_path: Path, monkeypatch
):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from uniti.ui.main_window import UNITIMainWindow

    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_path.write_text("replacement\n", encoding="utf-8")
    target_path.write_text("old\n", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    source = window.open_path(source_path)
    target = window.open_path(target_path)
    assert source is not None and target is not None
    old_target_document = target.document
    window._tabs.setCurrentWidget(source)
    titles: list[str] = []

    def accept(_parent, title, text, *args, **kwargs):
        titles.append(title)
        return QMessageBox.StandardButton.Yes

    monkeypatch.setattr(QMessageBox, "warning", accept)
    try:
        assert (
            window.save_current_as(target_path, source.document.output_format)
            == target_path
        )
        assert titles == ["Replace Existing File", "Replace Open Document"]
        assert window._tabs.count() == 2
        assert window.current_view is target
        assert target.document is not old_target_document
        assert target_path.read_bytes() == b"replacement\n"
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()


@pytest.mark.skipif(
    importlib.util.find_spec("PySide6") is None,
    reason="PySide6 is not installed",
)
def test_a17_dirty_open_target_blocks_replacement_before_write(
    tmp_path: Path, monkeypatch
):
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QMessageBox

    from uniti.ui.main_window import UNITIMainWindow

    source_path = tmp_path / "source.txt"
    target_path = tmp_path / "target.txt"
    source_path.write_text("replacement\n", encoding="utf-8")
    target_path.write_text("old\n", encoding="utf-8")
    app = QApplication.instance() or QApplication([])
    window = UNITIMainWindow()
    source = window.open_path(source_path)
    target = window.open_path(target_path)
    assert source is not None and target is not None
    target.state.insert_text("dirty ")
    before = target_path.read_bytes()
    window._tabs.setCurrentWidget(source)
    titles: list[str] = []

    def record(_parent, title, text, *args, **kwargs):
        titles.append(title)
        return QMessageBox.StandardButton.Ok

    monkeypatch.setattr(QMessageBox, "warning", record)
    try:
        assert (
            window.save_current_as(target_path, source.document.output_format)
            is None
        )
        assert titles == ["Target Has Unsaved Changes"]
        assert target_path.read_bytes() == before
        assert window._tabs.count() == 2
    finally:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()
