from __future__ import annotations

from pathlib import Path

import pytest

from uniti.resources import MemorySnapshot
from uniti.resources.telemetry import (
    HostResourceProfile,
    ResourceSampler,
    ResourceSnapshot,
    current_process_rss_bytes,
    peak_process_rss_bytes,
    probe_host_profile,
)


def _profile(tmp_path: Path) -> HostResourceProfile:
    return HostResourceProfile(
        cpu_model="Test CPU",
        architecture="arm64",
        physical_cores=4,
        logical_cores=8,
        physical_memory=16 << 30,
        platform="darwin",
        platform_release="test",
        temp_root=tmp_path,
    )


def test_sampler_normalizes_load_and_captures_queue_state(tmp_path: Path):
    sampler = ResourceSampler(
        _profile(tmp_path),
        memory_probe=lambda: MemorySnapshot(16 << 30, 8 << 30),
        rss_probe=lambda: 96 << 20,
        load_probe=lambda: 4.0,
        disk_probe=lambda _path: 20 << 30,
        clock=lambda: 12.5,
    )

    snapshot = sampler.sample(
        cache_used_bytes=32 << 20,
        active_workers=2,
        queued_tasks=3,
    )

    assert snapshot == ResourceSnapshot(
        physical_memory=16 << 30,
        available_memory=8 << 30,
        process_rss=96 << 20,
        load_per_logical_core=0.5,
        free_disk=20 << 30,
        cache_used=32 << 20,
        active_workers=2,
        queued_tasks=3,
        captured_at=12.5,
    )


def test_sampler_preserves_unavailable_load_and_clamps_counters(tmp_path: Path):
    sampler = ResourceSampler(
        _profile(tmp_path),
        memory_probe=lambda: MemorySnapshot(16 << 30, 8 << 30),
        rss_probe=lambda: -1,
        load_probe=lambda: None,
        disk_probe=lambda _path: -1,
        clock=lambda: 1.0,
    )

    snapshot = sampler.sample(
        cache_used_bytes=-1,
        active_workers=-1,
        queued_tasks=-1,
    )

    assert snapshot.load_per_logical_core is None
    assert snapshot.process_rss == 0
    assert snapshot.free_disk == 0
    assert snapshot.cache_used == 0
    assert snapshot.active_workers == 0
    assert snapshot.queued_tasks == 0


@pytest.mark.parametrize(
    "changes",
    [
        {"physical_memory": -1},
        {"available_memory": -1},
        {"process_rss": -1},
        {"free_disk": -1},
        {"cache_used": -1},
        {"active_workers": -1},
        {"queued_tasks": -1},
        {"captured_at": -1.0},
        {"load_per_logical_core": -0.1},
    ],
)
def test_resource_snapshot_rejects_negative_measurements(changes):
    values = {
        "physical_memory": 1,
        "available_memory": 1,
        "process_rss": 1,
        "load_per_logical_core": 0.0,
        "free_disk": 1,
        "cache_used": 1,
        "active_workers": 0,
        "queued_tasks": 0,
        "captured_at": 1.0,
    }
    values.update(changes)

    with pytest.raises(ValueError, match="non-negative"):
        ResourceSnapshot(**values)


def test_real_host_probe_is_bounded_and_nonempty(tmp_path: Path):
    profile = probe_host_profile(tmp_path)

    assert profile.logical_cores >= 1
    assert profile.physical_cores >= 1
    assert profile.physical_cores <= profile.logical_cores
    assert profile.physical_memory >= 0
    assert profile.architecture
    assert profile.cpu_model
    assert profile.temp_root == tmp_path.resolve()


def test_windows_host_probe_avoids_interruptible_wmi_processor_query(
    tmp_path: Path,
    monkeypatch,
):
    from uniti.resources import telemetry

    monkeypatch.setattr(telemetry.sys, "platform", "win32")
    monkeypatch.setattr(telemetry.os, "cpu_count", lambda: 4)
    monkeypatch.setenv("PROCESSOR_IDENTIFIER", "Hosted Test CPU")
    monkeypatch.setattr(telemetry.platform_module, "machine", lambda: "AMD64")
    monkeypatch.setattr(telemetry.platform_module, "release", lambda: "test")
    monkeypatch.setattr(
        telemetry.platform_module,
        "processor",
        lambda: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    monkeypatch.setattr(
        telemetry,
        "probe_memory",
        lambda: MemorySnapshot(16 << 30, 8 << 30),
    )

    profile = telemetry.probe_host_profile(tmp_path)

    assert profile.cpu_model == "Hosted Test CPU"
    assert profile.architecture == "AMD64"


def test_process_rss_probes_are_non_negative():
    current = current_process_rss_bytes()
    peak = peak_process_rss_bytes()

    assert current >= 0
    assert peak >= current
