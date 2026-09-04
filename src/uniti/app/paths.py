"""Cross-platform UNITI application storage paths without external dependencies."""

from __future__ import annotations

import hashlib
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from .platform_policy import (
    PlatformFamily,
    absolute_environment_root,
    classify_platform,
)


@dataclass(frozen=True, slots=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    state_dir: Path
    cache_dir: Path
    platform_family: PlatformFamily | None = None

    def __post_init__(self) -> None:
        roots = tuple(
            Path(value)
            for value in (
                self.config_dir,
                self.data_dir,
                self.state_dir,
                self.cache_dir,
            )
        )
        if not all(path.is_absolute() and "\0" not in str(path) for path in roots):
            raise ValueError("application roots must be absolute")
        if self.platform_family is not None and not isinstance(
            self.platform_family, PlatformFamily
        ):
            raise TypeError("platform family must be a PlatformFamily")
        for name, value in zip(
            ("config_dir", "data_dir", "state_dir", "cache_dir"),
            roots,
            strict=True,
        ):
            object.__setattr__(self, name, value)

    @property
    def family(self) -> PlatformFamily:
        return self.platform_family or classify_platform(sys.platform)

    @property
    def owned_roots(self) -> tuple[Path, Path, Path, Path]:
        return (
            self.config_dir,
            self.data_dir,
            self.state_dir,
            self.cache_dir,
        )

    @property
    def recovery_dir(self) -> Path:
        return self.state_dir / "recovery"

    @property
    def settings_file(self) -> Path:
        return self.config_dir / "settings.json"

    @property
    def local_runtime_dir(self) -> Path:
        return self.data_dir / "runtime" / "venv"

    @property
    def setup_state_file(self) -> Path:
        return self.state_dir / "setup-state.json"

    @property
    def log_dir(self) -> Path:
        return self.state_dir / "logs"

    @property
    def startup_log_file(self) -> Path:
        return self.log_dir / "startup.jsonl"

    @property
    def temp_dir(self) -> Path:
        return self.cache_dir / "temp"

    @property
    def session_dir(self) -> Path:
        return self.cache_dir / "sessions"

    @property
    def durable_session_dir(self) -> Path:
        return self.state_dir / "session"

    @property
    def instance_lock_file(self) -> Path:
        return self.state_dir / "uniti-instance.lock"

    @property
    def instance_endpoint_name(self) -> str:
        digest = hashlib.sha256(
            str(self.data_dir.resolve()).encode("utf-8")
        ).hexdigest()
        return f"uniti-{digest[:24]}"

    @classmethod
    def for_platform(
        cls,
        platform_name: str,
        *,
        home: Path,
        environ: Mapping[str, str],
    ) -> "AppPaths":
        selected_home = Path(home)
        if not selected_home.is_absolute() or "\0" in str(selected_home):
            raise ValueError("home directory must be absolute")
        family = classify_platform(platform_name)
        if family is PlatformFamily.MACOS:
            base = selected_home / "Library" / "Application Support" / "UNITI"
            return cls(
                config_dir=base,
                data_dir=base,
                state_dir=base / "State",
                cache_dir=selected_home / "Library" / "Caches" / "UNITI",
                platform_family=family,
            )
        if family is PlatformFamily.WINDOWS:
            local = absolute_environment_root(
                environ,
                "LOCALAPPDATA",
                selected_home / "AppData" / "Local",
            )
            base = local / "UNITI"
            return cls(
                config_dir=base,
                data_dir=base,
                state_dir=base / "State",
                cache_dir=base / "Cache",
                platform_family=family,
            )

        config_root = absolute_environment_root(
            environ,
            "XDG_CONFIG_HOME",
            selected_home / ".config",
        )
        data_root = absolute_environment_root(
            environ,
            "XDG_DATA_HOME",
            selected_home / ".local" / "share",
        )
        state_root = absolute_environment_root(
            environ,
            "XDG_STATE_HOME",
            selected_home / ".local" / "state",
        )
        cache_root = absolute_environment_root(
            environ,
            "XDG_CACHE_HOME",
            selected_home / ".cache",
        )
        return cls(
            config_dir=config_root / "uniti",
            data_dir=data_root / "uniti",
            state_dir=state_root / "uniti",
            cache_dir=cache_root / "uniti",
            platform_family=family,
        )

    @classmethod
    def current(cls) -> "AppPaths":
        return cls.for_platform(sys.platform, home=Path.home(), environ=os.environ)

    def ensure(self) -> None:
        for directory in (
            self.config_dir,
            self.data_dir,
            self.state_dir,
            self.cache_dir,
            self.recovery_dir,
            self.log_dir,
            self.temp_dir,
            self.session_dir,
            self.durable_session_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
