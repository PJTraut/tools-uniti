"""Application-layer controllers for UNITI."""

from .document_registry import (
    DocumentEntry,
    DocumentRegistry,
    DuplicateDocumentError,
)
from .editor_state import EditorState
from .service import QuitChoice, QuitDecision, QuitPlan, UNITIService
from .window_manager import WindowManager

__all__ = [
    "DocumentEntry",
    "DocumentRegistry",
    "DuplicateDocumentError",
    "EditorState",
    "QuitChoice",
    "QuitDecision",
    "QuitPlan",
    "UNITIService",
    "WindowManager",
]
