"""Bounded encoding preview with independent streaming EOL inspection."""

from __future__ import annotations

from dataclasses import dataclass

from .byte_source import ByteSource
from .decoder import DecodeError, iter_decoded_spans
from .encoding import (
    SERIOUS_CONFIDENCE_THRESHOLD,
    EncodingAssessment,
    EncodingInfo,
    detect_encoding,
)
from .eol import EOLReport, analyze_eol
from .text_format import EncodingProfile, encoding_profiles, profile_from_codec


@dataclass(frozen=True, slots=True)
class FormatPreview:
    text: str
    invalid_bytes: tuple[DecodeError, ...]
    truncated: bool


@dataclass(frozen=True, slots=True)
class TextFileInspection:
    encoding: EncodingAssessment
    eol: EOLReport


def _observed_bom(source: ByteSource) -> bytes:
    prefix = source.read(0, min(4, source.size))
    ordered = sorted(encoding_profiles(), key=lambda item: len(item.bom), reverse=True)
    for profile in ordered:
        if profile.bom and prefix.startswith(profile.bom):
            return profile.bom
    return b""


def preview_source(
    source: ByteSource,
    profile: EncodingProfile,
    *,
    max_bytes: int = 65_536,
) -> FormatPreview:
    """Decode at most one safe bounded span under an exact profile."""

    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    prefix = source.read(0, min(len(profile.bom), source.size))
    content_start = len(profile.bom) if profile.bom and prefix == profile.bom else 0
    if content_start >= source.size:
        return FormatPreview("", (), False)

    spans = iter_decoded_spans(
        source,
        profile.codec,
        start=content_start,
        end=source.size,
        chunk_size=max_bytes,
    )
    span = next(spans)
    return FormatPreview(
        text=span.text,
        invalid_bytes=span.errors,
        truncated=span.byte_end < source.size,
    )


def _profile_alternatives(info: EncodingInfo) -> tuple[EncodingProfile, ...]:
    alternatives: list[EncodingProfile] = []
    for codec in info.alternatives:
        try:
            profile = profile_from_codec(codec)
        except ValueError:
            continue
        if profile not in alternatives:
            alternatives.append(profile)
    return tuple(alternatives)


def inspect_source(
    source: ByteSource,
    *,
    override: EncodingProfile | None = None,
    sample_bytes: int = 65_536,
) -> TextFileInspection:
    """Return separate encoding-severity and line-ending reports."""

    if sample_bytes <= 0:
        raise ValueError("sample_bytes must be positive")

    if override is None:
        info = detect_encoding(source, sample_size=sample_bytes)
        profile = profile_from_codec(info.detected, info.bom)
        confidence = info.confidence
        alternatives = _profile_alternatives(info)
    else:
        info = EncodingInfo(
            detected=override.codec,
            confidence=1.0,
            bom=override.bom or None,
            user_override=True,
            output_encoding=override.codec,
        )
        profile = override
        confidence = 1.0
        alternatives = ()

    preview = preview_source(source, profile, max_bytes=sample_bytes)
    observed_bom = _observed_bom(source)
    contradictory = observed_bom != profile.bom

    reasons: list[str] = []
    if override is not None:
        reasons.append(f"User selected {profile.label}.")
    elif info.bom:
        reasons.append(f"A matching {profile.label} marker was found.")
    elif confidence < SERIOUS_CONFIDENCE_THRESHOLD:
        reasons.append(
            f"Encoding confidence {confidence:.0%} is below "
            f"{SERIOUS_CONFIDENCE_THRESHOLD:.0%}."
        )
    else:
        reasons.append(f"Detection confidence is {confidence:.0%}.")
    if contradictory:
        observed = observed_bom.hex(" ") if observed_bom else "no BOM"
        expected = profile.bom.hex(" ") if profile.bom else "no BOM"
        reasons.append(
            f"BOM evidence is contradictory: found {observed}, expected {expected}."
        )
    if preview.invalid_bytes:
        reasons.append("The preview contains malformed byte sequences.")

    requires_confirmation = (
        confidence < SERIOUS_CONFIDENCE_THRESHOLD
        or contradictory
        or bool(preview.invalid_bytes)
    )
    assessment = EncodingAssessment(
        suggested=profile,
        confidence=confidence,
        alternatives=alternatives,
        reasons=tuple(reasons),
        contradictory=contradictory,
        malformed_preview=preview.invalid_bytes,
        requires_confirmation=requires_confirmation,
    )
    eol = analyze_eol(source, encoding=profile.codec)
    return TextFileInspection(encoding=assessment, eol=eol)
