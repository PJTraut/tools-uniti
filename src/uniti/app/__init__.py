"""Application-layer controllers for UNITI with cycle-safe lazy exports."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "DocumentEntry": (".document_registry", "DocumentEntry"),
    "DocumentRegistry": (".document_registry", "DocumentRegistry"),
    "DuplicateDocumentError": (".document_registry", "DuplicateDocumentError"),
    "EditorState": (".editor_state", "EditorState"),
    "EditorStateSnapshot": (".editor_state", "EditorStateSnapshot"),
    "QuitChoice": (".service", "QuitChoice"),
    "QuitDecision": (".service", "QuitDecision"),
    "QuitPlan": (".service", "QuitPlan"),
    "UNITIService": (".service", "UNITIService"),
    "WindowManager": (".window_manager", "WindowManager"),
}


def __getattr__(name: str):
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name, __name__), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))

__all__ = [
    "DocumentEntry",
    "DocumentRegistry",
    "DuplicateDocumentError",
    "EditorState",
    "EditorStateSnapshot",
    "QuitChoice",
    "QuitDecision",
    "QuitPlan",
    "UNITIService",
    "WindowManager",
]
