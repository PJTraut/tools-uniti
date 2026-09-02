"""Stable JSON models for isolated performance results."""

from __future__ import annotations

import json
import math
import statistics
from dataclasses import dataclass
from enum import StrEnum
from typing import Mapping


class ResultState(StrEnum):
    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    INVALID = "INVALID"
    NOT_RUN = "NOT RUN"


@dataclass(frozen=True, slots=True)
class MetricSample:
    values: tuple[float, ...]

    def __post_init__(self) -> None:
        normalized = tuple(float(value) for value in self.values)
        if not normalized or any(not math.isfinite(value) for value in normalized):
            raise ValueError("metric samples must contain finite values")
        object.__setattr__(self, "values", normalized)

    @property
    def median(self) -> float:
        return float(statistics.median(self.values))

    @property
    def p95(self) -> float:
        ordered = sorted(self.values)
        index = min(len(ordered) - 1, math.ceil(len(ordered) * 0.95) - 1)
        return ordered[index]

    @property
    def maximum(self) -> float:
        return max(self.values)

    def as_dict(self) -> dict[str, object]:
        return {"values": list(self.values)}

    @classmethod
    def from_dict(cls, payload: object) -> "MetricSample":
        if not isinstance(payload, dict) or set(payload) != {"values"}:
            raise ValueError("invalid metric sample")
        values = payload["values"]
        if not isinstance(values, list):
            raise ValueError("invalid metric values")
        return cls(tuple(float(value) for value in values))


@dataclass(frozen=True, slots=True)
class ScenarioResult:
    schema: int
    scenario: str
    state: ResultState
    metrics: Mapping[str, MetricSample]
    facts: Mapping[str, object]
    messages: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.schema != 1:
            raise ValueError(f"unsupported scenario result schema: {self.schema!r}")
        if not self.scenario:
            raise ValueError("scenario name must be nonempty")

    @classmethod
    def success(
        cls,
        *,
        scenario: str,
        metrics: Mapping[str, MetricSample] | None = None,
        facts: Mapping[str, object] | None = None,
        messages: tuple[str, ...] = (),
    ) -> "ScenarioResult":
        return cls(1, scenario, ResultState.PASS, metrics or {}, facts or {}, messages)

    @classmethod
    def failed(cls, scenario: str, message: str) -> "ScenarioResult":
        return cls(1, scenario, ResultState.FAIL, {}, {}, (message,))

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "scenario": self.scenario,
            "state": self.state.value,
            "metrics": {
                name: sample.as_dict() for name, sample in sorted(self.metrics.items())
            },
            "facts": dict(self.facts),
            "messages": list(self.messages),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True)

    @classmethod
    def from_dict(cls, payload: object) -> "ScenarioResult":
        if not isinstance(payload, dict):
            raise ValueError("scenario result must be an object")
        required = {"schema", "scenario", "state", "metrics", "facts", "messages"}
        if set(payload) != required:
            raise ValueError("invalid scenario result keys")
        metrics = payload["metrics"]
        facts = payload["facts"]
        messages = payload["messages"]
        if not isinstance(metrics, dict) or not isinstance(facts, dict):
            raise ValueError("invalid scenario mappings")
        if not isinstance(messages, list) or not all(
            isinstance(message, str) for message in messages
        ):
            raise ValueError("invalid scenario messages")
        return cls(
            schema=int(payload["schema"]),
            scenario=str(payload["scenario"]),
            state=ResultState(str(payload["state"])),
            metrics={
                str(name): MetricSample.from_dict(sample)
                for name, sample in metrics.items()
            },
            facts=dict(facts),
            messages=tuple(messages),
        )

    @classmethod
    def from_json(cls, text: str) -> "ScenarioResult":
        return cls.from_dict(json.loads(text))


@dataclass(frozen=True, slots=True)
class ScenarioEvaluation:
    scenario: str
    state: ResultState
    messages: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "scenario": self.scenario,
            "state": self.state.value,
            "messages": list(self.messages),
        }

    @classmethod
    def from_dict(cls, payload: object) -> "ScenarioEvaluation":
        if not isinstance(payload, dict):
            raise ValueError("scenario evaluation must be an object")
        required = {"scenario", "state", "messages"}
        if set(payload) != required or not isinstance(payload["messages"], list):
            raise ValueError("invalid scenario evaluation")
        return cls(
            scenario=str(payload["scenario"]),
            state=ResultState(str(payload["state"])),
            messages=tuple(str(message) for message in payload["messages"]),
        )


@dataclass(frozen=True, slots=True)
class SuiteResult:
    schema: int
    tier: str
    mode: str
    host: Mapping[str, object]
    scenarios: tuple[ScenarioResult, ...]
    evaluations: tuple[ScenarioEvaluation, ...]

    @property
    def state(self) -> ResultState:
        severity = {
            ResultState.PASS: 0,
            ResultState.WARN: 1,
            ResultState.NOT_RUN: 2,
            ResultState.INVALID: 3,
            ResultState.FAIL: 4,
        }
        states = [evaluation.state for evaluation in self.evaluations]
        return max(states, key=severity.__getitem__) if states else ResultState.NOT_RUN

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "tier": self.tier,
            "mode": self.mode,
            "state": self.state.value,
            "host": dict(self.host),
            "scenarios": [scenario.as_dict() for scenario in self.scenarios],
            "evaluations": [evaluation.as_dict() for evaluation in self.evaluations],
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    @classmethod
    def from_dict(cls, payload: object) -> "SuiteResult":
        if not isinstance(payload, dict):
            raise ValueError("suite result must be an object")
        required = {
            "schema",
            "tier",
            "mode",
            "state",
            "host",
            "scenarios",
            "evaluations",
        }
        if set(payload) != required or payload["schema"] != 1:
            raise ValueError("invalid suite result")
        if not isinstance(payload["host"], dict):
            raise ValueError("invalid suite host")
        scenarios = payload["scenarios"]
        evaluations = payload["evaluations"]
        if not isinstance(scenarios, list) or not isinstance(evaluations, list):
            raise ValueError("invalid suite scenario collections")
        result = cls(
            schema=1,
            tier=str(payload["tier"]),
            mode=str(payload["mode"]),
            host=dict(payload["host"]),
            scenarios=tuple(ScenarioResult.from_dict(item) for item in scenarios),
            evaluations=tuple(
                ScenarioEvaluation.from_dict(item) for item in evaluations
            ),
        )
        if str(payload["state"]) != result.state.value:
            raise ValueError("suite aggregate state does not match evaluations")
        return result

    @classmethod
    def from_json(cls, text: str) -> "SuiteResult":
        return cls.from_dict(json.loads(text))
