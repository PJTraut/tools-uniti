"""A minimal Paratext project for tests: USFM assumes one (round 3 T1)."""

from __future__ import annotations

from pathlib import Path

USFM_SUFFIXES = frozenset({".usfm", ".sfm"})

# ruCARSv3's custom.vrs numbers psalm titles as verse 1 (its chapter
# counts, and a few of its mappings onto the original text).
RUSSIAN_PSALMS_VRS = (
    "PSA 1:6 2:12 3:9 4:9 5:13 6:11 7:18 8:10 9:39 10:7 11:9 12:6 13:7 14:5 15:11 16:15 17:51 18:15 19:10 20:14"
    " 21:32 22:6 23:10 24:22 25:12 26:14 27:9 28:11 29:13 30:25 31:11 32:22 33:23 34:28 35:13 36:40 37:23 38:14"
    " 39:18 40:14 41:12 42:5 43:27 44:18 45:12 46:10 47:15 48:21 49:23 50:21\n"
    "PSA 9:22-39 = PSA 10:1-18\n"
    "PSA 10:1-7 = PSA 11:1-7\n"
    "PSA 11:1-9 = PSA 12:1-9\n"
    "PSA 50:1-21 = PSA 51:1-21\n"
)


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
