from pathlib import Path

from uniti.app.smoke import run_alpha_smoke, run_gui_smoke


def test_alpha_smoke_exercises_core_workflow(tmp_path: Path):
    result = run_alpha_smoke(tmp_path)
    assert result["ok"] is True
    assert result["regex_replacements"] == 2
    assert result["recovered_text"] == "abcX"
    assert result["external_change_blocked"] is True
    assert result["text_integrity"] is True
    assert result["utf16_output"].endswith("John [2026-09-01]\n")
    assert result["legacy_output"] == "café\nlegacy\n"


def test_gui_smoke_opens_and_self_closes_real_main_window(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    result = run_gui_smoke(tmp_path / "gui")

    assert result["ok"] is True
    assert result["window_shown"] is True
    assert result["document_profile"] == "utf-8"
    assert result["qt_platform"] == "offscreen"
