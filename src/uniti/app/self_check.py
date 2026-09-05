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
from uniti.core.offsets import OffsetMapper, ReadIntent
from uniti.core.pieces import EditStore, PieceTable
from uniti.core.save import (
    SaveVerificationError,
    commit_staged_document,
    discard_staged_document,
    stage_document,
    verify_staged_document,
)
from uniti.core.text_format import (
    EOLPolicy,
    OutputFormat,
    encoding_profile,
    encoding_profiles,
)
from uniti.core.text_inspection import inspect_source
from uniti.regex.analysis import AnalysisState, analyze_pattern
from uniti.regex.captures import CaptureReportRequest, resolve_capture_report
from uniti.regex.engine import compile_pattern
from uniti.regex.replace import replace_all
from uniti.regex.search import SearchOptions, search_document
from uniti.resources import (
    ResourceManager,
    TaskKind,
    TaskSpec,
    WorkCancelled,
)

from .capabilities import CapabilityStatus, probe_filesystem, probe_runtime
from .paths import AppPaths
from .recovery_manager import RecoveryManager
from .settings import SETTINGS_SCHEMA, SettingsStore
from .setup_state import SetupStateStore
from .sparse import deallocate_file_range
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
            "settings": SETTINGS_SCHEMA,
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
    def _deep_regex_intelligence(root: Path) -> tuple[str, Mapping[str, object]]:
        fixtures = (
            r"(?P<item>a)(?P<item>b)",
            r"(?|(a)|(b))(c)",
            r"(?im-s:^a.+$)",
            r"(?P<digit>\d)+",
            r"(a)?(?(1)b|c)",
        )
        analyses = tuple(
            analyze_pattern(pattern, generation)
            for generation, pattern in enumerate(fixtures, start=1)
        )
        if any(
            analysis.state is not AnalysisState.VALID
            or not analysis.identities_reconciled
            for analysis in analyses
        ):
            raise RuntimeError("advanced regex metadata did not reconcile")

        path = root / "regex-intelligence.txt"
        path.write_text("aa aa", encoding="utf-8")
        with Document.open(path) as document:
            original = document.read(0, document.total_chars())
            capture_pattern = compile_pattern(r"(?P<item>a)+(?P<empty>)")
            capture_records = tuple(
                search_document(
                    document,
                    capture_pattern,
                    options=SearchOptions(include_captures=False),
                )
            )
            request = CaptureReportRequest(
                pattern_generation=len(fixtures),
                pattern_text=capture_pattern.pattern,
                document_key=str(id(document)),
                revision=document.revision,
                store_id="deep-self-check",
                requested_index=0,
                match_count=len(capture_records),
                matches=tuple(enumerate(capture_records[:2])),
            )
            with document.snapshot() as snapshot:
                report = resolve_capture_report(snapshot, capture_pattern, request)
            if (
                report.payload_bytes > 1 << 20
                or len(report.matches) != 2
                or any(
                    len(group.previews) > 5
                    for match in report.matches
                    for group in match.groups
                )
            ):
                raise RuntimeError("capture report bounds failed")

            zero_width = tuple(
                search_document(
                    document,
                    compile_pattern(r"(?=a)|(?<=a)"),
                    options=SearchOptions(include_captures=False),
                )
            )
            replacement_count = replace_all(
                document,
                compile_pattern(r"(?=a)"),
                "X",
            )
            document.undo()
            undo_exact = document.read(0, document.total_chars()) == original
        if [record.start for record in zero_width] != [0, 1, 2, 3, 4, 5]:
            raise RuntimeError("zero-width search positions were not exact")
        if replacement_count != 4 or not undo_exact:
            raise RuntimeError("zero-width replacement undo was not exact")

        return "regex intelligence, captures, zero-width, and undo passed", {
            "regex_version": importlib.metadata.version("regex"),
            "advanced_patterns": len(analyses),
            "zero_width_matches": len(zero_width),
            "report_payload_bytes": report.payload_bytes,
            "replacement_count": replacement_count,
            "undo_exact": undo_exact,
        }

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
    def _deep_text_integrity(root: Path) -> tuple[str, Mapping[str, object]]:
        expected_keys = (
            "utf-8",
            "utf-8-bom",
            "windows-1252",
            "utf-16-le",
            "utf-16-le-bom",
            "utf-16-be",
            "utf-16-be-bom",
            "utf-32-le",
            "utf-32-le-bom",
            "utf-32-be",
            "utf-32-be-bom",
        )
        registered = tuple(profile.key for profile in encoding_profiles())
        if registered != expected_keys:
            raise RuntimeError("exact encoding profile registry mismatch")

        utf8_path = root / "integrity-utf8.txt"
        utf8_path.write_bytes("Alpha Привет\r\n".encode("utf-8"))
        with ByteSource.open(utf8_path) as source:
            utf8_inspection = inspect_source(source)
        if (
            utf8_inspection.encoding.suggested.key != "utf-8"
            or utf8_inspection.encoding.requires_confirmation
            or utf8_inspection.eol.kind != "CRLF"
        ):
            raise RuntimeError("UTF-8 no-BOM inspection mismatch")

        utf16_profile = encoding_profile("utf-16-be-bom")
        utf16_path = root / "integrity-utf16-be-bom.txt"
        utf16_text = "Western café Привет\n"
        utf16_path.write_bytes(
            utf16_profile.bom + utf16_text.encode(utf16_profile.codec)
        )
        with ByteSource.open(utf16_path) as source:
            utf16_inspection = inspect_source(source)
        if utf16_inspection.encoding.suggested != utf16_profile:
            raise RuntimeError("UTF-16 BE BOM inspection mismatch")
        with Document.open(utf16_path, profile=utf16_profile) as document:
            if document.read(0, document.total_chars()) != utf16_text:
                raise RuntimeError("UTF-16 BE BOM logical-text mismatch")

        mixed_path = root / "integrity-mixed.txt"
        mixed_copy = root / "integrity-mixed-copy.txt"
        mixed_payload = b"one\r\ntwo\nthree\r"
        mixed_path.write_bytes(mixed_payload)
        with ByteSource.open(mixed_path) as source:
            mixed_inspection = inspect_source(source)
        if mixed_inspection.eol.kind != "MIXED":
            raise RuntimeError("mixed-EOL inspection mismatch")
        with Document.open(
            mixed_path,
            profile=encoding_profile("utf-8"),
        ) as document:
            document.export_copy(
                mixed_copy,
                output_format=document.output_format,
                expected_destination_identity=None,
            )
        if mixed_copy.read_bytes() != mixed_payload:
            raise RuntimeError("mixed-EOL preserve mismatch")

        malformed_path = root / "integrity-malformed.txt"
        malformed_copy = root / "integrity-malformed-copy.txt"
        malformed_payload = b"A\xffB\r\n"
        malformed_path.write_bytes(malformed_payload)
        with ByteSource.open(malformed_path) as source:
            malformed_inspection = inspect_source(
                source,
                override=encoding_profile("utf-8"),
            )
        if not malformed_inspection.encoding.malformed_preview:
            raise RuntimeError("malformed-byte evidence missing")
        with Document.open(
            malformed_path,
            profile=encoding_profile("utf-8"),
        ) as document:
            document.export_copy(
                malformed_copy,
                output_format=document.output_format,
                expected_destination_identity=None,
            )
        if malformed_copy.read_bytes() != malformed_payload:
            raise RuntimeError("malformed-byte preserve mismatch")

        stage_source_path = root / "integrity-stage-source.txt"
        stage_target = root / "integrity-stage-target.txt"
        stage_source_path.write_text("Alpha Привет\n", encoding="utf-8")
        source = ByteSource.open(stage_source_path)
        mapper = OffsetMapper(source, "utf-8")
        table = PieceTable(source, "utf-8", mapper, EditStore())
        staged = None
        staged_format = OutputFormat(utf16_profile, EOLPolicy.CRLF)
        try:
            staged = stage_document(
                source,
                table,
                source_profile=encoding_profile("utf-8"),
                destination=stage_target,
                output_format=staged_format,
            )
            verify_staged_document(staged, table.iter_text())
            commit_staged_document(staged)
        finally:
            if staged is not None:
                discard_staged_document(staged)
            source.close()
        expected_stage_bytes = utf16_profile.bom + "Alpha Привет\r\n".encode(
            utf16_profile.codec
        )
        if stage_target.read_bytes() != expected_stage_bytes:
            raise RuntimeError("verified exact-format stage mismatch")
        with Document.open(stage_target, profile=utf16_profile) as reopened:
            if reopened.read(0, reopened.total_chars()) != "Alpha Привет\r\n":
                raise RuntimeError("verified output reopen mismatch")

        refusal_target = root / "integrity-refusal.txt"
        refusal_target.write_bytes(b"untouched")
        source = ByteSource.open(stage_source_path)
        mapper = OffsetMapper(source, "utf-8")
        table = PieceTable(source, "utf-8", mapper, EditStore())
        refused = False
        staged = None
        try:
            staged = stage_document(
                source,
                table,
                source_profile=encoding_profile("utf-8"),
                destination=refusal_target,
                output_format=OutputFormat(
                    encoding_profile("utf-8"),
                    EOLPolicy.LF,
                ),
            )
            with staged.temporary.open("ab") as handle:
                handle.write(b"tampered")
            try:
                verify_staged_document(staged, table.iter_text())
            except SaveVerificationError:
                refused = True
        finally:
            if staged is not None:
                discard_staged_document(staged)
            source.close()
        if not refused:
            raise RuntimeError("tampered staged output was not refused")
        if refusal_target.read_bytes() != b"untouched":
            raise RuntimeError("verification refusal changed destination bytes")
        if list(root.glob(".integrity-refusal.txt.*.uniti-tmp")):
            raise RuntimeError("verification refusal left staged artifacts")

        return "exact profiles, verified output, and failure cleanup passed", {
            "profiles": len(registered),
            "utf8_eol": utf8_inspection.eol.kind,
            "utf16_profile": utf16_inspection.encoding.suggested.key,
            "mixed_eol": mixed_inspection.eol.kind,
            "malformed_errors": len(
                malformed_inspection.encoding.malformed_preview
            ),
            "verified_bytes": stage_target.stat().st_size,
            "refusal_cleanup": refused,
        }

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
    def _deep_recovery_session(root: Path) -> tuple[str, Mapping[str, object]]:
        """Exercise hash-gated saved history and semantic crash recovery."""

        from datetime import UTC, datetime

        from uniti.core.file_identity import (
            FileIdentity,
            FileMatch,
            SavedFileStamp,
            sha256_file,
        )

        from .session import (
            SESSION_SCHEMA,
            DocumentRecord,
            FindReplaceManifestRecord,
            HistoryPack,
            InputStateRecord,
            SessionManifest,
            SessionSnapshot,
        )
        from .session_runtime import restore_document_pack
        from .session_store import SessionStore

        timestamp = datetime.now(UTC).isoformat().replace("+00:00", "Z")
        session_source = root / "saved-session-source.txt"
        session_source.write_text("abc", encoding="utf-8")
        with Document.open(session_source) as document:
            document.insert(document.total_chars(), "X")
            document.save()
            history = document.export_history()
            stamp = SavedFileStamp(
                FileIdentity.from_path(session_source),
                sha256_file(session_source),
            )
            source_profile = document.source_profile.key
            selected_profile = document.output_format.encoding.key
            selected_eol = (
                None
                if document.output_format.eol is EOLPolicy.PRESERVE
                else document.output_format.eol.value
            )
            saved_profile = document.saved_output_format.encoding.key
            saved_eol = (
                None
                if document.saved_output_format.eol is EOLPolicy.PRESERVE
                else document.saved_output_format.eol.value
            )

        document_id = "deep-session-document"
        pack = HistoryPack(
            document_id=document_id,
            generation="deep-session-history",
            canonical_path=str(session_source),
            saved_stamp=stamp,
            source_profile_key=source_profile,
            selected_output_profile_key=selected_profile,
            selected_output_eol=selected_eol,
            saved_output_profile_key=saved_profile,
            saved_output_eol=saved_eol,
            history=history,
            last_active_at=timestamp,
            closed_at=timestamp,
        )
        empty_input = InputStateRecord("", 0, 0)
        manifest = SessionManifest(
            schema=SESSION_SCHEMA,
            generation="deep-session-generation",
            service_id="deep-session-service",
            build_identity=uniti.__display_version__,
            created_at=timestamp,
            updated_at=timestamp,
            clean_shutdown=True,
            active_window_id=None,
            active_view_id=None,
            windows=(),
            views=(),
            documents=(
                DocumentRecord(
                    document_id,
                    str(session_source),
                    (),
                    timestamp,
                    timestamp,
                ),
            ),
            find_replace=FindReplaceManifestRecord(
                empty_input,
                empty_input,
                False,
                False,
                False,
                False,
                None,
                100,
                False,
                None,
                None,
            ),
            packs=(),
        )
        store = SessionStore(root / "saved-sessions")
        store.publish(SessionSnapshot(manifest, (pack,), None))
        loaded = store.load_latest()
        if loaded.manifest is None or len(loaded.packs) != 1:
            raise RuntimeError("saved session history was not published")

        resources = ResourceManager(max_workers=1)
        restored_result = restore_document_pack(
            loaded.packs[0],
            (),
            resource_manager=resources,
        )
        restored = restored_result.document
        try:
            if restored is None or restored_result.match not in {
                FileMatch.EXACT_FAST,
                FileMatch.EXACT_HASH,
            }:
                raise RuntimeError("saved session history hash did not match")
            session_transactions = len(restored.export_history().transactions)
        finally:
            if restored is not None:
                restored.close()
            resources.shutdown()

        changed_bytes = b"changed outside UNITI"
        session_source.write_bytes(changed_bytes)
        before_discovery = session_source.read_bytes()
        external_problems = store.discover_restore_problems(loaded.manifest)
        after_discovery = session_source.read_bytes()
        external_change_detected = any(
            problem.kind == "changed_source" for problem in external_problems
        )

        recovery_source = root / "semantic-recovery-source.txt"
        recovery_source.write_text("base", encoding="utf-8")
        recovery_root = root / "semantic-recovery"
        first = RecoveryManager(recovery_root)
        recovery_document = Document.open(recovery_source)
        first.attach(recovery_document)
        recovery_document.insert(recovery_document.total_chars(), "X")
        recovery_document.undo()
        recovery_document.redo()
        first.detach(recovery_document, clean=False)
        recovery_document.close()
        first.shutdown()

        second = RecoveryManager(recovery_root)
        recovered = None
        try:
            candidates = second.discover()
            if len(candidates) != 1:
                raise RuntimeError("semantic recovery candidate missing")
            recovered = second.recover(candidates[0])
            recovery_transactions = len(recovered.export_history().transactions)
            recovery_undo_available = recovered.can_undo
            expected = recovered.read(0, recovered.total_chars())
            recovered.undo()
            recovered.redo()
            recovery_redo_exact = (
                recovered.read(0, recovered.total_chars()) == expected
            )
            second.detach(recovered, clean=True)
        finally:
            if recovered is not None:
                recovered.close()
            second.shutdown()

        if not all(
            (
                session_transactions == 1,
                external_change_detected,
                before_discovery == after_discovery == changed_bytes,
                recovery_transactions == 1,
                recovery_undo_available,
                recovery_redo_exact,
            )
        ):
            raise RuntimeError("recovery/session history invariant failed")
        return "saved session and crash recovery histories passed", {
            "session_documents": len(loaded.manifest.documents),
            "session_transactions": session_transactions,
            "session_hash_exact": True,
            "recovery_candidates": len(candidates),
            "recovery_transactions": recovery_transactions,
            "recovery_undo_available": recovery_undo_available,
            "recovery_redo_exact": recovery_redo_exact,
            "external_change_detected": external_change_detected,
            "external_source_preserved": before_discovery == after_discovery,
        }

    @staticmethod
    def _deep_large_file(root: Path) -> tuple[str, Mapping[str, object]]:
        sparse_path = root / "large-file-sparse.txt"
        streaming_path = root / "large-file-streaming.txt"
        tail_offset = (1 << 30) + 12_345
        marker = b"UNITI_TAIL"
        manager = ResourceManager(max_workers=1)
        cancelled = False
        cache_bypassed = False
        lazy_open = False
        cleanup_ok = False
        try:
            with sparse_path.open("wb") as handle:
                handle.write(b"hello\n")
                handle.seek(tail_offset)
                handle.write(marker)
                handle.flush()
                deallocate_file_range(
                    handle.fileno(),
                    8192,
                    tail_offset + len(marker) - 16_384,
                )
            sparse_stat = sparse_path.stat()
            sparse_blocks = getattr(sparse_stat, "st_blocks", None)
            allocated_bytes = (
                None if sparse_blocks is None else sparse_blocks * 512
            )
            if (
                allocated_bytes is not None
                and allocated_bytes >= sparse_stat.st_size // 2
            ):
                raise RuntimeError("large-file fixture is not physically sparse")
            with Document.open(sparse_path, encoding="utf-8") as document:
                lazy_open = (
                    document.source.size == tail_offset + len(marker)
                    and document.source.read(tail_offset, len(marker)) == marker
                    and document.read(0, 6) == "hello\n"
                    and not document.offset_mapper.complete
                    and not document.document_line_index.complete
                    and document.offset_mapper.indexed_byte_end < (1 << 20)
                )

            streaming_path.write_bytes(b"x" * (2 << 20))
            with ByteSource.open(streaming_path) as source:
                mapper = OffsetMapper(
                    source,
                    "utf-8",
                    resource_manager=manager,
                    cache_owner="deep-large-file",
                )
                before = manager.cache.used_bytes
                chars = mapper.total_chars(intent=ReadIntent.STREAMING)
                cache_bypassed = (
                    chars == 2 << 20 and manager.cache.used_bytes == before
                )

            def cancellation_probe(context):
                context.report("Checking cancellation", 1, 2)
                while not context.token.wait(0.01):
                    pass
                context.check_cancelled()

            task = manager.tasks.submit(
                TaskSpec.create(TaskKind.INDEX, foreground=False),
                cancellation_probe,
            )
            task.wait_for_progress(timeout=1.0)
            task.cancel()
            try:
                task.future.result(timeout=1.0)
            except WorkCancelled:
                cancelled = True
            if not (lazy_open and cache_bypassed and cancelled):
                raise RuntimeError("large-file bounded-work invariant failed")
        finally:
            manager.shutdown()
            sparse_path.unlink(missing_ok=True)
            streaming_path.unlink(missing_ok=True)
            cleanup_ok = not sparse_path.exists() and not streaming_path.exists()
        if not cleanup_ok:
            raise RuntimeError("large-file probe cleanup failed")
        return "sparse access, streaming cache, and cancellation passed", {
            "sparse_bytes": tail_offset + len(marker),
            "allocated_bytes": allocated_bytes,
            "lazy_open": lazy_open,
            "streaming_cache_bypassed": cache_bypassed,
            "task_cancelled": cancelled,
            "cleanup_ok": cleanup_ok,
        }

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
                    ("regex-intelligence", self._deep_regex_intelligence),
                    ("streaming-save", self._deep_save),
                    ("text-integrity", self._deep_text_integrity),
                    ("large-file", self._deep_large_file),
                    ("recovery", self._deep_recovery),
                    ("recovery-session", self._deep_recovery_session),
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
