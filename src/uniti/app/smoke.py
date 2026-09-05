"""Reproducible headless smoke workflow for the UNITI private alpha."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
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
    """Exercise process-lifetime service state through a complete restart."""

    directory = Path(base_dir)
    directory.mkdir(parents=True, exist_ok=True)
    source = directory / "gui-smoke.txt"
    source.write_text("UNITI smoke Привет\r\n", encoding="utf-8")

    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    from uniti.app.service import QuitChoice, UNITIService
    from uniti.app.session_store import SessionStore
    from uniti.app.settings import SettingsStore
    from uniti.resources import ResourceManager

    app = QApplication.instance() or QApplication(["uniti-smoke"])
    app.setQuitOnLastWindowClosed(False)
    store = SessionStore(directory / "sessions")
    first_service = None
    second_service = None

    def wait_until(predicate, *, timeout: float = 5.0) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            app.processEvents()
            if predicate():
                return
            time.sleep(0.005)
        app.processEvents()
        if not predicate():
            raise TimeoutError("GUI smoke state did not settle")

    try:
        first_resources = ResourceManager(max_workers=2)
        first_service = UNITIService(
            resource_manager=first_resources,
            settings_store=SettingsStore(directory / "first-settings.json"),
            session_store=store,
            recovery_manager=RecoveryManager(
                directory / "first-recovery",
                resource_manager=first_resources,
            ),
            service_id="smoke-first-service",
            build_identity="smoke-build",
        )
        window = first_service.new_window()
        view = window.open_path(source)
        if view is None:
            raise RuntimeError("GUI smoke document open was cancelled")
        window.show()
        app.processEvents()
        window_shown = window.isVisible()
        document_profile = view.document.source_profile.key
        qt_platform = QGuiApplication.platformName()
        entry = first_service.documents.entry_for_view(view.view_id)
        if entry is None:
            raise RuntimeError("GUI smoke document was not registered")
        view.document.insert(view.document.total_chars(), "saved")
        view.document.save()
        wait_until(lambda: entry.saved_stamp is not None)
        saved_text = view.document.read(0, view.document.total_chars())

        panel = first_service.find_replace
        panel.find_input.setPlainText("needle")
        panel.find_input.setPlainText("needle-next")
        panel.find_input.undo_input()
        panel.replace_input.setPlainText("replacement")
        panel.replace_input.setPlainText("replacement-next")
        panel.replace_input.undo_input()
        panel.regex_checkbox.setChecked(True)
        panel.show()
        first_service.set_active_view(window.window_id, view.view_id)
        first_service.attach_find_replace()
        app.processEvents()
        find_replace_attached = (
            panel.placement == "attached"
            and panel.parentWidget() is window
        )

        follow_window = first_service.new_window()
        first_service.set_active_view(follow_window.window_id, None)
        app.processEvents()
        find_replace_followed_window = (
            first_service.find_replace is panel
            and panel.placement == "attached"
            and panel.parentWidget() is follow_window
        )
        first_service.detach_find_replace()
        app.processEvents()
        find_replace_detached = (
            panel.placement == "detached" and panel.isFloating()
        )
        follow_window.close()
        wait_until(lambda: first_service.window_count == 1)

        original_document = view.document
        window.close()
        wait_until(lambda: first_service.window_count == 0)
        closed = not window.isVisible()
        service_remained_running = first_service.is_running

        activation = first_service.new_window()
        activation_view = activation.open_existing_document(original_document)
        activation.show()
        app.processEvents()
        activation_created_window = first_service.window_count == 1
        one_document_authority = (
            first_service.documents.count == 1
            and activation_view.document is original_document
        )
        first_quit = first_service.request_quit(
            lambda _entry: QuitChoice.DISCARD
        )
        app.processEvents()

        loaded = store.load_latest()
        if loaded.manifest is None:
            raise RuntimeError("GUI smoke session was not published")
        second_resources = ResourceManager(max_workers=2)
        second_service = UNITIService(
            resource_manager=second_resources,
            settings_store=SettingsStore(directory / "second-settings.json"),
            session_store=store,
            recovery_manager=RecoveryManager(
                directory / "second-recovery",
                resource_manager=second_resources,
            ),
            service_id="smoke-second-service",
            build_identity="smoke-build",
        )
        second_service.restore_shell(
            loaded.manifest,
            packs=loaded.packs,
            find_replace_pack=loaded.find_replace_pack,
        )
        second_service.restore_active()
        second_service.schedule_lazy_restore()
        wait_until(lambda: second_service.documents.count == 1)
        restored_entry = second_service.documents.entries[0]
        restored_panel = second_service.find_replace
        session_restored = (
            second_service.window_count == 1
            and second_service.active_view is not None
            and restored_entry.document.read(
                0, restored_entry.document.total_chars()
            )
            == saved_text
        )
        history_restored = restored_entry.document.can_undo
        find_replace_restored = (
            restored_panel.find_input.text() == "needle"
            and restored_panel.find_input.can_undo_input
            and restored_panel.find_input.can_redo_input
            and restored_panel.replace_input.text() == "replacement"
            and restored_panel.replace_input.can_undo_input
            and restored_panel.replace_input.can_redo_input
            and restored_panel.regex_checkbox.isChecked()
        )
        second_quit = second_service.request_quit(
            lambda _entry: QuitChoice.DISCARD
        )
        app.processEvents()
        explicit_quit = (
            first_quit
            and second_quit
            and not first_service.is_running
            and not second_service.is_running
        )
        return {
            "ok": (
                window_shown
                and closed
                and document_profile == "utf-8"
                and service_remained_running
                and activation_created_window
                and one_document_authority
                and session_restored
                and history_restored
                and find_replace_attached
                and find_replace_followed_window
                and find_replace_detached
                and find_replace_restored
                and explicit_quit
            ),
            "window_shown": window_shown,
            "window_closed": closed,
            "document_profile": document_profile,
            "qt_platform": qt_platform,
            "platform": sys.platform,
            "exit_code": 0,
            "service_remained_running": service_remained_running,
            "activation_created_window": activation_created_window,
            "one_document_authority": one_document_authority,
            "session_restored": session_restored,
            "history_restored": history_restored,
            "find_replace_attached": find_replace_attached,
            "find_replace_followed_window": find_replace_followed_window,
            "find_replace_detached": find_replace_detached,
            "find_replace_restored": find_replace_restored,
            "explicit_quit": explicit_quit,
        }
    except Exception as error:
        for service in (second_service, first_service):
            if service is not None and service.is_running:
                service.request_quit(lambda _entry: QuitChoice.DISCARD)
        app.processEvents()
        return {
            "ok": False,
            "window_shown": False,
            "window_closed": True,
            "document_profile": None,
            "qt_platform": QGuiApplication.platformName(),
            "platform": sys.platform,
            "exit_code": 1,
            "error": type(error).__name__,
            "service_remained_running": False,
            "activation_created_window": False,
            "one_document_authority": False,
            "session_restored": False,
            "history_restored": False,
            "find_replace_attached": False,
            "find_replace_followed_window": False,
            "find_replace_detached": False,
            "find_replace_restored": False,
            "explicit_quit": False,
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
