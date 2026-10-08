"""A minimal Paratext project for tests: USFM assumes one (round 3 T1)."""

from __future__ import annotations

from pathlib import Path

USFM_SUFFIXES = frozenset({".usfm", ".sfm"})


def ensure_project(folder: Path, name: str = "TST", post: str = ".usfm") -> Path:
    """Make `folder` a Paratext project, unless it already is one."""

    folder.mkdir(parents=True, exist_ok=True)
    settings = folder / "Settings.xml"
    if not settings.exists():
        settings.write_text(
            f'<ScriptureText><Name>{name}</Name><Naming PrePart="" PostPart="{post}" BookNameForm="41MAT" />'
            "</ScriptureText>",
            encoding="utf-8",
        )
    return folder


def in_project(path: Path) -> Path:
    """`path`, with its folder made a project when it's a USFM file."""

    if path.suffix.lower() in USFM_SUFFIXES:
        ensure_project(path.parent, post=path.suffix)
    return path
