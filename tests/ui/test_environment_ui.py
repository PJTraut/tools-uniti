from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

if importlib.util.find_spec("PySide6") is None:  # pragma: no cover
    pytest.skip("PySide6 is not installed", allow_module_level=True)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from usfm_project_fixture import ensure_project, in_project  # noqa: E402
from uniti.app.file_environment_manager import FileEnvironmentManager  # noqa: E402
from uniti.app.settings import SettingsStore  # noqa: E402
from uniti.core.syntax_profiles import JSON, MARKDOWN, PLAIN_TEXT, USFM  # noqa: E402
from uniti.ui.environment_assignment_editor import (  # noqa: E402
    EnvironmentAssignmentEditor,
    parse_extensions,
)
from uniti.ui.main_window import UNITIMainWindow  # noqa: E402

_USFM = "\\id GEN\n\\c 1\n\\p\n\\v 1 In the beginning\n\\v 2 And\n"


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def window(app, tmp_path: Path):
    window = UNITIMainWindow(settings_store=SettingsStore(tmp_path / "settings.json"))
    yield window
    window.close_all_documents(force=True)
    window.close()
    app.processEvents()


def _open(window, tmp_path: Path, name: str, text: str):
    path = in_project(tmp_path / name)
    path.write_text(text, encoding="utf-8")
    return window.open_path(path)


def _menu_texts(window) -> list[str]:
    return [action.text() for action in window._environment.menu.actions() if not action.isSeparator()]


def test_menu_is_titled_after_the_active_environment(window, tmp_path: Path):
    environment = window._environment
    assert environment.menu.title() == "Environment"
    assert "No document open" in _menu_texts(window)

    _open(window, tmp_path, "book.usfm", _USFM)
    assert environment.menu.title() == "USFM"
    assert _menu_texts(window) == [
        "Go to Chapter:Verse…",
        "Validate USFM",
        "Check Marker Placement",
        "Check Undefined Markers",
        "Inspect Marker at Cursor",
        "Style Inspector…",
        "Load Stylesheet…",
        "Reload Project Stylesheets",
        "Export Resolved Stylesheet…",
        "Export Stylesheet Overrides…",
        "Plain Text",
        "Standard",
        "Preview",
        "Move to Environment Window",
        "Show One Chapter",
        "Lock Book",
        "Check Spelling",
        "Sync Side-by-Side by Reference",
        "Versification",
        "Configuration Files…",
        "Plain Text Mode",
        "Environment for This Document",
        "File Type Environments…",
    ]

    _open(window, tmp_path, "notes.txt", "hi")
    assert environment.menu.title() == "Plain Text"
    assert "Plain Text Mode" not in _menu_texts(window)
    # Plain text gets an environment window too (no reference sync).
    assert _menu_texts(window) == [
        "No environment tools for plain text",
        "Move to Environment Window",
        "Configuration Files…",
        "Environment for This Document",
        "File Type Environments…",
    ]


def test_menu_sits_between_view_and_tools(window):
    titles = [action.text() for action in window.menuBar().actions()]
    assert titles.index("Environment") == titles.index("&View") + 1
    assert titles.index("&Tools") == titles.index("Environment") + 1


def test_plain_text_mode_is_per_view_and_reversible(window, tmp_path: Path):
    environment = window._environment
    json_view = _open(window, tmp_path, "a.json", '{"a": 1}')
    assert json_view.syntax_profile is JSON

    environment.plain_mode_action.trigger()

    assert environment.is_plain_mode(json_view)
    assert json_view.syntax_profile is PLAIN_TEXT
    assert environment.menu.title() == "JSON (Plain Text)"
    assert environment.command_actions["format"].isEnabled() is False
    assert window.format_current_document() is False

    md_view = _open(window, tmp_path, "b.md", "# hi")
    assert md_view.syntax_profile is MARKDOWN
    assert environment.plain_mode_action.isChecked() is False

    window._select_view(json_view)
    assert environment.plain_mode_action.isChecked() is True
    environment.plain_mode_action.trigger()
    assert json_view.syntax_profile is JSON
    assert environment.menu.title() == "JSON"
    assert environment.command_actions["format"].isEnabled() is True


def test_plain_text_mode_wins_over_and_restores_the_per_view_profile(window, tmp_path: Path):
    view = _open(window, tmp_path, "a.json", "{}")
    window.set_syntax_choice("yaml")
    window._environment.set_plain_mode(True)
    assert view.syntax_profile is PLAIN_TEXT
    window._environment.set_plain_mode(False)
    assert view.syntax_profile.key == "yaml"


def test_plain_text_mode_disables_and_closes_markdown_preview(window, tmp_path: Path, app):
    _open(window, tmp_path, "b.md", "# hi")
    assert window._markdown_preview_action in window._environment.menu.actions()
    window.toggle_markdown_preview()
    assert window._markdown_preview is not None

    window._environment.set_plain_mode(True)

    assert window._markdown_preview is None
    assert window._markdown_preview_action.isEnabled() is False


def test_failed_activation_falls_back_to_plain_text_within_the_environment(app, tmp_path: Path):
    class Exploding:
        key = "json"

        def activate(self, context):
            raise RuntimeError("boom")

    manager = FileEnvironmentManager.with_builtin_environments()
    manager.register("json", Exploding)
    window = UNITIMainWindow(file_environment_manager=manager)
    try:
        view = _open(window, tmp_path, "a.json", "{}")
        environment = window._environment
        assert view.syntax_profile is PLAIN_TEXT
        assert environment.menu.title() == "JSON (Plain Text)"
        assert "JSON failed to load — showing Plain Text" in _menu_texts(window)
        assert environment.plain_mode_action.isChecked() is True
        assert environment.plain_mode_action.isEnabled() is False
        assert view.document.read(0, view.document.total_chars()) == "{}"
    finally:
        window.close_all_documents(force=True)
        window.close()


def test_go_to_verse_moves_the_caret(window, tmp_path: Path):
    view = _open(window, tmp_path, "book.usfm", _USFM)

    assert window._environment.run_command("go_to", "1:2") is True

    assert view.state.cursor == _USFM.index("\\v 2")


def test_validate_opens_a_findings_list_that_navigates(window, tmp_path: Path):
    text = '{"a": [1}\n'
    view = _open(window, tmp_path, "a.json", text)

    assert window._environment.run_command("validate") is True

    dialog = window._environment._findings_dialog
    assert dialog is not None and dialog.isVisible()
    assert dialog.list.count() >= 1
    assert dialog.list.item(0).text().startswith("Line 1, Col ")
    dialog.list.itemActivated.emit(dialog.list.item(0))
    assert view.state.cursor == text.index("}")
    dialog.close()


def test_command_exceptions_are_reported_not_raised(window, tmp_path: Path, monkeypatch):
    _open(window, tmp_path, "book.usfm", _USFM)
    shown = {}
    monkeypatch.setattr(
        QMessageBox, "critical", lambda parent, title, text, *a, **k: shown.update(title=title, text=text)
    )
    import uniti.core.environments.usfm_environment as usfm_module

    monkeypatch.setattr(
        usfm_module, "build_chapter_verse_index", lambda text: (_ for _ in ()).throw(RuntimeError("bad"))
    )

    assert window._environment.run_command("go_to", "1:1") is False
    assert "bad" in shown["text"]


def test_sfm_files_open_as_usfm_and_follow_reassignment(window, tmp_path: Path):
    """Round 2 R5: .sfm belongs to USFM; reassigning it switches open files."""

    view = _open(window, tmp_path, "book.sfm", _USFM)
    assert view.syntax_profile is USFM
    assert window._environment.menu.title() == "USFM"
    assert "Go to Chapter:Verse…" in _menu_texts(window)

    window.set_extension_assignments({"sfm": "plain_text"})

    assert window._environment.menu.title() == "Plain Text"
    assert window._settings_store.load().syntax_extension_overrides == {"sfm": "plain_text"}


def test_a_saved_sfm_assignment_is_read_as_usfm(window, tmp_path: Path):
    window.set_extension_assignments({"lex": "sfm"})
    ensure_project(tmp_path)
    view = _open(window, tmp_path, "words.lex", _USFM)
    assert view.syntax_profile is USFM
    assert window._environment.menu.title() == "USFM"


def test_assignment_editor_round_trips_and_rejects_conflicts(app, monkeypatch):
    editor = EnvironmentAssignmentEditor({})
    assert editor.assignments()["usfm"] == [".sfm", ".usfm"]  # one USFM row owns both
    editor.set_extensions("usfm", ".USFM + .sfm + .ptx")
    editor._save()
    assert editor.overrides() == {"ptx": "usfm"}

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warnings.append(a))
    conflicted = EnvironmentAssignmentEditor({})
    conflicted.set_extensions("xml", "xml, sfm")
    conflicted._save()
    assert warnings and conflicted.overrides() == {}

    reopened = EnvironmentAssignmentEditor({"ptx": "usfm"})
    assert reopened.assignments()["usfm"] == [".ptx", ".sfm", ".usfm"]


def test_parse_extensions_accepts_common_separators():
    assert parse_extensions(".USFM + .sfm") == [".USFM", ".sfm"]
    assert parse_extensions("usfm, sfm;  ptx") == ["usfm", "sfm", "ptx"]
    assert parse_extensions("  ") == []


def test_document_can_be_pinned_to_another_environment(window, tmp_path: Path):
    environment = window._environment
    ensure_project(tmp_path)
    view = _open(window, tmp_path, "book.txt", _USFM)
    assert environment.menu.title() == "Plain Text"
    assert environment.document_environment_actions[None].text() == "By Extension (Plain Text)"
    assert environment.document_environment_actions[None].isChecked()

    environment.document_environment_actions["usfm"].trigger()

    assert view.syntax_profile is USFM
    assert environment.menu.title() == "USFM"
    assert environment.document_environment_actions["usfm"].isChecked()
    assert environment.run_command("go_to", "1:2") is True
    assert view.state.cursor == _USFM.index("\\v 2")

    environment.document_environment_actions[None].trigger()
    assert view.syntax_profile is PLAIN_TEXT
    assert environment.menu.title() == "Plain Text"


def test_environment_slots_have_shortcuts_and_follow_the_environment(window, tmp_path: Path):
    actions = window._command_actions
    assert actions["environment.validate"].shortcut().toString() == "Ctrl+Alt+V"
    assert actions["environment.plain_mode"].shortcut().toString() == "Ctrl+Alt+T"
    assert all(actions[f"environment.{slot}"].isEnabled() is False for slot in ("format", "validate", "go_to"))

    view = _open(window, tmp_path, "book.usfm", _USFM)
    assert actions["environment.go_to"].isEnabled() is True
    assert actions["environment.validate"].isEnabled() is True
    assert actions["environment.format"].isEnabled() is False
    assert window._environment.command_actions["validate"] is actions["environment.validate"]
    assert actions["environment.validate"].text() == "Validate USFM"

    actions["environment.plain_mode"].trigger()
    assert view.environment_plain_mode is True
    assert actions["environment.go_to"].isEnabled() is False
    actions["environment.plain_mode"].trigger()
    assert view.environment_plain_mode is False
    assert actions["environment.go_to"].isEnabled() is True

    _open(window, tmp_path, "a.json", "{}")
    assert actions["environment.format"].isEnabled() is True
    assert actions["environment.go_to"].isEnabled() is False
    _open(window, tmp_path, "notes.txt", "x")
    assert actions["environment.plain_mode"].isEnabled() is False


def test_markdown_preview_is_the_environment_preview_slot(window, tmp_path: Path):
    assert window._command_actions["environment.preview"] is window._markdown_preview_action
    assert window._markdown_preview_action.shortcut().toString() == "Ctrl+Alt+P"


def test_plain_text_mode_is_saved_with_the_view(window, tmp_path: Path):
    view = _open(window, tmp_path, "a.json", "{}")
    assert "environment_plain_mode" not in view.export_state("doc").extra
    window._environment.set_plain_mode(True)
    record = view.export_state("doc")
    assert record.extra["environment_plain_mode"] is True


def test_style_inspector_opens_on_the_marker_at_the_cursor(window, tmp_path: Path):
    (tmp_path / "custom.sty").write_text("\\Marker q1\n\\FontSize 11\n", encoding="utf-8")
    text = "\\id GEN\n\\c 1\n\\q1 Poetry line\n"
    view = _open(window, tmp_path, "book.usfm", text)
    view.state.move_to(text.index("Poetry"))

    assert window._command_actions["environment.inspect"].isEnabled() is True
    window._command_actions["environment.inspect"].trigger()

    inspector = window._environment._style_inspector
    assert inspector is not None and inspector.isVisible()
    assert inspector.current_marker() == "q1"
    rows = inspector.detail_rows()
    assert rows["FontSize"] == ("11", "custom.sty", "12")
    assert rows["Effective source"][0] == "custom.sty"
    inspector.filter.setText("bd")
    visible = [inspector.markers.item(i).text() for i in range(inspector.markers.count()) if not inspector.markers.item(i).isHidden()]
    assert "\\bd" in visible and "\\q1" not in visible
    inspector.close()


def test_load_stylesheet_host_feature_layers_a_chosen_file(window, tmp_path: Path):
    extra = tmp_path / "house.sty"
    extra.write_text("\\Marker q1\n\\FontSize 9\n", encoding="utf-8")
    view = _open(window, tmp_path, "book.usfm", "\\q1 x\n")
    assert window._import_stylesheet_action.isEnabled() is True

    assert window._environment.import_stylesheet(extra) is True

    environment = window._environment.active_for(view.document).environment
    assert environment.layered_styles.formatting("q1")["fontsize"] == "9"
    window._environment.set_plain_mode(True)
    assert window._import_stylesheet_action.isEnabled() is False
    assert window._environment.import_stylesheet(extra) is False


def test_save_text_file_writes_the_exported_stylesheet(window, tmp_path: Path):
    (tmp_path / "custom.sty").write_text("\\Marker q1\n\\FontSize 11\n", encoding="utf-8")
    view = _open(window, tmp_path, "book.usfm", "\\q1 x\n")
    commands = {c.command_id: c for c in window._environment.commands_for(view)}
    from uniti.core.environment import EnvironmentContext

    result = commands["export_stylesheet_overrides"].run(EnvironmentContext.for_document(view.document), None)
    target = tmp_path / "out" / "overrides.sty"
    target.parent.mkdir()

    assert window._environment.save_text_file(view, result, target) is True

    assert "\\FontSize 11" in target.read_text(encoding="utf-8")
    assert not list(target.parent.glob(".*uniti-tmp"))
