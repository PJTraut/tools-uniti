import json
from pathlib import Path

from uniti.app.smoke import run_alpha_smoke, run_combined_smoke, run_gui_smoke
from scripts.alpha_smoke import DOGFOOD_SMOKE_FIELDS


def test_alpha_smoke_exercises_core_workflow(tmp_path: Path):
    result = run_alpha_smoke(tmp_path)
    assert result["ok"] is True
    assert result["regex_replacements"] == 2
    assert result["utf16_output_exact"] is True
    assert result["legacy_output_exact"] is True
    assert result["recovery_exact"] is True
    assert result["external_change_blocked"] is True
    assert result["text_integrity"] is True
    assert "Pieter [2026-08-31]" not in json.dumps(result)


def test_gui_smoke_opens_and_self_closes_real_main_window(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    result = run_gui_smoke(tmp_path / "gui")

    assert result["ok"] is True
    assert result["window_shown"] is True
    assert result["document_profile"] == "utf-8"
    assert result["qt_platform"] == "offscreen"
    assert result["platform_family"] in {"macos", "windows", "linux"}
    assert result["durability"] in {"full", "file_synced"}
    assert result["font"]["fixed_pitch"] is True
    assert result["font"]["latin_coverage"] is True
    assert result["font"]["cyrillic_coverage"] is True
    assert result["shortcut_defaults"] is True
    assert result["instance_forwarded"] is True
    assert result["unicode_spaced_path"] is True


def test_combined_smoke_exercises_service_lifetime_and_session_restart(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")

    result = run_combined_smoke(tmp_path / "combined")

    assert result["ok"] is True
    assert result["gui"]["service_remained_running"] is True
    assert result["gui"]["activation_created_window"] is True
    assert result["gui"]["one_document_authority"] is True
    assert result["gui"]["session_restored"] is True
    assert result["gui"]["history_restored"] is True
    assert result["gui"]["find_replace_restored"] is True
    assert result["gui"]["explicit_quit"] is True
    assert result["platform_family"] in {"macos", "windows", "linux"}
    assert result["qt_platform"] == "offscreen"
    assert result["durability"] in {"full", "file_synced"}
    assert result["font"]["fixed_pitch"] is True
    assert result["shortcut_defaults"] is True
    assert result["instance_forwarded"] is True
    assert result["unicode_spaced_path"] is True
    assert result["service_remained_running"] is True
    assert result["session_restored"] is True
    assert result["history_restored"] is True
    assert result["explicit_quit"] is True
    assert result["dogfood_single_owner"] is True
    assert result["dogfood_remained_active"] is True
    assert result["dogfood_published"] is True
    assert result["dogfood_retention_days"] == 7
    assert result["dogfood_aggregate_max_mib"] == 16
    assert set(DOGFOOD_SMOKE_FIELDS) <= set(result)
    serialized = json.dumps(result, ensure_ascii=False)
    assert str(tmp_path) not in serialized
    assert "UNITI smoke Привет" not in serialized
    assert "uniti-smoke-instance" not in serialized
    assert "dogfood_dir" not in serialized
    assert "operations" not in serialized
