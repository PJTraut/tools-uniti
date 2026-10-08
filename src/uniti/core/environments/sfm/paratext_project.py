"""Paratext projects: a folder with a `Settings.xml` (plan P1, 2026-10-07).

A project is *which text*: its name, how its book files are named, its
stylesheet, encoding and versification. A folder is a project only when it
has a valid Paratext `Settings.xml`; anything else is a folder of single
files (user decision, 2026-10-07). Qt-free, read-only, and never raises:
an unreadable or invalid project reads as "not a project".

`Settings.xml` varies across Paratext versions, so only these fields are
read: `Name`, `FullName`, `LanguageIsoCode`, `Encoding`, `Versification`,
`StyleSheet`, `Guid`, `BooksPresent`, and the file naming — Paratext 8+
`<Naming PrePart PostPart BookNameForm>` or the older `FileNamePrePart` /
`FileNamePostPart` / `FileNameBookNameForm` elements.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .references import ID_PROBE_BYTES, book_code

logger = logging.getLogger("uniti.environment.sfm.project")

SETTINGS_FILE = "Settings.xml"
BOOK_NAMES_FILE = "BookNames.xml"
MAX_SETTINGS_BYTES = 1024 * 1024
# Bound on the files read when a book's expected file name is missing.
MAX_FALLBACK_FILES = 400

# Paratext canon order: book number = index + 1 (`BooksPresent` is one
# 0/1 character per book number).
PARATEXT_BOOKS: tuple[str, ...] = (
    "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI",
    "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER",
    "LAM", "EZK", "DAN", "HOS", "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP",
    "HAG", "ZEC", "MAL", "MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL",
    "EPH", "PHP", "COL", "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE",
    "2PE", "1JN", "2JN", "3JN", "JUD", "REV", "TOB", "JDT", "ESG", "WIS", "SIR", "BAR",
    "LJE", "S3Y", "SUS", "BEL", "1MA", "2MA", "3MA", "4MA", "1ES", "2ES", "MAN", "PS2",
    "ODA", "PSS", "JSA", "JDB", "TBS", "SST", "DNT", "BLT", "XXA", "XXB", "XXC", "XXD",
    "XXE", "XXF", "XXG", "FRT", "BAK", "OTH", "3ES", "EZA", "5EZ", "6EZ", "INT", "CNC",
    "GLO", "TDX", "NDX", "DAG", "PS3", "2BA", "LBA", "JUB", "ENO", "1MQ", "2MQ", "3MQ",
    "REP", "4BA", "LAO",
)
_BOOK_NUMBERS = {code: index + 1 for index, code in enumerate(PARATEXT_BOOKS)}

# `<Versification>` values -> (display name, .vrs file stem).
VERSIFICATIONS: dict[int, tuple[str, str]] = {
    1: ("Original", "org"),
    2: ("Septuagint", "lxx"),
    3: ("Vulgate", "vul"),
    4: ("English", "eng"),
    5: ("Russian Protestant", "rsc"),
    6: ("Russian Orthodox", "rso"),
}
DEFAULT_VERSIFICATION = 4  # English (user decision, 2026-10-07)

# `<Encoding>` code pages UNITI can open directly.
_CODE_PAGES = {
    "65001": "utf-8",
    "1252": "windows-1252",
    "1200": "utf-16-le",
    "1201": "utf-16-be",
    "12000": "utf-32-le",
    "12001": "utf-32-be",
}


def book_file_number(code: str) -> str | None:
    """Paratext's file-name number for a book: ``01``–``39``, then ``41``…
    (40 is skipped) up to ``99``, then ``A0`` (FRT), ``A1``, … ``C3``."""

    number = _BOOK_NUMBERS.get(code)
    if number is None:
        return None
    if number <= 39:
        return f"{number:02d}"
    if number < 99:
        return str(number + 1)
    if number == 99:
        return "100"
    offset = number - 100
    return f"{chr(ord('A') + offset // 10)}{offset % 10}"


@dataclass(frozen=True, slots=True)
class BookNaming:
    """How a project names its book files: PrePart + form + PostPart, where
    the form ("41MAT", "MAT", "41", "MAT41"…) spells the book's number as
    41 and its code as MAT."""

    pre: str = ""
    post: str = ".SFM"
    form: str = "41MAT"

    def file_name(self, code: str) -> str | None:
        number = book_file_number(code)
        if number is None:
            return None
        middle = self.form.replace("MAT", "\0").replace("41", number).replace("\0", code)
        return f"{self.pre}{middle}{self.post}"

    def matches(self, name: str) -> bool:
        lowered = name.lower()
        return lowered.startswith(self.pre.lower()) and lowered.endswith(self.post.lower())


@dataclass(frozen=True, slots=True)
class ProjectBook:
    code: str
    path: Path
    name: str | None = None


@dataclass(frozen=True, slots=True)
class ParatextProject:
    folder: Path
    name: str
    full_name: str | None = None
    language: str | None = None
    encoding: str | None = None  # a Python codec name; None: detect as usual
    versification: int = DEFAULT_VERSIFICATION
    stylesheet: str | None = None
    guid: str | None = None
    naming: BookNaming = BookNaming()
    books_present: tuple[str, ...] = ()

    @classmethod
    def load(cls, folder: Path) -> "ParatextProject | None":
        """The project in `folder`, or None when it has no valid `Settings.xml`."""

        folder = Path(folder)
        root = _read_xml(folder / SETTINGS_FILE, "ScriptureText")
        if root is None:
            return None
        name = _text(root, "Name")
        if not name:
            return None
        naming_element = root.find("Naming")
        if naming_element is not None:
            naming = BookNaming(
                naming_element.get("PrePart", ""),
                naming_element.get("PostPart", ".SFM"),
                naming_element.get("BookNameForm", "41MAT") or "41MAT",
            )
        else:
            naming = BookNaming(
                _text(root, "FileNamePrePart") or "",
                _text(root, "FileNamePostPart") or ".SFM",
                _text(root, "FileNameBookNameForm") or "41MAT",
            )
        versification = _int(_text(root, "Versification"))
        language = _text(root, "LanguageIsoCode")
        present = _text(root, "BooksPresent") or ""
        return cls(
            folder=folder,
            name=name,
            full_name=_text(root, "FullName"),
            language=language.split(":", 1)[0] or None if language else None,
            encoding=_CODE_PAGES.get(_text(root, "Encoding") or ""),
            versification=versification if versification in VERSIFICATIONS else DEFAULT_VERSIFICATION,
            stylesheet=_text(root, "StyleSheet"),
            guid=_text(root, "Guid"),
            naming=naming,
            books_present=tuple(
                code for code, flag in zip(PARATEXT_BOOKS, present) if flag == "1"
            ),
        )

    @property
    def versification_name(self) -> str:
        return VERSIFICATIONS[self.versification][0]

    @property
    def versification_file(self) -> str:
        """The `.vrs` stem (``eng``, ``org``, ``lxx``…)."""

        return VERSIFICATIONS[self.versification][1]

    def book_path(self, code: str) -> Path | None:
        """Where the naming pattern puts book `code` (it may not exist)."""

        name = self.naming.file_name(code.upper())
        return None if name is None else self.folder / name

    def books(self) -> tuple[ProjectBook, ...]:
        """The books this project has, in Paratext canon order.

        A book counts when `BooksPresent` lists it (or, with no
        `BooksPresent`, whenever its file exists) and its file is found:
        by the naming pattern, else by the `\\id` of a file that matches
        the pattern's prefix and suffix.
        """

        names = self.book_names()
        candidates = self.books_present or PARATEXT_BOOKS
        found: dict[str, Path] = {}
        missing: list[str] = []
        for code in candidates:
            path = self.book_path(code)
            if path is not None and _is_file(path):
                found[code] = path
            elif self.books_present:
                missing.append(code)
        if missing:
            scanned = self._scan_by_id()
            for code in missing:
                if code in scanned:
                    found[code] = scanned[code]
        return tuple(
            ProjectBook(code, found[code], names.get(code))
            for code in PARATEXT_BOOKS
            if code in found
        )

    def book_for(self, code: str) -> ProjectBook | None:
        return next((book for book in self.books() if book.code == code.upper()), None)

    def _scan_by_id(self) -> dict[str, Path]:
        result: dict[str, Path] = {}
        try:
            entries = sorted(self.folder.iterdir())
        except OSError:
            return result
        read = 0
        for path in entries:
            if read >= MAX_FALLBACK_FILES:
                break
            if not self.naming.matches(path.name) or not _is_file(path):
                continue
            read += 1
            try:
                with path.open("rb") as handle:
                    head = handle.read(ID_PROBE_BYTES)
            except OSError:
                continue
            code = book_code(head.decode(self.encoding or "utf-8-sig", errors="replace").lstrip("\ufeff"))
            if code is not None and code not in result:
                result[code] = path
        return result

    def book_names(self) -> dict[str, str]:
        """Short book names from `BookNames.xml`, when the project has one."""

        return _book_names(self.folder / BOOK_NAMES_FILE, _mtime(self.folder / BOOK_NAMES_FILE))

    def owns(self, path: Path) -> bool:
        """Whether `path` is a file directly in this project's folder."""

        try:
            return Path(path).resolve().parent == self.folder.resolve()
        except OSError:
            return False


def project_for_file(path: Path) -> ParatextProject | None:
    """The project whose folder holds `path`, if that folder is a project."""

    folder = Path(path).parent
    return _cached_project(folder, _mtime(folder / SETTINGS_FILE))


_BOMS = {
    "utf-8": b"\xef\xbb\xbf",
    "utf-16-le": b"\xff\xfe",
    "utf-16-be": b"\xfe\xff",
    "utf-32-le": b"\xff\xfe\x00\x00",
    "utf-32-be": b"\x00\x00\xfe\xff",
}
ENCODING_PROBE_BYTES = 65_536


def project_encoding_profile(path: Path):
    """The `EncodingProfile` to open a project book with (plan P3).

    The project's declared `<Encoding>`, with the file's own BOM, when the
    start of the file decodes cleanly in it; otherwise None, so ordinary
    detection — and its prompt when unsure — decides.
    """

    project = project_for_file(Path(path))
    if project is None or project.encoding is None:
        return None
    try:
        with Path(path).open("rb") as handle:
            head = handle.read(ENCODING_PROBE_BYTES)
    except OSError:
        return None
    bom = _BOMS.get(project.encoding)
    has_bom = bom is not None and head.startswith(bom)
    body = head[len(bom) :] if has_bom else head
    try:
        body.decode(project.encoding)
    except UnicodeDecodeError as error:
        # Only a character cut off at the probe's end is acceptable.
        if len(head) < ENCODING_PROBE_BYTES or error.start < len(body) - 4:
            return None
    from uniti.core.text_format import profile_from_codec

    try:
        return profile_from_codec(project.encoding, bom if has_bom else None)
    except ValueError:
        return None


@lru_cache(maxsize=64)
def _cached_project(folder: Path, _settings_mtime: float | None) -> ParatextProject | None:
    # Keyed by Settings.xml's mtime, so an edited project is re-read.
    return ParatextProject.load(folder)


@lru_cache(maxsize=64)
def _book_names(path: Path, _mtime_key: float | None) -> dict[str, str]:
    root = _read_xml(path, "BookNames")
    if root is None:
        return {}
    names: dict[str, str] = {}
    for element in root.iter("book"):
        code = (element.get("code") or "").upper()
        name = element.get("short") or element.get("long") or element.get("abbr")
        if code and name:
            names[code] = name.strip()
    return names


def _read_xml(path: Path, root_tag: str):
    try:
        if not path.is_file() or path.stat().st_size > MAX_SETTINGS_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    try:
        # ElementTree never fetches external entities; the size cap bounds
        # the rest.
        root = ElementTree.fromstring(data)
    except ElementTree.ParseError:
        logger.warning("ignoring unreadable %s", path)
        return None
    return root if root.tag == root_tag else None


def _text(root, tag: str) -> str | None:
    element = root.find(tag)
    if element is None or element.text is None:
        return None
    return element.text.strip() or None


def _int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except OSError:
        return None


def _is_file(path: Path) -> bool:
    try:
        return path.is_file()
    except OSError:
        return False


__all__ = [
    "BookNaming",
    "DEFAULT_VERSIFICATION",
    "PARATEXT_BOOKS",
    "ParatextProject",
    "ProjectBook",
    "SETTINGS_FILE",
    "VERSIFICATIONS",
    "book_file_number",
    "project_encoding_profile",
    "project_for_file",
]
