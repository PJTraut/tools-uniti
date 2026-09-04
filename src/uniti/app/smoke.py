"""Reproducible headless smoke workflow for the UNITI private alpha."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from uniti.app.recovery_manager import RecoveryManager
from uniti.core.document import Document
from uniti.core.file_identity import ExternalFileChangedError
from uniti.core.text_format import EOLPolicy, OutputFormat, encoding_profile
from uniti.regex.engine import compile_pattern
from uniti.regex.replace import replace_all


def _run_in(directory: Path) -> dict[str, object]:
    directory.mkdir(parents=True, exist_ok=True)

    regex_source = directory / "regex-input.txt"
    regex_output = directory / "regex-output-utf16.txt"
    regex_source.write_bytes(
        "2026-08-31 Pieter\r\n2026-09-01 John\r\n".encode("utf-8")
    )
    pattern = compile_pattern(r"(?P<date>\d{4}-\d{2}-\d{2})\s+(?P<name>\w+)")
    with Document.open(regex_source) as document:
        replacements = replace_all(document, pattern, r"\g<name> [\g<date>]")
        document.set_output_encoding("utf-16-le")
        document.set_output_eol("LF")
        document.export_copy(regex_output, output_format=document.output_format)
    with Document.open(regex_output, encoding="utf-16-le") as reopened:
        utf16_output = reopened.read(0, reopened.total_chars())

    legacy_source = directory / "legacy-cp1252.txt"
    legacy_output = directory / "legacy-normalized.txt"
    legacy_source.write_bytes(b"caf\xe9\rlegacy\r")
    with Document.open(legacy_source, encoding="windows-1252") as document:
        document.set_output_eol("LF")
        document.export_copy(legacy_output, output_format=document.output_format)
    legacy_output_text = legacy_output.read_bytes().decode("windows-1252")

    integrity_source = directory / "integrity-source.txt"
    integrity_output = directory / "integrity-output-utf16be-bom.txt"
    integrity_text = "Western café Привет\n"
    integrity_source.write_bytes(integrity_text.encode("utf-8"))
    integrity_format = OutputFormat(
        encoding_profile("utf-16-be-bom"),
        EOLPolicy.CRLF,
    )
    with Document.open(
        integrity_source,
        profile=encoding_profile("utf-8"),
    ) as document:
        document.export_copy(
            integrity_output,
            output_format=integrity_format,
            expected_destination_identity=None,
        )
    integrity_payload = integrity_output.read_bytes()
    expected_integrity_payload = (
        integrity_format.encoding.bom
        + "Western café Привет\r\n".encode(integrity_format.encoding.codec)
    )
    with Document.open(
        integrity_output,
        profile=integrity_format.encoding,
    ) as reopened:
        integrity_reopened = reopened.read(0, reopened.total_chars())
    text_integrity = (
        integrity_payload == expected_integrity_payload
        and integrity_reopened == "Western café Привет\r\n"
        and integrity_payload.startswith(b"\xfe\xff")
    )

    recovery_source = directory / "recovery-source.txt"
    recovery_source.write_text("abc", encoding="utf-8")
    recovery_dir = directory / "recovery"
    first_manager = RecoveryManager(recovery_dir)
    recovery_document = Document.open(recovery_source)
    first_manager.attach(recovery_document)
    recovery_document.insert(3, "X")
    first_manager.detach(recovery_document, clean=False)
    recovery_document.close()
    second_manager = RecoveryManager(recovery_dir)
    candidate = second_manager.discover()[0]
    recovered = second_manager.recover(candidate)
    try:
        recovered_text = recovered.read(0, recovered.total_chars())
    finally:
        second_manager.detach(recovered, clean=True)
        recovered.close()

    external_source = directory / "external-source.txt"
    external_replacement = directory / "external-replacement.txt"
    external_source.write_text("abc", encoding="utf-8")
    external_change_blocked = False
    with Document.open(external_source) as document:
        document.insert(3, "X")
        external_replacement.write_text("changed elsewhere", encoding="utf-8")
        external_replacement.replace(external_source)
        try:
            document.save()
        except ExternalFileChangedError:
            external_change_blocked = True

    return {
        "ok": (
            replacements == 2
            and utf16_output == "Pieter [2026-08-31]\nJohn [2026-09-01]\n"
            and legacy_output_text == "café\nlegacy\n"
            and recovered_text == "abcX"
            and external_change_blocked
            and text_integrity
        ),
        "regex_replacements": replacements,
        "utf16_output": utf16_output,
        "legacy_output": legacy_output_text,
        "recovered_text": recovered_text,
        "external_change_blocked": external_change_blocked,
        "text_integrity": text_integrity,
    }


def run_alpha_smoke(base_dir: str | Path | None = None) -> dict[str, object]:
    if base_dir is not None:
        return _run_in(Path(base_dir))
    with tempfile.TemporaryDirectory(prefix="uniti-alpha-smoke-") as temporary:
        return _run_in(Path(temporary))


def run_gui_smoke(base_dir: str | Path) -> dict[str, object]:
    """Open a real main window on the selected Qt platform and self-close."""

    directory = Path(base_dir)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "gui-smoke.txt"
    source.write_text("UNITI smoke Привет\r\n", encoding="utf-8")

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from uniti.ui.main_window import UNITIMainWindow

    app = QApplication.instance() or QApplication(["uniti-smoke"])
    app.setQuitOnLastWindowClosed(True)
    window = UNITIMainWindow()
    try:
        view = window.open_path(source)
        if view is None:
            raise RuntimeError("GUI smoke document open was cancelled")
        window.show()
        app.processEvents()
        window_shown = window.isVisible()
        document_profile = view.document.source_profile.key
        qt_platform = QGuiApplication.platformName()
        QTimer.singleShot(250, window.close)
        exit_code = int(app.exec())
        closed = not window.isVisible()
        return {
            "ok": (
                exit_code == 0
                and window_shown
                and closed
                and document_profile == "utf-8"
            ),
            "window_shown": window_shown,
            "window_closed": closed,
            "document_profile": document_profile,
            "qt_platform": qt_platform,
            "platform": sys.platform,
            "exit_code": exit_code,
        }
    except Exception as error:
        window.close_all_documents(force=True)
        window.close()
        app.processEvents()
        return {
            "ok": False,
            "window_shown": False,
            "window_closed": not window.isVisible(),
            "document_profile": None,
            "qt_platform": QGuiApplication.platformName(),
            "platform": sys.platform,
            "exit_code": 1,
            "error": type(error).__name__,
        }


def run_combined_smoke(base_dir: str | Path | None = None) -> dict[str, object]:
    def run(directory: Path) -> dict[str, object]:
        core = run_alpha_smoke(directory / "core")
        gui = run_gui_smoke(directory / "gui")
        return {
            "ok": core.get("ok") is True and gui.get("ok") is True,
            "core_ok": core.get("ok") is True,
            "gui_ok": gui.get("ok") is True,
            "core": core,
            "gui": gui,
        }

    if base_dir is not None:
        return run(Path(base_dir))
    with tempfile.TemporaryDirectory(prefix="uniti-combined-smoke-") as temporary:
        return run(Path(temporary))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, help="keep smoke artifacts in this directory")
    args = parser.parse_args(argv)
    result = run_alpha_smoke(args.workdir)
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
