"""Spelling from Paratext's word lists (plan 2026-10-13-usfm-spellcheck-plan).

UNITI only reads the lists, and never writes them (ADR-0018):

- `SpellingStatus.xml`: `<Status Word="…" State="R|W">`, with optional
  `<SpecificCase>` forms on an R entry and a `<Correction>` on a W entry;
- `hyphenatedWords.txt`: Publishing Assistant's list, one word per line with
  `=` at its break points, `*` in front of a line the user fixed.

S1 is this loading and `SpellingList.status`. Qt-free.
"""

from __future__ import annotations

import re
import threading
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from enum import IntEnum
from pathlib import Path

SPELLING_STATUS_FILE = "SpellingStatus.xml"
HYPHENATED_WORDS_FILE = "hyphenatedWords.txt"
# Hyphens a word can be split at, besides the list's own HardHyphen.
_HYPHENS = frozenset({"-", "‐", "‑"})
_SETTING_RE = re.compile(r'^\s*([A-Za-z]+)\s*=\s*"(.*)"\s*$')


class SpellingState(IntEnum):
    """A word's status; a higher value is worse (a hyphenated word takes its
    worst part's)."""

    CORRECT = 0
    UNKNOWN = 1
    WRONG_CASE = 2
    WRONG = 3


@dataclass(frozen=True, slots=True)
class Spelling:
    state: SpellingState
    correction: str | None = None  # a W entry's Correction
    forms: tuple[str, ...] = ()  # the accepted capitalizations of a wrong-case word


CORRECT = Spelling(SpellingState.CORRECT)
UNKNOWN = Spelling(SpellingState.UNKNOWN)


def normalize(word: str) -> str:
    """The form words are compared in: NFC, case-folded."""

    return unicodedata.normalize("NFC", word).casefold()


@dataclass(slots=True)
class SpellingStatusData:
    """`SpellingStatus.xml`: the normalized word → "R"/"W", and the rarer
    details only for the entries that have them."""

    states: dict[str, str] = field(default_factory=dict)
    forms: dict[str, tuple[str, ...]] = field(default_factory=dict)
    corrections: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class HyphenatedWordsData:
    """`hyphenatedWords.txt`: each word (without `=` and `*`) → its line
    with the `=` break points kept, for hyphenation later; and the settings."""

    words: dict[str, str] = field(default_factory=dict)
    settings: dict[str, str] = field(default_factory=dict)
    rules: object | None = field(default=None, repr=False)  # `HyphenationRules`, made on first use

    @property
    def hard_hyphen(self) -> str:
        return self.settings.get("HardHyphen") or "-"


def load_spelling_status(path: Path) -> SpellingStatusData | None:
    """Read `SpellingStatus.xml`; None when it's missing or damaged."""

    data = SpellingStatusData()
    try:
        with Path(path).open("rb") as handle:
            for _event, element in ET.iterparse(handle, events=("end",)):
                if element.tag != "Status":
                    continue
                word = element.get("Word")
                state = element.get("State")
                if word and state in ("R", "W"):
                    key = normalize(word)
                    data.states[key] = state
                    forms = tuple(
                        unicodedata.normalize("NFC", child.text)
                        for child in element.findall("SpecificCase")
                        if child.text
                    )
                    if forms:
                        data.forms[key] = forms
                    correction = element.findtext("Correction")
                    if correction:
                        data.corrections[key] = unicodedata.normalize("NFC", correction.strip())
                element.clear()
    except (OSError, ET.ParseError):
        return None
    return data


def load_hyphenated_words(path: Path) -> HyphenatedWordsData | None:
    """Read `hyphenatedWords.txt` (UTF-8, BOM or not); None when it's missing."""

    try:
        text = Path(path).read_bytes().decode("utf-8-sig", errors="replace")
    except OSError:
        return None
    data = HyphenatedWordsData()
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        setting = _SETTING_RE.match(line)
        if setting is not None:
            data.settings[setting.group(1)] = setting.group(2)
            continue
        line = line.removeprefix("*")
        soft = data.settings.get("SoftHyphen") or "="
        plain = line.replace(soft, "")
        if not plain or " " in plain:
            continue  # a word pair: read, not used for matching (see Later)
        data.words.setdefault(normalize(plain), line)
    return data


@dataclass(slots=True)
class SpellingList:
    """The word lists of one project, answering `status(word)`."""

    status_data: SpellingStatusData | None
    hyphenated: HyphenatedWordsData | None
    _cache: dict[str, Spelling] = field(default_factory=dict, repr=False)

    @property
    def available(self) -> bool:
        return self.status_data is not None or self.hyphenated is not None

    def status(self, word: str) -> Spelling:
        """Rules 1–6 of the plan; a word's own status is remembered."""

        cached = self._cache.get(word)
        if cached is None:
            cached = self._cache[word] = self._status(word)
        return cached

    def _status(self, word: str) -> Spelling:
        word = unicodedata.normalize("NFC", word)
        key = normalize(word)
        data = self.status_data
        if data is not None:
            state = data.states.get(key)
            if state == "W":
                return Spelling(SpellingState.WRONG, correction=data.corrections.get(key))
            if state == "R":
                forms = data.forms.get(key)
                if forms is None or word in forms or (word == word.upper() and word != word.lower()):
                    return CORRECT
                return Spelling(SpellingState.WRONG_CASE, forms=forms)
        if self.hyphenated is not None and key in self.hyphenated.words:
            return CORRECT
        hyphens = set(_HYPHENS)
        if self.hyphenated is not None:
            hyphens.add(self.hyphenated.hard_hyphen)
        if any(hyphen in word for hyphen in hyphens):
            parts = [part for part in re.split("|".join(re.escape(h) for h in hyphens), word)]
            if len(parts) > 1 and all(parts):
                worst = max((self.status(part) for part in parts), key=lambda item: item.state)
                return worst
        return UNKNOWN


def load_spelling_list(folder: Path) -> SpellingList:
    """Both lists of the project in `folder`; a missing or damaged one is
    ignored. A plain function, so a worker can run it."""

    folder = Path(folder)
    return SpellingList(
        load_spelling_status(folder / SPELLING_STATUS_FILE),
        load_hyphenated_words(folder / HYPHENATED_WORDS_FILE),
    )


def list_signature(folder: Path) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
    """(modification time, size) of each list file, None for a missing one:
    what changes when Paratext's Send/Receive rewrites them."""

    def stamp(name: str):
        try:
            info = (Path(folder) / name).stat()
        except OSError:
            return None
        return (info.st_mtime_ns, info.st_size)

    return stamp(SPELLING_STATUS_FILE), stamp(HYPHENATED_WORDS_FILE)


_CACHE: dict[str, tuple[tuple, SpellingList]] = {}
_CACHE_LOCK = threading.Lock()


def spelling_list_for(folder: Path) -> SpellingList:
    """The project's lists, cached per folder and re-read when a file's
    modification time or size changed."""

    key = str(Path(folder))
    signature = list_signature(folder)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None and cached[0] == signature:
        return cached[1]
    loaded = load_spelling_list(folder)
    with _CACHE_LOCK:
        _CACHE[key] = (signature, loaded)
    return loaded


def lists_changed(folder: Path) -> bool:
    """Whether the project's cached lists are out of date."""

    with _CACHE_LOCK:
        cached = _CACHE.get(str(Path(folder)))
    return cached is None or cached[0] != list_signature(folder)


__all__ = [
    "CORRECT",
    "HYPHENATED_WORDS_FILE",
    "SPELLING_STATUS_FILE",
    "UNKNOWN",
    "HyphenatedWordsData",
    "Spelling",
    "SpellingList",
    "SpellingState",
    "SpellingStatusData",
    "list_signature",
    "lists_changed",
    "load_hyphenated_words",
    "load_spelling_list",
    "load_spelling_status",
    "normalize",
    "spelling_list_for",
]
