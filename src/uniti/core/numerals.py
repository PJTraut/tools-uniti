"""Display numerals (Preview, 2026-11-05).

Preview can show every decimal digit of the text in one numeral system
whatever the source holds (Latin `1`, Arabic-Indic `١`, Persian `۱`, …). It is
a display choice only: a digit is swapped for one digit, so view and source
offsets stay equal. Qt-free.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import replace
from pathlib import Path

from uniti.core.rich_views.projection import NoteSection, Projection
from uniti.core.rich_views.source_map import SourceMap

AS_WRITTEN = "as-written"

# key -> (label, code point of the system's zero)
NUMERAL_SYSTEMS: dict[str, tuple[str, int]] = {
    "latin": ("Latin (0123456789)", 0x30),
    "arabic-indic": ("Arabic-Indic / Hindi (٠١٢٣٤٥٦٧٨٩)", 0x660),
    "persian": ("Persian / Urdu (۰۱۲۳۴۵۶۷۸۹)", 0x6F0),
    "devanagari": ("Devanagari (०१२३४५६७८९)", 0x966),
    "bengali": ("Bengali (০১২৩৪৫৬৭৮৯)", 0x9E6),
    "thai": ("Thai (๐๑๒๓๔๕๖๗๘๙)", 0xE50),
}


def numeral_choices() -> tuple[tuple[str, str], ...]:
    return ((AS_WRITTEN, "As written"), *((key, label) for key, (label, _zero) in NUMERAL_SYSTEMS.items()))


def convert_numerals(text: str, system: str) -> str:
    """`text` with every decimal digit in `system`; unchanged for
    `as-written` or an unknown system."""

    entry = NUMERAL_SYSTEMS.get(system)
    if entry is None:
        return text
    zero = entry[1]
    out = []
    for char in text:
        if char.isdigit():
            try:
                value = unicodedata.decimal(char)
            except ValueError:
                out.append(char)
                continue
            out.append(chr(zero + value))
        else:
            out.append(char)
    return "".join(out)


def with_numerals(projection: Projection, system: str) -> Projection:
    """`projection` showing its digits in `system` (notes frame included)."""

    if system not in NUMERAL_SYSTEMS:
        return projection
    source_map = projection.source_map
    text = convert_numerals(source_map.view_text, system)
    notes = tuple(
        NoteSection(section.key, section.label, with_numerals(section.projection, system))
        for section in projection.notes
    )
    if text == source_map.view_text and not notes:
        return projection
    return replace(
        projection,
        source_map=SourceMap(source_map.segments, text, source_map.source_length),
        notes=notes,
    )


PROJECT_NUMERALS_FILE = "project_numerals.json"
_CHOICES = frozenset((AS_WRITTEN, *NUMERAL_SYSTEMS))


def _store_path() -> Path | None:
    from uniti.core.environments.user_config import environment_folder

    folder = environment_folder("USFM")
    return None if folder is None else folder / PROJECT_NUMERALS_FILE


_session: dict[str, dict[str, str]] = {}  # used when there is no user data folder


def _clean(data: object) -> dict[str, dict[str, str]]:
    out: dict[str, dict[str, str]] = {"projects": {}, "languages": {}}
    if isinstance(data, dict):
        for section in out:
            rows = data.get(section)
            if isinstance(rows, dict):
                out[section] = {k: v for k, v in rows.items() if isinstance(k, str) and v in _CHOICES}
    return out


def _read() -> dict[str, dict[str, str]]:
    path = _store_path()
    if path is None:
        return _clean(_session)
    try:
        return _clean(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return _clean(None)


def _write(data: dict[str, dict[str, str]]) -> None:
    path = _store_path()
    if path is None:
        _session.clear()
        _session.update(data)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def _language_key(language: str | None) -> str | None:
    return language.strip().lower() if language and language.strip() else None


def project_numerals(project_name: str | None) -> str | None:
    """The project's own choice, None when it follows its language's."""

    return _read()["projects"].get(project_name or "")


def language_numerals(language: str | None) -> str | None:
    """The default for every project in `language` (its code), if any."""

    key = _language_key(language)
    return None if key is None else _read()["languages"].get(key)


def effective_numerals(project_name: str | None, language: str | None) -> str:
    """What Preview uses: the project's choice, else its language's, else
    `as-written`."""

    return project_numerals(project_name) or language_numerals(language) or AS_WRITTEN


def set_project_numerals(project_name: str, system: str | None) -> None:
    """Remember `system` for the project; None makes it follow its language."""

    data = _read()
    if system in _CHOICES:
        data["projects"][project_name] = system
    else:
        data["projects"].pop(project_name, None)
    _write(data)


def set_language_numerals(language: str | None, system: str | None) -> None:
    """Remember `system` as the default of every project in `language`."""

    key = _language_key(language)
    if key is None:
        return
    data = _read()
    if system in _CHOICES:
        data["languages"][key] = system
    else:
        data["languages"].pop(key, None)
    _write(data)


def numerals_for_path(path: Path | None) -> str:
    """The numeral system for the project a book file belongs to."""

    if path is None:
        return AS_WRITTEN
    from uniti.core.environments.sfm.paratext_project import project_for_file

    project = project_for_file(path)
    return AS_WRITTEN if project is None else effective_numerals(project.name, project.language)


__all__ = [
    "effective_numerals",
    "language_numerals",
    "numerals_for_path",
    "project_numerals",
    "set_language_numerals",
    "set_project_numerals","AS_WRITTEN", "NUMERAL_SYSTEMS", "convert_numerals", "numeral_choices", "with_numerals"]
