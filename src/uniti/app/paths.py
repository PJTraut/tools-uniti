"""Cross-platform UNITI application storage paths without external dependencies."""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class AppPaths:
    config_dir: Path
    data_dir: Path
    state_dir: Path
    cache_dir: Path

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

    @classmethod
    def for_platform(
        cls,
        platform_name: str,
        *,
        home: Path,
        environ: Mapping[str, str],
    ) -> "AppPaths":
        if platform_name == "darwin":
            base = home / "Library" / "Application Support" / "UNITI"
            return cls(
                config_dir=base,
                data_dir=base,
                state_dir=base / "State",
                cache_dir=home / "Library" / "Caches" / "UNITI",
            )
        if platform_name.startswith("win"):
            local = Path(environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
            base = local / "UNITI"
            return cls(
                config_dir=base,
                data_dir=base,
                state_dir=base / "State",
                cache_dir=base / "Cache",
            )

        config_root = Path(environ.get("XDG_CONFIG_HOME", home / ".config"))
        data_root = Path(environ.get("XDG_DATA_HOME", home / ".local" / "share"))
        state_root = Path(environ.get("XDG_STATE_HOME", home / ".local" / "state"))
        cache_root = Path(environ.get("XDG_CACHE_HOME", home / ".cache"))
        return cls(
            config_dir=config_root / "uniti",
            data_dir=data_root / "uniti",
            state_dir=state_root / "uniti",
            cache_dir=cache_root / "uniti",
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
        ):
            directory.mkdir(parents=True, exist_ok=True)
