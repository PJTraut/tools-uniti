"""Qt-independent UNITI text-engine primitives."""

from .byte_source import ByteSource
from .decoder import DecodeError, DecodedSpan, decode_span, iter_decoded_spans
from .encoding import EncodingAssessment, EncodingInfo, detect_encoding
from .file_identity import ExternalFileChangedError, FileIdentity
from .eol import EOLAnalysisCancelled, EOLReport, analyze_eol
from .offsets import OffsetCheckpoint, OffsetMapper
from .lines import LineIndex
from .document_lines import (
    DocumentLineIndex,
    LineChunkDetail,
    LineChunkSummary,
    LineIndexBatch,
)
from .index_jobs import LineNavigationResult, build_line_index_batch
from .pieces import AnnotatedChunk, AnnotatedText, InvalidByteSpan, EditPiece, EditRef, EditStore, PieceTable, SourcePiece
from .document import Document, ReplacementPlanLimitError
from .save_job import (
    DocumentSaveRequest,
    PreparedDocumentSave,
    prepare_document_save,
)
from .snapshot import DocumentReadSnapshot, EditStoreSnapshot, PieceTableSnapshot
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
from .text_inspection import FormatPreview, TextFileInspection, inspect_source, preview_source

__all__ = [
    "ByteSource",
    "DecodeError",
    "DecodedSpan",
    "EncodingAssessment",
    "EncodingInfo",
    "EncodingProfile",
    "EOLPolicy",
    "OutputFormat",
    "FileIdentity",
    "ExternalFileChangedError",
    "EOLReport",
    "EOLAnalysisCancelled",
    "FormatPreview",
    "OffsetCheckpoint",
    "OffsetMapper",
    "LineIndex",
    "DocumentLineIndex",
    "LineChunkDetail",
    "LineChunkSummary",
    "LineIndexBatch",
    "LineNavigationResult",
    "AnnotatedText",
    "AnnotatedChunk",
    "InvalidByteSpan",
    "EditRef",
    "EditStore",
    "SourcePiece",
    "EditPiece",
    "PieceTable",
    "TextFileInspection",
    "Document",
    "DocumentSaveRequest",
    "PreparedDocumentSave",
    "ReplacementPlanLimitError",
    "DocumentReadSnapshot",
    "EditStoreSnapshot",
    "PieceTableSnapshot",
    "decode_span",
    "iter_decoded_spans",
    "build_line_index_batch",
    "analyze_eol",
    "atomic_copy_source",
    "detect_encoding",
    "encoding_profile",
    "encoding_profiles",
    "format_summary",
    "inspect_source",
    "profile_from_codec",
    "preview_source",
    "prepare_document_save",
]
