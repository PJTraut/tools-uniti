from __future__ import annotations

import sys
import json
import subprocess
from pathlib import Path

from benchmarks.corpus import CorpusKind, CorpusSpec, generate_corpus
from benchmarks.models import MetricSample, ResultState, ScenarioResult
from benchmarks.runner import merge_scenario_results, run_child_commands
from benchmarks.scenarios import (
    corpus_kind_for_scenario,
    initial_scenario_names,
    run_scenario,
)


def test_child_failure_does_not_stop_later_scenario(tmp_path: Path):
    outcomes = run_child_commands(
        (
            ("fails", [sys.executable, "-c", "raise SystemExit(3)"]),
            ("passes", [sys.executable, "-c", "print('{}')"]),
        ),
        timeout_seconds=5,
        artifact_root=tmp_path,
    )

    assert [item.scenario for item in outcomes] == ["fails", "passes"]
    assert outcomes[0].state is ResultState.FAIL
    assert outcomes[0].returncode == 3
    assert outcomes[1].state is ResultState.PASS


def test_child_timeout_is_reported_and_later_scenario_runs(tmp_path: Path):
    outcomes = run_child_commands(
        (
            ("timeout", [sys.executable, "-c", "import time; time.sleep(1)"]),
            ("passes", [sys.executable, "-c", "print('{}')"]),
        ),
        timeout_seconds=0.05,
        artifact_root=tmp_path,
    )

    assert outcomes[0].state is ResultState.FAIL
    assert outcomes[0].timed_out
    assert outcomes[1].state is ResultState.PASS


def test_merge_scenario_repetitions_preserves_every_metric_sample():
    merged = merge_scenario_results(
        (
            ScenarioResult.success(
                scenario="navigation",
                metrics={"interaction_max_ms": MetricSample((10.0,))},
                facts={"integrity_ok": True},
            ),
            ScenarioResult.success(
                scenario="navigation",
                metrics={"interaction_max_ms": MetricSample((20.0,))},
                facts={"integrity_ok": True},
            ),
        )
    )

    assert merged.metrics["interaction_max_ms"].values == (10.0, 20.0)
    assert merged.facts["integrity_ok"] is True


def test_navigation_child_writes_one_schema_result(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=2 << 20),
        tmp_path / "corpus",
    )
    manifest_path = tmp_path / "manifest.json"
    result_path = tmp_path / "result.json"
    manifest_path.write_text(json.dumps(manifest.as_dict()), encoding="utf-8")

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmarks.runner",
            "--child",
            "navigation",
            str(manifest_path),
            str(result_path),
        ],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 0, completed.stderr
    result = ScenarioResult.from_json(result_path.read_text(encoding="utf-8"))
    assert result.scenario == "navigation"
    assert result.state is ResultState.PASS
    assert result.metrics["interaction_max_ms"].values[0] >= 0
    assert result.metrics["gui_heartbeat_max_ms"].values[0] >= 0
    assert result.metrics["navigation_completion_ms"].values[0] >= 0
    assert result.facts["integrity_ok"] is True


def test_repository_performance_script_exposes_cli_without_running_a_tier():
    completed = subprocess.run(
        [sys.executable, "scripts/performance_suite.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
        timeout=5,
    )

    assert completed.returncode == 0
    assert "--tier" in completed.stdout
    assert "--mode" in completed.stdout
    assert "--native-gui" in completed.stdout


def test_a18_search_and_replace_scenarios_are_registered_for_routine_runs():
    names = initial_scenario_names("routine")

    assert "search_sparse" in names
    assert "search_dense" in names
    assert "replace" in names
    assert "save" in names
    assert "save_as" in names
    assert corpus_kind_for_scenario("search_dense") is CorpusKind.SEARCH_DENSE
    assert corpus_kind_for_scenario("replace") is CorpusKind.SEARCH_DENSE


def test_dense_search_and_replace_scenarios_preserve_integrity(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.SEARCH_DENSE, size_bytes=1 << 20),
        tmp_path / "dense",
    )

    search = run_scenario("search_dense", manifest)
    replace = run_scenario("replace", manifest)

    assert search.state is ResultState.PASS
    assert search.facts["integrity_ok"] is True
    assert search.facts["spilled"] is True
    assert replace.state is ResultState.PASS
    assert replace.facts["integrity_ok"] is True
    assert replace.facts["safe_refusal"] is True
    assert replace.facts["atomic_undo"] is True


def test_progressive_save_scenarios_preserve_integrity(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=1 << 20),
        tmp_path / "save",
    )

    save = run_scenario("save", manifest)
    save_as = run_scenario("save_as", manifest)

    assert save.state is ResultState.PASS
    assert save.facts["integrity_ok"] is True
    assert save_as.state is ResultState.PASS
    assert save_as.facts["integrity_ok"] is True
