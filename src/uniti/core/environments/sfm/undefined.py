"""Undefined markup: markers no loaded stylesheet defines (round 2, R7).

"Undefined" means Standard and Preview can't style the marker: it is in
none of the layers they render with (official `usfm.sty`, the built-in and
your `uniti.sty`, the project's stylesheets, loaded stylesheets). Nested
`\\+name` and end markers count as `name`; a column-range cell (`\\th1-2`)
as its first column. Milestones (`\\qt-s`, `\\*`) are skipped: they mark
positions and never carry text to style. Qt-free.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from .markers import is_closing, is_milestone, is_milestone_close, marker_name
from .references import ReferenceMap
from .style_layers import LayeredStyleRegistry
from .tokenizer import tokenize_sfm
from .tokens import SfmTokenKind

_COLUMN_RANGE_RE = re.compile(r"(t[hc][rc]?\d+)-\d+")
MAX_REPORTED_LOCATIONS = 500


@dataclass(frozen=True, slots=True)
class UndefinedMarker:
    marker: str  # bare name, e.g. "zfoo"
    starts: tuple[int, ...]  # source offset of each use
    closed: bool  # the document closes it (`\\zfoo*`): a character style

    @property
    def count(self) -> int:
        return len(self.starts)

    @property
    def custom(self) -> bool:
        """A `\\z…` marker: USFM's namespace for project-defined markers."""

        return self.marker.startswith("z")

    @property
    def display(self) -> str:
        return f"\\{self.marker}"

    @property
    def advice(self) -> str:
        if self.custom:
            return "custom marker: define it in the project's custom.sty"
        return "not defined in any loaded stylesheet"


def undefined_markers(text: str, styles: LayeredStyleRegistry) -> tuple[UndefinedMarker, ...]:
    """Every undefined marker `text` uses, in order of first use."""

    order: list[str] = []  # first use, opener or end marker
    uses: dict[str, list[int]] = {}
    stray_closers: dict[str, list[int]] = {}
    closed: set[str] = set()
    for token in tokenize_sfm(text):
        if token.kind is not SfmTokenKind.MARKER or is_milestone(token.text) or is_milestone_close(token.text):
            continue
        name = marker_name(token.text)
        if not name:
            continue
        cell = _COLUMN_RANGE_RE.fullmatch(name)
        if styles.style_for(cell.group(1) if cell else name) is not None:
            continue
        if name not in uses and name not in stray_closers:
            order.append(name)
        if is_closing(token.text):
            # An end marker belongs to its opener's use; on its own (a
            # stray `\\x*`) it still counts once.
            closed.add(name)
            stray_closers.setdefault(name, []).append(token.start)
            continue
        uses.setdefault(name, []).append(token.start)
    return tuple(
        UndefinedMarker(name, tuple(uses.get(name) or stray_closers[name]), name in closed) for name in order
    )


def definition_stubs(markers: tuple[UndefinedMarker, ...], document_name: str) -> str:
    """Starter `.sty` records for `markers`, to complete by hand."""

    lines = [f"# Added by UNITI on {date.today().isoformat()} for markers {document_name} uses but no stylesheet defined.", "# Complete each \\Name, and adjust the style (see docs/usfm-stylesheet-rules.md).", ""]
    for marker in markers:
        lines.append(f"\\Marker {marker.marker}")
        if marker.closed:
            lines.append(f"\\Endmarker {marker.marker}*")
        lines.append(f"\\Name {marker.marker} - (describe this marker)")
        lines.append("\\StyleType Character" if marker.closed else "\\StyleType Paragraph")
        lines.append("\\TextProperties publishable" if marker.closed else "\\TextProperties paragraph publishable")
        lines.append("")
    return "\n".join(lines)


def location_label(reference_map: ReferenceMap | None, text: str, offset: int) -> str:
    """``GEN 1:2, line 5`` (whatever of that is known)."""

    line = text.count("\n", 0, offset) + 1
    if reference_map is None:
        return f"line {line}"
    reference = reference_map.reference_at(offset)
    parts = [reference.book] if reference.book else []
    if reference.chapter is not None:
        place = reference.chapter if reference.verse is None else f"{reference.chapter}:{reference.verse}"
        parts.append(place)
    return f"{' '.join(parts)}, line {line}" if parts else f"line {line}"


def report_text(document_name: str, layer_names: tuple[str, ...], markers: tuple[UndefinedMarker, ...], text: str) -> str:
    """A plain-text report: the file, the layers checked, every marker with
    its locations (at most `MAX_REPORTED_LOCATIONS` in all)."""

    reference_map = ReferenceMap(text) if text else None
    lines = [
        f"Undefined markers in {document_name}",
        f"Checked against: {' → '.join(layer_names) if layer_names else 'no stylesheet'}",
        "",
    ]
    if not markers:
        lines.append("Every marker is defined.")
        return "\n".join(lines) + "\n"
    remaining = MAX_REPORTED_LOCATIONS
    for marker in markers:
        lines.append(f"{marker.display} — {marker.count} use{'s' if marker.count != 1 else ''} — {marker.advice}")
        for start in marker.starts[: max(0, remaining)]:
            lines.append(f"    {location_label(reference_map, text, start)}")
        remaining -= marker.count
        lines.append("")
    if remaining < 0:
        lines.append(f"(locations after the first {MAX_REPORTED_LOCATIONS} are not listed)")
    return "\n".join(lines).rstrip("\n") + "\n"


__all__ = [
    "MAX_REPORTED_LOCATIONS",
    "UndefinedMarker",
    "definition_stubs",
    "location_label",
    "report_text",
    "undefined_markers",
]
