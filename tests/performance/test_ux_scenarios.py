from pathlib import Path

from benchmarks.corpus import CorpusKind, CorpusSpec, generate_corpus
from benchmarks.models import ResultState
from benchmarks.scenarios import (
    corpus_kind_for_scenario,
    initial_scenario_names,
    run_scenario,
)


def test_quick_and_routine_suites_cover_daily_editor_friction():
    expected = {"typing", "scroll", "giant_line", "resource_recovery"}

    assert expected <= set(initial_scenario_names("quick"))
    assert expected <= set(initial_scenario_names("routine"))
    assert corpus_kind_for_scenario("giant_line") is CorpusKind.GIANT_LINE


def test_editor_interaction_scenarios_preserve_text_and_stay_bounded(tmp_path: Path):
    ordinary = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=1 << 20),
        tmp_path / "ordinary",
    )
    giant = generate_corpus(
        CorpusSpec(CorpusKind.GIANT_LINE, size_bytes=1 << 20),
        tmp_path / "giant",
    )

    typing = run_scenario("typing", ordinary)
    scroll = run_scenario("scroll", ordinary)
    giant_line = run_scenario("giant_line", giant)

    for result in (typing, scroll, giant_line):
        assert result.state is ResultState.PASS
        assert result.facts["integrity_ok"] is True
        assert result.metrics["interaction_p95_ms"].values
        assert result.metrics["interaction_max_ms"].values

    assert giant_line.facts["resident_wrapped_rows"] <= 2048
    assert scroll.facts["integrity_read_bytes"] == 256
    assert giant_line.facts["integrity_read_bytes"] == 256


def test_resource_recovery_scenario_restores_parallel_capacity(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=1 << 20),
        tmp_path / "resources",
    )

    result = run_scenario("resource_recovery", manifest)

    assert result.state is ResultState.PASS
    assert result.facts["integrity_ok"] is True
    assert result.facts["critical_worker_limit"] == 1
    assert result.facts["recovered_worker_limit"] == result.facts["normal_worker_limit"]


def test_sparse_design_navigation_stays_lazy(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.SPARSE_FILE, size_bytes=16 << 20),
        tmp_path / "sparse-navigation",
    )

    result = run_scenario("navigation", manifest)

    assert result.state is ResultState.PASS
    assert result.facts["integrity_ok"] is True
    assert result.facts["lazy_source_navigation"] is True
    assert result.facts["mapped_bytes"] < 1 << 20
