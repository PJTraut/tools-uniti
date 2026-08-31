"""Qt-independent UNITI text-engine primitives."""

from .byte_source import ByteSource
from .encoding import EncodingInfo, detect_encoding

__all__ = ["ByteSource", "EncodingInfo", "detect_encoding"]
