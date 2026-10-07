"""Scripture references in USFM source: book, chapter, verse (ADR-0017).

Drives the environment window's Book/Chapter/Verse selector and the
side-by-side reference sync. Qt-free. Like `navigation.py`, it reads the
fixed USFM lexical conventions (`\\id`, `\\c`, `\\v`), not stylesheet data.
"""

from __future__ import annotations

import bisect
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .tokenizer import tokenize_sfm
from .tokens import SfmTokenKind

# USFM book identifiers in canonical order (USFM 3.1 "Book Identifiers").
BOOK_ORDER: tuple[str, ...] = (
    "FRT", "INT",
    "GEN", "EXO", "LEV", "NUM", "DEU", "JOS", "JDG", "RUT", "1SA", "2SA", "1KI", "2KI",
    "1CH", "2CH", "EZR", "NEH", "EST", "JOB", "PSA", "PRO", "ECC", "SNG", "ISA", "JER",
    "LAM", "EZK", "DAN", "HOS", "JOL", "AMO", "OBA", "JON", "MIC", "NAM", "HAB", "ZEP",
    "HAG", "ZEC", "MAL",
    "MAT", "MRK", "LUK", "JHN", "ACT", "ROM", "1CO", "2CO", "GAL", "EPH", "PHP", "COL",
    "1TH", "2TH", "1TI", "2TI", "TIT", "PHM", "HEB", "JAS", "1PE", "2PE", "1JN", "2JN",
    "3JN", "JUD", "REV",
    "TOB", "JDT", "ESG", "WIS", "SIR", "BAR", "LJE", "S3Y", "SUS", "BEL", "1MA", "2MA",
    "3MA", "4MA", "1ES", "2ES", "MAN", "PS2", "ODA", "PSS", "EZA", "5EZ", "6EZ", "DAG",
    "PS3", "2BA", "LBA", "JUB", "ENO", "1MQ", "2MQ", "3MQ", "REP", "4BA", "LAO",
    "BAK", "OTH", "CNC", "GLO", "TDX", "NDX", "XXA", "XXB", "XXC", "XXD", "XXE", "XXF", "XXG",
)
_BOOK_RANK = {code: rank for rank, code in enumerate(BOOK_ORDER)}
_ID_RE = re.compile(r"\A\ufeff?\s*\\id\s+([A-Za-z0-9]{3})(?![A-Za-z0-9])")
_LEADING_RE = re.compile(r"\s*(\S+)")
_NUMBER_RE = re.compile(r"(\d+)(?:\s*-\s*(\d+))?")
# Enough of a file's start to hold its `\id` line.
ID_PROBE_BYTES = 4096
MAX_SCANNED_FILES = 400


def book_code(text: str) -> str | None:
    """The book identifier of `\\id GEN …` at the start of `text`, upper-cased."""

    match = _ID_RE.match(text)
    return match.group(1).upper() if match else None


def book_rank(code: str | None) -> int:
    """Sort key: canonical order, unknown books after every known one."""

    return _BOOK_RANK.get(code or "", len(BOOK_ORDER))


def _numbers(label: str) -> tuple[int, int] | None:
    """``"16"`` → (16, 16), a bridge ``"16-17"`` → (16, 17), ``"16a"`` → (16, 16)."""

    match = _NUMBER_RE.match(label)
    if match is None:
        return None
    first = int(match.group(1))
    return first, int(match.group(2)) if match.group(2) else first


@dataclass(frozen=True, slots=True)
class Chapter:
    label: str
    start: int


@dataclass(frozen=True, slots=True)
class Verse:
    chapter: str | None
    label: str
    start: int  # the `\\v` marker


@dataclass(frozen=True, slots=True)
class Reference:
    """Where a source offset is: `verse` is None between `\\c` and the first `\\v`."""

    book: str | None
    chapter: str | None
    verse: str | None


class ReferenceMap:
    """Chapter and verse starts of one USFM text, with lookups both ways."""

    def __init__(self, text: str) -> None:
        self.book = book_code(text)
        self.length = len(text)
        chapters: list[Chapter] = []
        verses: list[Verse] = []
        tokens = tokenize_sfm(text)
        current: str | None = None
        for index, token in enumerate(tokens):
            if token.kind is not SfmTokenKind.MARKER or token.text not in (r"\c", r"\v"):
                continue
            following = tokens[index + 1] if index + 1 < len(tokens) else None
            if following is None or following.kind is not SfmTokenKind.TEXT:
                continue
            match = _LEADING_RE.match(following.text)
            if match is None:
                continue
            if token.text == r"\c":
                current = match.group(1)
                chapters.append(Chapter(current, token.start))
            else:
                verses.append(Verse(current, match.group(1), token.start))
        self.chapters: tuple[Chapter, ...] = tuple(chapters)
        self.verses: tuple[Verse, ...] = tuple(verses)
        self._chapter_starts = [chapter.start for chapter in chapters]
        self._verse_starts = [verse.start for verse in verses]
        # Every boundary a verse runs up to: the next verse or chapter.
        self._boundaries = sorted(self._chapter_starts + self._verse_starts)

    def verses_in(self, chapter: str) -> tuple[Verse, ...]:
        return tuple(verse for verse in self.verses if verse.chapter == chapter)

    def chapter_start(self, chapter: str) -> int | None:
        found = next((item for item in self.chapters if item.label == chapter), None)
        return None if found is None else found.start

    def reference_at(self, offset: int) -> Reference:
        chapter_index = bisect.bisect_right(self._chapter_starts, offset) - 1
        chapter = self.chapters[chapter_index] if chapter_index >= 0 else None
        verse_index = bisect.bisect_right(self._verse_starts, offset) - 1
        verse = self.verses[verse_index] if verse_index >= 0 else None
        if verse is not None and chapter is not None and verse.start < chapter.start:
            verse = None  # in a chapter's heading, before its first verse
        return Reference(
            self.book,
            chapter.label if chapter is not None else (verse.chapter if verse else None),
            verse.label if verse is not None else None,
        )

    def find(self, chapter: str | None, verse: str | None) -> Verse | None:
        """The verse covering `chapter`:`verse` (bridges and ``16a`` count)."""

        if verse is None:
            return None
        wanted = _numbers(verse)
        if wanted is None:
            return None
        for item in self.verses:
            if item.chapter != chapter:
                continue
            numbers = _numbers(item.label)
            if numbers is not None and numbers[0] <= wanted[0] <= numbers[1]:
                return item
        return None

    def verse_range(self, verse: Verse) -> tuple[int, int]:
        """`verse` from its marker up to the next verse or chapter."""

        index = bisect.bisect_right(self._boundaries, verse.start)
        end = self._boundaries[index] if index < len(self._boundaries) else self.length
        return verse.start, end


@dataclass(frozen=True, slots=True)
class BookFile:
    code: str
    path: Path


def scan_books(folder: Path, extensions: Iterable[str]) -> tuple[BookFile, ...]:
    """The book files in `folder` (not recursive) with one of `extensions`
    (lower-case, no dot), by `\\id`, in canonical order. Never raises."""

    wanted = {extension.lower().lstrip(".") for extension in extensions}
    found: list[BookFile] = []
    try:
        entries = sorted(folder.iterdir())
    except OSError:
        return ()
    for path in entries[: MAX_SCANNED_FILES * 4]:
        if len(found) >= MAX_SCANNED_FILES:
            break
        if path.suffix.lower().lstrip(".") not in wanted:
            continue
        try:
            if not path.is_file():
                continue
            with path.open("rb") as handle:
                head = handle.read(ID_PROBE_BYTES)
        except OSError:
            continue
        code = book_code(head.decode("utf-8-sig", errors="replace"))
        if code is not None:
            found.append(BookFile(code, path))
    found.sort(key=lambda item: (book_rank(item.code), item.code, item.path.name.lower()))
    return tuple(found)


__all__ = [
    "BOOK_ORDER",
    "BookFile",
    "Chapter",
    "Reference",
    "ReferenceMap",
    "Verse",
    "book_code",
    "book_rank",
    "scan_books",
]
