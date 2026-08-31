"""Bounded decoding and local byte/character mapping."""

from __future__ import annotations

from dataclasses import dataclass

from .byte_source import ByteSource


@dataclass(frozen=True, slots=True)
class DecodeError:
    """An undecodable source-byte range represented visibly as U+FFFD."""

    byte_start: int
    byte_end: int
    raw: bytes


@dataclass(frozen=True, slots=True)
class DecodedSpan:
    """A bounded decoded view that retains source-byte boundaries."""

    text: str
    byte_start: int
    byte_end: int
    encoding: str
    errors: tuple[DecodeError, ...]
    char_boundaries: tuple[int, ...]

    def byte_offset_for_char_boundary(self, char_boundary: int) -> int:
        if char_boundary < 0 or char_boundary >= len(self.char_boundaries):
            raise ValueError("character boundary is outside decoded span")
        return self.byte_start + self.char_boundaries[char_boundary]


def _decode_payload(raw: bytes, start: int, encoding: str) -> tuple[str, int, str]:
    normalized = encoding.lower().replace("_", "-")
    if normalized == "utf-8-sig":
        bom = b"\xef\xbb\xbf"
        if start == 0 and raw.startswith(bom):
            return raw[len(bom) :].decode("utf-8", errors="surrogateescape"), len(bom), "utf-8"
        return raw.decode("utf-8", errors="surrogateescape"), 0, "utf-8"
    return raw.decode(encoding, errors="surrogateescape"), 0, encoding


def decode_span(
    source: ByteSource,
    start: int,
    length: int,
    encoding: str,
) -> DecodedSpan:
    """Decode one bounded source range without discarding undecodable bytes."""

    raw = source.read(start, length)
    decoded, prefix_length, roundtrip_encoding = _decode_payload(raw, start, encoding)

    display: list[str] = []
    errors: list[DecodeError] = []
    boundaries = [prefix_length]
    byte_count = prefix_length

    for char in decoded:
        encoded = char.encode(roundtrip_encoding, errors="surrogateescape")
        width = len(encoded)
        if 0xDC80 <= ord(char) <= 0xDCFF:
            errors.append(
                DecodeError(
                    byte_start=start + byte_count,
                    byte_end=start + byte_count + width,
                    raw=encoded,
                )
            )
            display.append("\ufffd")
        else:
            display.append(char)
        byte_count += width
        boundaries.append(byte_count)

    if byte_count != len(raw):
        raise UnicodeError(
            f"codec {encoding!r} does not provide stable per-character byte boundaries"
        )

    return DecodedSpan(
        text="".join(display),
        byte_start=start,
        byte_end=start + length,
        encoding=encoding,
        errors=tuple(errors),
        char_boundaries=tuple(boundaries),
    )
