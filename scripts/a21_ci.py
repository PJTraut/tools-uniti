#!/usr/bin/env python3
"""Owned-runtime A21 CI phases, exact skips, and bounded artifacts."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
import xml.etree.ElementTree as ET
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

FAMILIES = ("macos", "linux", "windows")
MAX_INPUT_BYTES = 2 << 20
MAX_TOTAL_INPUT_BYTES = 8 << 20
MAX_FAILURE_TEXT = 4 << 10
ARTIFACT_RETENTION_DAYS = 7
_RESULT_NAMES = (
    "runtime.json",
    "self-check.json",
    "smoke-offscreen.json",
    "smoke-native.json",
    "pytest.xml",
)
_CROSS_PLATFORM_FIELDS = {
    "family",
    "python_version",
    "pyside_version",
    "qt_version",
    "platform_plugin",
    "path_categories",
    "filesystem_capabilities",
    "durability",
    "font",
    "launcher_mode",
}
_SMOKE_FIELDS = {
    "ok",
    "core_ok",
    "gui_ok",
    "platform_family",
    "qt_platform",
    "durability",
    "font",
    "shortcut_defaults",
    "instance_forwarded",
    "unicode_spaced_path",
    "service_remained_running",
    "activation_created_window",
    "one_document_authority",
    "session_restored",
    "history_restored",
    "find_replace_attached",
    "find_replace_followed_window",
    "find_replace_detached",
    "find_replace_restored",
    "display_settings_applied",
    "explicit_quit",
}
_RUNTIME_FIELDS = {
    "schema",
    "family",
    "python_version",
    "python_implementation",
    "uniti_version",
    "display_version",
    "metadata_version",
    "pyside_version",
    "regex_version",
    "owned",
    "launcher_mode",
}
_FONT_FIELDS = {
    "requested_family",
    "resolved_family",
    "fixed_pitch",
    "latin_coverage",
    "cyrillic_coverage",
    "fallback",
}
_FILESYSTEM_FIELDS = {
    "write",
    "fsync",
    "atomic_replace",
    "directory_sync",
    "durability",
    "mmap",
    "xattrs",
}


class A21CIError(RuntimeError):
    def __init__(self, message: str, *, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = max(1, int(exit_code))


def _platform_family(platform_name: str) -> str:
    if platform_name == "darwin":
        return "macos"
    if platform_name.startswith("win"):
        return "windows"
    if platform_name.startswith("linux"):
        return "linux"
    raise A21CIError("host platform is unsupported")


def _runtime_python(environment: Path, platform_name: str) -> Path:
    if platform_name.startswith("win"):
        return Path(environment) / "Scripts" / "python.exe"
    return Path(environment) / "bin" / "python"


def _reject_constant(value: str):
    raise ValueError(f"invalid JSON constant: {value}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON field")
        result[key] = value
    return result


def _json_loads(text: str) -> object:
    return json.loads(
        text,
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )


def _read_bounded(path: Path) -> bytes:
    try:
        size = path.stat().st_size
    except OSError as error:
        raise A21CIError(f"required evidence is unreadable: {path.name}") from error
    if size > MAX_INPUT_BYTES:
        raise A21CIError(f"evidence exceeds its size limit: {path.name}")
    try:
        return path.read_bytes()
    except OSError as error:
        raise A21CIError(f"required evidence is unreadable: {path.name}") from error


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


def _write_json(path: Path, payload: Mapping[str, object]) -> None:
    encoded = (
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")
    _atomic_write(path, encoded)


def load_skip_policy(path: Path) -> dict[str, tuple[tuple[str, str], ...]]:
    try:
        payload = _json_loads(_read_bounded(Path(path)).decode("utf-8"))
    except (UnicodeError, ValueError) as error:
        raise A21CIError("skip policy is malformed") from error
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema", "families"}
        or payload.get("schema") != 1
        or not isinstance(payload.get("families"), dict)
        or set(payload["families"]) != set(FAMILIES)
    ):
        raise A21CIError("skip policy schema or families are invalid")

    policy: dict[str, tuple[tuple[str, str], ...]] = {}
    for family in FAMILIES:
        raw_entries = payload["families"][family]
        if not isinstance(raw_entries, list):
            raise A21CIError("skip policy entries are invalid")
        entries: list[tuple[str, str]] = []
        seen: set[str] = set()
        for raw_entry in raw_entries:
            if (
                not isinstance(raw_entry, list)
                or len(raw_entry) != 2
                or any(
                    not isinstance(value, str) or not value or len(value) > 512
                    for value in raw_entry
                )
            ):
                raise A21CIError("skip policy entry is invalid")
            node_id, reason = raw_entry
            if node_id in seen:
                raise A21CIError("skip policy contains a duplicate node ID")
            seen.add(node_id)
            entries.append((node_id, reason))
        policy[family] = tuple(entries)
    return policy


def _junit_node_id(case: ET.Element) -> str:
    file_name = case.get("file")
    if not file_name:
        class_name = case.get("classname", "")
        if not class_name:
            raise A21CIError("JUnit testcase has no file or class identity")
        file_name = class_name.replace(".", "/") + ".py"
    name = case.get("name", "")
    if not name:
        raise A21CIError("JUnit testcase name is missing")
    return f"{file_name.replace('\\', '/')}::{name}"


def _parse_junit(path: Path) -> tuple[ET.Element, tuple[ET.Element, ...]]:
    try:
        root = ET.fromstring(_read_bounded(Path(path)))
    except ET.ParseError as error:
        raise A21CIError("JUnit evidence is malformed") from error
    cases = tuple(root.iter("testcase"))
    if not cases:
        raise A21CIError("JUnit evidence contains zero tests")
    seen: set[str] = set()
    for case in cases:
        node_id = _junit_node_id(case)
        if node_id in seen:
            raise A21CIError("JUnit evidence contains a duplicate testcase")
        seen.add(node_id)
    return root, cases


def verify_skips(
    junit_path: Path,
    family: str,
    policy_path: Path,
) -> dict[str, object]:
    if family not in FAMILIES:
        raise A21CIError("requested CI family is invalid")
    policy = load_skip_policy(policy_path)
    _root, cases = _parse_junit(junit_path)
    expected = dict(policy[family])
    known_elsewhere = {
        node_id
        for other_family, entries in policy.items()
        if other_family != family
        for node_id, _reason in entries
    }
    observed: dict[str, str] = {}
    for case in cases:
        skipped = case.find("skipped")
        if skipped is None:
            continue
        node_id = _junit_node_id(case)
        reason = (skipped.get("message") or skipped.text or "").strip()
        if node_id in expected:
            if reason != expected[node_id]:
                raise A21CIError(f"skip reason mismatch for {node_id}")
        elif node_id in known_elsewhere:
            raise A21CIError(f"test should run on {family}: {node_id}")
        else:
            raise A21CIError(f"unknown skip on {family}: {node_id}")
        observed[node_id] = reason
    missing = tuple(sorted(set(expected).difference(observed)))
    if missing:
        raise A21CIError(f"missing expected skip on {family}: {missing[0]}")
    return {
        "schema": 1,
        "family": family,
        "tests": len(cases),
        "skips": len(observed),
    }


_RUNTIME_PROBE = """import importlib.metadata,json,platform,sys
import PySide6,regex,uniti
print(json.dumps({
    'python_version': platform.python_version(),
    'python_implementation': platform.python_implementation(),
    'uniti_version': uniti.__version__,
    'display_version': uniti.__display_version__,
    'metadata_version': importlib.metadata.version('uniti-editor'),
    'pyside_version': PySide6.__version__,
    'regex_version': importlib.metadata.version('regex'),
}))
"""


class A21CIDriver:
    def __init__(
        self,
        root: Path,
        family: str,
        *,
        platform_name: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        which: Callable[[str], str | None] = shutil.which,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.root = Path(root).resolve()
        self.family = family
        self.platform_name = sys.platform if platform_name is None else platform_name
        if family not in FAMILIES:
            raise A21CIError("requested CI family is invalid")
        if _platform_family(self.platform_name) != family:
            raise A21CIError("requested CI family does not match the host")
        self.runner = runner
        self.which = which
        self.environ = dict(os.environ if environ is None else environ)
        self.environment = self.root / ".venv"
        self.runtime_python = _runtime_python(self.environment, self.platform_name)
        self.results = self.root / "ci-results"
        self.launcher_mode = self._validate_owned_runtime()

    def _validate_owned_runtime(self) -> str:
        marker_path = self.environment / ".uniti-runtime.json"
        if not self.runtime_python.is_file():
            raise A21CIError("owned runtime Python is missing")
        try:
            payload = _json_loads(_read_bounded(marker_path).decode("utf-8"))
        except (UnicodeError, ValueError) as error:
            raise A21CIError("owned runtime marker is malformed") from error
        if not isinstance(payload, dict):
            raise A21CIError("owned runtime marker is invalid")
        mode = payload.get("mode")
        valid = (
            payload.get("schema") == 1
            and payload.get("owner") == "uniti-editor"
            and payload.get("healthy") is True
            and mode in {"source", "local"}
            and Path(str(payload.get("environment_path", ""))).resolve()
            == self.environment
        )
        if not valid:
            raise A21CIError("owned runtime marker does not match this runtime")
        return str(mode)

    def _run(
        self,
        name: str,
        command: Sequence[str],
        *,
        capture: bool = False,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        try:
            if capture:
                completed = self.runner(
                    list(command),
                    cwd=self.root,
                    text=True,
                    check=False,
                    shell=False,
                    env=dict(self.environ if env is None else env),
                    capture_output=True,
                )
            else:
                completed = self.runner(
                    list(command),
                    cwd=self.root,
                    text=True,
                    check=False,
                    shell=False,
                    env=dict(self.environ if env is None else env),
                )
        except (OSError, subprocess.SubprocessError) as error:
            raise A21CIError(f"{name} failed to start") from error
        if completed.returncode != 0:
            raise A21CIError(
                f"{name} failed with exit code {completed.returncode}",
                exit_code=completed.returncode,
            )
        return completed

    def run_runtime(self) -> dict[str, object]:
        completed = self._run(
            "runtime validation",
            [str(self.runtime_python), "-c", _RUNTIME_PROBE],
            capture=True,
        )
        try:
            observed = _json_loads(completed.stdout)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise A21CIError("runtime validation returned invalid JSON") from error
        if not isinstance(observed, dict):
            raise A21CIError("runtime validation returned invalid evidence")
        try:
            version = tuple(
                int(part) for part in str(observed["python_version"]).split(".")
            )
        except (KeyError, TypeError, ValueError) as error:
            raise A21CIError("runtime Python version is invalid") from error
        if version < (3, 12):
            raise A21CIError("runtime Python is older than 3.12")
        if (
            observed.get("metadata_version") != observed.get("uniti_version")
            or observed.get("regex_version") != "2026.5.9"
            or not observed.get("pyside_version")
        ):
            raise A21CIError("runtime package metadata or dependencies are invalid")
        self._run(
            "pip check",
            [str(self.runtime_python), "-m", "pip", "check"],
        )
        evidence = {
            "schema": 1,
            "family": self.family,
            **{key: observed[key] for key in observed if key in _RUNTIME_FIELDS},
            "owned": True,
            "launcher_mode": self.launcher_mode,
        }
        _write_json(self.results / "runtime.json", evidence)
        return evidence

    def run_pytest(self) -> None:
        self.results.mkdir(parents=True, exist_ok=True)
        self._run(
            "pytest",
            [
                str(self.runtime_python),
                "-m",
                "pytest",
                "-q",
                f"--junitxml={self.results / 'pytest.xml'}",
            ],
        )

    def run_compile(self) -> None:
        self._run(
            "compile",
            [
                str(self.runtime_python),
                "-m",
                "compileall",
                "-q",
                "src",
                "scripts",
                "benchmarks",
                "tests",
            ],
        )

    def run_self_check(self) -> dict[str, object]:
        environment = dict(self.environ)
        environment["QT_QPA_PLATFORM"] = "offscreen"
        completed = self._run(
            "self-check",
            [
                str(self.runtime_python),
                "-m",
                "uniti",
                "--self-check",
                "--deep",
                "--json",
            ],
            capture=True,
            env=environment,
        )
        payload = self._validated_json_result(completed.stdout, "self-check")
        results = payload.get("results")
        cross = None
        if isinstance(results, list):
            cross = next(
                (
                    item
                    for item in results
                    if isinstance(item, dict) and item.get("name") == "cross-platform"
                ),
                None,
            )
        if (
            payload.get("status") != "pass"
            or not isinstance(cross, dict)
            or set(cross.get("details", {})) != _CROSS_PLATFORM_FIELDS
            or cross["details"].get("family") != self.family
        ):
            raise A21CIError("self-check evidence does not satisfy A21")
        _write_json(self.results / "self-check.json", payload)
        print(completed.stdout, end="")
        return payload

    @staticmethod
    def _validated_json_result(text: str, name: str) -> dict[str, object]:
        try:
            payload = _json_loads(text)
        except (TypeError, ValueError, json.JSONDecodeError) as error:
            raise A21CIError(f"{name} returned invalid JSON") from error
        if not isinstance(payload, dict):
            raise A21CIError(f"{name} returned invalid evidence")
        return payload

    def run_smoke(self, mode: str) -> dict[str, object]:
        if mode not in {"offscreen", "native"}:
            raise A21CIError("smoke mode is invalid")
        environment = dict(self.environ)
        command = [str(self.runtime_python), "-m", "uniti", "--smoke"]
        expected_plugin = "offscreen"
        if mode == "offscreen":
            environment["QT_QPA_PLATFORM"] = "offscreen"
        elif self.family == "linux":
            xvfb = self.which("xvfb-run")
            if not xvfb:
                raise A21CIError("Linux native smoke requires xvfb-run")
            command = [xvfb, "-a", *command]
            environment["QT_QPA_PLATFORM"] = "xcb"
            expected_plugin = "xcb"
        else:
            environment.pop("QT_QPA_PLATFORM", None)
            expected_plugin = "cocoa" if self.family == "macos" else "windows"
        completed = self._run(
            f"{mode} smoke",
            command,
            capture=True,
            env=environment,
        )
        payload = self._validated_json_result(completed.stdout, f"{mode} smoke")
        if (
            payload.get("ok") is not True
            or payload.get("platform_family") != self.family
            or payload.get("qt_platform") != expected_plugin
        ):
            raise A21CIError(f"{mode} smoke evidence does not satisfy A21")
        _write_json(self.results / f"smoke-{mode}.json", payload)
        print(completed.stdout, end="")
        return payload


def _redactor(
    workspace: Path,
    home: Path,
    temp_root: Path,
    runner_work: Path | None,
) -> Callable[[str], str]:
    roots = [
        (str(workspace.resolve()), "<workspace>"),
        (str(home.resolve()), "<home>"),
        (str(temp_root.resolve()), "<temp>"),
    ]
    if runner_work is not None:
        roots.append((str(runner_work.resolve()), "<runner>"))
    roots.sort(key=lambda item: len(item[0]), reverse=True)

    def redact(value: str) -> str:
        selected = value
        for root, replacement in roots:
            selected = selected.replace(root, replacement)
            selected = selected.replace(root.replace("/", "\\"), replacement)
        return selected

    return redact


def _bounded_text(
    value: object,
    redact: Callable[[str], str],
    *,
    maximum: int = MAX_FAILURE_TEXT,
) -> str:
    selected = "" if value is None else str(value)
    selected = "".join(
        character if character.isprintable() or character in "\n\t" else "?"
        for character in selected
    )
    return redact(selected)[:maximum]


def _safe_scalar(value: object, redact: Callable[[str], str]) -> object | None:
    if value is None or type(value) in {bool, int, float}:
        return value
    if isinstance(value, str):
        return _bounded_text(value, redact, maximum=512)
    return None


def _sanitized_font(
    value: object,
    redact: Callable[[str], str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    return {
        key: selected
        for key in _FONT_FIELDS
        if key in value
        and (selected := _safe_scalar(value[key], redact)) is not None
    }


def _sanitized_cross_platform(
    value: object,
    redact: Callable[[str], str],
) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    result: dict[str, object] = {}
    for key in _CROSS_PLATFORM_FIELDS:
        if key not in value:
            continue
        if key == "font":
            result[key] = _sanitized_font(value[key], redact)
        elif key == "path_categories" and isinstance(value[key], dict):
            paths = value[key]
            path_result: dict[str, object] = {}
            category = _safe_scalar(paths.get("category"), redact)
            if category is not None:
                path_result["category"] = category
            for root_name in ("config", "data", "state", "cache"):
                root = paths.get(root_name)
                if isinstance(root, dict):
                    path_result[root_name] = {
                        name: root[name]
                        for name in ("absolute", "writable")
                        if type(root.get(name)) is bool
                    }
            result[key] = path_result
        elif key == "filesystem_capabilities" and isinstance(value[key], dict):
            capabilities = value[key]
            result[key] = {
                name: selected
                for name in _FILESYSTEM_FIELDS
                if name in capabilities
                and (selected := _safe_scalar(capabilities[name], redact))
                is not None
            }
        else:
            selected = _safe_scalar(value[key], redact)
            if selected is not None:
                result[key] = selected
    return result


def _sanitized_json(
    name: str,
    raw: bytes,
    redact: Callable[[str], str],
) -> dict[str, object]:
    payload = _json_loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("JSON evidence must be an object")
    if name == "runtime.json":
        return {
            key: selected
            for key in _RUNTIME_FIELDS
            if key in payload
            and (selected := _safe_scalar(payload[key], redact)) is not None
        }
    if name.startswith("smoke-"):
        result = {
            key: selected
            for key in _SMOKE_FIELDS.difference({"font"})
            if key in payload
            and (selected := _safe_scalar(payload[key], redact)) is not None
        }
        if "font" in payload:
            result["font"] = _sanitized_font(payload["font"], redact)
        return result
    if name == "self-check.json":
        results = payload.get("results")
        cross_results: list[dict[str, object]] = []
        if isinstance(results, list):
            for item in results:
                if not isinstance(item, dict) or item.get("name") != "cross-platform":
                    continue
                details = item.get("details")
                if not isinstance(details, dict):
                    continue
                cross_results.append(
                    {
                        "name": "cross-platform",
                        "status": item.get("status"),
                        "exit_code": item.get("exit_code"),
                        "details": {
                            **_sanitized_cross_platform(details, redact)
                        },
                    }
                )
        return {
            key: payload[key]
            for key in ("schema", "mode", "status", "exit_code")
            if key in payload
        } | {"results": cross_results}
    raise ValueError("JSON evidence name is not allowed")


def _sanitized_junit(raw: bytes, redact: Callable[[str], str]) -> bytes:
    root = ET.fromstring(raw)
    output = ET.Element("testsuites")
    for suite in root.iter("testsuite"):
        clean_suite = ET.SubElement(
            output,
            "testsuite",
            {
                key: _bounded_text(suite.get(key), redact)
                for key in ("name", "tests", "failures", "errors", "skipped", "time")
                if suite.get(key) is not None
            },
        )
        for case in suite.findall("testcase"):
            clean_case = ET.SubElement(
                clean_suite,
                "testcase",
                {
                    key: _bounded_text(case.get(key), redact)
                    for key in ("classname", "name", "file", "time")
                    if case.get(key) is not None
                },
            )
            for status in ("skipped", "failure", "error"):
                child = case.find(status)
                if child is None:
                    continue
                clean_child = ET.SubElement(
                    clean_case,
                    status,
                    {
                        key: _bounded_text(child.get(key), redact)
                        for key in ("message", "type")
                        if child.get(key) is not None
                    },
                )
                clean_child.text = _bounded_text(child.text, redact)
    ET.indent(output)
    return ET.tostring(output, encoding="utf-8", xml_declaration=True)


def sanitize_results(
    root: Path,
    family: str,
    *,
    home: Path | None = None,
    temp: Path | None = None,
    runner_work: Path | None = None,
) -> dict[str, object]:
    if family not in FAMILIES:
        raise A21CIError("requested CI family is invalid")
    workspace = Path(root).resolve()
    results = workspace / "ci-results"
    destination = results / "sanitized"
    if destination.is_symlink():
        raise A21CIError("sanitized output directory must not be a symlink")
    destination.mkdir(parents=True, exist_ok=True)
    errors: list[dict[str, str]] = []
    for existing in destination.iterdir():
        if existing.is_file() or existing.is_symlink():
            existing.unlink()
        else:
            raise A21CIError("sanitized output contains an unexpected directory")
    candidates_list: list[Path] = []
    for name in _RESULT_NAMES:
        candidate = results / name
        if candidate.is_symlink():
            errors.append({"file": name, "reason": "unsafe"})
        elif candidate.is_file():
            candidates_list.append(candidate)
    candidates = tuple(candidates_list)
    try:
        total = sum(path.stat().st_size for path in candidates)
    except OSError:
        total = MAX_TOTAL_INPUT_BYTES + 1
    if total > MAX_TOTAL_INPUT_BYTES:
        errors.append({"file": "<aggregate>", "reason": "total_budget"})
        candidates = ()

    redact = _redactor(
        workspace,
        Path.home() if home is None else Path(home),
        Path(tempfile.gettempdir()) if temp is None else Path(temp),
        (
            Path(os.environ["RUNNER_WORKSPACE"])
            if runner_work is None and os.environ.get("RUNNER_WORKSPACE")
            else runner_work
        ),
    )
    written: list[str] = []
    for source in candidates:
        if source.stat().st_size > MAX_INPUT_BYTES:
            errors.append({"file": source.name, "reason": "oversized"})
            continue
        try:
            raw = source.read_bytes()
            if source.suffix == ".json":
                sanitized = _sanitized_json(source.name, raw, redact)
                encoded = (
                    json.dumps(
                        sanitized,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                        allow_nan=False,
                    )
                    + "\n"
                ).encode("utf-8")
            else:
                encoded = _sanitized_junit(raw, redact)
            if len(encoded) > MAX_INPUT_BYTES:
                raise ValueError("sanitized evidence exceeds its size limit")
            _atomic_write(destination / source.name, encoded)
            written.append(source.name)
        except (OSError, UnicodeError, ValueError, ET.ParseError):
            errors.append({"file": source.name, "reason": "invalid"})

    metadata = {
        "schema": 1,
        "family": family,
        "retention_days": ARTIFACT_RETENTION_DAYS,
        "files": sorted(written),
    }
    _write_json(destination / "artifact-metadata.json", metadata)
    if errors:
        _write_json(
            destination / "artifact-errors.json",
            {"schema": 1, "errors": errors},
        )
    return {
        "schema": 1,
        "family": family,
        "files": len(written),
        "errors": len(errors),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in (
        "runtime",
        "pytest",
        "compile",
        "self-check",
        "verify-skips",
        "sanitize",
    ):
        command = commands.add_parser(name)
        command.add_argument("--family", choices=FAMILIES, required=True)
    smoke = commands.add_parser("smoke")
    smoke.add_argument("--family", choices=FAMILIES, required=True)
    smoke.add_argument("--mode", choices=("offscreen", "native"), required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    root = Path(__file__).resolve().parents[1]
    try:
        if arguments.command == "verify-skips":
            result = verify_skips(
                root / "ci-results" / "pytest.xml",
                arguments.family,
                root / "ci" / "a21-skip-policy.json",
            )
            print(json.dumps(result, sort_keys=True))
            return 0
        if arguments.command == "sanitize":
            result = sanitize_results(root, arguments.family)
            print(json.dumps(result, sort_keys=True))
            return 0
        driver = A21CIDriver(root, arguments.family)
        if arguments.command == "runtime":
            driver.run_runtime()
        elif arguments.command == "pytest":
            driver.run_pytest()
        elif arguments.command == "compile":
            driver.run_compile()
        elif arguments.command == "self-check":
            driver.run_self_check()
        elif arguments.command == "smoke":
            driver.run_smoke(arguments.mode)
        return 0
    except A21CIError as error:
        print(f"a21-ci: {error}", file=sys.stderr)
        return error.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
