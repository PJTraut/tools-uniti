"""Small atomic JSON settings store for UNITI."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    last_directory: str | None = None
    performance_mode: str = "Automatic"


class SettingsStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> Settings:
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return Settings()
        if not isinstance(payload, dict):
            return Settings()
        last_directory = payload.get("last_directory")
        if last_directory is not None and not isinstance(last_directory, str):
            last_directory = None
        performance_mode = payload.get("performance_mode", "Automatic")
        if performance_mode not in {"Conservative", "Automatic", "Maximum Performance"}:
            performance_mode = "Automatic"
        return Settings(
            last_directory=last_directory,
            performance_mode=performance_mode,
        )

    def save(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=self.path.parent,
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            delete=False,
        )
        temp_path = Path(handle.name)
        try:
            with handle:
                json.dump(asdict(settings), handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            try:
                temp_path.unlink()
            except OSError:
                pass
            raise
