"""Token types for the lossless generic-SFM tokenizer (Phase E5)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class SfmTokenKind(StrEnum):
    """The two kinds `tokenize_sfm` ever produces.

    Finer-grained kinds (whitespace vs. line-break vs. other text, the fuller
    list the external handover spec sketches) are deferred until a consumer
    actually needs the distinction — nothing in E5 (the source tree, the
    end-marker validator) does.
    """

    MARKER = "marker"
    TEXT = "text"


@dataclass(frozen=True, slots=True)
class SfmToken:
    """One token with its exact source span.

    `tokenize_sfm` guarantees tokens are contiguous and gap-free, so
    ``"".join(token.text for token in tokens) == source`` always holds —
    the lossless invariant this exists to preserve.
    """

    kind: SfmTokenKind
    start: int
    end: int
    text: str
