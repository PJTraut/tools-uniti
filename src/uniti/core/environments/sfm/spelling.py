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
from collections.abc import Iterable
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
    pair: bool = False  # two words Paratext marks wrong together (`grain field`)
    user: bool = False  # the user's own list says so, not Paratext's


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
    # W entries of two words (`grain field`): (first, second) → its Correction.
    wrong_pairs: dict[tuple[str, str], str | None] = field(default_factory=dict)


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
                    if state == "W":
                        parts = key.split()
                        if len(parts) == 2:
                            data.wrong_pairs[(parts[0], parts[1])] = data.corrections.get(key)
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
    """The word lists of one project, answering `status(word)`.

    `derive` makes the list the checker uses: Paratext's two files plus the
    user's own approved and rejected words and the project's word affixes.
    """

    status_data: SpellingStatusData | None
    hyphenated: HyphenatedWordsData | None
    approved: frozenset[str] = frozenset()  # the user's words, normalized
    rejected: frozenset[str] = frozenset()
    prefixes: tuple[str, ...] = ()  # normalized, longest first
    suffixes: tuple[str, ...] = ()
    _cache: dict[str, Spelling] = field(default_factory=dict, repr=False)
    _vocabulary: dict[int, list[tuple[str, int]]] | None = field(default=None, repr=False)

    @property
    def available(self) -> bool:
        return self.status_data is not None or self.hyphenated is not None

    @property
    def wrong_pairs(self) -> dict[tuple[str, str], str | None]:
        return self.status_data.wrong_pairs if self.status_data is not None else {}

    def derive(
        self,
        approved: Iterable[str] = (),
        rejected: Iterable[str] = (),
        prefixes: Iterable[str] = (),
        suffixes: Iterable[str] = (),
    ) -> "SpellingList":
        """A list over the same files with the user's words and the
        project's affixes; it has a status cache of its own."""

        def affixes(items: Iterable[str]) -> tuple[str, ...]:
            kept = {normalize(item) for item in items if item.strip()}
            return tuple(sorted(kept, key=lambda item: (-len(item), item)))

        return SpellingList(
            self.status_data,
            self.hyphenated,
            frozenset(normalize(word) for word in approved),
            frozenset(normalize(word) for word in rejected),
            affixes(prefixes),
            affixes(suffixes),
            _vocabulary=self._vocabulary,
        )

    def status(self, word: str) -> Spelling:
        """Rules 1–6 of the plan, after the user's own words; a word's own
        status is remembered."""

        cached = self._cache.get(word)
        if cached is None:
            cached = self._cache[word] = self._status(word)
        return cached

    def _status(self, word: str) -> Spelling:
        word = unicodedata.normalize("NFC", word)
        key = normalize(word)
        if key in self.rejected:
            return Spelling(SpellingState.WRONG, user=True)
        if key in self.approved:
            return CORRECT
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
        found = UNKNOWN
        if any(hyphen in word for hyphen in hyphens):
            parts = [part for part in re.split("|".join(re.escape(h) for h in hyphens), word)]
            if len(parts) > 1 and all(parts):
                found = max((self.status(part) for part in parts), key=lambda item: item.state)
        if found.state is SpellingState.UNKNOWN and self._with_affix(word, key):
            return CORRECT
        return found

    def _with_affix(self, word: str, key: str) -> bool:
        """Whether `word` is a correct word plus one of the project's
        prefixes or suffixes (F-D5): `Paul` + `ʼs`."""

        if len(key) != len(word):
            return False  # case folding changed the length: offsets wouldn't line up
        for suffix in self.suffixes:
            if len(key) > len(suffix) and key.endswith(suffix):
                if self.status(word[: len(word) - len(suffix)]).state is SpellingState.CORRECT:
                    return True
        for prefix in self.prefixes:
            if len(key) > len(prefix) and key.startswith(prefix):
                if self.status(word[len(prefix) :]).state is SpellingState.CORRECT:
                    return True
        return False

    # --- suggestions (F-D2) ----------------------------------------------------------

    def _words_by_length(self) -> dict[int, list[tuple[str, int]]]:
        """The correct words by length, each with its letter mask (below)."""

        if self._vocabulary is None:
            vocabulary: dict[int, list[tuple[str, int]]] = {}
            data = self.status_data
            if data is not None:
                for key, state in data.states.items():
                    if state == "R" and " " not in key:
                        vocabulary.setdefault(len(key), []).append((key, _letter_mask(key)))
            if self.hyphenated is not None:
                for key in self.hyphenated.words:
                    if not data or key not in data.states:
                        vocabulary.setdefault(len(key), []).append((key, _letter_mask(key)))
            self._vocabulary = vocabulary
        return self._vocabulary

    def suggestions(self, word: str, limit: int = 5) -> list[str]:
        """Correct words close to `word`, nearest first, then alphabetical:
        one edit (a letter changed, added, left out, or two swapped) for a
        word up to seven letters, two from eight. Taken from the lists only,
        with the word's capitalization (F-D2)."""

        word = unicodedata.normalize("NFC", word)
        key = normalize(word)
        reach = 1 if len(key) <= 7 else 2
        vocabulary = self._words_by_length()
        mask = _letter_mask(key)
        scored: list[tuple[int, str]] = []
        for length in range(max(1, len(key) - reach), len(key) + reach + 1):
            for candidate, candidate_mask in vocabulary.get(length, ()):
                if candidate == key or (mask ^ candidate_mask).bit_count() > 2 * reach:
                    continue  # too many different letters for `reach` edits
                distance = _edit_distance(key, candidate, reach)
                if distance is not None:
                    scored.append((distance, candidate))
        scored.sort()
        forms = self.status_data.forms if self.status_data is not None else {}
        result: list[str] = []
        for _distance, candidate in scored:
            shown = forms[candidate][0] if candidate in forms else _match_case(candidate, word)
            if shown not in result and self.status(shown).state is SpellingState.CORRECT:
                result.append(shown)
                if len(result) == limit:
                    break
        return result


def _letter_mask(word: str) -> int:
    """The set of a word's letters as bits (folded into 64): a quick way to
    rule out words that can't be within a few edits."""

    mask = 0
    for char in word:
        mask |= 1 << (ord(char) % 64)
    return mask


def _match_case(candidate: str, word: str) -> str:
    if len(word) > 1 and word == word.upper() and word != word.lower():
        return candidate.upper()
    if word[:1].isupper():
        return candidate[:1].upper() + candidate[1:]
    return candidate


def _edit_distance(a: str, b: str, limit: int) -> int | None:
    """The Damerau–Levenshtein distance of `a` and `b` (an adjacent swap is
    one edit) when it is at most `limit`, else None."""

    if abs(len(a) - len(b)) > limit:
        return None
    previous2: list[int] | None = None
    previous = list(range(len(b) + 1))
    for i, char_a in enumerate(a, start=1):
        row = [i]
        for j, char_b in enumerate(b, start=1):
            cost = 0 if char_a == char_b else 1
            value = min(previous[j] + 1, row[j - 1] + 1, previous[j - 1] + cost)
            if previous2 is not None and i > 1 and j > 1 and char_a == b[j - 2] and a[i - 2] == char_b:
                value = min(value, previous2[j - 2] + 1)
            row.append(value)
        if min(row) > limit:
            return None
        previous2, previous = previous, row
    return previous[-1] if previous[-1] <= limit else None


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
_EFFECTIVE: dict[tuple[str, str], tuple[tuple, SpellingList, SpellingList]] = {}


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


def effective_spelling_list(project) -> SpellingList:
    """The list the checker uses for a Paratext project: its files, the
    user's own words (`user_words`) and the project's word affixes. The same
    object comes back until one of them changes, so views and documents can
    share a cache built on it."""

    from .user_words import user_words_for

    base = spelling_list_for(project.folder)
    user = user_words_for(project.name)
    key = (str(project.folder), project.name)
    stamp = (id(base), user.version, project.word_prefixes, project.word_suffixes)
    with _CACHE_LOCK:
        cached = _EFFECTIVE.get(key)
    if cached is not None and cached[0] == stamp and cached[1] is base:
        return cached[2]
    derived = base.derive(user.approved, user.rejected, project.word_prefixes, project.word_suffixes)
    with _CACHE_LOCK:
        _EFFECTIVE[key] = (stamp, base, derived)
    return derived


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
    "effective_spelling_list",
    "normalize",
    "spelling_list_for",
]
