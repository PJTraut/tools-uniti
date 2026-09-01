"""Qt-independent UNITI text-engine primitives."""

from .byte_source import ByteSource
from .decoder import DecodeError, DecodedSpan, decode_span, iter_decoded_spans
from .encoding import EncodingInfo, detect_encoding
from .file_identity import ExternalFileChangedError, FileIdentity
from .eol import EOLReport, analyze_eol
from .offsets import OffsetCheckpoint, OffsetMapper
from .lines import LineIndex
from .pieces import AnnotatedText, InvalidByteSpan, EditPiece, EditRef, EditStore, PieceTable, SourcePiece
from .document import Document
from .streaming import atomic_copy_source
from .text_format import (
    EOLPolicy,
    EncodingProfile,
    OutputFormat,
    encoding_profile,
    encoding_profiles,
    format_summary,
    profile_from_codec,
)

__all__ = [
    "ByteSource",
    "DecodeError",
    "DecodedSpan",
    "EncodingInfo",
    "EncodingProfile",
    "EOLPolicy",
    "OutputFormat",
    "FileIdentity",
    "ExternalFileChangedError",
    "EOLReport",
    "OffsetCheckpoint",
    "OffsetMapper",
    "LineIndex",
    "AnnotatedText",
    "InvalidByteSpan",
    "EditRef",
    "EditStore",
    "SourcePiece",
    "EditPiece",
    "PieceTable",
    "Document",
    "decode_span",
    "iter_decoded_spans",
    "analyze_eol",
    "atomic_copy_source",
    "detect_encoding",
    "encoding_profile",
    "encoding_profiles",
    "format_summary",
    "profile_from_codec",
]
