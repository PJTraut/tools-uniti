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
    "\u2003": "EMSP",
    "\u2002": "ENSP",
    "\u2009": "THINSP",
    "\u200a": "HAIRSP",
    "\u3000": "IDSP",
    "\u00a0": "NBSP",
    "\u202f": "NNBSP",
    "\u200b": "ZWSP",
    "\u200c": "ZWNJ",
    "\u200d": "ZWJ",
    "\u2060": "WJ",
    "\ufeff": "BOM",
    "\u200e": "LRM",
    "\u200f": "RLM",
}


def marker_detail(label: str) -> str:
    parts = []
    identities = {value: key for key, value in _KNOWN_LABELS.items()}
    identities.update({"SPACE": " ", "TAB": "\t", "LF": "\n", "CR": "\r", "CRLF": "\r\n"})
    for item in label.split(" / "):
        name, separator, count = item.partition("×")
        characters = identities.get(name)
        code = " ".join(f"U+{ord(c):04X}" for c in characters) if characters else ""
        detail = f"{name} {code}".strip()
        parts.append(detail + (f" ×{count}" if separator else ""))
    return " / ".join(parts)


def character_detail(character: str) -> str:
    aliases = {"\t": "CHARACTER TABULATION", "\n": "LINE FEED", "\r": "CARRIAGE RETURN"}
    name = aliases.get(character) or unicodedata.name(character, "<no Unicode name>")
    return f"U+{ord(character):04X} — {name}"


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
