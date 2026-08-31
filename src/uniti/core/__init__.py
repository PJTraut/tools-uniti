"""Qt-independent UNITI text-engine primitives."""

from .byte_source import ByteSource
from .decoder import DecodeError, DecodedSpan, decode_span
from .encoding import EncodingInfo, detect_encoding

__all__ = [
    "ByteSource",
    "DecodeError",
    "DecodedSpan",
    "EncodingInfo",
    "decode_span",
    "detect_encoding",
]
