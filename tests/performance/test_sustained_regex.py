from __future__ import annotations

from pathlib import Path

from benchmarks.corpus import CorpusKind, CorpusSpec, generate_corpus
from benchmarks.models import ResultState
from benchmarks.sustained_workloads import run_sustained_workload


def test_regex_cycle_is_exact_bounded_cancellable_and_revision_sealed(
    tmp_path: Path,
):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.SEARCH_DENSE, size_bytes=65_536, seed=18),
        tmp_path / "corpus",
    )
    application_root = (tmp_path / "application").resolve()
    application_root.mkdir()

    result = run_sustained_workload(
        "regex_replacement",
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
    assert checkpoint.metrics["regex_cycle_ms"] >= 0
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
    assert result.facts["dense_fixture_bytes"] == 65_536
    assert result.facts["dense_matches"] == 256
    assert result.facts["dense_result_digest"] == (
        "d0d1eaff9aa0df0ecd62bc112e031b53a1b5fd06c2d1d49f5e858df991642e95"
    )
    assert result.facts["dense_store_spilled"] is True
    assert result.facts["sparse_matches"] == 1
    assert result.facts["sparse_result_digest"] == (
        "0d49377470ad4f311ebeb926f0b3c79da0c520b4529fa06f3f8fd5fc3e1cd016"
    )
    assert result.facts["zero_width_positions"] == (0, 1, 2)
    assert result.facts["zero_navigation_indices"] == (1, 0)
    assert result.facts["zero_width_replacements"] == 2
    assert result.facts["zero_width_digest"] == (
        "44920c03214ffba1dee0ac0f6ca2537ecbac72148859766df07fe914d4fffa69"
    )
    assert result.facts["capture_occurrences"] == 6
    assert result.facts["capture_payload_bytes"] <= 1 << 20
    assert result.facts["lookaround_span"] == (2, 3)
    assert result.facts["pathological_timeout"] is True
    assert result.facts["cancelled_before_publication"] is True
    assert result.facts["replacement_plan_count"] == 256
    assert result.facts["replacement_plan_spilled"] is True
    assert result.facts["replacement_plan_refused"] is True
    assert result.facts["replace_current_count"] == 1
    assert result.facts["replace_current_exact"] is True
    assert result.facts["replace_all_count"] == 256
    assert result.facts["replacement_digest"] == (
        "167a5517b50ca7cf9ffc9a37e4418d3c184565c505ef72357f5dc4415102ff78"
    )
    assert result.facts["atomic_undo_redo"] is True
    assert result.facts["result_revision_sealed"] is True
    assert result.facts["stale_result_rejected"] is True
    assert result.facts["stale_plan_rejected"] is True
    assert result.facts["snapshots_closed"] is True
    assert result.facts["store_closed"] is True
    assert result.facts["plan_closed"] is True
    assert result.facts["integrity_ok"] is True
    assert result.facts["cleanup_ok"] is True
    assert result.messages == ()


def test_regex_replacement_caps_repeated_dense_churn_at_256_kib(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.SEARCH_DENSE, size_bytes=1 << 20, seed=19),
        tmp_path / "corpus",
    )
    application_root = (tmp_path / "application").resolve()
    application_root.mkdir()

    result = run_sustained_workload(
        "regex_replacement",
        profile="hosted",
        cycles=1,
        manifest=manifest,
        application_root=application_root,
    )

    assert result.state is ResultState.PASS
    assert result.facts["dense_fixture_bytes"] == 256 << 10
    assert result.facts["dense_matches"] == 1024
