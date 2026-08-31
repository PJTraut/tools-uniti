"""Qt-independent UNITI text-engine primitives."""

from .byte_source import ByteSource
from .decoder import DecodeError, DecodedSpan, decode_span
from .encoding import EncodingInfo, detect_encoding
from .eol import EOLReport, analyze_eol

__all__ = [
    "ByteSource",
    "DecodeError",
    "DecodedSpan",
    "EncodingInfo",
    "EOLReport",
    "decode_span",
    "analyze_eol",
    "detect_encoding",
]
