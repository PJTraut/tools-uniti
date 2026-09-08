"""Canonical dependency installation and validation inside managed runtimes."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tomllib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from .model import BootstrapError, BootstrapMode, RuntimeMarker

_VERSION_CODE = """
import importlib.metadata as metadata
import json
import PySide6
import regex
import uniti
print(json.dumps({
    "uniti-editor": metadata.version("uniti-editor"),
    "regex": metadata.version("regex"),
    "PySide6": metadata.version("PySide6"),
}, sort_keys=True))
""".strip()


@dataclass(frozen=True, slots=True)
class DependencyManifest:
    project_name: str
    version: str
    requires_python: str
    base: tuple[str, ...]
    ui: tuple[str, ...]
    dev: tuple[str, ...]

    @classmethod
    def load(cls, source_root: Path) -> "DependencyManifest":
        path = Path(source_root) / "pyproject.toml"
        try:
            payload = tomllib.loads(path.read_text(encoding="utf-8"))
            project = payload["project"]
            optional = project["optional-dependencies"]
            name = project["name"]
            version = project["version"]
            requires_python = project["requires-python"]
            base = project["dependencies"]
            ui = optional["ui"]
            dev = optional.get("dev", [])
            groups = (base, ui, dev)
            if name != "uniti-editor" or not all(
                isinstance(group, list) and all(isinstance(item, str) for item in group)
                for group in groups
            ):
                raise ValueError
        except (OSError, KeyError, TypeError, ValueError, tomllib.TOMLDecodeError) as error:
            raise BootstrapError("pyproject.toml has invalid UNITI dependency metadata", 12) from error
        return cls(
            str(name),
            str(version),
            str(requires_python),
            tuple(base),
            tuple(ui),
            tuple(dev),
        )

    def selected(self, *, dev: bool) -> tuple[str, ...]:
        return self.base + self.ui + (self.dev if dev else ())


@dataclass(frozen=True, slots=True)
class DependencyResult:
    fingerprint: str
    versions: Mapping[str, str]
    fast_path: bool


class DependencyManager:
    def __init__(
        self,
        runtime_python: Path,
        source_root: Path,
        *,
        mode: BootstrapMode,
        dev: bool = False,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        progress: Callable[[str], None] | None = None,
    ) -> None:
        self.runtime_python = Path(runtime_python).absolute()
        self.source_root = Path(source_root).resolve()
        self.mode = mode
        self.dev = dev
        self.runner = runner
        self._progress = progress if progress is not None else lambda _message: None
        self.manifest = DependencyManifest.load(self.source_root)

    def install_command(self) -> tuple[str, ...]:
        extras = "ui,dev" if self.dev else "ui"
        command = [str(self.runtime_python), "-m", "pip", "install", "--upgrade"]
        if self.mode is BootstrapMode.SOURCE:
            command.append("-e")
        command.append(f"{self.source_root}[{extras}]")
        return tuple(command)

    def _run(self, command: Sequence[str]) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                list(command),
                cwd=self.source_root,
                text=True,
                capture_output=True,
                check=False,
                timeout=900,
                shell=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise BootstrapError("managed dependency command could not run", 12) from error

    def _install(self) -> None:
        pip_identity = self._run((str(self.runtime_python), "-m", "pip", "--version"))
        if pip_identity.returncode != 0:
            raise BootstrapError("pip is unavailable in the UNITI runtime", 12)
        completed = self._run(self.install_command())
        if completed.returncode != 0:
            raise BootstrapError("UNITI dependency installation failed", 12)

    def validate(self) -> dict[str, str]:
        imported = self._run((str(self.runtime_python), "-c", _VERSION_CODE))
        if imported.returncode != 0:
            raise BootstrapError("UNITI runtime dependencies cannot be imported", 12)
        try:
            payload = json.loads(imported.stdout)
            if not isinstance(payload, dict):
                raise ValueError
            versions = {
                name: str(payload[name]) for name in ("uniti-editor", "regex", "PySide6")
            }
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as error:
            raise BootstrapError("UNITI dependency metadata is incomplete", 12) from error
        if versions["uniti-editor"] != self.manifest.version:
            raise BootstrapError(
                "installed UNITI version does not match canonical project metadata", 12
            )
        checked = self._run((str(self.runtime_python), "-m", "pip", "check"))
        if checked.returncode != 0:
            raise BootstrapError("UNITI runtime has broken dependency requirements", 12)
        return versions

    def _build_identity(self) -> str:
        git = self.source_root / ".git"
        try:
            head = (git / "HEAD").read_text(encoding="utf-8").strip()
            if head.startswith("ref: "):
                ref = head[5:]
                head = (git / ref).read_text(encoding="utf-8").strip()
            return head[:40]
        except OSError:
            return self.manifest.version

    def fingerprint(
        self,
        marker: RuntimeMarker,
        versions: Mapping[str, str],
    ) -> str:
        payload = {
            "schema": 1,
            "project": self.manifest.project_name,
            "package_version": self.manifest.version,
            "build_identity": self._build_identity(),
            "requirements": list(self.manifest.selected(dev=self.dev)),
            "source_root": str(self.source_root),
            "mode": self.mode.value,
            "host": dict(marker.host),
            "runtime": dict(marker.runtime),
            "installed_versions": dict(sorted(versions.items())),
        }
        canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def ensure(self, *, marker: RuntimeMarker, repair: bool) -> DependencyResult:
        if marker.healthy and not repair:
            try:
                versions = self.validate()
            except BootstrapError:
                pass
            else:
                fingerprint = self.fingerprint(marker, versions)
                if fingerprint == marker.dependency_fingerprint:
                    return DependencyResult(fingerprint, versions, True)
        self._progress("// installing UNITI dependencies")
        self._install()
        self._progress("// validating UNITI setup")
        versions = self.validate()
        return DependencyResult(self.fingerprint(marker, versions), versions, False)
