from __future__ import annotations

import json
import os
import sys
from pathlib import Path


os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


def test_a21_ci_policy_and_driver_are_checked_in_with_bounded_contracts():
    import json

    policy_path = Path("ci/a21-skip-policy.json")
    driver_path = Path("scripts/a21_ci.py")

    assert policy_path.is_file()
    assert driver_path.is_file()
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    assert policy["schema"] == 1
    assert set(policy["families"]) == {"macos", "linux", "windows"}
    source = driver_path.read_text(encoding="utf-8")
    assert "shell=False" in source
    assert "ARTIFACT_RETENTION_DAYS = 7" in source
    assert "MAX_INPUT_BYTES = 2 << 20" in source
    assert "ci-results/" in Path(".gitignore").read_text(encoding="utf-8").splitlines()


def test_a21_workflow_is_pinned_read_only_and_runs_every_required_lane():
    workflow = Path(".github/workflows/a21-cross-platform.yml")

    assert workflow.is_file()
    source = workflow.read_text(encoding="utf-8")
    assert "name: A21 cross-platform" in source
    assert "  push:" in source
    assert "  pull_request:" in source
    assert "  workflow_dispatch:" in source
    for forbidden_trigger in ("pull_request_target:", "release:", "schedule:"):
        assert forbidden_trigger not in source
    assert "permissions:\n  contents: read" in source
    assert "contents: write" not in source
    assert "fail-fast: false" in source
    for row in (
        '{id: macos-py312, os: macos-15, python: "3.12", family: macos}',
        '{id: windows-py312, os: windows-2025, python: "3.12", family: windows}',
        '{id: linux-py312, os: ubuntu-24.04, python: "3.12", family: linux}',
        '{id: linux-latest, os: ubuntu-24.04, python: "3.x", family: linux}',
    ):
        assert source.count(row) == 1
    assert "name: ${{ matrix.id }}" in source
    assert "runs-on: ${{ matrix.os }}" in source
    assert "macos-latest" not in source
    assert "windows-latest" not in source
    assert "ubuntu-latest" not in source

    assert (
        "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1 # v7.0.1"
        in source
    )
    assert (
        "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97 # v7.0.0"
        in source
    )
    assert (
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a # v7.0.1"
        in source
    )
    assert "python-version: ${{ matrix.python }}" in source
    assert "allow-prereleases: false" in source
    assert "check-latest: ${{ matrix.python == '3.x' }}" in source
    assert "cache:" not in source

    assert "./uniti.command --dev --no-launch" in source
    assert "uniti.bat --dev --no-launch" in source
    assert "if: runner.os != 'Windows'" in source
    assert "if: runner.os == 'Windows'" in source
    assert "shell: cmd" in source
    for command in (
        "runtime --family ${{ matrix.family }}",
        "pytest --family ${{ matrix.family }}",
        "compile --family ${{ matrix.family }}",
        "self-check --family ${{ matrix.family }}",
        "smoke --mode offscreen --family ${{ matrix.family }}",
        "smoke --mode native --family ${{ matrix.family }}",
        "verify-skips --family ${{ matrix.family }}",
        "sanitize --family ${{ matrix.family }}",
    ):
        assert source.count(f"python scripts/a21_ci.py {command}") == 1
    assert source.count("if: failure()") == 2
    assert "path: ci-results/sanitized" in source
    assert "if-no-files-found: error" in source
    assert "retention-days: 7" in source
    assert "name: a21-${{ matrix.id }}" in source

    lowered = source.lower()
    assert "continue-on-error" not in lowered
    assert "secrets." not in lowered
    assert "pip install" not in lowered
    assert "python -m build" not in lowered
    assert "deploy" not in lowered


def test_a21_safe_diagnostics_omit_user_paths(tmp_path: Path):
    from uniti.app.diagnostics import diagnostics_snapshot
    from uniti.core.document import Document

    source = tmp_path / "Unicode Ω & spaced" / "private Привет.txt"
    source.parent.mkdir()
    source.write_text("private document content", encoding="utf-8")
    startup = {
        "session_path": str(tmp_path / "private-session"),
        "endpoint": "private-endpoint-name",
    }
    with Document.open(source) as document:
        ordinary = diagnostics_snapshot([document], startup_snapshot=startup)
        exported = diagnostics_snapshot(
            [document],
            startup_snapshot=startup,
            safe_for_export=True,
        )

    assert ordinary["documents"][0]["path"] == str(source)
    serialized = json.dumps(exported, ensure_ascii=False)
    assert "path" not in exported["documents"][0]
    assert "temp_root" not in exported["host"]
    assert "startup" not in exported
    assert str(tmp_path) not in serialized
    assert str(Path.home()) not in serialized
    assert os.environ.get("USER", "not-present") not in serialized
    assert "private document content" not in serialized
    assert "private-endpoint-name" not in serialized


def test_a21_combined_smoke_exports_only_bounded_cross_platform_facts(
    tmp_path: Path,
):
    from uniti.app.platform_policy import classify_platform
    from uniti.app.smoke import run_combined_smoke

    result = run_combined_smoke(tmp_path / "smoke private root")

    assert result["ok"] is True
    assert result["platform_family"] == classify_platform(sys.platform).value
    assert result["qt_platform"] == "offscreen"
    assert result["durability"] in {"full", "file_synced"}
    assert result["font"]["fixed_pitch"] is True
    assert result["font"]["latin_coverage"] is True
    assert result["font"]["cyrillic_coverage"] is True
    assert result["shortcut_defaults"] is True
    assert result["instance_forwarded"] is True
    assert result["unicode_spaced_path"] is True
    serialized = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "UNITI smoke Привет" not in serialized


def test_a21_editor_docking_preserves_authority_layout_and_bytes(tmp_path: Path):
    from PySide6.QtWidgets import QApplication, QDockWidget

    from uniti.app.session import DockReturnRecord
    from uniti.app.session_store import SessionStore
    from uniti.app.service import QuitChoice, UNITIService
    from uniti.app.settings import SettingsStore
    from uniti.resources import ResourceManager
    from uniti.ui.theme import active_theme
    from uniti.ui.whitespace import WhitespaceMode

    class Recovery:
        def attach(self, _document, **_kwargs):
            return None

        def detach(self, _document, *, clean):
            return None

        def shutdown(self):
            return None

    app = QApplication.instance() or QApplication([])
    source_path = tmp_path / "docking-integrity.txt"
    original_bytes = b"alpha\nbeta\ngamma\n"
    source_path.write_bytes(original_bytes)
    service = UNITIService(
        resource_manager=ResourceManager(max_workers=2),
        settings_store=SettingsStore(tmp_path / "settings.json"),
        session_store=SessionStore(tmp_path / "sessions"),
        recovery_manager=Recovery(),
    )
    window = service.new_window()
    original = window.open_path(source_path)
    assert original is not None
    clone = window.split_right()
    assert clone is not None
    location = window.view_location(clone.view_id)
    try:
        assert clone.document is original.document
        assert service.documents.count == 1

        detached = service.undock_view(clone.view_id)

        expected_anchor = DockReturnRecord(
            window.window_id,
            location.pane_id,
            location.tab_index,
        )
        assert clone.dock_return == expected_anchor
        captured = service.capture_session(clean_shutdown=False)
        captured_view = next(
            item for item in captured.manifest.views if item.view_id == clone.view_id
        )
        assert captured_view.dock_return == expected_anchor
        assert all(
            not isinstance(parent, QDockWidget)
            for parent in _widget_ancestors(clone)
        )

        service.dock_view(clone.view_id)

        assert window.view_location(clone.view_id) == location
        assert detached not in service.windows.windows
        assert clone.dock_return is None
        assert source_path.read_bytes() == original_bytes
        assert clone.document.read(0, clone.document.total_chars()) == (
            original_bytes.decode("utf-8")
        )

        panel = service.find_replace
        panel.find_input.set_text("beta")
        service.set_active_view(window.window_id, original.view_id)
        service.attach_find_replace()
        assert panel.parentWidget() is window
        assert panel.placement == "attached"

        second = service.new_window()
        service.set_active_view(second.window_id, None)
        assert service.find_replace is panel
        assert panel.parentWidget() is second
        assert panel.find_input.text() == "beta"

        service.detach_find_replace()
        assert panel.placement == "detached"
        assert panel.isFloating() is True
        assert service.capture_session().manifest.find_replace.placement == "detached"

        window.set_whitespace_mode(WhitespaceMode.ALL)
        window.set_theme("Dark")
        window.set_theme_contrast("High Contrast")
        assert original.whitespace_mode is WhitespaceMode.ALL
        assert active_theme(app).mode == "Dark"
        assert active_theme(app).contrast == "High Contrast"
        assert source_path.read_bytes() == original_bytes
    finally:
        if service.is_running:
            service.request_quit(lambda _entry: QuitChoice.DISCARD)
        app.processEvents()


def _widget_ancestors(widget):
    parent = widget.parentWidget()
    while parent is not None:
        yield parent
        parent = parent.parentWidget()
