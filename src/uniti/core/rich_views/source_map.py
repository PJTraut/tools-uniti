"""Bidirectional source map between canonical source and a view (spec §31).

A projection is a gap-free sequence of `Segment`s covering the whole source
in order. Each segment says how one source range appears in the view:

- `TEXT` — shown verbatim, 1:1 offsets, freely editable;
- `MARKER` — source syntax shown as a protected token (SFM Standard);
  its view text may differ from the source (``\\v`` shown as ``v``);
- `HIDDEN` — source syntax with no view text at all (SFM Preview);
- `GENERATED` — view text with no source (e.g. a paragraph break the
  view inserts before a paragraph marker it hides).

Positions are character offsets; view offsets index `SourceMap.view_text`.
"""

from __future__ import annotations

import bisect
from dataclasses import dataclass
from enum import StrEnum


# Marker of the zero-width HIDDEN segment holding the `\r` of a CRLF.
EOL_MARKER = "eol"


class SegmentRole(StrEnum):
    TEXT = "text"
    MARKER = "marker"
    HIDDEN = "hidden"
    GENERATED = "generated"


@dataclass(frozen=True, slots=True)
class Segment:
    role: SegmentRole
    source_start: int
    source_end: int
    view_start: int
    view_end: int
    marker: str | None = None

    @property
    def editable(self) -> bool:
        return self.role is SegmentRole.TEXT


class SourceMap:
    def __init__(self, segments: tuple[Segment, ...], view_text: str, source_length: int) -> None:
        self.segments = segments
        self.view_text = view_text
        self.source_length = source_length
        self._view_starts = [segment.view_start for segment in segments]
        self._source_starts = [segment.source_start for segment in segments]

    def check(self) -> None:
        """Assert the gap-free invariants (tests and debug builds)."""

        source = 0
        view = 0
        for segment in self.segments:
            assert segment.source_start == source, segment
            assert segment.view_start == view, segment
            assert segment.source_end >= segment.source_start
            assert segment.view_end >= segment.view_start
            if segment.role is SegmentRole.TEXT:
                assert segment.source_end - segment.source_start == segment.view_end - segment.view_start
                assert "\r" not in self.view_text[segment.view_start : segment.view_end]
            if segment.role is SegmentRole.HIDDEN:
                assert segment.view_end == segment.view_start
            if segment.role is SegmentRole.GENERATED:
                assert segment.source_end == segment.source_start
            source = segment.source_end
            view = segment.view_end
        assert source == self.source_length
        assert view == len(self.view_text)

    def source_to_view(self, offset: int) -> int:
        """Where source `offset` appears in the view (a caret position).

        An offset at the edge of editable text maps into that text; one
        inside protected/hidden syntax snaps to the syntax's view edge.
        """

        offset = max(0, min(offset, self.source_length))
        index = bisect.bisect_right(self._source_starts, offset) - 1
        for candidate in (index - 1, index, index + 1):
            if 0 <= candidate < len(self.segments):
                segment = self.segments[candidate]
                if segment.editable and segment.source_start <= offset <= segment.source_end:
                    return segment.view_start + (offset - segment.source_start)
        for candidate in (index, index - 1):
            if 0 <= candidate < len(self.segments):
                segment = self.segments[candidate]
                if segment.source_start <= offset < segment.source_end:
                    return segment.view_start if offset == segment.source_start else segment.view_end
        return len(self.view_text)

    def view_to_source(self, position: int, *, prefer_left: bool = True) -> int:
        """The source offset for view caret `position`.

        At a boundary between an editable segment and protected/hidden
        syntax, `prefer_left` keeps the caret inside the left text (typing
        at the end of a bold word stays bold), otherwise after the syntax.
        """

        position = max(0, min(position, len(self.view_text)))
        index = bisect.bisect_right(self._view_starts, position) - 1
        index = max(index, 0)
        if prefer_left:
            # Walk back over zero-width/ending segments to the editable one
            # that ends exactly here.
            probe = index
            while probe > 0 and self.segments[probe].view_start == position:
                previous = self.segments[probe - 1]
                if previous.view_end != position:
                    break
                probe -= 1
                if previous.editable:
                    return previous.source_end
        segment = self.segments[index] if self.segments else None
        if segment is None:
            return 0
        if segment.role is SegmentRole.TEXT:
            return segment.source_start + (position - segment.view_start)
        if position <= segment.view_start:
            return segment.source_start
        return segment.source_end

    def segments_in_view(self, start: int, end: int) -> tuple[Segment, ...]:
        """Segments overlapping view range [start, end) (zero-width included
        when strictly inside)."""

        result = []
        for segment in self.segments:
            if segment.view_end < start:
                continue
            if segment.view_start > end:
                break
            if segment.view_start == segment.view_end:
                if start < segment.view_start < end:
                    result.append(segment)
                continue
            if segment.view_end > start and segment.view_start < end:
                result.append(segment)
        return tuple(result)

    def hidden_eol_ending_at(self, offset: int) -> bool:
        """Whether source `offset` directly follows the hidden `\r` of a CRLF."""

        index = bisect.bisect_right(self._source_starts, offset - 1) - 1
        if not 0 <= index < len(self.segments):
            return False
        segment = self.segments[index]
        return (
            segment.role is SegmentRole.HIDDEN
            and segment.marker == EOL_MARKER
            and segment.source_end == offset
        )

    def segment_at_view(self, position: int) -> Segment | None:
        for segment in self.segments:
            if segment.view_start <= position < segment.view_end:
                return segment
        return None

    def view_selection_to_source(self, start: int, end: int) -> tuple[int, int]:
        if start > end:
            start, end = end, start
        return self.view_to_source(start, prefer_left=False), self.view_to_source(end, prefer_left=True)
