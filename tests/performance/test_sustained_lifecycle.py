from __future__ import annotations

from pathlib import Path

import benchmarks.sustained_workloads as sustained_workloads
from benchmarks.corpus import CorpusKind, CorpusSpec, generate_corpus
from benchmarks.models import ResultState
from benchmarks.sustained_workloads import run_sustained_workload
from uniti.core.durability import NativeDurabilityAdapter


def test_lifecycle_uses_a_bounded_alternating_find_replace_vocabulary():
    values = [
        sustained_workloads._lifecycle_panel_values(sequence)
        for sequence in range(51)
    ]

    assert len(set(values)) == 2
    assert all(current != following for current, following in zip(values, values[1:]))


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
    assert checkpoint.owned_counts["documents"] == 2
    assert checkpoint.owned_counts["views"] == 4
    assert all(
        checkpoint.owned_counts[name] == 0
        for name in (
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
    assert result.facts["stable_base_views_retained"] is True
    assert result.facts["explicit_quit"] is True
    assert result.facts["integrity_ok"] is True
    assert result.facts["cleanup_ok"] is True
    assert result.messages == ()


def test_lifecycle_accepts_file_synced_recovery_as_safe(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        NativeDurabilityAdapter,
        "sync_directory",
        lambda _adapter, _directory: False,
    )
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=32_768, seed=22),
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
    assert result.facts["recovery_cleanup"] is True
    assert result.facts["integrity_ok"] is True
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
    assert all(
        checkpoint.owned_counts["documents"] == 2
        for checkpoint in result.checkpoints
    )
    assert all(
        checkpoint.owned_counts["views"] == 4
        for checkpoint in result.checkpoints
    )
    assert len(
        {checkpoint.owned_counts["temp_paths"] for checkpoint in result.checkpoints}
    ) == 1


def test_lifecycle_caps_primary_document_churn_at_64_kib(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=1 << 20, seed=21),
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
    assert result.facts["primary_fixture_bytes"] == 64 << 10


def test_lifecycle_reuses_the_restored_two_window_shell_between_cycles(
    tmp_path: Path,
    monkeypatch,
):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=1_024, seed=20),
        tmp_path / "corpus",
    )
    application_root = (tmp_path / "application").resolve()
    application_root.mkdir()
    real_create = sustained_workloads.create_application_harness
    created = []

    def create_observed_harness(root: Path, **options):
        harness = real_create(root, **options)
        new_window = harness.service.new_window

        def observed_new_window(*args, **kwargs):
            created.append(1)
            return new_window(*args, **kwargs)

        harness.service.new_window = observed_new_window
        return harness

    monkeypatch.setattr(
        sustained_workloads,
        "create_application_harness",
        create_observed_harness,
    )

    result = run_sustained_workload(
        "session_lifecycle",
        profile="hosted",
        cycles=5,
        manifest=manifest,
        application_root=application_root,
    )

    assert result.state is ResultState.PASS
    assert len(created) <= 4
