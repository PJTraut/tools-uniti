import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path

from uniti.app.cleanup import cleanup_stale, create_session_record
from uniti.app.paths import AppPaths


def _paths(tmp_path: Path) -> AppPaths:
    paths = AppPaths(
        tmp_path / "config",
        tmp_path / "data",
        tmp_path / "state",
        tmp_path / "cache",
    )
    paths.ensure()
    return paths


def _make_old(path: Path, *, days: int) -> None:
    timestamp = (datetime.now(UTC) - timedelta(days=days)).timestamp()
    os.utime(path, (timestamp, timestamp))


def test_cleanup_removes_only_known_old_owned_artifacts(tmp_path: Path):
    paths = _paths(tmp_path)
    owned = paths.temp_dir / "uniti-temp-old"
    arbitrary = paths.temp_dir / "keep-me"
    owned.write_text("x", encoding="utf-8")
    arbitrary.write_text("x", encoding="utf-8")
    _make_old(owned, days=8)
    _make_old(arbitrary, days=8)

    report = cleanup_stale(paths)

    assert owned in report.removed
    assert arbitrary.exists()
    assert arbitrary not in report.removed


def test_cleanup_preserves_live_and_active_sessions(tmp_path: Path):
    paths = _paths(tmp_path)
    live = create_session_record(
        paths, session_id="live-session", pid=os.getpid(), build_identity="build"
    ).parent
    active = create_session_record(
        paths, session_id="active-session", pid=999_999_999, build_identity="build"
    ).parent
    _make_old(live, days=8)
    _make_old(active, days=8)

    report = cleanup_stale(paths, active_session_ids=("active-session",))

    assert live.exists()
    assert active.exists()
    assert report.removed == ()


def test_session_record_has_schema_pid_start_and_build(tmp_path: Path):
    paths = _paths(tmp_path)

    record = create_session_record(
        paths, session_id="session-1", pid=321, build_identity="abc123"
    )

    payload = json.loads(record.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["pid"] == 321
    assert payload["build_identity"] == "abc123"
    assert payload["started_at"].endswith("Z")


def test_cleanup_honors_inspection_and_removal_limits(tmp_path: Path):
    paths = _paths(tmp_path)
    for index in range(12):
        path = paths.temp_dir / f"uniti-temp-{index:02d}"
        path.write_text("x", encoding="utf-8")
        _make_old(path, days=8)

    report = cleanup_stale(paths, max_inspected=7, max_removed=3)

    assert report.inspected == 7
    assert len(report.removed) == 3


def test_process_cleanup_never_touches_durable_session_state(tmp_path: Path):
    paths = _paths(tmp_path)
    durable = paths.durable_session_dir / "manifests" / "00000000000000000001.json"
    durable.parent.mkdir(parents=True)
    durable.write_text("{}", encoding="utf-8")
    _make_old(durable, days=30)

    cleanup_stale(paths)

    assert durable.exists()
