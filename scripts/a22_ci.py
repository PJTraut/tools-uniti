#!/usr/bin/env python3
"""A22 sustained performance gate and bounded failure sanitizer."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
import uuid
from collections.abc import Mapping, Sequence
from pathlib import Path


FAMILIES = ("macos", "linux", "windows")
SUSTAINED_FAMILIES = (
    "daily_editing",
    "format_integrity",
    "regex_replacement",
    "session_lifecycle",
)
MAX_FAMILY_BYTES = 2 << 20
MAX_SUITE_BYTES = 8 << 20
ARTIFACT_RETENTION_DAYS = 7
HOSTED_CYCLES = 5
WARMUP_CYCLES = 1
RESULT_NAME = "sustained-hosted.json"
_STATES = {"PASS", "WARN", "FAIL", "INVALID", "NOT RUN"}
_STATE_RANK = {"PASS": 0, "WARN": 1, "NOT RUN": 2, "INVALID": 3, "FAIL": 4}
_TOKEN = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_SUITE_FIELDS = {
    "schema",
    "profile",
    "execution_class",
    "state",
    "host",
    "families",
    "evaluations",
}
_HOST_FIELDS = {
    "architecture",
    "platform",
    "physical_cores",
    "physical_memory",
    "python_version",
    "qt_version",
    "corpus_schema",
    "git_commit",
    "contended",
}
_FAMILY_FIELDS = {
    "schema",
    "family",
    "profile",
    "state",
    "warmup_cycles",
    "measured_cycles",
    "checkpoints",
    "facts",
    "messages",
}
_CHECKPOINT_FIELDS = {
    "cycle",
    "metrics",
    "owned_counts",
    "unavailable_probes",
}
_EVALUATION_FIELDS = {"subject", "state", "messages"}
_OWNED_COUNT_FIELDS = {
    "documents",
    "views",
    "active_workers",
    "active_tasks",
    "queued_tasks",
    "result_stores",
    "replacement_plans",
    "snapshots",
    "temp_paths",
}
_BASE_METRICS = {"rss_mib", "cache_used_mib"}
_TIMING_METRIC = {
    "daily_editing": "daily_cycle_ms",
    "format_integrity": "format_cycle_ms",
    "regex_replacement": "regex_cycle_ms",
    "session_lifecycle": "lifecycle_cycle_ms",
}
_PROBES = {"handle_count", "temp_paths"}


class A22CIError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = max(1, int(exit_code))


def _reject_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _decode(raw: bytes) -> object:
    if not isinstance(raw, bytes) or len(raw) > MAX_SUITE_BYTES:
        raise A22CIError("sustained result exceeds its size limit")
    try:
        return json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_unique_object,
            parse_constant=_reject_constant,
        )
    except UnicodeError as error:
        raise A22CIError("sustained result is not UTF-8") from error
    except ValueError as error:
        message = "duplicate JSON field" if "duplicate" in str(error) else "invalid JSON"
        raise A22CIError(f"sustained result contains {message}") from error


def _exact(value: object, fields: set[str], label: str) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise A22CIError(f"sustained {label} fields are invalid")
    return value


def _plain_int(value: object, label: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise A22CIError(f"sustained {label} is invalid")
    return value


def _state(value: object, label: str) -> str:
    if not isinstance(value, str) or value not in _STATES:
        raise A22CIError(f"sustained {label} state is invalid")
    return value


def _messages(value: object, label: str) -> list[str]:
    if (
        not isinstance(value, list)
        or len(value) > 32
        or any(
            not isinstance(item, str) or len(item) > 1024
            for item in value
        )
    ):
        raise A22CIError(f"sustained {label} messages are invalid")
    return value


def _private_fact(value: object) -> bool:
    if value is None or isinstance(value, bool):
        return False
    if isinstance(value, int):
        return False
    if isinstance(value, float):
        return not math.isfinite(value)
    if isinstance(value, str):
        return _TOKEN.fullmatch(value) is None
    if isinstance(value, list):
        return len(value) > 256 or any(_private_fact(item) for item in value)
    if isinstance(value, dict):
        return (
            len(value) > 256
            or any(not isinstance(key, str) or _TOKEN.fullmatch(key) is None for key in value)
            or any(_private_fact(item) for item in value.values())
        )
    return True


def _validate_checkpoint(
    value: object,
    *,
    family: str,
    cycle: int,
) -> None:
    checkpoint = _exact(value, _CHECKPOINT_FIELDS, "checkpoint")
    if _plain_int(checkpoint["cycle"], "checkpoint cycle", minimum=1) != cycle:
        raise A22CIError("sustained checkpoint cycles are invalid")
    metrics = checkpoint["metrics"]
    allowed_metrics = _BASE_METRICS | {_TIMING_METRIC[family], "handle_count"}
    required_metrics = _BASE_METRICS | {_TIMING_METRIC[family]}
    if (
        not isinstance(metrics, dict)
        or not required_metrics <= set(metrics) <= allowed_metrics
        or any(
            isinstance(item, bool)
            or not isinstance(item, (int, float))
            or not math.isfinite(float(item))
            or float(item) < 0
            for item in metrics.values()
        )
    ):
        raise A22CIError("sustained checkpoint metrics are invalid")
    owned = checkpoint["owned_counts"]
    if (
        not isinstance(owned, dict)
        or set(owned) != _OWNED_COUNT_FIELDS
        or any(
            isinstance(item, bool) or not isinstance(item, int) or item < 0
            for item in owned.values()
        )
    ):
        raise A22CIError("sustained checkpoint owned counts are invalid")
    probes = checkpoint["unavailable_probes"]
    if (
        not isinstance(probes, list)
        or len(probes) != len(set(probes))
        or any(item not in _PROBES for item in probes)
    ):
        raise A22CIError("sustained checkpoint probes are invalid")


def validate_sustained_result(
    raw: bytes,
    *,
    require_pass: bool,
) -> dict[str, object]:
    """Strictly validate one hosted result without importing project code."""

    suite = _exact(_decode(raw), _SUITE_FIELDS, "suite")
    if (
        suite["schema"] != 2
        or suite["profile"] != "a22-v1"
        or suite["execution_class"] != "hosted"
    ):
        raise A22CIError("sustained suite identity is invalid")
    suite_state = _state(suite["state"], "suite")
    host = _exact(suite["host"], _HOST_FIELDS, "host")
    if (
        _plain_int(host["physical_cores"], "host core count", minimum=1) < 1
        or _plain_int(host["physical_memory"], "host memory", minimum=1) < 1
        or host["corpus_schema"] != 2
        or type(host["contended"]) is not bool
        or any(
            not isinstance(host[name], str) or _TOKEN.fullmatch(host[name]) is None
            for name in (
                "architecture",
                "platform",
                "python_version",
                "qt_version",
                "git_commit",
            )
        )
    ):
        raise A22CIError("sustained host facts are invalid")
    families = suite["families"]
    if not isinstance(families, list) or len(families) != len(SUSTAINED_FAMILIES):
        raise A22CIError("sustained families are invalid")
    family_states: list[str] = []
    for expected, value in zip(SUSTAINED_FAMILIES, families, strict=True):
        family = _exact(value, _FAMILY_FIELDS, "family")
        if (
            family["schema"] != 2
            or family["family"] != expected
            or family["profile"] != "a22-v1"
            or family["warmup_cycles"] != WARMUP_CYCLES
            or family["measured_cycles"] != HOSTED_CYCLES
        ):
            raise A22CIError("sustained family identity is invalid")
        family_states.append(_state(family["state"], "family"))
        checkpoints = family["checkpoints"]
        if not isinstance(checkpoints, list) or len(checkpoints) != HOSTED_CYCLES:
            raise A22CIError("sustained checkpoint count is invalid")
        for cycle, checkpoint in enumerate(checkpoints, start=1):
            _validate_checkpoint(checkpoint, family=expected, cycle=cycle)
        facts = family["facts"]
        if not isinstance(facts, dict) or _private_fact(facts):
            raise A22CIError("sustained result contains private facts")
        _messages(family["messages"], "family")
        encoded_family = json.dumps(
            family,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded_family) > MAX_FAMILY_BYTES:
            raise A22CIError("sustained family exceeds its size limit")
    evaluations = suite["evaluations"]
    if not isinstance(evaluations, list) or len(evaluations) != len(SUSTAINED_FAMILIES):
        raise A22CIError("sustained evaluations are invalid")
    evaluation_states: list[str] = []
    for expected, value in zip(SUSTAINED_FAMILIES, evaluations, strict=True):
        evaluation = _exact(value, _EVALUATION_FIELDS, "evaluation")
        if evaluation["subject"] != expected:
            raise A22CIError("sustained evaluation subject is invalid")
        evaluation_states.append(_state(evaluation["state"], "evaluation"))
        _messages(evaluation["messages"], "evaluation")
    aggregate = max(evaluation_states, key=_STATE_RANK.__getitem__)
    if aggregate != suite_state:
        raise A22CIError("sustained aggregate state is invalid")
    if require_pass and (
        suite_state != "PASS"
        or any(state != "PASS" for state in family_states)
        or any(state != "PASS" for state in evaluation_states)
    ):
        raise A22CIError("sustained gate requires PASS state")
    return suite


def _platform_family(platform_name: str) -> str:
    if platform_name == "darwin":
        return "macos"
    if platform_name.startswith("linux"):
        return "linux"
    if platform_name.startswith("win"):
        return "windows"
    raise A22CIError("host platform is unsupported")


def _runtime_python(environment: Path, platform_name: str) -> Path:
    if platform_name.startswith("win"):
        return environment / "Scripts" / "python.exe"
    return environment / "bin" / "python"


def _owned_runtime(root: Path, platform_name: str) -> Path:
    environment = root / ".venv"
    manifest_path = environment / ".uniti-runtime.json"
    try:
        if manifest_path.is_symlink():
            raise A22CIError("owned runtime manifest must not be a symlink")
        manifest = _decode(manifest_path.read_bytes())
    except OSError as error:
        raise A22CIError("owned runtime manifest is unavailable") from error
    if (
        not isinstance(manifest, dict)
        or manifest.get("schema") != 1
        or manifest.get("owner") != "uniti-editor"
        or manifest.get("healthy") is not True
        or manifest.get("mode") != "source"
    ):
        raise A22CIError("owned runtime manifest is invalid")
    try:
        selected = Path(manifest["environment_path"]).resolve()
    except (TypeError, OSError) as error:
        raise A22CIError("owned runtime path is invalid") from error
    if selected != environment.resolve():
        raise A22CIError("owned runtime manifest points outside the repository")
    runtime = _runtime_python(environment, platform_name)
    if not runtime.is_file():
        raise A22CIError("owned runtime Python is unavailable")
    return runtime


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_json(path: Path, value: Mapping[str, object]) -> None:
    payload = (
        json.dumps(
            dict(value),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    if len(payload) > MAX_FAMILY_BYTES:
        raise A22CIError("sanitized result exceeds its size limit")
    _atomic_write(path, payload)


class A22CIDriver:
    def __init__(
        self,
        root: Path,
        family: str,
        *,
        platform_name: str = sys.platform,
        runner=subprocess.run,
        environ: Mapping[str, str] = os.environ,
    ) -> None:
        selected_root = Path(root).resolve()
        if family not in FAMILIES:
            raise A22CIError("requested CI family is invalid")
        if _platform_family(platform_name) != family:
            raise A22CIError("requested CI family does not match the host")
        if not callable(runner):
            raise TypeError("runner must be callable")
        self.root = selected_root
        self.family = family
        self.platform_name = platform_name
        self.runtime_python = _owned_runtime(selected_root, platform_name)
        self._runner = runner
        self._environ = dict(environ)

    def run(self) -> dict[str, object]:
        results = self.root / "ci-results"
        if results.is_symlink():
            raise A22CIError("CI result directory must not be a symlink")
        results.mkdir(parents=True, exist_ok=True)
        output = results / RESULT_NAME
        if output.is_symlink():
            raise A22CIError("sustained result path must not be a symlink")
        output.unlink(missing_ok=True)
        work = results / "a22-work"
        if work.is_symlink():
            raise A22CIError("sustained work directory must not be a symlink")
        work.mkdir(parents=True, exist_ok=True)
        environment = dict(self._environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        command = [
            str(self.runtime_python),
            "scripts/performance_suite.py",
            "--suite",
            "sustained",
            "--profile",
            "hosted",
            "--output",
            str(output),
            "--temp-root",
            str(work),
        ]
        try:
            completed = self._runner(
                command,
                cwd=self.root,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                shell=False,
            )
        except OSError as error:
            raise A22CIError("sustained runner could not start") from error
        try:
            if output.is_symlink() or not output.is_file():
                raise A22CIError("sustained runner produced no regular result")
            raw = output.read_bytes()
        except OSError as error:
            raise A22CIError("sustained result is unreadable") from error
        suite = validate_sustained_result(raw, require_pass=True)
        if completed.returncode != 0:
            raise A22CIError(
                "sustained runner failed",
                exit_code=completed.returncode,
            )
        return {
            "schema": 1,
            "family": self.family,
            "state": suite["state"],
            "families": len(suite["families"]),
            "cycles": HOSTED_CYCLES,
        }


def _sanitized_summary(suite: dict[str, object]) -> dict[str, object]:
    families = suite["families"]
    evaluations = suite["evaluations"]
    return {
        "schema": 1,
        "profile": suite["profile"],
        "execution_class": suite["execution_class"],
        "state": suite["state"],
        "families": [
            {
                "family": family["family"],
                "state": family["state"],
                "warmup_cycles": family["warmup_cycles"],
                "measured_cycles": family["measured_cycles"],
                "checkpoint_count": len(family["checkpoints"]),
                "message_count": len(family["messages"]),
            }
            for family in families
        ],
        "evaluations": [
            {
                "subject": evaluation["subject"],
                "state": evaluation["state"],
                "message_count": len(evaluation["messages"]),
            }
            for evaluation in evaluations
        ],
    }


def sanitize_results(root: Path, family: str) -> dict[str, object]:
    if family not in FAMILIES:
        raise A22CIError("requested CI family is invalid")
    results = Path(root).resolve() / "ci-results"
    if results.is_symlink():
        raise A22CIError("CI result directory must not be a symlink")
    destination = results / "sanitized"
    if destination.is_symlink():
        raise A22CIError("sanitized output directory must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    for existing in destination.iterdir():
        if existing.is_file() or existing.is_symlink():
            existing.unlink()
        else:
            raise A22CIError("sanitized output contains an unexpected directory")
    written = 0
    errors = 0
    source = results / RESULT_NAME
    try:
        if source.is_symlink() or not source.is_file():
            raise A22CIError("sustained result is unavailable")
        suite = validate_sustained_result(source.read_bytes(), require_pass=False)
        if suite["state"] == "PASS":
            raise A22CIError("successful sustained evidence is not a failure artifact")
        _write_json(destination / RESULT_NAME, _sanitized_summary(suite))
        written = 1
    except (OSError, A22CIError, ValueError):
        errors = 1
        _write_json(
            destination / "artifact-errors.json",
            {"schema": 1, "errors": [{"file": RESULT_NAME, "reason": "invalid"}]},
        )
    _write_json(
        destination / "artifact-metadata.json",
        {
            "schema": 1,
            "family": family,
            "retention_days": ARTIFACT_RETENTION_DAYS,
            "files": [RESULT_NAME] if written else [],
        },
    )
    return {"schema": 1, "family": family, "files": written, "errors": errors}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "sanitize"):
        command = commands.add_parser(name)
        command.add_argument("--family", choices=FAMILIES, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if arguments.command == "sanitize":
            result = sanitize_results(root, arguments.family)
        else:
            result = A22CIDriver(root, arguments.family).run()
        print(json.dumps(result, sort_keys=True))
        return 0
    except A22CIError as error:
        print(f"a22-ci: {error}", file=sys.stderr)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
