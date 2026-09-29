"""Decoration-provider seam for environments (ADR-0013, Phase E1).

Wraps the existing `syntax_profiles.py` tokenizer system rather than
duplicating or reshaping it — that system (BF-027/BF-041, extended BF-071/
BF-063) is already the bounded, per-logical-line, stateful tokenizer this
seam needs. Every existing `SyntaxProfile` becomes a `DecorationProvider`
through `SyntaxProfileDecorationAdapter`. `profile_for_extension`,
`PROFILES_BY_KEY`, and `Settings.syntax_extension_overrides` remain the one
resolution path shared by both the pre-existing per-view manual override
(View > Syntax Profile) and the new per-document environment default.
"""

from __future__ import annotations

from typing import Protocol

from .syntax_profiles import SyntaxProfile, SyntaxToken


class DecorationProvider(Protocol):
    """Tokenizes one logical line, threading opaque state across lines."""

    def tokenize(
        self,
        line: str,
        state: object,
    ) -> tuple[tuple[SyntaxToken, ...], object]: ...


class SyntaxProfileDecorationAdapter:
    """Adapts an existing `SyntaxProfile` to the `DecorationProvider` seam."""

    def __init__(self, profile: SyntaxProfile) -> None:
        self._profile = profile

    @property
    def key(self) -> str:
        return self._profile.key

    @property
    def initial_state(self) -> object:
        return self._profile.initial_state

    def tokenize(
        self,
        line: str,
        state: object,
    ) -> tuple[tuple[SyntaxToken, ...], object]:
        return self._profile.tokenize(line, state)
