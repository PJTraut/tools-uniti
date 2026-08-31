"""Qt-independent UNITI text-engine primitives."""

from .byte_source import ByteSource
from .decoder import DecodeError, DecodedSpan, decode_span
from .encoding import EncodingInfo, detect_encoding
from .eol import EOLReport, analyze_eol
from .streaming import atomic_copy_source

__all__ = [
    "ByteSource",
    "DecodeError",
    "DecodedSpan",
    "EncodingInfo",
    "EOLReport",
    "decode_span",
    "analyze_eol",
    "atomic_copy_source",
    "detect_encoding",
]
