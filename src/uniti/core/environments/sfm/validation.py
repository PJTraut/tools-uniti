"""Shared generic-SFM structural checks (ADR-0013, Phases E5/E6).

Factored out of `sfm_environment.py` so `usfm_environment.py` (Phase E6)
reuses the exact same lexical check rather than a second, potentially
drifting copy — USFM is generic SFM plus more, not a different syntax.
"""

from __future__ import annotations

from uniti.core.environment_findings import EnvironmentFinding, FindingSeverity

from .markers import is_closing, is_milestone, is_milestone_close
from .tokenizer import tokenize_sfm
from .tokens import SfmTokenKind


def unmatched_end_marker_findings(text: str) -> tuple[EnvironmentFinding, ...]:
    """Flag an end marker (`\\xyz*`) with no matching open marker anywhere.

    Does **not** flag an unclosed open marker — in SFM (generic or USFM) an
    unclosed `\\p`/`\\v`/`\\c` is the overwhelmingly normal case, not a
    defect, since USFM only assigns `EndMarker`s to character-style markers.
    """

    findings: list[EnvironmentFinding] = []
    open_markers: list[str] = []
    for token in tokenize_sfm(text):
        if token.kind is not SfmTokenKind.MARKER:
            continue
        if is_milestone(token.text) or is_milestone_close(token.text):
            continue  # milestones close themselves with `\*`
        if not is_closing(token.text):
            open_markers.append(token.text)
            continue
        base = token.text[:-1]
        match_index = next(
            (i for i in range(len(open_markers) - 1, -1, -1) if open_markers[i] == base),
            None,
        )
        if match_index is None:
            findings.append(
                EnvironmentFinding(
                    token.start,
                    token.end,
                    FindingSeverity.ERROR,
                    f"end marker {token.text!r} has no matching open marker",
                    code="sfm.end-marker-unmatched",
                )
            )
        else:
            del open_markers[match_index:]
    return tuple(findings)


__all__ = ["unmatched_end_marker_findings"]
