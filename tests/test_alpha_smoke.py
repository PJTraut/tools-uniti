from pathlib import Path

from scripts.alpha_smoke import run_alpha_smoke


def test_alpha_smoke_exercises_core_workflow(tmp_path: Path):
    result = run_alpha_smoke(tmp_path)
    assert result["ok"] is True
    assert result["regex_replacements"] == 2
    assert result["recovered_text"] == "abcX"
    assert result["external_change_blocked"] is True
    assert result["utf16_output"].endswith("John [2026-09-01]\n")
    assert result["legacy_output"] == "café\nlegacy\n"
