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
