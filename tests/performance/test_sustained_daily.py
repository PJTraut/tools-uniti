from __future__ import annotations

import hashlib
from pathlib import Path

from benchmarks.corpus import CorpusKind, CorpusSpec, generate_corpus
from benchmarks.models import ResultState
from benchmarks.sustained_workloads import run_sustained_workload


def test_daily_cycle_preserves_saved_text_navigation_and_owned_resources(
    tmp_path: Path,
):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=1024, seed=18),
        tmp_path / "corpus",
    )
    application_root = (tmp_path / "application").resolve()
    application_root.mkdir()
    expected_payload = bytearray(manifest.path.read_bytes())
    needle = b"UNITI_DAILY_NEEDLE"
    expected_payload[32 : 32 + len(needle)] = needle
    expected_digest = hashlib.sha256(expected_payload).hexdigest()

    result = run_sustained_workload(
        "daily_editing",
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
    assert checkpoint.metrics["daily_cycle_ms"] >= 0
    assert checkpoint.owned_counts == {
        "active_tasks": 0,
        "active_workers": 0,
        "documents": 1,
        "queued_tasks": 0,
        "replacement_plans": 0,
        "result_stores": 0,
        "snapshots": 0,
        "temp_paths": checkpoint.owned_counts["temp_paths"],
        "views": 1,
    }
    assert result.facts == {
        "cleanup_ok": True,
        "cycles_completed": 2,
        "daily_fixture_bytes": 1024,
        "document_authorities": 1,
        "expected_digest": expected_digest,
        "final_history_cursor": 4,
        "final_revision": 8,
        "final_saved_cursor": 4,
        "integrity_ok": True,
        "match_count": 1,
        "next_span": (32, 32 + len(needle)),
        "previous_span": (32, 32 + len(needle)),
        "reopened_same_document": True,
        "result_revision": 8,
        "saved_digest": expected_digest,
        "service_identity_reused": True,
        "stable_view_reused": True,
    }
    assert result.messages == ()


def test_daily_editing_caps_the_repeated_working_set_at_256_kib(tmp_path: Path):
    manifest = generate_corpus(
        CorpusSpec(CorpusKind.ORDINARY_LINES, size_bytes=1 << 20, seed=19),
        tmp_path / "corpus",
    )
    application_root = (tmp_path / "application").resolve()
    application_root.mkdir()

    result = run_sustained_workload(
        "daily_editing",
        profile="hosted",
        cycles=1,
        manifest=manifest,
        application_root=application_root,
    )

    assert result.state is ResultState.PASS
    assert result.facts["daily_fixture_bytes"] == 256 << 10
