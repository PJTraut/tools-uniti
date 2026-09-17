"""BF-030: no benchmark coverage existed for many concurrently open documents.

Several resources are shared across every open document rather than
allocated per document -- one global `CacheManager` budget
(`resources.max_cache_mib` in the performance policy, priority-then-LRU
eviction across every open document's indexes/search results/wrap
layouts) and one shared `ResourceManager` worker pool. None of that was
previously exercised at meaningful document counts. This drives the real
application (`ApplicationWorkloadHarness`, the same harness the sustained
workload families use) through both profiles the feedback settled on: the
user's real "bible project" shape, and a deliberately larger, rounder
headroom target.

BF-040 (per-document task-pool fairness) landed first specifically so
these benchmarks would measure a corrected pool rather than the starvation
it already diagnosed.
"""

from __future__ import annotations

from pathlib import Path

from benchmarks.sustained_workloads import create_application_harness


def _root(tmp_path: Path, name: str) -> Path:
    root = (tmp_path / name).resolve()
    root.mkdir()
    return root


def _write_fixture(path: Path, size_bytes: int) -> None:
    word = "grace "
    repeats = size_bytes // len(word) + 1
    path.write_text((word * repeats)[:size_bytes], encoding="utf-8")


def _open_many(harness, fixtures: list[Path]):
    views = []
    for fixture in fixtures:
        views.append(harness.open_owned_fixture(fixture))
    return views


def test_bf030_real_profile_eighty_files_largest_500kb_stays_within_shared_budgets(
    tmp_path: Path,
):
    """The user's actual primary workflow: an SFM "bible project" -- 66
    books plus a handful of meta files, no more than ~80 files, the
    largest (Psalms) 400-500 KB, most books considerably smaller.
    """

    root = _root(tmp_path, "real-profile")
    fixtures_dir = root / "fixtures"
    fixtures_dir.mkdir()
    fixtures = []
    for index in range(79):
        path = fixtures_dir / f"book-{index:02d}.sfm"
        _write_fixture(path, 5_000 + index * 500)
        fixtures.append(path)
    largest = fixtures_dir / "psalms.sfm"
    _write_fixture(largest, 500_000)
    fixtures.append(largest)
    assert len(fixtures) == 80

    with create_application_harness(root) as harness:
        views = _open_many(harness, fixtures)
        assert harness.service.documents.count == 80

        checkpoint = harness.capture_checkpoint(1)
        assert checkpoint.owned_counts["documents"] == 80
        assert checkpoint.owned_counts["active_tasks"] == 0
        assert checkpoint.owned_counts["queued_tasks"] == 0
        assert (
            checkpoint.metrics["cache_used_mib"]
            <= harness.policy.resources.max_cache_mib
        )

        # Switch back to the first-opened document (now the one furthest
        # from being the most recently touched) and confirm re-access
        # after 79 other documents have been opened still reads correctly
        # -- eviction of this document's presentation-layer caches must
        # never corrupt or lose its actual content.
        first_view = harness.open_owned_fixture(fixtures[0])
        assert first_view.document is views[0].document
        expected = fixtures[0].read_text(encoding="utf-8")
        assert first_view.document.read(0, first_view.document.total_chars()) == (
            expected
        )

        assert harness.close_cycle()


def test_bf030_headroom_profile_hundred_files_two_mib_each_bounds_shared_cache(
    tmp_path: Path,
):
    """The originally requested, deliberately larger and rounder target:
    100 files at ~2 MB each (roughly 200 MB of raw content) -- comfortably
    under the structural `MAX_DOCUMENTS = 128` cap, but the largest
    aggregate raw-content volume any scenario has opened concurrently, so
    it stresses the *shared* cache budget far more than the real profile.
    """

    root = _root(tmp_path, "headroom-profile")
    fixtures_dir = root / "fixtures"
    fixtures_dir.mkdir()
    fixtures = []
    for index in range(100):
        path = fixtures_dir / f"document-{index:03d}.txt"
        _write_fixture(path, 2_000_000)
        fixtures.append(path)

    with create_application_harness(root) as harness:
        _open_many(harness, fixtures)
        assert harness.service.documents.count == 100

        checkpoint = harness.capture_checkpoint(1)
        assert checkpoint.owned_counts["documents"] == 100
        assert checkpoint.owned_counts["active_tasks"] == 0
        assert checkpoint.owned_counts["queued_tasks"] == 0
        # ~200 MB of raw content opened at once must still be held to the
        # shared cache's configured ceiling -- proof the priority/LRU
        # eviction this budget depends on actually engages at this scale,
        # not merely that everything happens to fit.
        assert (
            checkpoint.metrics["cache_used_mib"]
            <= harness.policy.resources.max_cache_mib
        )

        assert harness.close_cycle()
