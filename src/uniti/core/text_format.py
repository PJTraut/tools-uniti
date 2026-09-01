"""Exact text-encoding profiles and independent line-ending policy."""

from __future__ import annotations

import codecs
from dataclasses import dataclass
from enum import StrEnum


class EOLPolicy(StrEnum):
    """Requested output treatment for logical line endings."""

    PRESERVE = "PRESERVE"
    LF = "LF"
    CRLF = "CRLF"
    CR = "CR"


@dataclass(frozen=True, slots=True)
class EncodingProfile:
    """An indivisible content codec, byte order, and BOM choice."""

    key: str
    label: str
    codec: str
    bom: bytes = b""


@dataclass(frozen=True, slots=True)
class OutputFormat:
    """The exact encoding and independent EOL policy selected for output."""

    encoding: EncodingProfile
    eol: EOLPolicy = EOLPolicy.PRESERVE


_PROFILES = (
    EncodingProfile("utf-8", "UTF-8", "utf-8"),
    EncodingProfile("utf-8-bom", "UTF-8 BOM", "utf-8", b"\xef\xbb\xbf"),
    EncodingProfile("windows-1252", "Windows-1252", "windows-1252"),
    EncodingProfile("utf-16-le", "UTF-16 LE", "utf-16-le"),
    EncodingProfile("utf-16-le-bom", "UTF-16 LE BOM", "utf-16-le", b"\xff\xfe"),
    EncodingProfile("utf-16-be", "UTF-16 BE", "utf-16-be"),
    EncodingProfile("utf-16-be-bom", "UTF-16 BE BOM", "utf-16-be", b"\xfe\xff"),
    EncodingProfile("utf-32-le", "UTF-32 LE", "utf-32-le"),
    EncodingProfile(
        "utf-32-le-bom",
        "UTF-32 LE BOM",
        "utf-32-le",
        b"\xff\xfe\x00\x00",
    ),
    EncodingProfile("utf-32-be", "UTF-32 BE", "utf-32-be"),
    EncodingProfile(
        "utf-32-be-bom",
        "UTF-32 BE BOM",
        "utf-32-be",
        b"\x00\x00\xfe\xff",
    ),
)

_BY_KEY = {profile.key: profile for profile in _PROFILES}


def _normalize_codec(codec: str) -> str:
    try:
        normalized = codecs.lookup(codec).name
    except LookupError as exc:
        raise ValueError(f"unsupported encoding codec: {codec}") from exc
    aliases = {
        "cp1252": "windows-1252",
        "utf-8-sig": "utf-8",
    }
    return aliases.get(normalized, normalized)


_BY_CODEC_AND_BOM = {
    (_normalize_codec(profile.codec), profile.bom): profile for profile in _PROFILES
}


def encoding_profiles() -> tuple[EncodingProfile, ...]:
    """Return profiles in their canonical presentation order."""

    return _PROFILES


def encoding_profile(key: str) -> EncodingProfile:
    """Resolve a canonical profile key."""

    try:
        return _BY_KEY[key.lower()]
    except KeyError as exc:
        raise ValueError(f"unknown encoding profile: {key}") from exc


def profile_from_codec(codec: str, bom: bytes | None = None) -> EncodingProfile:
    """Resolve an exact profile from a codec and observed BOM bytes."""

    normalized = _normalize_codec(codec)
    exact_bom = b"" if bom is None else bytes(bom)
    try:
        return _BY_CODEC_AND_BOM[(normalized, exact_bom)]
    except KeyError as exc:
        raise ValueError(
            f"unsupported codec/BOM combination: {codec}, {exact_bom.hex() or 'none'}"
        ) from exc


def format_summary(profile: EncodingProfile, eol: EOLPolicy | str) -> str:
    """Render encoding and EOL as separate dimensions in compact grammar."""

    eol_text = eol.value if isinstance(eol, EOLPolicy) else str(eol)
    if eol_text == EOLPolicy.PRESERVE.value:
        eol_text = "Preserve"
    return f"{profile.label}, {eol_text}"

