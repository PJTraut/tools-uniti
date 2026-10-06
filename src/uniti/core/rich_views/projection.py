"""Projections: a view text, its source map, and presentation (spec §31, §49).

Presentation is backend-neutral (spec §50): `BlockFormat`/`SpanFormat`
carry plain attribute maps (``bold``, ``italic``, ``font_size`` …) that a UI
renderer translates into its own toolkit's formats. Nothing here knows Qt.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

from .source_map import Segment, SegmentRole, SourceMap

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
class Projection:
    provider_key: str
    source_map: SourceMap
    blocks: tuple[BlockFormat, ...] = ()
    spans: tuple[SpanFormat, ...] = ()

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

    def text(self, source_end: int, source_text: str) -> Segment:
        """Verbatim source text up to `source_end` (`source_text` is that slice)."""

        if len(source_text) != source_end - self._source_position:
            raise ValueError("text segment length must match its source range")
        return self._add(SegmentRole.TEXT, source_end, source_text, None)

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

    def build(self, source_length: int) -> Projection:
        if self._source_position != source_length:
            raise ValueError("projection must cover the whole source")
        source_map = SourceMap(tuple(self._segments), "".join(self._view), source_length)
        return Projection(self.provider_key, source_map, tuple(self._blocks), tuple(self._spans))


def identity_projection(provider_key: str, source: str) -> Projection:
    builder = ProjectionBuilder(provider_key)
    builder.text(len(source), source)
    return builder.build(len(source))
