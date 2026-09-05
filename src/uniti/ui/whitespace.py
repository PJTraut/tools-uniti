"""Qt-free grammar for display-only whitespace markers."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from enum import StrEnum
import unicodedata


class WhitespaceMode(StrEnum):
    OFF = "off"
    EOL = "eol"
    SPACES_TABS = "spaces_tabs"
    INVISIBLE_UNICODE = "invisible_unicode"
    ALL = "all"


class WhitespaceKind(StrEnum):
    SPACE = "space"
    TAB = "tab"
    INVISIBLE = "invisible"


@dataclass(frozen=True, slots=True)
class WhitespaceMarker:
    index: int
    kind: WhitespaceKind
    label: str


_KNOWN_LABELS = {
    "\u00a0": "NBSP",
    "\u202f": "NNBSP",
    "\u200b": "ZWSP",
    "\u200c": "ZWNJ",
    "\u200d": "ZWJ",
    "\u2060": "WJ",
    "\ufeff": "BOM",
}


def parse_whitespace_mode(value: object) -> WhitespaceMode:
    if isinstance(value, WhitespaceMode):
        return value
    if not isinstance(value, str):
        raise TypeError("whitespace mode must be a string or WhitespaceMode")
    try:
        return WhitespaceMode(value)
    except ValueError as exc:
        raise ValueError(f"unsupported whitespace mode: {value}") from exc


def _is_invisible_unicode(character: str) -> bool:
    return character not in {" ", "\t", "\r", "\n"} and (
        character.isspace() or unicodedata.category(character) == "Cf"
    )


def iter_character_markers(
    text: str,
    mode: WhitespaceMode,
) -> Iterator[WhitespaceMarker]:
    if not isinstance(text, str):
        raise TypeError("marker text must be a string")
    selected = parse_whitespace_mode(mode)
    show_ascii = selected in {WhitespaceMode.SPACES_TABS, WhitespaceMode.ALL}
    show_unicode = selected in {
        WhitespaceMode.INVISIBLE_UNICODE,
        WhitespaceMode.ALL,
    }
    if not show_ascii and not show_unicode:
        return
    for index, character in enumerate(text):
        if show_ascii and character == " ":
            yield WhitespaceMarker(index, WhitespaceKind.SPACE, "SPACE")
        elif show_ascii and character == "\t":
            yield WhitespaceMarker(index, WhitespaceKind.TAB, "TAB")
        elif show_unicode and _is_invisible_unicode(character):
            label = _KNOWN_LABELS.get(character, f"U+{ord(character):04X}")
            yield WhitespaceMarker(index, WhitespaceKind.INVISIBLE, label)


def shows_eol(mode: WhitespaceMode) -> bool:
    return parse_whitespace_mode(mode) in {WhitespaceMode.EOL, WhitespaceMode.ALL}


__all__ = [
    "WhitespaceKind",
    "WhitespaceMarker",
    "WhitespaceMode",
    "iter_character_markers",
    "parse_whitespace_mode",
    "shows_eol",
]
