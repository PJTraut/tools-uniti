"""Versification: how a text numbers its chapters and verses (plan P4).

Translations number some verses differently: English Ps 51:1 is the
original-text 51:3, Mal 4:1 is 3:19, Joel 2:28 is 3:1. Comparing two texts
by reference maps the reference from one versification, through
**Original**, into the other.

Where versification files come from:

- English (`eng`) and Original (`org`) are built in (shipped with `usfmtc`);
- Septuagint (`lxx`), Vulgate (`vul`), Russian Protestant (`rsc`) and
  Russian Orthodox (`rso`) come from your USFM folder,
  `<user data>/Environments/USFM/Versification/<stem>.vrs` — copy them
  from a Paratext installation;
- a project's `custom.vrs` is read on top of its base versification.

A text's versification: its own choice (a per-file override), else its
Paratext project's (`Settings.xml` + `custom.vrs`), else English. A missing
file falls back to English and says so. Mapping uses `usfmtc`'s tables.
Qt-free.
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .paratext_project import VERSIFICATIONS, project_for_file

logger = logging.getLogger("uniti.environment.usfm.versification")

DEFAULT_STEM = "eng"
BUILT_IN_STEMS = ("eng", "org")
_NAMES = {stem: name for name, stem in VERSIFICATIONS.values()}
_NUMBER_RE = re.compile(r"\d+")


def versification_name(stem: str) -> str:
    return _NAMES.get(stem, stem)


def _built_in_path(stem: str) -> Path | None:
    try:
        import usfmtc
    except ImportError:  # pragma: no cover - a declared dependency
        return None
    path = Path(os.path.dirname(usfmtc.__file__)) / f"{stem}.vrs"
    return path if path.is_file() else None


def _user_folder() -> Path | None:
    from uniti.core.environments.user_config import usfm_versification_folder

    return usfm_versification_folder()


def versification_path(stem: str) -> Path | None:
    """Where versification `stem` comes from: your folder first (so a
    newer copy wins), then the built-in files."""

    folder = _user_folder()
    if folder is not None:
        candidate = folder / f"{stem}.vrs"
        if candidate.is_file():
            return candidate
    return _built_in_path(stem)


def available_versifications() -> tuple[str, ...]:
    """Stems that can be used: the built-in ones plus your `.vrs` files."""

    stems = list(BUILT_IN_STEMS)
    folder = _user_folder()
    try:
        extra = sorted(path.stem for path in folder.glob("*.vrs")) if folder is not None and folder.is_dir() else []
    except OSError:
        extra = []
    stems.extend(stem for stem in extra if stem not in stems and stem != "custom")
    return tuple(stems)


def _stamp(path: Path | None) -> float | None:
    try:
        return None if path is None else path.stat().st_mtime
    except OSError:
        return None


@lru_cache(maxsize=32)
def _load(base: Path, _base_stamp: float | None, custom: Path | None, _custom_stamp: float | None):
    from usfmtc.versification import Versification

    versification = Versification(str(base))
    if custom is not None:
        try:
            _overlay(versification, Versification(str(custom)))
        except Exception:  # a broken custom.vrs never breaks the base
            logger.warning("ignoring unreadable %s", custom, exc_info=True)
    return versification


def _overlay(base, custom) -> None:
    """Apply `custom.vrs` the way Paratext does: its mappings *replace* the
    base's for the verses they name (usfmtc's `readFile` would merge them
    into ranges instead), and its chapter/verse counts and exclusions win."""

    for key, original in custom.toorg.items():
        previous = base.toorg.get(key)
        if previous is not None and str(base.fromorg.get(str(previous), "")) == key:
            del base.fromorg[str(previous)]
        base.toorg[key] = original
    base.fromorg.update(custom.fromorg)
    base.vnums.update(custom.vnums)
    base.exclusions |= custom.exclusions


@dataclass(frozen=True)
class TextVersification:
    """The versification one text uses."""

    stem: str  # the one in use
    requested: str  # what the text asked for
    custom: Path | None  # a project's custom.vrs layered on top
    table: object  # usfmtc Versification

    @property
    def name(self) -> str:
        return versification_name(self.stem)

    @property
    def fell_back(self) -> bool:
        """The requested versification's file is missing: English is used."""

        return self.stem != self.requested

    @property
    def label(self) -> str:
        label = self.name + (" + custom.vrs" if self.custom is not None else "")
        if self.fell_back:
            label += f" ({versification_name(self.requested)} file missing)"
        return label


def load_versification(stem: str, custom: Path | None = None) -> TextVersification:
    """`stem`'s versification, with `custom` on top; English when `stem`'s
    file is missing."""

    requested = stem
    path = versification_path(stem)
    if path is None:
        stem = DEFAULT_STEM
        path = versification_path(DEFAULT_STEM)
    if custom is not None and not custom.is_file():
        custom = None
    table = _load(path, _stamp(path), custom, _stamp(custom))
    return TextVersification(stem, requested, custom, table)


def versification_for(document_path: Path | None, override: str | None = None) -> TextVersification:
    """A text's versification: `override` (its own choice), else its
    project's, else English."""

    project = None if document_path is None else project_for_file(document_path)
    custom = None
    if project is not None:
        candidate = project.folder / "custom.vrs"
        custom = candidate if candidate.is_file() else None
    if override:
        return load_versification(override, custom)
    if project is not None:
        return load_versification(project.versification_file, custom)
    return load_versification(DEFAULT_STEM)


def map_reference(
    book: str | None, chapter: str | None, verse: str | None, source: TextVersification, target: TextVersification
) -> tuple[str | None, str | None]:
    """`chapter`:`verse` of `book` in `source`'s numbering, in `target`'s.

    Goes through Original. Verse bridges and parts map by their first
    number (``16-17`` and ``16a`` as 16). Anything that can't be mapped
    (no book, no verse, an unparseable number) is returned unchanged.
    """

    if book is None or chapter is None or verse is None or source.table is target.table:
        return chapter, verse
    chapter_match, verse_match = _NUMBER_RE.match(chapter), _NUMBER_RE.match(verse)
    if chapter_match is None or verse_match is None:
        return chapter, verse
    try:
        from usfmtc.reference import Ref

        ref = Ref(f"{book} {chapter_match.group()}:{verse_match.group()}", versification=source.table)
        original = source.table.remap(ref, None)
        mapped = target.table.remap(original, None, reverse=True)
    except Exception:
        logger.debug("could not map %s %s:%s", book, chapter, verse, exc_info=True)
        return chapter, verse
    mapped_chapter, mapped_verse = getattr(mapped, "chapter", None), getattr(mapped, "verse", None)
    if mapped_chapter is None or mapped_verse is None:
        return chapter, verse
    return str(mapped_chapter), str(mapped_verse)


__all__ = [
    "BUILT_IN_STEMS",
    "DEFAULT_STEM",
    "TextVersification",
    "available_versifications",
    "load_versification",
    "map_reference",
    "versification_for",
    "versification_name",
    "versification_path",
]
