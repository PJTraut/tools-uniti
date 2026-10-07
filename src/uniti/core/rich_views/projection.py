"""Projections: a view text, its source map, and presentation (spec §31, §49).

Presentation is backend-neutral (spec §50): `BlockFormat`/`SpanFormat`
carry plain attribute maps (``bold``, ``italic``, ``font_size`` …) that a UI
renderer translates into its own toolkit's formats. Nothing here knows Qt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .source_map import EOL_MARKER, Segment, SegmentRole, SourceMap

# Recognized presentation attributes (all optional):
#   bold, italic, underline, superscript, smallcaps, monospace, muted,
#   marker_token  -> "yes"
#   font_scale    -> float as text, relative to the base font (1.0 = base)
#   color         -> "#rrggbb"
#   align         -> left | center | right | justify
#   left_margin, right_margin, first_indent -> inches as text
#   space_before, space_after               -> points as text
#   heading_level -> "1".."6"


@dataclass(frozen=True, slots=True)
class SpanFormat:
    view_start: int
    view_end: int
    attrs: Mapping[str, str]
    marker: str | None = None


@dataclass(frozen=True, slots=True)
class BlockFormat:
    """Paragraph-level formatting for the view lines in [view_start, view_end)."""

    view_start: int
    view_end: int
    attrs: Mapping[str, str]
    marker: str | None = None


@dataclass(frozen=True, slots=True)
class NoteSection:
    """An auxiliary projection shown below the main text (SFM Preview's notes frame).

    `projection` covers the whole source like any projection, with
    everything but this class's note bodies hidden, so a view position in
    it maps back to the note's source.
    """

    key: str  # note marker, e.g. "f", "x"
    label: str  # display label, plural, e.g. "Footnotes", "Cross References"
    projection: "Projection"


@dataclass(frozen=True, slots=True)
class Projection:
    provider_key: str
    source_map: SourceMap
    blocks: tuple[BlockFormat, ...] = ()
    spans: tuple[SpanFormat, ...] = ()
    notes: tuple[NoteSection, ...] = ()

    @property
    def text(self) -> str:
        return self.source_map.view_text


@dataclass
class ProjectionBuilder:
    """Accumulates segments in source order; enforces the gap-free invariant."""

    provider_key: str
    _segments: list[Segment] = field(default_factory=list)
    _view: list[str] = field(default_factory=list)
    _view_length: int = 0
    _source_position: int = 0
    _blocks: list[BlockFormat] = field(default_factory=list)
    _spans: list[SpanFormat] = field(default_factory=list)

    @property
    def view_position(self) -> int:
        return self._view_length

    @property
    def source_position(self) -> int:
        return self._source_position

    def _add(self, role: SegmentRole, source_end: int, view_text: str, marker: str | None) -> Segment:
        if source_end < self._source_position:
            raise ValueError("segments must advance through the source in order")
        segment = Segment(
            role,
            self._source_position,
            source_end,
            self._view_length,
            self._view_length + len(view_text),
            marker,
        )
        if segment.source_end == segment.source_start and segment.view_end == segment.view_start:
            return segment
        self._segments.append(segment)
        self._view.append(view_text)
        self._view_length = segment.view_end
        self._source_position = source_end
        return segment

    def text(self, source_end: int, source_text: str, *, line_break: str = "\n") -> Segment:
        """Source text up to `source_end` (`source_text` is that slice).

        Every line break (``\n``, ``\r\n`` or a lone ``\r``) is shown as
        the single character `line_break` — ``"\n"``, or ``" "`` where the
        view flows source lines into one paragraph. The ``\r`` of a CRLF
        becomes a zero-width hidden ``eol`` segment, so view text never
        holds a ``\r``: a UI text widget collapses ``\r\n`` to one
        paragraph break, which would shift every later view offset.
        """

        if len(source_text) != source_end - self._source_position:
            raise ValueError("text segment length must match its source range")
        if len(line_break) != 1:
            raise ValueError("line_break must be one character")
        if "\r" not in source_text and (line_break == "\n" or "\n" not in source_text):
            return self._add(SegmentRole.TEXT, source_end, source_text, None)
        position = self._source_position
        run: list[str] = []
        segment: Segment | None = None
        index = 0
        while index < len(source_text):
            char = source_text[index]
            if char == "\r" and index + 1 < len(source_text) and source_text[index + 1] == "\n":
                if run:
                    segment = self._add(SegmentRole.TEXT, position + index, "".join(run), None)
                    run = []
                segment = self._add(SegmentRole.HIDDEN, position + index + 1, "", EOL_MARKER)
                run.append(line_break)
                index += 2
                continue
            run.append(line_break if char in "\r\n" else char)
            index += 1
        if run:
            segment = self._add(SegmentRole.TEXT, source_end, "".join(run), None)
        assert segment is not None
        return segment

    def marker(self, source_end: int, label: str, marker: str | None = None) -> Segment:
        return self._add(SegmentRole.MARKER, source_end, label, marker)

    def hidden(self, source_end: int, marker: str | None = None) -> Segment:
        return self._add(SegmentRole.HIDDEN, source_end, "", marker)

    def generated(self, view_text: str, marker: str | None = None) -> Segment:
        return self._add(SegmentRole.GENERATED, self._source_position, view_text, marker)

    def span(self, view_start: int, view_end: int, attrs: Mapping[str, str], marker: str | None = None) -> None:
        if view_end > view_start and attrs:
            self._spans.append(SpanFormat(view_start, view_end, MappingProxyType(dict(attrs)), marker))

    def block(self, view_start: int, view_end: int, attrs: Mapping[str, str], marker: str | None = None) -> None:
        if attrs:
            self._blocks.append(BlockFormat(view_start, view_end, MappingProxyType(dict(attrs)), marker))

    def build(self, source_length: int, notes: tuple[NoteSection, ...] = ()) -> Projection:
        if self._source_position != source_length:
            raise ValueError("projection must cover the whole source")
        source_map = SourceMap(tuple(self._segments), "".join(self._view), source_length)
        return Projection(self.provider_key, source_map, tuple(self._blocks), tuple(self._spans), tuple(notes))


def identity_projection(provider_key: str, source: str) -> Projection:
    builder = ProjectionBuilder(provider_key)
    builder.text(len(source), source)
    return builder.build(len(source))
