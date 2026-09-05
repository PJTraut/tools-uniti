from __future__ import annotations

from pathlib import Path

from benchmarks.corpus import CorpusKind, CorpusSpec, generate_corpus
from benchmarks.models import ResultState
from benchmarks.sustained_workloads import run_sustained_workload


def test_lifecycle_cycle_restores_one_service_and_cleans_recovery(
    tmp_path: Path,
):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=32_768, seed=18),
        tmp_path / "corpus",
    )
    application_root = (tmp_path / "application").resolve()
    application_root.mkdir()

    result = run_sustained_workload(
        "session_lifecycle",
        profile="hosted",
        cycles=1,
        manifest=manifest,
        application_root=application_root,
    )

    assert result.state is ResultState.PASS
    assert result.warmup_cycles == 1
    assert result.measured_cycles == 1
    assert len(result.checkpoints) == 1
    checkpoint = result.checkpoints[0]
    assert checkpoint.cycle == 1
    assert checkpoint.metrics["lifecycle_cycle_ms"] >= 0
    assert all(
        checkpoint.owned_counts[name] == 0
        for name in (
            "documents",
            "views",
            "active_tasks",
            "queued_tasks",
            "result_stores",
            "replacement_plans",
            "snapshots",
        )
    )
    assert result.facts["cycles_completed"] == 2
    assert result.facts["service_identity_reused"] is True
    assert result.facts["one_global_panel"] is True
    assert result.facts["panel_attach_detach"] is True
    assert result.facts["one_authority_per_path"] is True
    assert result.facts["independent_view_state"] is True
    assert result.facts["service_survived_last_window"] is True
    assert result.facts["activation_created_window"] is True
    assert result.facts["session_generation_current"] is True
    assert result.facts["active_first_restored"] is True
    assert result.facts["lazy_documents_restored"] is True
    assert result.facts["history_undo_redo_exact"] is True
    assert result.facts["find_replace_history_restored"] is True
    assert result.facts["background_storage"] is True
    assert result.facts["injected_capacity"] is True
    assert result.facts["injected_durability"] is True
    assert result.facts["injected_resource_pressure"] is True
    assert result.facts["injected_worker_state"] is True
    assert result.facts["recovery_choices"] == ("recover", "discard")
    assert result.facts["recovery_undo_redo_exact"] is True
    assert result.facts["recovery_cleanup"] is True
    assert result.facts["explicit_quit"] is True
    assert result.facts["integrity_ok"] is True
    assert result.facts["cleanup_ok"] is True
    assert result.messages == ()


def test_lifecycle_reuses_owned_fixture_paths_across_measured_cycles(
    tmp_path: Path,
):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=1_024, seed=19),
        tmp_path / "corpus",
    )
    application_root = (tmp_path / "application").resolve()
    application_root.mkdir()

    result = run_sustained_workload(
        "session_lifecycle",
        profile="hosted",
        cycles=5,
        manifest=manifest,
        application_root=application_root,
    )

    assert result.state is ResultState.PASS
    assert len(result.checkpoints) == 5
    assert len(
        {checkpoint.owned_counts["temp_paths"] for checkpoint in result.checkpoints}
    ) == 1
