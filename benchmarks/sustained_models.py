"""Bounded schema-2 models for sustained performance evidence."""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from benchmarks.models import ResultState, aggregate_result_state


class ExecutionClass(StrEnum):
    HOSTED = "hosted"
    CONTROLLED = "controlled"


def _plain_integer(value: object, name: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ValueError(f"{name} must be an integer of at least {minimum}")
    return value


def _nonempty_string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{name} must be a nonempty string")
    return value


def _freeze_json(value: object, name: str) -> object:
    if value is None or isinstance(value, (bool, str)):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} contains a non-finite number")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, object] = {}
        for key, item in value.items():
            if not isinstance(key, str) or not key:
                raise ValueError(f"{name} keys must be nonempty strings")
            frozen[key] = _freeze_json(item, f"{name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(
            _freeze_json(item, f"{name}[{index}]")
            for index, item in enumerate(value)
        )
    raise ValueError(f"{name} contains a non-JSON value")


def _freeze_mapping(value: object, name: str) -> Mapping[str, object]:
    frozen = _freeze_json(value, name)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{name} must be an object")
    return frozen


def _thaw_json(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw_json(item) for item in value]
    return value


def _exact_keys(payload: object, required: set[str], name: str) -> dict[str, object]:
    if not isinstance(payload, dict) or set(payload) != required:
        raise ValueError(f"invalid {name} keys")
    return payload


def _messages(value: object, name: str) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)) or not all(
        isinstance(message, str) for message in value
    ):
        raise ValueError(f"{name} must be a string collection")
    return tuple(value)


@dataclass(frozen=True, slots=True)
class ResourceCheckpoint:
    cycle: int
    metrics: Mapping[str, float]
    owned_counts: Mapping[str, int]
    unavailable_probes: tuple[str, ...]

    def __post_init__(self) -> None:
        _plain_integer(self.cycle, "checkpoint cycle")
        if not isinstance(self.metrics, Mapping):
            raise ValueError("checkpoint metrics must be an object")
        metrics: dict[str, float] = {}
        for name, value in self.metrics.items():
            _nonempty_string(name, "metric name")
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(float(value))
                or float(value) < 0
            ):
                raise ValueError("checkpoint metrics must be finite non-negative numbers")
            metrics[name] = float(value)
        if not isinstance(self.owned_counts, Mapping):
            raise ValueError("checkpoint owned counts must be an object")
        owned_counts: dict[str, int] = {}
        for name, value in self.owned_counts.items():
            _nonempty_string(name, "owned count name")
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError("checkpoint owned counts must be non-negative integers")
            owned_counts[name] = value
        probes = _messages(self.unavailable_probes, "unavailable probes")
        if any(not probe for probe in probes) or len(set(probes)) != len(probes):
            raise ValueError("unavailable probes must be unique nonempty strings")
        object.__setattr__(self, "metrics", MappingProxyType(metrics))
        object.__setattr__(self, "owned_counts", MappingProxyType(owned_counts))
        object.__setattr__(self, "unavailable_probes", tuple(sorted(probes)))

    def as_dict(self) -> dict[str, object]:
        return {
            "cycle": self.cycle,
            "metrics": dict(self.metrics),
            "owned_counts": dict(self.owned_counts),
            "unavailable_probes": list(self.unavailable_probes),
        }

    @classmethod
    def from_dict(cls, payload: object) -> "ResourceCheckpoint":
        values = _exact_keys(
            payload,
            {"cycle", "metrics", "owned_counts", "unavailable_probes"},
            "resource checkpoint",
        )
        return cls(
            cycle=values["cycle"],  # type: ignore[arg-type]
            metrics=values["metrics"],  # type: ignore[arg-type]
            owned_counts=values["owned_counts"],  # type: ignore[arg-type]
            unavailable_probes=_messages(
                values["unavailable_probes"], "unavailable probes"
            ),
        )


@dataclass(frozen=True, slots=True)
class SustainedEvaluation:
    subject: str
    state: ResultState
    messages: tuple[str, ...]

    def __post_init__(self) -> None:
        _nonempty_string(self.subject, "evaluation subject")
        if not isinstance(self.state, ResultState):
            raise ValueError("evaluation state must be a ResultState")
        object.__setattr__(self, "messages", _messages(self.messages, "messages"))

    def as_dict(self) -> dict[str, object]:
        return {
            "subject": self.subject,
            "state": self.state.value,
            "messages": list(self.messages),
        }

    @classmethod
    def from_dict(cls, payload: object) -> "SustainedEvaluation":
        values = _exact_keys(
            payload, {"subject", "state", "messages"}, "sustained evaluation"
        )
        try:
            state = ResultState(values["state"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid sustained evaluation state") from exc
        return cls(
            subject=values["subject"],  # type: ignore[arg-type]
            state=state,
            messages=_messages(values["messages"], "messages"),
        )


@dataclass(frozen=True, slots=True)
class SustainedFamilyResult:
    schema: int
    family: str
    profile: str
    state: ResultState
    warmup_cycles: int
    measured_cycles: int
    checkpoints: tuple[ResourceCheckpoint, ...]
    facts: Mapping[str, object]
    messages: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema, bool)
            or not isinstance(self.schema, int)
            or self.schema != 2
        ):
            raise ValueError(f"unsupported sustained family schema: {self.schema!r}")
        _nonempty_string(self.family, "family")
        _nonempty_string(self.profile, "profile")
        if not isinstance(self.state, ResultState):
            raise ValueError("family state must be a ResultState")
        _plain_integer(self.warmup_cycles, "warmup cycles")
        _plain_integer(self.measured_cycles, "measured cycles", minimum=1)
        if not isinstance(self.checkpoints, tuple) or not all(
            isinstance(checkpoint, ResourceCheckpoint)
            for checkpoint in self.checkpoints
        ):
            raise ValueError("family checkpoints must be ResourceCheckpoint values")
        if len(self.checkpoints) > self.measured_cycles:
            raise ValueError("family checkpoint count exceeds measured cycles")
        cycles = tuple(checkpoint.cycle for checkpoint in self.checkpoints)
        if len(set(cycles)) != len(cycles) or cycles != tuple(sorted(cycles)):
            raise ValueError("family checkpoint cycles must be unique and ordered")
        if any(cycle > self.measured_cycles for cycle in cycles):
            raise ValueError("family checkpoint cycle exceeds measured cycles")
        object.__setattr__(self, "facts", _freeze_mapping(self.facts, "family facts"))
        object.__setattr__(self, "messages", _messages(self.messages, "messages"))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "family": self.family,
            "profile": self.profile,
            "state": self.state.value,
            "warmup_cycles": self.warmup_cycles,
            "measured_cycles": self.measured_cycles,
            "checkpoints": [checkpoint.as_dict() for checkpoint in self.checkpoints],
            "facts": _thaw_json(self.facts),
            "messages": list(self.messages),
        }

    @classmethod
    def from_dict(cls, payload: object) -> "SustainedFamilyResult":
        values = _exact_keys(
            payload,
            {
                "schema",
                "family",
                "profile",
                "state",
                "warmup_cycles",
                "measured_cycles",
                "checkpoints",
                "facts",
                "messages",
            },
            "sustained family result",
        )
        checkpoints = values["checkpoints"]
        if not isinstance(checkpoints, list):
            raise ValueError("family checkpoints must be a collection")
        try:
            state = ResultState(values["state"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid sustained family state") from exc
        return cls(
            schema=values["schema"],  # type: ignore[arg-type]
            family=values["family"],  # type: ignore[arg-type]
            profile=values["profile"],  # type: ignore[arg-type]
            state=state,
            warmup_cycles=values["warmup_cycles"],  # type: ignore[arg-type]
            measured_cycles=values["measured_cycles"],  # type: ignore[arg-type]
            checkpoints=tuple(
                ResourceCheckpoint.from_dict(checkpoint)
                for checkpoint in checkpoints
            ),
            facts=values["facts"],  # type: ignore[arg-type]
            messages=_messages(values["messages"], "messages"),
        )


@dataclass(frozen=True, slots=True)
class SustainedSuiteResult:
    schema: int
    profile: str
    execution_class: ExecutionClass
    host: Mapping[str, object]
    families: tuple[SustainedFamilyResult, ...]
    evaluations: tuple[SustainedEvaluation, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema, bool)
            or not isinstance(self.schema, int)
            or self.schema != 2
        ):
            raise ValueError(f"unsupported sustained suite schema: {self.schema!r}")
        _nonempty_string(self.profile, "suite profile")
        if not isinstance(self.execution_class, ExecutionClass):
            raise ValueError("execution class must be an ExecutionClass")
        host = _freeze_mapping(self.host, "host fingerprint")
        if not isinstance(self.families, tuple) or not all(
            isinstance(family, SustainedFamilyResult) for family in self.families
        ):
            raise ValueError("suite families must be SustainedFamilyResult values")
        if not isinstance(self.evaluations, tuple) or not all(
            isinstance(evaluation, SustainedEvaluation)
            for evaluation in self.evaluations
        ):
            raise ValueError("suite evaluations must be SustainedEvaluation values")
        family_names = tuple(family.family for family in self.families)
        if len(set(family_names)) != len(family_names):
            raise ValueError("suite family names must be unique")
        if any(family.profile != self.profile for family in self.families):
            raise ValueError("suite and family profiles must match")
        evaluation_subjects = tuple(
            evaluation.subject for evaluation in self.evaluations
        )
        if len(set(evaluation_subjects)) != len(evaluation_subjects):
            raise ValueError("suite evaluation subjects must be unique")
        object.__setattr__(self, "host", host)

    @property
    def state(self) -> ResultState:
        return aggregate_result_state(
            tuple(evaluation.state for evaluation in self.evaluations)
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "profile": self.profile,
            "execution_class": self.execution_class.value,
            "state": self.state.value,
            "host": _thaw_json(self.host),
            "families": [family.as_dict() for family in self.families],
            "evaluations": [
                evaluation.as_dict() for evaluation in self.evaluations
            ],
        }

    @classmethod
    def from_dict(cls, payload: object) -> "SustainedSuiteResult":
        values = _exact_keys(
            payload,
            {
                "schema",
                "profile",
                "execution_class",
                "state",
                "host",
                "families",
                "evaluations",
            },
            "sustained suite result",
        )
        families = values["families"]
        evaluations = values["evaluations"]
        if not isinstance(families, list) or not isinstance(evaluations, list):
            raise ValueError("invalid sustained suite collections")
        try:
            execution_class = ExecutionClass(values["execution_class"])
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid execution class") from exc
        result = cls(
            schema=values["schema"],  # type: ignore[arg-type]
            profile=values["profile"],  # type: ignore[arg-type]
            execution_class=execution_class,
            host=values["host"],  # type: ignore[arg-type]
            families=tuple(
                SustainedFamilyResult.from_dict(family) for family in families
            ),
            evaluations=tuple(
                SustainedEvaluation.from_dict(evaluation)
                for evaluation in evaluations
            ),
        )
        if values["state"] != result.state.value:
            raise ValueError("suite aggregate state does not match evaluations")
        return result


@dataclass(frozen=True, slots=True)
class CandidateEvidence:
    schema: int
    candidate_commit: str
    suites: tuple[SustainedSuiteResult, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema, bool)
            or not isinstance(self.schema, int)
            or self.schema != 2
        ):
            raise ValueError(f"unsupported candidate evidence schema: {self.schema!r}")
        _nonempty_string(self.candidate_commit, "candidate commit")
        if not isinstance(self.suites, tuple) or not all(
            isinstance(suite, SustainedSuiteResult) for suite in self.suites
        ):
            raise ValueError("candidate suites must be SustainedSuiteResult values")
        if not 1 <= len(self.suites) <= 2:
            raise ValueError("candidate evidence requires one or two suites")
        if any(
            suite.execution_class is not ExecutionClass.CONTROLLED
            for suite in self.suites
        ):
            raise ValueError("candidate evidence requires controlled suites")
        if any(
            suite.host.get("git_commit") != self.candidate_commit
            for suite in self.suites
        ):
            raise ValueError("candidate suite commit is incompatible")
        first = self.suites[0]
        signature = _suite_compatibility_signature(first)
        if any(
            _suite_compatibility_signature(suite) != signature
            for suite in self.suites[1:]
        ):
            raise ValueError("candidate suites must be compatible")
        if any(
            suite.state not in {ResultState.PASS, ResultState.WARN}
            for suite in self.suites
        ):
            raise ValueError("candidate evidence requires clean suites")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "candidate_commit": self.candidate_commit,
            "suites": [suite.as_dict() for suite in self.suites],
        }

    @classmethod
    def from_dict(cls, payload: object) -> "CandidateEvidence":
        values = _exact_keys(
            payload,
            {"schema", "candidate_commit", "suites"},
            "candidate evidence",
        )
        suites = values["suites"]
        if not isinstance(suites, list):
            raise ValueError("candidate suites must be a collection")
        return cls(
            schema=values["schema"],  # type: ignore[arg-type]
            candidate_commit=values["candidate_commit"],  # type: ignore[arg-type]
            suites=tuple(SustainedSuiteResult.from_dict(suite) for suite in suites),
        )


def _suite_compatibility_signature(suite: SustainedSuiteResult) -> tuple[object, ...]:
    return (
        suite.profile,
        tuple(sorted(suite.host.items())),
        tuple(
            (
                family.family,
                family.profile,
                family.warmup_cycles,
                family.measured_cycles,
            )
            for family in suite.families
        ),
    )


def _limit(value: object, name: str, *, minimum: int = 1) -> int:
    return _plain_integer(value, name, minimum=minimum)


def _reject_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _decode_payload(payload: bytes, *, max_bytes: int, label: str) -> dict[str, object]:
    _limit(max_bytes, "maximum payload bytes")
    if not isinstance(payload, bytes):
        raise ValueError(f"{label} payload must be bytes")
    if len(payload) > max_bytes:
        raise ValueError(f"{label} payload exceeds {max_bytes} bytes")
    try:
        text = payload.decode("utf-8", errors="strict")
        decoded = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_constant,
        )
    except UnicodeDecodeError as exc:
        raise ValueError(f"{label} payload is not UTF-8") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"{label} payload is not valid JSON") from exc
    if not isinstance(decoded, dict):
        raise ValueError(f"{label} payload must be an object")
    return decoded


def _encode_payload(payload: object, *, max_bytes: int, label: str) -> bytes:
    _limit(max_bytes, "maximum payload bytes")
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} payload is not strict JSON") from exc
    if len(encoded) > max_bytes:
        raise ValueError(f"{label} payload exceeds {max_bytes} bytes")
    return encoded


def _check_checkpoint_limit(
    family: SustainedFamilyResult, max_checkpoints: int
) -> None:
    _limit(max_checkpoints, "maximum checkpoints", minimum=0)
    if len(family.checkpoints) > max_checkpoints:
        raise ValueError(
            f"family checkpoint limit exceeded: "
            f"{len(family.checkpoints)} > {max_checkpoints}"
        )


def encode_family_result(
    result: SustainedFamilyResult,
    *,
    max_bytes: int,
    max_checkpoints: int,
) -> bytes:
    if not isinstance(result, SustainedFamilyResult):
        raise ValueError("family result is required")
    _check_checkpoint_limit(result, max_checkpoints)
    return _encode_payload(result.as_dict(), max_bytes=max_bytes, label="family")


def decode_family_result(
    payload: bytes,
    *,
    max_bytes: int,
    max_checkpoints: int,
) -> SustainedFamilyResult:
    result = SustainedFamilyResult.from_dict(
        _decode_payload(payload, max_bytes=max_bytes, label="family")
    )
    _check_checkpoint_limit(result, max_checkpoints)
    return result


def _check_suite_limits(
    suite: SustainedSuiteResult,
    *,
    family_max_bytes: int,
    max_checkpoints: int,
) -> None:
    for family in suite.families:
        encode_family_result(
            family,
            max_bytes=family_max_bytes,
            max_checkpoints=max_checkpoints,
        )


def encode_suite_result(
    result: SustainedSuiteResult,
    *,
    max_bytes: int,
    family_max_bytes: int,
    max_checkpoints: int,
) -> bytes:
    if not isinstance(result, SustainedSuiteResult):
        raise ValueError("suite result is required")
    _check_suite_limits(
        result,
        family_max_bytes=family_max_bytes,
        max_checkpoints=max_checkpoints,
    )
    return _encode_payload(result.as_dict(), max_bytes=max_bytes, label="suite")


def decode_suite_result(
    payload: bytes,
    *,
    max_bytes: int,
    family_max_bytes: int,
    max_checkpoints: int,
) -> SustainedSuiteResult:
    result = SustainedSuiteResult.from_dict(
        _decode_payload(payload, max_bytes=max_bytes, label="suite")
    )
    _check_suite_limits(
        result,
        family_max_bytes=family_max_bytes,
        max_checkpoints=max_checkpoints,
    )
    return result


def encode_candidate_evidence(
    result: CandidateEvidence,
    *,
    max_bytes: int,
    family_max_bytes: int,
    max_checkpoints: int,
) -> bytes:
    if not isinstance(result, CandidateEvidence):
        raise ValueError("candidate evidence is required")
    for suite in result.suites:
        _check_suite_limits(
            suite,
            family_max_bytes=family_max_bytes,
            max_checkpoints=max_checkpoints,
        )
    return _encode_payload(result.as_dict(), max_bytes=max_bytes, label="candidate")


def decode_candidate_evidence(
    payload: bytes,
    *,
    max_bytes: int,
    family_max_bytes: int,
    max_checkpoints: int,
) -> CandidateEvidence:
    result = CandidateEvidence.from_dict(
        _decode_payload(payload, max_bytes=max_bytes, label="candidate")
    )
    for suite in result.suites:
        _check_suite_limits(
            suite,
            family_max_bytes=family_max_bytes,
            max_checkpoints=max_checkpoints,
        )
    return result
