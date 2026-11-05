"""Qt-independent UNITI text-engine primitives."""

from .byte_source import ByteSource
from .decoder import DecodedSpan, DecodeError, decode_span, iter_decoded_spans
from .document import Document, ReplacementPlanLimitError
from .document_lines import (
    DocumentLineIndex,
    LineChunkDetail,
    LineChunkSummary,
    LineIndexBatch,
)
from .encoding import EncodingAssessment, EncodingInfo, detect_encoding
from .eol import EOLAnalysisCancelled, EOLReport, analyze_eol
from .file_identity import ExternalFileChangedError, FileIdentity
from .index_jobs import LineNavigationResult, build_line_index_batch
from .lines import LineIndex
from .offsets import OffsetCheckpoint, OffsetMapper
from .pieces import (
    AnnotatedChunk,
    AnnotatedText,
    EditPiece,
    EditRef,
    EditStore,
    InvalidByteSpan,
    PieceTable,
    SourcePiece,
)
from .save_job import (
    DocumentSaveRequest,
    PreparedDocumentSave,
    prepare_document_save,
)
from .snapshot import DocumentReadSnapshot, EditStoreSnapshot, PieceTableSnapshot
from .streaming import atomic_copy_source
from .text_format import (
    EncodingProfile,
    EOLPolicy,
    OutputFormat,
    encoding_profile,
    encoding_profiles,
    format_summary,
    profile_from_codec,
)
from .text_inspection import (
    FormatPreview,
    TextFileInspection,
    inspect_source,
    preview_source,
)

__all__ = [
    "AnnotatedChunk",
    "AnnotatedText",
    "ByteSource",
    "DecodeError",
    "DecodedSpan",
    "Document",
    "DocumentLineIndex",
    "DocumentReadSnapshot",
    "DocumentSaveRequest",
    "EOLAnalysisCancelled",
    "EOLPolicy",
    "EOLReport",
    "EditPiece",
    "EditRef",
    "EditStore",
    "EditStoreSnapshot",
    "EncodingAssessment",
    "EncodingInfo",
    "EncodingProfile",
    "ExternalFileChangedError",
    "FileIdentity",
    "FormatPreview",
    "InvalidByteSpan",
    "LineChunkDetail",
    "LineChunkSummary",
    "LineIndex",
    "LineIndexBatch",
    "LineNavigationResult",
    "OffsetCheckpoint",
    "OffsetMapper",
    "OutputFormat",
    "PieceTable",
    "PieceTableSnapshot",
    "PreparedDocumentSave",
    "ReplacementPlanLimitError",
    "SourcePiece",
    "TextFileInspection",
    "analyze_eol",
    "atomic_copy_source",
    "build_line_index_batch",
    "decode_span",
    "detect_encoding",
    "encoding_profile",
    "encoding_profiles",
    "format_summary",
    "inspect_source",
    "iter_decoded_spans",
    "prepare_document_save",
    "preview_source",
    "profile_from_codec",
]
