"""Fast and deep UNITI lifecycle checks with stable safe reports."""

from __future__ import annotations

import importlib.metadata
import json
import os
import platform
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import uniti

from uniti.core.byte_source import ByteSource
from uniti.core.document import Document
from uniti.core.encoding import detect_encoding
from uniti.core.eol import analyze_eol
from uniti.regex.engine import compile_pattern
from uniti.regex.replace import replace_all
from uniti.resources import ResourceManager

from .capabilities import CapabilityStatus, probe_filesystem, probe_runtime
from .paths import AppPaths
from .recovery_manager import RecoveryManager
from .settings import SettingsStore
from .setup_state import SetupStateStore
from .startup import ExitCode


class CheckStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    SKIP = "skip"


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    status: CheckStatus
    duration_ms: float
    summary: str
    details: Mapping[str, object]
    exit_code: ExitCode = ExitCode.SUCCESS

    @classmethod
    def passed(
        cls,
        name: str,
        summary: str,
        details: Mapping[str, object] | None = None,
        *,
        duration_ms: float = 0.0,
    ) -> "CheckResult":
        return cls(name, CheckStatus.PASS, duration_ms, summary, details or {})

    @classmethod
    def failed(
        cls,
        name: str,
        exit_code: ExitCode,
        summary: str,
        details: Mapping[str, object] | None = None,
        *,
        duration_ms: float = 0.0,
    ) -> "CheckResult":
        return cls(name, CheckStatus.FAIL, duration_ms, summary, details or {}, exit_code)

    @classmethod
    def skipped(
        cls,
        name: str,
        summary: str,
        details: Mapping[str, object] | None = None,
        *,
        duration_ms: float = 0.0,
    ) -> "CheckResult":
        return cls(name, CheckStatus.SKIP, duration_ms, summary, details or {})

    def as_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "status": self.status.value,
            "duration_ms": round(self.duration_ms, 3),
            "summary": self.summary,
            "details": dict(self.details),
            "exit_code": int(self.exit_code),
        }


@dataclass(frozen=True, slots=True)
class SelfCheckReport:
    mode: str
    identity: Mapping[str, object]
    results: tuple[CheckResult, ...]
    status: CheckStatus
    exit_code: ExitCode

    @classmethod
    def from_results(
        cls,
        mode: str,
        identity: Mapping[str, object],
        results: Sequence[CheckResult],
    ) -> "SelfCheckReport":
        collected = tuple(results)
        failed = tuple(result for result in collected if result.status is CheckStatus.FAIL)
        if failed:
            exit_code = max((result.exit_code for result in failed), key=int)
            status = CheckStatus.FAIL
        else:
            exit_code = ExitCode.SUCCESS
            status = CheckStatus.PASS
        return cls(mode, dict(identity), collected, status, exit_code)

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": 1,
            "mode": self.mode,
            "identity": dict(self.identity),
            "status": self.status.value,
            "exit_code": int(self.exit_code),
            "results": [result.as_dict() for result in self.results],
        }


def render_json(report: SelfCheckReport) -> str:
    return json.dumps(report.as_dict(), ensure_ascii=False, indent=2) + "\n"


def render_human(report: SelfCheckReport) -> str:
    lines = [f"UNITI self-check ({report.mode}): {report.status.value}"]
    for result in report.results:
        lines.append(
            f"  {result.status.value.upper():4} {result.name}: {result.summary}"
        )
    lines.append(f"Exit code: {int(report.exit_code)}")
    return "\n".join(lines) + "\n"


class SelfCheckRunner:
    def __init__(
        self,
        paths: AppPaths | None = None,
        *,
        marker_path: Path | None = None,
        runtime_python: Path | None = None,
        process_runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.paths = paths or AppPaths.current()
        self.marker_path = marker_path or (Path(sys.prefix) / ".uniti-runtime.json")
        self.runtime_python = Path(runtime_python or sys.executable)
        self.process_runner = process_runner

    def _run_check(
        self,
        name: str,
        failure_code: ExitCode,
        check: Callable[[], tuple[str, Mapping[str, object]]],
    ) -> CheckResult:
        started = time.perf_counter()
        try:
            summary, details = check()
        except Exception as error:
            return CheckResult.failed(
                name,
                failure_code,
                f"{name} check failed ({type(error).__name__})",
                duration_ms=(time.perf_counter() - started) * 1000.0,
            )
        return CheckResult.passed(
            name,
            summary,
            details,
            duration_ms=(time.perf_counter() - started) * 1000.0,
        )

    def _runtime(self) -> tuple[str, Mapping[str, object]]:
        results = probe_runtime(self.paths, marker_path=self.marker_path)
        marker = results["environment_marker"]
        if sys.version_info < (3, 12):
            raise RuntimeError("Python 3.12+ is required")
        if marker.status is not CapabilityStatus.AVAILABLE:
            raise RuntimeError(marker.reason)
        return "runtime and ownership marker are valid", {
            key: result.as_dict() for key, result in results.items()
        }

    def _dependencies(self) -> tuple[str, Mapping[str, object]]:
        import PySide6
        import regex

        versions = {
            "uniti-editor": importlib.metadata.version("uniti-editor"),
            "regex": importlib.metadata.version("regex"),
            "PySide6": importlib.metadata.version("PySide6"),
        }
        if versions["uniti-editor"] != uniti.__version__:
            raise RuntimeError("installed UNITI metadata does not match the imported package")
        completed = self.process_runner(
            [str(self.runtime_python), "-m", "pip", "check"],
            text=True,
            capture_output=True,
            check=False,
            timeout=120,
            shell=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("pip check failed")
        return "declared dependencies import and pass pip check", versions

    def _paths(self) -> tuple[str, Mapping[str, object]]:
        self.paths.ensure()
        probe = self.paths.temp_dir / "uniti-self-check-write"
        try:
            probe.write_bytes(b"ok")
            if probe.read_bytes() != b"ok":
                raise OSError("short read")
        finally:
            try:
                probe.unlink()
            except FileNotFoundError:
                pass
        return "application-owned paths are writable", {
            "config": str(self.paths.config_dir),
            "data": str(self.paths.data_dir),
            "state": str(self.paths.state_dir),
            "cache": str(self.paths.cache_dir),
        }

    def _schemas(self) -> tuple[str, Mapping[str, object]]:
        setup = SetupStateStore(self.paths.setup_state_file).prepare()
        settings = SettingsStore(self.paths.settings_file).prepare()
        return "setup and settings schemas are readable", {
            "setup": setup["schema"],
            "settings": 1,
            "settings_migrated": settings.migrated,
        }

    @staticmethod
    def _regex() -> tuple[str, Mapping[str, object]]:
        pattern = compile_pattern(r"(?P<word>\p{L}+)")
        match = pattern.search("UNITI café")
        if match is None or match.group("word") != "UNITI":
            raise RuntimeError("third-party regex search failed")
        return "third-party regex compile/search succeeded", {"regex_version": importlib.metadata.version("regex")}

    @staticmethod
    def _resources() -> tuple[str, Mapping[str, object]]:
        manager = ResourceManager()
        try:
            return "resource policy calibrated", {
                "cache_budget_bytes": manager.cache_budget_bytes,
                "worker_count": manager.worker_count,
                "pressure": manager.pressure.value,
            }
        finally:
            manager.shutdown()

    def _filesystem(self) -> tuple[str, Mapping[str, object]]:
        results = probe_filesystem(self.paths)
        required = ("write", "fsync", "atomic_replace")
        if any(results[name].status is not CapabilityStatus.AVAILABLE for name in required):
            raise RuntimeError("required filesystem primitive failed")
        return "bounded filesystem probes completed", {
            key: value.as_dict() for key, value in results.items()
        }

    @staticmethod
    def _qt_fast() -> tuple[str, Mapping[str, object]]:
        import PySide6
        from PySide6.QtCore import qVersion

        return "PySide6 and Qt are importable", {
            "pyside_version": PySide6.__version__,
            "qt_version": qVersion(),
        }

    @staticmethod
    def _deep_encodings(root: Path) -> tuple[str, Mapping[str, object]]:
        text = "Alpha café 日本語\n"
        cases = {
            "utf-8": (text.encode("utf-8"), "utf-8"),
            "windows-1252": (b"Price \x96 10\x80", "windows-1252"),
            "utf-16-le": (text.encode("utf-16-le"), "utf-16-le"),
            "utf-16-le-bom": (b"\xff\xfe" + text.encode("utf-16-le"), "utf-16-le"),
            "utf-16-be": (text.encode("utf-16-be"), "utf-16-be"),
            "utf-16-be-bom": (b"\xfe\xff" + text.encode("utf-16-be"), "utf-16-be"),
            "utf-32-le": (text.encode("utf-32-le"), "utf-32-le"),
            "utf-32-le-bom": (b"\xff\xfe\x00\x00" + text.encode("utf-32-le"), "utf-32-le"),
            "utf-32-be": (text.encode("utf-32-be"), "utf-32-be"),
            "utf-32-be-bom": (b"\x00\x00\xfe\xff" + text.encode("utf-32-be"), "utf-32-be"),
        }
        detected: dict[str, str] = {}
        for name, (payload, expected) in cases.items():
            path = root / f"{name}.txt"
            path.write_bytes(payload)
            with ByteSource.open(path) as source:
                actual = detect_encoding(source).detected
            if actual != expected:
                raise RuntimeError(f"encoding detection mismatch for {name}")
            detected[name] = actual
        return "encoding and endian matrix passed", detected

    @staticmethod
    def _deep_eol(root: Path) -> tuple[str, Mapping[str, object]]:
        observed: dict[str, str] = {}
        for name, payload in (("LF", b"a\nb\n"), ("CRLF", b"a\r\nb\r\n"), ("CR", b"a\rb\r")):
            path = root / f"eol-{name}.txt"
            path.write_bytes(payload)
            with ByteSource.open(path) as source:
                report = analyze_eol(source)
            if report.kind != name:
                raise RuntimeError(f"EOL analysis mismatch for {name}")
            observed[name] = report.kind
        source_path = root / "eol-convert.txt"
        output_path = root / "eol-converted.txt"
        source_path.write_bytes(b"a\r\nb\r\n")
        with Document.open(source_path) as document:
            document.set_output_eol("LF")
            document.export_copy(output_path, output_format=document.output_format)
        if output_path.read_bytes() != b"a\nb\n":
            raise RuntimeError("EOL conversion failed")
        return "LF, CRLF, CR, and conversion passed", observed

    @staticmethod
    def _deep_mmap(root: Path) -> tuple[str, Mapping[str, object]]:
        path = root / "byte-source.bin"
        path.write_bytes(b"0123456789")
        with ByteSource.open(path, prefer_mmap=True) as mapped:
            mapped_value = mapped.read(2, 4)
            uses_mmap = mapped.uses_mmap
        with ByteSource.open(path, prefer_mmap=False) as fallback:
            fallback_value = fallback.read(2, 4)
            uses_fallback = not fallback.uses_mmap
        if mapped_value != b"2345" or fallback_value != b"2345" or not uses_fallback:
            raise RuntimeError("byte-source path mismatch")
        return "mmap preference and explicit fallback passed", {"mmap_used": uses_mmap}

    @staticmethod
    def _deep_bytes(root: Path) -> tuple[str, Mapping[str, object]]:
        payload = b"valid\xff\x81bytes"
        path = root / "invalid-bytes.bin"
        path.write_bytes(payload)
        with ByteSource.open(path) as source:
            preserved = source.read(0, source.size)
        if preserved != payload:
            raise RuntimeError("invalid bytes changed")
        return "invalid source bytes remained exact", {"bytes": len(payload)}

    @staticmethod
    def _deep_regex(root: Path) -> tuple[str, Mapping[str, object]]:
        path = root / "regex.txt"
        path.write_text("Pieter 2026 John 2027", encoding="utf-8")
        with Document.open(path) as document:
            replacements = replace_all(document, compile_pattern(r"\d{4}"), "YEAR")
            text = document.read(0, document.total_chars())
        if replacements != 2 or text != "Pieter YEAR John YEAR":
            raise RuntimeError("regex replacement mismatch")
        return "third-party regex search and replacement passed", {"replacements": replacements}

    @staticmethod
    def _deep_save(root: Path) -> tuple[str, Mapping[str, object]]:
        source = root / "save-source.txt"
        output = root / "save-output.txt"
        source.write_text("alpha\n", encoding="utf-8")
        with Document.open(source) as document:
            document.insert(document.total_chars(), "beta\n")
            document.export_copy(output, output_format=document.output_format)
        with Document.open(output) as reopened:
            text = reopened.read(0, reopened.total_chars())
        if text != "alpha\nbeta\n":
            raise RuntimeError("streaming save/reopen mismatch")
        return "streaming atomic save and reopen passed", {"output_bytes": output.stat().st_size}

    @staticmethod
    def _deep_recovery(root: Path) -> tuple[str, Mapping[str, object]]:
        source = root / "recovery-source.txt"
        source.write_text("abc", encoding="utf-8")
        recovery_dir = root / "recovery"
        first = RecoveryManager(recovery_dir)
        document = Document.open(source)
        first.attach(document)
        document.insert(3, "X")
        first.detach(document, clean=False)
        document.close()
        first.shutdown()
        second = RecoveryManager(recovery_dir)
        try:
            candidates = second.discover()
            if len(candidates) != 1:
                raise RuntimeError("recovery candidate missing")
            recovered = second.recover(candidates[0])
            try:
                text = recovered.read(0, recovered.total_chars())
                second.detach(recovered, clean=True)
            finally:
                recovered.close()
        finally:
            second.shutdown()
        if text != "abcX":
            raise RuntimeError("recovery replay mismatch")
        return "recovery journal creation and replay passed", {"candidates": 1}

    @staticmethod
    def _deep_qt(root: Path) -> tuple[str, Mapping[str, object]]:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        from uniti.app.editor_state import EditorState
        from uniti.app.capabilities import probe_qt
        from uniti.ui.text_view import UNITITextView

        app = QApplication.instance() or QApplication(["uniti-self-check"])
        source = root / "qt-view.txt"
        source.write_text("UNITI\n", encoding="utf-8")
        document = Document.open(source)
        view = UNITITextView(EditorState(document))
        try:
            view.resize(320, 200)
            view.show()
            app.processEvents()
            results = probe_qt(app)
            if results["qt"].status is not CapabilityStatus.AVAILABLE:
                raise RuntimeError("Qt application probe failed")
            details = {key: value.as_dict() for key, value in results.items()}
        finally:
            view.close()
            document.close()
        return "offscreen Qt view and platform probes passed", details

    def run(self, *, deep: bool = False) -> SelfCheckReport:
        results = [
            self._run_check("runtime", ExitCode.ENVIRONMENT, self._runtime),
            self._run_check("dependencies", ExitCode.DEPENDENCIES, self._dependencies),
            self._run_check("paths", ExitCode.STATE, self._paths),
            self._run_check("schemas", ExitCode.STATE, self._schemas),
            self._run_check("regex", ExitCode.DEPENDENCIES, self._regex),
            self._run_check("resources", ExitCode.FUNCTIONAL, self._resources),
            self._run_check("filesystem", ExitCode.STATE, self._filesystem),
            self._run_check("qt", ExitCode.GUI, self._qt_fast),
        ]
        if deep:
            with tempfile.TemporaryDirectory(prefix="uniti-deep-self-check-") as temporary:
                root = Path(temporary)
                deep_checks = (
                    ("encodings", self._deep_encodings),
                    ("eol", self._deep_eol),
                    ("mmap", self._deep_mmap),
                    ("byte-preservation", self._deep_bytes),
                    ("regex-functional", self._deep_regex),
                    ("streaming-save", self._deep_save),
                    ("recovery", self._deep_recovery),
                    ("qt-offscreen", self._deep_qt),
                )
                for name, check in deep_checks:
                    code = ExitCode.GUI if name == "qt-offscreen" else ExitCode.FUNCTIONAL
                    results.append(
                        self._run_check(name, code, lambda check=check: check(root))
                    )
        identity = {
            "display_version": uniti.__display_version__,
            "package_version": uniti.__version__,
            "python": platform.python_version(),
            "executable": str(self.runtime_python.resolve()),
            "platform": sys.platform,
        }
        return SelfCheckReport.from_results("deep" if deep else "fast", identity, results)
