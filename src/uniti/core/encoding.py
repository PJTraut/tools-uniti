"""Encoding metadata and first-pass detection for UNITI."""

from __future__ import annotations

from dataclasses import dataclass

from .byte_source import ByteSource


@dataclass(frozen=True, slots=True)
class EncodingInfo:
    detected: str
    confidence: float
    bom: bytes | None
    user_override: bool = False
    output_encoding: str | None = None
    alternatives: tuple[str, ...] = ()


_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xff\xfe", "utf-16-le"),
)


def _samples(source: ByteSource, sample_size: int) -> tuple[bytes, ...]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if source.size == 0:
        return (b"",)
    if source.size <= sample_size * 3:
        return (source.read(0, source.size),)

    starts = (0, max(0, source.size // 2 - sample_size // 2), source.size - sample_size)
    return tuple(source.read(start, min(sample_size, source.size - start)) for start in starts)


def _utf16_structural_guess(sample: bytes) -> str | None:
    if len(sample) < 8:
        return None
    usable = sample[: len(sample) - (len(sample) % 2)]
    even = usable[0::2]
    odd = usable[1::2]
    if not even or not odd:
        return None

    even_zero = even.count(0) / len(even)
    odd_zero = odd.count(0) / len(odd)
    if odd_zero >= 0.60 and even_zero <= 0.10:
        return "utf-16-le"
    if even_zero >= 0.60 and odd_zero <= 0.10:
        return "utf-16-be"
    return None


def detect_encoding(source: ByteSource, sample_size: int = 65_536) -> EncodingInfo:
    """Return deterministic first-pass encoding metadata from bounded samples."""

    prefix = source.read(0, min(source.size, 4))
    for bom, encoding in _BOMS:
        if prefix.startswith(bom):
            return EncodingInfo(encoding, 1.0, bom)

    samples = _samples(source, sample_size)
    utf16_guess = _utf16_structural_guess(samples[0])
    if utf16_guess is not None:
        return EncodingInfo(utf16_guess, 0.78, None)

    try:
        for sample in samples:
            sample.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return EncodingInfo(
            "windows-1252",
            0.35,
            None,
            alternatives=("iso-8859-1",),
        )

    return EncodingInfo("utf-8", 0.97, None)
