"""Bounded decoding and local byte/character mapping."""

from __future__ import annotations

import codecs
import threading
from dataclasses import dataclass

from .byte_source import ByteSource


_ERROR_HANDLER_NAME = "uniti-preserve-decode-bytes-v1"
_ERROR_SENTINEL = "\udc00"
_ERROR_CONTEXT = threading.local()


@dataclass(frozen=True, slots=True)
class _DecodeEvent:
    start: int
    end: int
    raw: bytes


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


def _preserve_decode_error(exc: UnicodeError) -> tuple[str, int]:
    if not isinstance(exc, UnicodeDecodeError):
        raise exc

    stack = getattr(_ERROR_CONTEXT, "stack", None)
    if not stack:
        raise exc

    raw = bytes(exc.object[exc.start : exc.end])
    stack[-1].append(_DecodeEvent(exc.start, exc.end, raw))
    return _ERROR_SENTINEL, exc.end


codecs.register_error(_ERROR_HANDLER_NAME, _preserve_decode_error)


def _decode_preserving(payload: bytes, encoding: str) -> tuple[str, tuple[_DecodeEvent, ...]]:
    events: list[_DecodeEvent] = []
    stack = getattr(_ERROR_CONTEXT, "stack", None)
    if stack is None:
        stack = []
        _ERROR_CONTEXT.stack = stack

    stack.append(events)
    try:
        decoded = payload.decode(encoding, errors=_ERROR_HANDLER_NAME)
    finally:
        stack.pop()
    return decoded, tuple(events)


def _decode_payload(
    raw: bytes,
    start: int,
    encoding: str,
) -> tuple[str, int, str, tuple[_DecodeEvent, ...]]:
    normalized = encoding.lower().replace("_", "-")
    bom_rules: dict[str, tuple[bytes, str]] = {
        "utf-8-sig": (b"\xef\xbb\xbf", "utf-8"),
        "utf-16-le": (b"\xff\xfe", "utf-16-le"),
        "utf-16-be": (b"\xfe\xff", "utf-16-be"),
        "utf-32-le": (b"\xff\xfe\x00\x00", "utf-32-le"),
        "utf-32-be": (b"\x00\x00\xfe\xff", "utf-32-be"),
    }

    if normalized in bom_rules:
        bom, roundtrip_encoding = bom_rules[normalized]
        if start == 0 and raw.startswith(bom):
            decoded, events = _decode_preserving(raw[len(bom) :], roundtrip_encoding)
            return decoded, len(bom), roundtrip_encoding, events
        if normalized == "utf-8-sig":
            decoded, events = _decode_preserving(raw, "utf-8")
            return decoded, 0, "utf-8", events

    decoded, events = _decode_preserving(raw, encoding)
    return decoded, 0, encoding, events


def decode_span(
    source: ByteSource,
    start: int,
    length: int,
    encoding: str,
) -> DecodedSpan:
    """Decode one bounded source range without discarding undecodable bytes."""

    raw = source.read(start, length)
    decoded, prefix_length, roundtrip_encoding, decode_events = _decode_payload(
        raw, start, encoding
    )

    display: list[str] = []
    errors: list[DecodeError] = []
    boundaries = [prefix_length]
    byte_count = prefix_length
    event_index = 0

    for char in decoded:
        if char == _ERROR_SENTINEL:
            if event_index >= len(decode_events):
                raise UnicodeError("decoder emitted an untracked UNITI error sentinel")
            event = decode_events[event_index]
            event_index += 1
            event_start = prefix_length + event.start
            event_end = prefix_length + event.end
            if byte_count != event_start:
                raise UnicodeError(
                    f"codec {encoding!r} produced unstable byte boundaries before decode error"
                )
            errors.append(
                DecodeError(
                    byte_start=start + event_start,
                    byte_end=start + event_end,
                    raw=event.raw,
                )
            )
            display.append("\ufffd")
            byte_count = event_end
            boundaries.append(byte_count)
            continue

        encoded = char.encode(roundtrip_encoding, errors="strict")
        byte_count += len(encoded)
        display.append(char)
        boundaries.append(byte_count)

    if event_index != len(decode_events):
        raise UnicodeError("decoder recorded an error span without emitting its sentinel")
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


def _normalized_encoding(encoding: str) -> str:
    return encoding.lower().replace("_", "-")


def _utf8_sequence_length(first: int) -> int | None:
    if first < 0x80:
        return 1
    if 0xC2 <= first <= 0xDF:
        return 2
    if 0xE0 <= first <= 0xEF:
        return 3
    if 0xF0 <= first <= 0xF4:
        return 4
    return None


def _utf8_safe_end(source: ByteSource, start: int, candidate: int, end: int) -> int:
    if candidate >= end:
        return end
    tail_start = max(start, candidate - 4)
    tail = source.read(tail_start, candidate - tail_start)
    if not tail:
        return candidate

    lead_index = len(tail) - 1
    while lead_index >= 0 and tail[lead_index] & 0xC0 == 0x80:
        lead_index -= 1

    if lead_index < 0:
        return candidate

    needed = _utf8_sequence_length(tail[lead_index])
    if needed is None:
        return candidate
    lead_offset = tail_start + lead_index
    if lead_offset + needed > candidate:
        safe = lead_offset
    else:
        safe = candidate

    if safe > start:
        return safe

    first = source.read(start, 1)[0]
    needed = _utf8_sequence_length(first) or 1
    return min(end, start + needed)


def _utf16_safe_end(
    source: ByteSource,
    start: int,
    candidate: int,
    end: int,
    *,
    byteorder: str,
) -> int:
    if candidate >= end:
        return end
    safe = candidate - (candidate % 2)
    if safe <= start:
        safe = min(end, start + 2)
    if safe <= start or safe >= end or safe < 2 or safe + 2 > end:
        return safe

    previous = int.from_bytes(source.read(safe - 2, 2), byteorder)
    following = int.from_bytes(source.read(safe, 2), byteorder)
    if 0xD800 <= previous <= 0xDBFF and 0xDC00 <= following <= 0xDFFF:
        if safe - 2 > start:
            return safe - 2
        return min(end, safe + 2)
    return safe


def _safe_chunk_end(
    source: ByteSource,
    start: int,
    candidate: int,
    end: int,
    encoding: str,
) -> int:
    normalized = _normalized_encoding(encoding)
    if normalized in {"utf-8", "utf-8-sig"}:
        return _utf8_safe_end(source, start, candidate, end)
    if normalized == "utf-16-le":
        return _utf16_safe_end(source, start, candidate, end, byteorder="little")
    if normalized == "utf-16-be":
        return _utf16_safe_end(source, start, candidate, end, byteorder="big")
    if normalized in {"utf-32-le", "utf-32-be"}:
        if candidate >= end:
            return end
        safe = candidate - (candidate % 4)
        if safe <= start:
            safe = min(end, start + 4)
        return safe
    return candidate


def iter_decoded_spans(
    source: ByteSource,
    encoding: str,
    *,
    start: int = 0,
    end: int | None = None,
    chunk_size: int = 65_536,
):
    """Yield bounded decoded spans without splitting supported characters."""

    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    stop = source.size if end is None else end
    if start < 0 or stop < start or stop > source.size:
        raise ValueError("invalid decoded span range")

    offset = start
    while offset < stop:
        candidate = min(stop, offset + chunk_size)
        safe_end = _safe_chunk_end(source, offset, candidate, stop, encoding)
        if safe_end <= offset:
            raise UnicodeError("unable to make progress to a safe decode boundary")
        yield decode_span(source, offset, safe_end - offset, encoding)
        offset = safe_end
