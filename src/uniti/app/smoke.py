"""Reproducible headless smoke workflow for the UNITI private alpha."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path

from uniti.app.recovery_manager import RecoveryManager
from uniti.core.document import Document
from uniti.core.durability import NativeDurabilityAdapter
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
    try:
        recovery_document = Document.open(recovery_source)
        try:
            first_manager.attach(recovery_document)
            recovery_document.insert(3, "X")
            first_manager.detach(recovery_document, clean=False)
        finally:
            recovery_document.close()
    finally:
        first_manager.shutdown()
    second_manager = RecoveryManager(recovery_dir)
    try:
        candidate = second_manager.discover()[0]
        recovered = second_manager.recover(candidate)
        try:
            recovered_text = recovered.read(0, recovered.total_chars())
        finally:
            second_manager.detach(recovered, clean=True)
            recovered.close()
    finally:
        second_manager.shutdown()

    utf16_output_exact = (
        utf16_output == "Pieter [2026-08-31]\nJohn [2026-09-01]\n"
    )
    legacy_output_exact = legacy_output_text == "café\nlegacy\n"
    recovery_exact = recovered_text == "abcX"

    external_source = directory / "external-source.txt"
    external_replacement = directory / "external-replacement.txt"
    external_source.write_text("abc", encoding="utf-8")
    external_change_blocked = False
    with Document.open(external_source) as document:
        document.insert(3, "X")
        external_replacement.write_text("changed elsewhere", encoding="utf-8")
        NativeDurabilityAdapter().replace(external_replacement, external_source)
        try:
            document.save()
        except ExternalFileChangedError:
            external_change_blocked = True

    return {
        "ok": (
            replacements == 2
            and utf16_output_exact
            and legacy_output_exact
            and recovery_exact
            and external_change_blocked
            and text_integrity
        ),
        "regex_replacements": replacements,
        "utf16_output_exact": utf16_output_exact,
        "legacy_output_exact": legacy_output_exact,
        "recovery_exact": recovery_exact,
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
    source_directory = directory / "Unicode Ω & spaced"
    source_directory.mkdir(parents=True, exist_ok=True)
    source = source_directory / "gui-smoke Привет.txt"
    source.write_text("UNITI smoke Привет\r\n", encoding="utf-8")

    from PySide6.QtGui import QGuiApplication, QKeySequence
    from PySide6.QtWidgets import QApplication

    from uniti.app.instance_protocol import (
        InstancePathOutcome,
        InstanceReply,
        InstanceRequest,
    )
    from uniti.app.instance_service import InstanceRole, InstanceService
    from uniti.app.dogfood import (
        OSFamily,
        DogfoodRecorder,
        HostFacts,
        classify_cpu,
        classify_ram,
    )
    from uniti.app.dogfood_store import DogfoodStore
    from uniti.app.platform_policy import classify_platform
    from uniti.app.service import QuitChoice, UNITIService
    from uniti.app.session_store import SessionStore
    from uniti.app.settings import SettingsStore
    from uniti.resources import ResourceManager, load_performance_policy
    from uniti.ui.font_policy import resolve_editor_font
    from uniti.ui.shortcut_policy import build_shortcut_policy
    from uniti.ui.theme import active_theme
    from uniti.ui.whitespace import WhitespaceMode

    app = QApplication.instance() or QApplication(["uniti-smoke"])
    app.setQuitOnLastWindowClosed(False)
    store = SessionStore(directory / "sessions")
    first_service = None
    second_service = None
    first_resources = None
    second_resources = None
    first_recorder = None
    second_recorder = None
    first_dogfood_store = None
    second_dogfood_store = None
    primary_instance = None
    forwarding_instance = None

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
        family = classify_platform(sys.platform).value
        dogfood_policy = load_performance_policy().dogfood

        def dogfood_runtime(resources, name: str):
            os_family = {
                "macos": OSFamily.MACOS,
                "windows": OSFamily.WINDOWS,
                "linux": OSFamily.LINUX,
            }[family]
            profile = resources.host_profile
            return (
                DogfoodRecorder(
                    HostFacts(
                        "smoke-build",
                        os_family,
                        classify_cpu(profile.logical_cores),
                        classify_ram(profile.physical_memory),
                    ),
                    day=date.today(),
                ),
                DogfoodStore(
                    directory / name,
                    retention_days=dogfood_policy.retention_days,
                    aggregate_max_bytes=dogfood_policy.aggregate_max_mib << 20,
                ),
            )
        font_resolution = resolve_editor_font()
        font = {
            "requested_family": font_resolution.requested_family[:128],
            "resolved_family": font_resolution.resolved_family[:128],
            "fixed_pitch": font_resolution.fixed_pitch,
            "latin_coverage": font_resolution.latin_coverage,
            "cyrillic_coverage": font_resolution.cyrillic_coverage,
            "fallback": font_resolution.fallback,
        }
        shortcuts = build_shortcut_policy({})
        definitions = {
            item.command_id: item.default_shortcut
            for item in shortcuts.definitions
        }
        standard = QKeySequence.StandardKey
        portable = QKeySequence.SequenceFormat.PortableText
        expected_shortcuts = {
            "file.open": QKeySequence(standard.Open).toString(portable),
            "file.save": QKeySequence(standard.Save).toString(portable),
            "editing.undo": QKeySequence(standard.Undo).toString(portable),
            "find.open": QKeySequence(standard.Find).toString(portable),
            "find.next": QKeySequence(standard.FindNext).toString(portable),
        }
        shortcut_defaults = (
            not shortcuts.notices
            and all(expected_shortcuts.values())
            and all(
                definitions.get(command_id) == sequence
                for command_id, sequence in expected_shortcuts.items()
            )
        )

        endpoint = f"uniti-smoke-instance-{uuid.uuid4().hex}"
        primary_instance = InstanceService(directory / "instance.lock", endpoint)
        forwarding_instance = InstanceService(directory / "instance.lock", endpoint)
        received: list[InstanceRequest] = []

        def accept_instance(connection, request: InstanceRequest) -> None:
            received.append(request)
            primary_instance.reply(
                connection,
                InstanceReply(
                    True,
                    tuple(
                        InstancePathOutcome(path, True, None)
                        for path in request.files
                    ),
                    None,
                ),
            )

        primary_instance.requestReceived.connect(accept_instance)
        primary_start = primary_instance.start(InstanceRequest(1, True, ()))
        forwarded_start = forwarding_instance.start(
            InstanceRequest(1, True, (str(source.resolve()),))
        )
        instance_forwarded = (
            primary_start.role is InstanceRole.PRIMARY
            and forwarded_start.role is InstanceRole.FORWARDED
            and forwarded_start.reply is not None
            and forwarded_start.reply.accepted
            and len(forwarded_start.reply.outcomes) == 1
            and received == [
                InstanceRequest(1, True, (str(source.resolve()),))
            ]
        )
        forwarding_instance.close()
        primary_instance.close()

        first_resources = ResourceManager(max_workers=2)
        first_recorder, first_dogfood_store = dogfood_runtime(
            first_resources,
            "first-dogfood",
        )
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
            dogfood_recorder=first_recorder,
            dogfood_store=first_dogfood_store,
            dogfood_publish_interval_seconds=dogfood_policy.publish_interval_seconds,
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
        from uniti.ui.find_replace import FIND_REPLACE_VIEW_ID

        find_replace_attached = (
            panel.placement == "attached"
            and panel._dock_host is window
            and window.panes.contains_view(FIND_REPLACE_VIEW_ID)
        )

        follow_window = first_service.new_window()
        first_service.set_active_view(follow_window.window_id, None)
        app.processEvents()
        find_replace_followed_window = (
            first_service.find_replace is panel
            and panel.placement == "attached"
            and panel._dock_host is follow_window
            and follow_window.panes.contains_view(FIND_REPLACE_VIEW_ID)
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
        if (
            first_service.window_count != 1
            or not window.isVisible()
            or window.views
        ):
            raise RuntimeError("last editor window did not remain available")
        # Retain coverage for old zero-window sessions and service-owned teardown.
        window.close_for_service()
        wait_until(lambda: first_service.window_count == 0)
        closed = first_service.window_count == 0
        service_remained_running = first_service.is_running
        dogfood_active_without_window = first_service.dogfood_is_active

        activation = first_service.new_window()
        activation_view = activation.open_existing_document(original_document)
        activation.show()
        app.processEvents()
        activation_created_window = first_service.window_count == 1
        one_document_authority = (
            first_service.documents.count == 1
            and activation_view.document is original_document
        )
        first_recorder_owned = (
            first_service.dogfood_recorder is first_recorder
            and first_service.dogfood_store is first_dogfood_store
        )
        activation.set_whitespace_mode(WhitespaceMode.ALL)
        activation.set_theme("Dark")
        activation.set_theme_contrast("High Contrast")
        display_settings_applied = (
            activation_view.whitespace_mode is WhitespaceMode.ALL
            and active_theme(app).mode == "Dark"
            and active_theme(app).contrast == "High Contrast"
        )
        first_quit = first_service.request_quit(
            lambda _entry: QuitChoice.DISCARD
        )
        app.processEvents()

        loaded = store.load_latest()
        if loaded.manifest is None:
            raise RuntimeError("GUI smoke session was not published")
        second_resources = ResourceManager(max_workers=2)
        second_recorder, second_dogfood_store = dogfood_runtime(
            second_resources,
            "second-dogfood",
        )
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
            dogfood_recorder=second_recorder,
            dogfood_store=second_dogfood_store,
            dogfood_publish_interval_seconds=dogfood_policy.publish_interval_seconds,
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
        first_dogfood_status = first_dogfood_store.status()
        second_dogfood_status = second_dogfood_store.status()
        dogfood_single_owner = (
            first_recorder_owned
            and second_service.dogfood_recorder is second_recorder
            and second_service.dogfood_store is second_dogfood_store
            and first_recorder is not second_recorder
        )
        dogfood_remained_active = (
            dogfood_active_without_window
            and first_service.dogfood_is_active is False
            and second_service.dogfood_is_active is False
        )
        dogfood_published = (
            first_dogfood_status.available
            and second_dogfood_status.available
            and first_dogfood_status.segment_count >= 1
            and second_dogfood_status.segment_count >= 1
            and first_dogfood_status.byte_count
            <= dogfood_policy.aggregate_max_mib << 20
            and second_dogfood_status.byte_count
            <= dogfood_policy.aggregate_max_mib << 20
        )
        durability_result = store.last_durability
        durability = (
            "unsafe"
            if durability_result is None
            else durability_result.level.value
        )
        unicode_spaced_path = (
            source.parent.name == "Unicode Ω & spaced"
            and source.name == "gui-smoke Привет.txt"
            and source.resolve().is_absolute()
        )
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
                and display_settings_applied
                and durability in {"full", "file_synced"}
                and font["fixed_pitch"]
                and font["latin_coverage"]
                and font["cyrillic_coverage"]
                and shortcut_defaults
                and instance_forwarded
                and unicode_spaced_path
                and explicit_quit
                and dogfood_single_owner
                and dogfood_remained_active
                and dogfood_published
            ),
            "window_shown": window_shown,
            "window_closed": closed,
            "document_profile": document_profile,
            "qt_platform": qt_platform,
            "platform_family": family,
            "exit_code": 0,
            "durability": durability,
            "font": font,
            "shortcut_defaults": shortcut_defaults,
            "instance_forwarded": instance_forwarded,
            "unicode_spaced_path": unicode_spaced_path,
            "service_remained_running": service_remained_running,
            "activation_created_window": activation_created_window,
            "one_document_authority": one_document_authority,
            "session_restored": session_restored,
            "history_restored": history_restored,
            "find_replace_attached": find_replace_attached,
            "find_replace_followed_window": find_replace_followed_window,
            "find_replace_detached": find_replace_detached,
            "find_replace_restored": find_replace_restored,
            "display_settings_applied": display_settings_applied,
            "explicit_quit": explicit_quit,
            "dogfood_single_owner": dogfood_single_owner,
            "dogfood_remained_active": dogfood_remained_active,
            "dogfood_published": dogfood_published,
            "dogfood_retention_days": dogfood_policy.retention_days,
            "dogfood_aggregate_max_mib": dogfood_policy.aggregate_max_mib,
        }
    except Exception as error:
        return {
            "ok": False,
            "window_shown": False,
            "window_closed": True,
            "document_profile": None,
            "qt_platform": QGuiApplication.platformName(),
            "platform_family": classify_platform(sys.platform).value,
            "exit_code": 1,
            "error": type(error).__name__,
            "durability": "unsafe",
            "font": {
                "requested_family": "unknown",
                "resolved_family": "unknown",
                "fixed_pitch": False,
                "latin_coverage": False,
                "cyrillic_coverage": False,
                "fallback": True,
            },
            "shortcut_defaults": False,
            "instance_forwarded": False,
            "unicode_spaced_path": False,
            "service_remained_running": False,
            "activation_created_window": False,
            "one_document_authority": False,
            "session_restored": False,
            "history_restored": False,
            "find_replace_attached": False,
            "find_replace_followed_window": False,
            "find_replace_detached": False,
            "find_replace_restored": False,
            "display_settings_applied": False,
            "explicit_quit": False,
            "dogfood_single_owner": False,
            "dogfood_remained_active": False,
            "dogfood_published": False,
            "dogfood_retention_days": 7,
            "dogfood_aggregate_max_mib": 16,
        }
    finally:
        for service in (second_service, first_service):
            if service is not None and service.is_running:
                service.request_quit(lambda _entry: QuitChoice.DISCARD)
        for instance in (forwarding_instance, primary_instance):
            if instance is not None:
                instance.close()
        for resources in (second_resources, first_resources):
            if resources is not None:
                resources.shutdown()
        app.processEvents()


def run_combined_smoke(base_dir: str | Path | None = None) -> dict[str, object]:
    def run(directory: Path) -> dict[str, object]:
        core = run_alpha_smoke(directory / "core")
        gui = run_gui_smoke(directory / "gui")
        combined = {
            "ok": core.get("ok") is True and gui.get("ok") is True,
            "core_ok": core.get("ok") is True,
            "gui_ok": gui.get("ok") is True,
            "core": core,
            "gui": gui,
        }
        for name in (
            "platform_family",
            "qt_platform",
            "durability",
            "font",
            "shortcut_defaults",
            "instance_forwarded",
            "unicode_spaced_path",
            "service_remained_running",
            "activation_created_window",
            "one_document_authority",
            "session_restored",
            "history_restored",
            "find_replace_attached",
            "find_replace_followed_window",
            "find_replace_detached",
            "find_replace_restored",
            "display_settings_applied",
            "explicit_quit",
            "dogfood_single_owner",
            "dogfood_remained_active",
            "dogfood_published",
            "dogfood_retention_days",
            "dogfood_aggregate_max_mib",
        ):
            combined[name] = gui.get(name)
        return combined

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
