from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import pytest

from benchmarks.models import ResultState
from benchmarks.sustained_models import (
    CandidateEvidence,
    ExecutionClass,
    ResourceCheckpoint,
    SustainedEvaluation,
    SustainedFamilyResult,
    SustainedSuiteResult,
    decode_candidate_evidence,
    decode_family_result,
    decode_suite_result,
    encode_candidate_evidence,
    encode_family_result,
    encode_suite_result,
)


def _checkpoint(cycle: int = 1) -> ResourceCheckpoint:
    return ResourceCheckpoint(
        cycle=cycle,
        metrics={"rss_mib": float(cycle), "interaction_p95_ms": 4.0},
        owned_counts={"documents": 0, "tasks": 0},
        unavailable_probes=("handle_count",),
    )


def _family(*, cycles: int = 1, profile: str = "a22-v1") -> SustainedFamilyResult:
    return SustainedFamilyResult(
        schema=2,
        family="daily_editing",
        profile=profile,
        state=ResultState.PASS,
        warmup_cycles=1,
        measured_cycles=cycles,
        checkpoints=tuple(_checkpoint(cycle) for cycle in range(1, cycles + 1)),
        facts={"integrity_ok": True, "saved_digest": "abc123"},
        messages=(),
    )


def _suite(
    *,
    execution_class: ExecutionClass = ExecutionClass.CONTROLLED,
    profile: str = "a22-v1",
    host: dict[str, object] | None = None,
) -> SustainedSuiteResult:
    family = _family(profile=profile)
    return SustainedSuiteResult(
        schema=2,
        profile=profile,
        execution_class=execution_class,
        host=host
        or {
            "git_commit": "candidate-abc",
            "os_family": "linux",
            "cpu_class": "reference",
        },
        families=(family,),
        evaluations=(
            SustainedEvaluation(family.family, ResultState.PASS, ()),
        ),
    )


def test_resource_checkpoint_is_strict_immutable_and_round_trips():
    checkpoint = _checkpoint()

    restored = ResourceCheckpoint.from_dict(checkpoint.as_dict())

    assert restored == checkpoint
    assert restored.metrics["rss_mib"] == 1.0
    with pytest.raises(FrozenInstanceError):
        restored.cycle = 2  # type: ignore[misc]
    with pytest.raises(TypeError):
        restored.metrics["rss_mib"] = 2.0  # type: ignore[index]


def test_resource_checkpoint_rejects_invalid_construction():
    with pytest.raises(ValueError, match="cycle"):
        ResourceCheckpoint(True, {}, {}, ())
    with pytest.raises(ValueError, match="finite non-negative"):
        ResourceCheckpoint(1, {"rss_mib": -1.0}, {}, ())
    with pytest.raises(ValueError, match="finite non-negative"):
        ResourceCheckpoint(1, {"rss_mib": float("nan")}, {}, ())
    with pytest.raises(ValueError, match="non-negative integers"):
        ResourceCheckpoint(1, {}, {"documents": 1.5}, ())
    with pytest.raises(ValueError, match="unique"):
        ResourceCheckpoint(1, {}, {}, ("rss", "rss"))


def test_schema_2_models_reject_float_schema_values():
    family = _family()
    suite = _suite()

    with pytest.raises(ValueError, match="family schema"):
        replace(family, schema=2.0)
    with pytest.raises(ValueError, match="suite schema"):
        replace(suite, schema=2.0)
    with pytest.raises(ValueError, match="evidence schema"):
        CandidateEvidence(2.0, "candidate-abc", (suite,))


def test_family_json_round_trip_preserves_bounded_schema_2_evidence():
    family = _family(cycles=5)

    encoded = encode_family_result(
        family,
        max_bytes=2 << 20,
        max_checkpoints=5,
    )
    restored = decode_family_result(
        encoded,
        max_bytes=2 << 20,
        max_checkpoints=5,
    )

    assert restored == family
    assert encoded == encode_family_result(
        restored,
        max_bytes=2 << 20,
        max_checkpoints=5,
    )


def test_suite_json_round_trip_recomputes_aggregate_state():
    suite = _suite()

    encoded = encode_suite_result(
        suite,
        max_bytes=8 << 20,
        family_max_bytes=2 << 20,
        max_checkpoints=50,
    )
    restored = decode_suite_result(
        encoded,
        max_bytes=8 << 20,
        family_max_bytes=2 << 20,
        max_checkpoints=50,
    )

    assert restored == suite
    assert restored.state is ResultState.PASS

    corrupted = encoded.replace(b'"state":"PASS"', b'"state":"FAIL"', 1)
    with pytest.raises(ValueError, match="aggregate state"):
        decode_suite_result(
            corrupted,
            max_bytes=8 << 20,
            family_max_bytes=2 << 20,
            max_checkpoints=50,
        )


def test_candidate_evidence_round_trip_accepts_one_or_two_compatible_runs():
    suite = _suite()
    candidate = CandidateEvidence(
        schema=2,
        candidate_commit="candidate-abc",
        suites=(suite, suite),
    )

    encoded = encode_candidate_evidence(
        candidate,
        max_bytes=8 << 20,
        family_max_bytes=2 << 20,
        max_checkpoints=50,
    )
    restored = decode_candidate_evidence(
        encoded,
        max_bytes=8 << 20,
        family_max_bytes=2 << 20,
        max_checkpoints=50,
    )

    assert restored == candidate


def test_candidate_evidence_rejects_incompatible_or_noncontrolled_runs():
    controlled = _suite()
    incompatible_host = _suite(
        host={
            "git_commit": "candidate-abc",
            "os_family": "windows",
            "cpu_class": "reference",
        }
    )

    with pytest.raises(ValueError, match="compatible"):
        CandidateEvidence(2, "candidate-abc", (controlled, incompatible_host))
    with pytest.raises(ValueError, match="controlled"):
        CandidateEvidence(
            2,
            "candidate-abc",
            (_suite(execution_class=ExecutionClass.HOSTED),),
        )
    with pytest.raises(ValueError, match="one or two"):
        CandidateEvidence(2, "candidate-abc", ())


def test_family_decoder_rejects_duplicate_unknown_and_nonfinite_values():
    encoded = encode_family_result(
        _family(),
        max_bytes=2 << 20,
        max_checkpoints=5,
    )
    duplicate = encoded.replace(b'"schema":2', b'"schema":2,"schema":2', 1)
    unknown = encoded.replace(b'"schema":2', b'"schema":2,"extra":0', 1)
    nonfinite = encoded.replace(b'"rss_mib":1.0', b'"rss_mib":NaN', 1)

    for payload, message in (
        (duplicate, "duplicate JSON key"),
        (unknown, "family result keys"),
        (nonfinite, "non-finite JSON number"),
    ):
        with pytest.raises(ValueError, match=message):
            decode_family_result(
                payload,
                max_bytes=2 << 20,
                max_checkpoints=5,
            )


def test_decoders_reject_oversized_payloads_and_excess_checkpoints():
    family = _family(cycles=2)
    family_bytes = encode_family_result(
        family,
        max_bytes=2 << 20,
        max_checkpoints=2,
    )
    with pytest.raises(ValueError, match="family payload exceeds"):
        decode_family_result(
            family_bytes,
            max_bytes=len(family_bytes) - 1,
            max_checkpoints=2,
        )
    with pytest.raises(ValueError, match="checkpoint limit"):
        decode_family_result(
            family_bytes,
            max_bytes=2 << 20,
            max_checkpoints=1,
        )

    suite = replace(_suite(), families=(family,))
    suite_bytes = encode_suite_result(
        suite,
        max_bytes=8 << 20,
        family_max_bytes=2 << 20,
        max_checkpoints=2,
    )
    with pytest.raises(ValueError, match="suite payload exceeds"):
        decode_suite_result(
            suite_bytes,
            max_bytes=len(suite_bytes) - 1,
            family_max_bytes=2 << 20,
            max_checkpoints=2,
        )
    with pytest.raises(ValueError, match="family payload exceeds"):
        decode_suite_result(
            suite_bytes,
            max_bytes=8 << 20,
            family_max_bytes=1,
            max_checkpoints=2,
        )
