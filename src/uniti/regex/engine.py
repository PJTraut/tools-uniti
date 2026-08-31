"""Authoritative third-party regex compilation for UNITI."""

from __future__ import annotations

import regex


def compile_pattern(pattern: str, flags: int = 0) -> regex.Pattern:
    """Compile a Unicode text pattern with the pinned third-party regex engine."""
    if not isinstance(pattern, str):
        raise TypeError("UNITI regex patterns must be Unicode strings")
    return regex.compile(pattern, flags)
