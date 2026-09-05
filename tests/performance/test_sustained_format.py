from __future__ import annotations

from pathlib import Path

from benchmarks.corpus import CorpusKind, CorpusSpec, generate_corpus
from benchmarks.models import ResultState
from benchmarks.sustained_workloads import run_sustained_workload


def test_format_cycle_preserves_exact_bytes_and_rejects_stale_authority(
    tmp_path: Path,
):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.MIXED_UNICODE, size_bytes=65_537, seed=18),
        tmp_path / "corpus",
    )
    application_root = (tmp_path / "application").resolve()
    application_root.mkdir()

    result = run_sustained_workload(
        "format_integrity",
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
    assert checkpoint.metrics["format_cycle_ms"] >= 0
    assert checkpoint.owned_counts["documents"] == 0
    assert checkpoint.owned_counts["views"] == 0
    assert checkpoint.owned_counts["active_tasks"] == 0
    assert checkpoint.owned_counts["queued_tasks"] == 0
    assert checkpoint.owned_counts["snapshots"] == 0
    assert result.facts["cycles_completed"] == 2
    assert result.facts["fixture_bytes"] == 161
    assert result.facts["sustained_digest"] == manifest.digest
    assert result.facts["mixed_eol_kind"] == "MIXED"
    assert result.facts["display_invalid_hex"] == "ff"
    assert result.facts["malformed_preserved"] is True
    assert result.facts["converted_digest"] == (
        "8f067c5cee737099e10457ad266a409b3a24434ab9a980e0f737639e4db54d4f"
    )
    assert result.facts["save_as_digest"] == (
        "c487d23b88fa7291e67805566cdcfb2bfe10aec8755f494562421dd66eb97ad6"
    )
    assert result.facts["history_restore_exact"] is True
    assert result.facts["external_save_rejected"] is True
    assert result.facts["stale_history_match"] == "changed"
    assert result.facts["integrity_ok"] is True
    assert result.facts["cleanup_ok"] is True
    assert result.messages == ()

