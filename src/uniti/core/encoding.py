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


@dataclass(frozen=True, slots=True)
class _Sample:
    start: int
    data: bytes


_BOMS: tuple[tuple[bytes, str], ...] = (
    (b"\x00\x00\xfe\xff", "utf-32-be"),
    (b"\xff\xfe\x00\x00", "utf-32-le"),
    (b"\xef\xbb\xbf", "utf-8-sig"),
    (b"\xfe\xff", "utf-16-be"),
    (b"\xff\xfe", "utf-16-le"),
)


def _samples(source: ByteSource, sample_size: int) -> tuple[_Sample, ...]:
    if sample_size <= 0:
        raise ValueError("sample_size must be positive")
    if source.size == 0:
        return (_Sample(0, b""),)
    if source.size <= sample_size * 3:
        return (_Sample(0, source.read(0, source.size)),)

    starts = (0, max(0, source.size // 2 - sample_size // 2), source.size - sample_size)
    return tuple(
        _Sample(start, source.read(start, min(sample_size, source.size - start)))
        for start in starts
    )


def _utf32_structural_guess(sample: bytes) -> str | None:
    if len(sample) < 16:
        return None
    usable = sample[: len(sample) - (len(sample) % 4)]
    lanes = tuple(usable[index::4] for index in range(4))
    if any(not lane for lane in lanes):
        return None

    zero_ratio = tuple(lane.count(0) / len(lane) for lane in lanes)
    if (
        zero_ratio[1] >= 0.60
        and zero_ratio[2] >= 0.60
        and zero_ratio[3] >= 0.60
        and zero_ratio[0] <= 0.50
    ):
        return "utf-32-le"
    if (
        zero_ratio[0] >= 0.60
        and zero_ratio[1] >= 0.60
        and zero_ratio[2] >= 0.60
        and zero_ratio[3] <= 0.50
    ):
        return "utf-32-be"
    return None


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


def _valid_utf8_sample(sample: _Sample, source_size: int) -> bool:
    """Strictly validate a sample while ignoring only cut code points at edges."""

    data = sample.data
    if sample.start > 0:
        trim = 0
        while trim < min(3, len(data)) and data[trim] & 0xC0 == 0x80:
            trim += 1
        data = data[trim:]

    allow_trailing_partial = sample.start + len(sample.data) < source_size
    while True:
        try:
            data.decode("utf-8", errors="strict")
            return True
        except UnicodeDecodeError as exc:
            if (
                allow_trailing_partial
                and exc.reason == "unexpected end of data"
                and exc.end == len(data)
            ):
                data = data[: exc.start]
                continue
            return False



def matching_bom(source: ByteSource, encoding: str) -> bytes | None:
    """Return a BOM only when it matches the explicitly selected codec."""

    normalized = encoding.lower().replace("_", "-")
    aliases = {
        "utf-8": "utf-8-sig",
        "utf8": "utf-8-sig",
        "utf-8-sig": "utf-8-sig",
        "utf-16-le": "utf-16-le",
        "utf-16-be": "utf-16-be",
        "utf-32-le": "utf-32-le",
        "utf-32-be": "utf-32-be",
    }
    expected = aliases.get(normalized)
    if expected is None:
        return None
    prefix = source.read(0, min(source.size, 4))
    for bom, codec in _BOMS:
        if codec == expected and prefix.startswith(bom):
            return bom
    return None

def detect_encoding(source: ByteSource, sample_size: int = 65_536) -> EncodingInfo:
    """Return deterministic first-pass encoding metadata from bounded samples."""

    prefix = source.read(0, min(source.size, 4))
    for bom, encoding in _BOMS:
        if prefix.startswith(bom):
            return EncodingInfo(encoding, 1.0, bom)

    samples = _samples(source, sample_size)
    utf32_guess = _utf32_structural_guess(samples[0].data)
    if utf32_guess is not None:
        return EncodingInfo(utf32_guess, 0.82, None)

    utf16_guess = _utf16_structural_guess(samples[0].data)
    if utf16_guess is not None:
        return EncodingInfo(utf16_guess, 0.78, None)

    if all(_valid_utf8_sample(sample, source.size) for sample in samples):
        return EncodingInfo("utf-8", 0.97, None)

    return EncodingInfo(
        "windows-1252",
        0.35,
        None,
        alternatives=("iso-8859-1",),
    )
