"""Bounded cleanup for known UNITI temp, session, and rotated-log artifacts."""

from __future__ import annotations

import json
import re
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .atomic_json import atomic_write_json, utc_timestamp
from .paths import AppPaths
from .process_liveness import process_is_live


def is_durable_session_artifact_name(name: str) -> bool:
    """Return whether *name* is reserved for bounded session-store cleanup."""

    generation = r"[0-9]{20}-[0-9a-f]{32}"
    return bool(
        re.fullmatch(rf"{generation}\.json", name)
        or re.fullmatch(r"[0-9a-f]{64}\.pack", name)
        or re.fullmatch(r"\..+\.[A-Za-z0-9_-]+\.tmp", name)
        or name.endswith(".invalid")
    )


@dataclass(frozen=True, slots=True)
class CleanupReport:
    inspected: int
    removed: tuple[Path, ...]
    retained: int
    errors: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return {
            "inspected": self.inspected,
            "removed": [str(path) for path in self.removed],
            "retained": self.retained,
            "errors": list(self.errors),
        }


def create_session_record(
    paths: AppPaths,
    *,
    session_id: str,
    pid: int,
    build_identity: str,
) -> Path:
    directory = paths.session_dir / session_id
    directory.mkdir(parents=True, exist_ok=False)
    record = directory / "session.json"
    atomic_write_json(
        record,
        {
            "schema": 1,
            "session_id": session_id,
            "pid": int(pid),
            "started_at": utc_timestamp(),
            "build_identity": build_identity,
        },
    )
    return record


def _old_enough(path: Path, cutoff: datetime) -> bool:
    modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
    return modified < cutoff


def _session_removable(path: Path, active: set[str], cutoff: datetime) -> bool:
    if not path.is_dir() or path.name in active or not _old_enough(path, cutoff):
        return False
    record = path / "session.json"
    try:
        payload = json.loads(record.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema") != 1:
            return False
        pid = int(payload.get("pid", 0))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return False
    return not process_is_live(pid)


def _safe_remove(path: Path, root: Path) -> None:
    path.resolve().relative_to(root.resolve())
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink()


def cleanup_stale(
    paths: AppPaths,
    *,
    active_session_ids: Iterable[str] = (),
    now: datetime | None = None,
    max_inspected: int = 200,
    max_removed: int = 100,
) -> CleanupReport:
    if max_inspected < 0 or max_removed < 0:
        raise ValueError("cleanup limits must be non-negative")
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current = current.astimezone(UTC)
    week_cutoff = current - timedelta(days=7)
    log_cutoff = current - timedelta(days=30)
    active = set(active_session_ids)
    removed: list[Path] = []
    errors: list[str] = []
    retained = 0
    inspected = 0

    groups = (
        (
            paths.temp_dir,
            lambda item: item.name.startswith("uniti-temp-")
            and _old_enough(item, week_cutoff),
        ),
        (paths.session_dir, lambda item: _session_removable(item, active, week_cutoff)),
        (
            paths.log_dir,
            lambda item: item.is_file()
            and item.name.startswith("startup.jsonl.")
            and _old_enough(item, log_cutoff),
        ),
    )
    stop = False
    for root, eligible in groups:
        root.mkdir(parents=True, exist_ok=True)
        for item in sorted(root.iterdir(), key=lambda path: path.name):
            if inspected >= max_inspected:
                stop = True
                break
            inspected += 1
            try:
                should_remove = eligible(item)
            except OSError:
                errors.append(f"could not inspect {item.name}")
                continue
            if not should_remove or len(removed) >= max_removed:
                retained += 1
                continue
            try:
                _safe_remove(item, root)
            except OSError:
                errors.append(f"could not remove {item.name}")
            else:
                removed.append(item)
        if stop:
            break
    return CleanupReport(inspected, tuple(removed), retained, tuple(errors))
