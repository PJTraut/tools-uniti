"""The generic-SFM source tree's node shape (Phase E5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SfmNodeKind(StrEnum):
    DOCUMENT = "document"
    TEXT = "text"
    MARKER = "marker"
    CHARACTER = "character"


@dataclass(frozen=True, slots=True)
class SfmNode:
    """One node of the lossless SFM overlay tree.

    This is an overlay over the canonical source, not a replacement
    serialization (ADR-0013 decision 6): `start`/`end` are source offsets,
    and nothing here is ever written back — see `parser.py`'s docstring for
    what `MARKER` vs. `CHARACTER` means.
    """

    kind: SfmNodeKind
    start: int
    end: int
    marker: str | None = None
    children: tuple["SfmNode", ...] = ()
