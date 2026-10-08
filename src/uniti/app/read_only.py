"""Read-only folders (field test round 3, T7).

A file in one of the user's read-only folders, or below one, opens
read-only: its `Document` refuses edits and saving in place. Meant for
Paratext projects that Paratext itself owns and synchronizes. The list is
`Settings.read_only_folders`; nothing is written into the folders.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path


def _resolved(path: Path | str) -> Path:
    try:
        return Path(path).expanduser().resolve()
    except OSError:
        return Path(path)


def read_only_folder_for(path: Path | str, folders: Iterable[str]) -> str | None:
    """The read-only folder `path` is in (or below), if any."""

    target = _resolved(path)
    for folder in folders:
        root = _resolved(folder)
        if target == root or root in target.parents:
            return folder
    return None


def is_read_only_path(path: Path | str, folders: Iterable[str]) -> bool:
    return read_only_folder_for(path, folders) is not None


def with_folder(folders: Iterable[str], folder: Path | str, read_only: bool) -> tuple[str, ...]:
    """`folders` with `folder` added (`read_only`) or removed."""

    folder = str(_resolved(folder))
    kept = tuple(item for item in folders if _resolved(item) != _resolved(folder))
    return kept + (folder,) if read_only else kept


__all__ = ["is_read_only_path", "read_only_folder_for", "with_folder"]
