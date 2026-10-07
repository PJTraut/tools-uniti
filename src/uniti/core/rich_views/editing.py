"""Turn view-level edits into canonical source edits (spec §32).

A rich view never edits its own text and serializes it back. A keystroke
becomes a view-range replacement, this planner maps it through the
`SourceMap` to source replacements, and the host applies those through
`Document.replace_many` as one undoable step. Protected syntax (markers,
hidden markers, generated text) is never deleted by character-level
editing; removing or changing it is a semantic command's job.
"""

from __future__ import annotations

from dataclasses import dataclass

from .source_map import SegmentRole, SourceMap


@dataclass(frozen=True, slots=True)
class EditPlan:
    replacements: tuple[tuple[int, int, str], ...]
    caret_source: int


class EditRejected(Exception):
    """The edit would touch protected syntax only; `caret_view` is where the
    caret should move instead (e.g. Backspace stepping over a marker)."""

    def __init__(self, reason: str, caret_view: int | None = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.caret_view = caret_view


def plan_view_edit(source_map: SourceMap, view_start: int, view_end: int, text: str) -> EditPlan:
    """Plan replacing view range [view_start, view_end) with `text`."""

    if view_start > view_end:
        view_start, view_end = view_end, view_start
    if view_start == view_end:
        segment = source_map.segment_at_view(view_start)
        if segment is not None and not segment.editable and segment.view_start < view_start:
            raise EditRejected("cannot type inside a protected marker", segment.view_end)
        position = source_map.view_to_source(view_start, prefer_left=True)
        return EditPlan(((position, position, text),) if text else (), position + len(text))

    deletions: list[tuple[int, int]] = []
    for segment in source_map.segments_in_view(view_start, view_end):
        if segment.role is not SegmentRole.TEXT:
            continue
        start = max(view_start, segment.view_start)
        end = min(view_end, segment.view_end)
        if end <= start:
            continue
        source_start = segment.source_start + (start - segment.view_start)
        source_end = source_start + (end - start)
        if source_map.hidden_eol_ending_at(source_start):
            # Deleting the `\n` of a CRLF takes its hidden `\r` with it.
            source_start -= 1
        deletions.append((source_start, source_end))

    if not deletions:
        if text:
            position = source_map.view_to_source(view_start, prefer_left=False)
            return EditPlan(((position, position, text),), position + len(text))
        raise EditRejected("only protected syntax is selected")

    merged: list[list[int]] = []
    for start, end in deletions:
        if merged and merged[-1][1] == start:
            merged[-1][1] = end
        else:
            merged.append([start, end])
    replacements = [(start, end, "") for start, end in merged]
    first_start = merged[0][0]
    replacements[0] = (first_start, merged[0][1], text)
    return EditPlan(tuple(replacements), first_start + len(text))
