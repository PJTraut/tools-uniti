"""Isolated file-type environment framework skeleton (ADR-0013, Phase E1).

Core owns the document. An environment sees only the restricted
`EnvironmentContext` below: it must never import `UNITIMainWindow`, never
reach a Qt widget or the piece table directly, and never persist anything
itself — Core owns open/save/recovery/undo unconditionally (see
ADR-0002/`core/document.py`). Environment activation failure must fall back
to `PlainEnvironment`; it must never leave a document unusable, and it must
never block save.

This module intentionally implements nothing beyond the contract and the
Plain fallback. Format-specific environments (JSON/XML/YAML in Phase E3/E4,
SFM/USFM/Markdown from Phase E5 onward) live under `core/environments/` and
build on this seam without changing it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .decoration import DecorationProvider, SyntaxProfileDecorationAdapter
from .document import Document
from .environment_edit import EnvironmentEditFacade
from .resource_profile import ResourceProfile
from .syntax_profiles import PLAIN_TEXT


@dataclass(frozen=True, slots=True)
class EnvironmentContext:
    """Everything an environment is allowed to see of one open document."""

    edits: EnvironmentEditFacade
    resource_profile: ResourceProfile

    @classmethod
    def for_document(cls, document: Document) -> "EnvironmentContext":
        return cls(
            edits=EnvironmentEditFacade(document),
            resource_profile=ResourceProfile(size_bytes=document.source.size),
        )


class Environment(Protocol):
    """One isolated file-type environment (Plain/Light/Rich)."""

    key: str

    def activate(self, context: EnvironmentContext) -> None: ...

    def deactivate(self) -> None: ...

    @property
    def decoration_provider(self) -> DecorationProvider | None: ...


class PlainEnvironment:
    """Always-available fallback: no enhanced behavior, never fails.

    Every enhanced environment must be able to deactivate back to this one
    (or fail activation straight into it) and leave the document unchanged
    and usable.
    """

    key = "plain_text"

    def __init__(self) -> None:
        self._decoration_provider = SyntaxProfileDecorationAdapter(PLAIN_TEXT)

    def activate(self, context: EnvironmentContext) -> None:
        del context

    def deactivate(self) -> None:
        pass

    @property
    def decoration_provider(self) -> DecorationProvider | None:
        return self._decoration_provider
