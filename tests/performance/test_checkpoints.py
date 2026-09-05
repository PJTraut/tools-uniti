from __future__ import annotations

from types import SimpleNamespace

from benchmarks.checkpoints import collect_resource_checkpoint
from uniti.resources.policy import load_performance_policy


def _service():
    task_snapshot = SimpleNamespace(active_count=2, queued_count=1)
    resources = SimpleNamespace(
        sample_resources=lambda: SimpleNamespace(
            process_rss=64 << 20,
            cache_used=8 << 20,
            active_workers=1,
            queued_tasks=1,
        ),
        tasks=SimpleNamespace(snapshot=lambda: task_snapshot),
    )
    return SimpleNamespace(
        resources=resources,
        documents=SimpleNamespace(count=1),
        windows=SimpleNamespace(ordered_view_ids=("view-a", "view-b")),
    )


def test_checkpoint_captures_service_and_explicit_owned_root_counts(tmp_path):
    owned_root = tmp_path / "owned"
    nested = owned_root / "nested"
    nested.mkdir(parents=True)
    (nested / "temporary.bin").write_bytes(b"bounded")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "must-not-be-walked").mkdir()
    external_link = owned_root / "external-link"
    try:
        external_link.symlink_to(outside, target_is_directory=True)
    except OSError:
        # Windows hosts can deny symlink creation without developer privileges.
        external_link.write_bytes(b"link-placeholder")

    checkpoint = collect_resource_checkpoint(
        3,
        service=_service(),
        owned_root=owned_root,
        policy=load_performance_policy(),
        tracked_counts={
            "result_stores": 2,
            "replacement_plans": 1,
            "snapshots": 3,
        },
        handle_probe=lambda: 11,
    )

    assert checkpoint.cycle == 3
    assert checkpoint.metrics == {
        "rss_mib": 64.0,
        "cache_used_mib": 8.0,
        "handle_count": 11.0,
    }
    assert checkpoint.owned_counts == {
        "documents": 1,
        "views": 2,
        "active_workers": 1,
        "active_tasks": 2,
        "queued_tasks": 1,
        "result_stores": 2,
        "replacement_plans": 1,
        "snapshots": 3,
        "temp_paths": 3,
    }
    assert checkpoint.unavailable_probes == ()


def test_checkpoint_marks_unavailable_or_capped_probes_explicitly(tmp_path):
    owned_root = tmp_path / "owned"
    owned_root.mkdir()
    for name in ("one", "two", "three"):
        (owned_root / name).write_bytes(b"")

    checkpoint = collect_resource_checkpoint(
        1,
        service=_service(),
        owned_root=owned_root,
        policy=load_performance_policy(),
        tracked_counts={},
        handle_probe=lambda: None,
        directory_entry_limit=2,
    )

    assert checkpoint.metrics == {
        "rss_mib": 64.0,
        "cache_used_mib": 8.0,
    }
    assert checkpoint.owned_counts["temp_paths"] == 2
    assert checkpoint.unavailable_probes == ("handle_count", "temp_paths")
