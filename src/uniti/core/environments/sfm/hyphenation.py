"""Hyphenation for Preview from Paratext's `hyphenatedWords.txt`
(plan 2026-10-15-usfm-hyphenation-and-spelling-followups-plan, H1).

The list gives, for each word it knows, the points where it may break
(`a=ro=se`). Preview puts a soft hyphen (U+00AD) at those points: Qt's text
layout breaks there at a line end, draws the hyphen only then, and shows
nothing elsewhere. Only words in the list break (H-D4). Qt-free.
"""

from __future__ import annotations

import unicodedata
import threading
from dataclasses import dataclass, field
from pathlib import Path

import regex

from .spelling import HYPHENATED_WORDS_FILE, HyphenatedWordsData, load_hyphenated_words, normalize

SOFT_HYPHEN = "­"
# A word the way the spellcheck finds one (letters, marks, joined by an
# apostrophe or hyphen only when a letter follows).
_WORD_RE = regex.compile(r"[\p{L}\p{M}]+(?:['’\-‑‌‍](?=[\p{L}\p{M}])[\p{L}\p{M}]*)*")
_HYPHENS = ("-", "‐", "‑")


@dataclass(slots=True)
class HyphenationRules:
    """One project's hyphenation: where each listed word breaks, and which
    paragraph markers the list says are hyphenated.

    Instances are compared by identity (a projection is cached per rules
    object), and made once per loaded list (`rules_for`)."""

    breaks: dict[str, tuple[int, ...]]
    markers: frozenset[str] | None  # `HyphenatedMarkers`; None when the file has no such line
    _memo: dict[str, tuple[int, ...]] = field(default_factory=dict, repr=False)

    __hash__ = object.__hash__
    __eq__ = object.__eq__  # type: ignore[assignment]

    def marker_hyphenates(self, marker: str, text_type: str | None) -> bool:
        """The default for a paragraph marker, when no stylesheet says
        `\\Hyphenate` (H-D3): the file's marker list, otherwise every
        paragraph of verse text."""

        if self.markers is not None:
            return marker in self.markers
        return (text_type or "").lower() == "versetext"

    def break_points(self, word: str) -> tuple[int, ...]:
        """Offsets in `word` (as written) where it may break, ascending;
        empty for a word the list doesn't have."""

        found = self._memo.get(word)
        if found is None:
            found = self._memo[word] = self._compute(word)
        return found

    def _compute(self, word: str) -> tuple[int, ...]:
        if unicodedata.normalize("NFC", word) != word:
            return ()  # offsets in the normalized form wouldn't line up
        key = normalize(word)
        if len(key) != len(word):
            return ()  # case folding changed the length (ß → ss)
        whole = self.breaks.get(key)
        if whole is not None:
            return whole
        points: list[int] = []
        offset = 0
        parts = _split_hyphens(word)
        if len(parts) < 2:
            return ()
        for part in parts:
            if part not in _HYPHENS:
                part_key = normalize(part)
                if len(part_key) == len(part):
                    points.extend(offset + point for point in self.breaks.get(part_key, ()))
            offset += len(part)
        return tuple(points)

    def points(self, text: str) -> list[int]:
        """Every offset in `text` where a soft hyphen may go, ascending."""

        result: list[int] = []
        for match in _WORD_RE.finditer(text):
            if len(match.group()) < 4:
                continue
            for point in self.break_points(match.group()):
                result.append(match.start() + point)
        return result


def _split_hyphens(word: str) -> list[str]:
    parts: list[str] = []
    current: list[str] = []
    for char in word:
        if char in _HYPHENS:
            if current:
                parts.append("".join(current))
                current = []
            parts.append(char)
        else:
            current.append(char)
    if current:
        parts.append("".join(current))
    return parts


def _parse_breaks(data: HyphenatedWordsData) -> dict[str, tuple[int, ...]]:
    soft = data.settings.get("SoftHyphen") or "="
    breaks: dict[str, tuple[int, ...]] = {}
    for key, line in data.words.items():
        points: list[int] = []
        index = 0
        for char in line:
            if char == soft:
                if 0 < index:
                    points.append(index)
            else:
                index += 1
        if points and points[-1] >= index:
            points.pop()
        if points:
            breaks[key] = tuple(points)
    return breaks


def rules_for(data: HyphenatedWordsData | None) -> HyphenationRules | None:
    """The rules of a loaded list; None without a list. Built once per
    loaded `HyphenatedWordsData` and kept on it."""

    if data is None:
        return None
    rules = data.rules
    if rules is None:
        listed = data.settings.get("HyphenatedMarkers")
        rules = data.rules = HyphenationRules(
            _parse_breaks(data), frozenset(listed.split()) if listed is not None else None
        )
    return rules


_CACHE: dict[str, tuple[tuple[int, int] | None, HyphenationRules | None]] = {}
_CACHE_LOCK = threading.Lock()


def _stamp(path: Path) -> tuple[int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size)


def has_hyphenation_list(folder: Path) -> bool:
    return (Path(folder) / HYPHENATED_WORDS_FILE).is_file()


def hyphenation_rules_for(folder: Path) -> HyphenationRules | None:
    """The project's rules, read from `hyphenatedWords.txt` and cached per
    folder; read again when the file's modification time or size changed
    (Paratext's Send/Receive can rewrite it). None without a readable list.
    The same object is returned until then, so a projection cached with it
    stays valid."""

    path = Path(folder) / HYPHENATED_WORDS_FILE
    key = str(path)
    stamp = _stamp(path)
    with _CACHE_LOCK:
        cached = _CACHE.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    rules = rules_for(load_hyphenated_words(path)) if stamp is not None else None
    with _CACHE_LOCK:
        _CACHE[key] = (stamp, rules)
    return rules


__all__ = ["HyphenationRules", "SOFT_HYPHEN", "has_hyphenation_list", "hyphenation_rules_for", "rules_for"]
