"""Deterministic sustained workload family registry."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from benchmarks.corpus import CorpusKind, CorpusManifest
from benchmarks.models import ResultState
from benchmarks.sustained_models import SustainedFamilyResult
from uniti.resources import PerformancePolicy

if TYPE_CHECKING:
    from benchmarks.application_harness import ApplicationWorkloadHarness


SUSTAINED_FAMILY_ORDER = (
    "daily_editing",
    "format_integrity",
    "regex_replacement",
    "session_lifecycle",
)


_CORPUS_KINDS = {
    "daily_editing": CorpusKind.ORDINARY_LINES,
    "format_integrity": CorpusKind.MIXED_UNICODE,
    "regex_replacement": CorpusKind.SEARCH_DENSE,
    "session_lifecycle": CorpusKind.ORDINARY_LINES,
}


def corpus_kind_for_sustained_family(family: str) -> CorpusKind:
    try:
        return _CORPUS_KINDS[family]
    except KeyError as exc:
        raise ValueError(f"unknown sustained workload family: {family}") from exc


def create_application_harness(
    application_root: Path,
    *,
    policy: PerformancePolicy | None = None,
    operation_timeout_seconds: float | None = None,
) -> "ApplicationWorkloadHarness":
    """Construct the shared real-application harness without importing Qt eagerly."""

    from benchmarks.application_harness import ApplicationWorkloadHarness

    return ApplicationWorkloadHarness(
        application_root,
        policy=policy,
        operation_timeout_seconds=operation_timeout_seconds,
    )


def run_sustained_workload(
    family: str,
    *,
    profile: str,
    cycles: int,
    manifest: CorpusManifest,
    application_root: Path,
) -> SustainedFamilyResult:
    """Dispatch a registered workload; concrete cycles arrive in Tasks 7–10."""

    corpus_kind_for_sustained_family(family)
    if profile not in {"hosted", "controlled"}:
        raise ValueError(f"unknown sustained execution profile: {profile}")
    if isinstance(cycles, bool) or not isinstance(cycles, int) or cycles <= 0:
        raise ValueError("sustained cycle count must be positive")
    if not isinstance(manifest, CorpusManifest):
        raise TypeError("manifest must be a CorpusManifest")
    if not isinstance(application_root, Path):
        raise TypeError("application_root must be a Path")
    return SustainedFamilyResult(
        schema=2,
        family=family,
        profile="a22-v1",
        state=ResultState.FAIL,
        warmup_cycles=1,
        measured_cycles=cycles,
        checkpoints=(),
        facts={"integrity_ok": False, "cleanup_ok": False},
        messages=("sustained workload family is not implemented yet",),
    )
