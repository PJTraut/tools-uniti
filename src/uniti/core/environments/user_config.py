"""Per-environment user configuration folders (field test round 2, R8).

Each environment has a folder of the user's own configuration under UNITI's
user data: `<user data>/Environments/<Environment>/` (e.g.
`.../UNITI/Environments/USFM/`). For USFM it holds the user's own
presentation rules (`uniti.sty`, a stylesheet layer that applies to every
USFM file) and user versification files (`Versification/*.vrs`).

The root is set once by the application (the folder its settings live
in); with no root set — tests, headless tools — there is no user layer.
"""

from __future__ import annotations

from pathlib import Path

ENVIRONMENTS_FOLDER = "Environments"
USER_RULES_FILE = "uniti.sty"
VERSIFICATION_FOLDER = "Versification"
REFERENCE_FOLDER = "Reference"

_root: Path | None = None


def set_user_config_root(path: Path | None) -> None:
    """Where UNITI's user data lives (the settings folder)."""

    global _root
    _root = None if path is None else Path(path)


def user_config_root() -> Path | None:
    return _root


def environment_folder(environment_label: str, *, create: bool = False) -> Path | None:
    """`<user data>/Environments/<environment_label>`; None without a root."""

    if _root is None:
        return None
    folder = _root / ENVIRONMENTS_FOLDER / environment_label
    if create:
        folder.mkdir(parents=True, exist_ok=True)
    return folder


def usfm_user_rules_path() -> Path | None:
    """The user's own USFM presentation rules (may not exist yet)."""

    folder = environment_folder("USFM")
    return None if folder is None else folder / USER_RULES_FILE


def usfm_versification_folder() -> Path | None:
    folder = environment_folder("USFM")
    return None if folder is None else folder / VERSIFICATION_FOLDER


__all__ = [
    "ENVIRONMENTS_FOLDER",
    "REFERENCE_FOLDER",
    "USER_RULES_FILE",
    "VERSIFICATION_FOLDER",
    "environment_folder",
    "set_user_config_root",
    "user_config_root",
    "usfm_user_rules_path",
    "usfm_versification_folder",
]
