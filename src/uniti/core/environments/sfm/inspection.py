"""Marker/style inspection model (ADR-0015; spec §47).

Qt-free: the Style Inspector window only lays out what this returns.
"""

from __future__ import annotations

from dataclasses import dataclass

from .markers import is_closing, is_milestone, is_milestone_close, marker_name
from .nodes import SfmNode, SfmNodeKind
from .parser import parse_sfm
from .style_layers import LayeredStyleRegistry, PropertyValue
from .tokenizer import tokenize_sfm
from .tokens import SfmTokenKind


@dataclass(frozen=True, slots=True)
class InspectionRow:
    label: str
    value: str
    origin: str | None = None
    base: str | None = None


@dataclass(frozen=True, slots=True)
class MarkerInspection:
    marker: str
    known: bool
    sections: tuple[tuple[str, tuple[InspectionRow, ...]], ...]


def _bare(marker: str) -> str:
    return marker_name(marker)


def _enclosing_character(node: SfmNode, offset: int) -> str | None:
    for child in node.children:
        if child.kind is SfmNodeKind.CHARACTER and child.start <= offset < child.end:
            return _enclosing_character(child, offset) or child.marker
    return None


def marker_at(text: str, offset: int) -> str | None:
    """The marker the caret is "in": on a marker token, inside a paired
    character span, else the nearest preceding opening marker."""

    tokens = tokenize_sfm(text)
    for token in tokens:
        if token.kind is SfmTokenKind.MARKER and token.start <= offset <= token.end:
            return _bare(token.text)
    enclosing = _enclosing_character(parse_sfm(tokens), offset)
    if enclosing is not None:
        return _bare(enclosing)
    # Openers seen before the caret, minus any already closed by `\x*`.
    open_markers: list[str] = []
    for token in tokens:
        if token.start >= offset:
            break
        if token.kind is not SfmTokenKind.MARKER or is_milestone(token.text) or is_milestone_close(token.text):
            continue
        if is_closing(token.text):
            base = token.text[:-1]
            for index in range(len(open_markers) - 1, -1, -1):
                if open_markers[index] == base:
                    del open_markers[index]
                    break
        else:
            open_markers.append(token.text)
    return _bare(open_markers[-1]) if open_markers else None


_SECTION_FIELDS = (
    ("Identity", (("Name", "name"), ("Description", "description"), ("Type", "style_type"))),
    (
        "Structure",
        (("End Marker", "end_marker"), ("Occurs Under", "occurs_under"), ("Rank", "rank"), ("Repeatable", "repeatable")),
    ),
    ("Semantics", (("Text Type", "text_type"), ("Text Properties", "text_properties"))),
)


def _row(label: str, value: PropertyValue) -> InspectionRow:
    return InspectionRow(label, value.value, value.origin_layer, value.base_value)


def inspect_marker(registry: LayeredStyleRegistry, marker: str) -> MarkerInspection:
    marker = _bare(marker)
    style = registry.style_for(marker)
    if style is None:
        return MarkerInspection(
            marker,
            False,
            (("Definition", (InspectionRow("Status", "Not defined by any loaded stylesheet"),)),),
        )
    sections: list[tuple[str, tuple[InspectionRow, ...]]] = []
    for heading, field_rows in _SECTION_FIELDS:
        rows = []
        for label, field_name in field_rows:
            value = registry.property(marker, field_name)
            if value is not None:
                rows.append(_row(label, value))
        if heading == "Structure" and registry.property(marker, "repeatable") is None:
            # `\NotRepeatable` is the only spelling; absent means repeatable.
            rows.append(InspectionRow("Repeatable", "yes"))
        if rows:
            sections.append((heading, tuple(rows)))
    presentation = tuple(_row(key, value) for key, value in registry.presentation(marker))
    if presentation:
        sections.append(("Presentation", presentation))
    defined = registry.defining_layers(marker)
    definition = [InspectionRow("Effective source", defined[-1])]
    if len(defined) > 1:
        definition.append(InspectionRow("Base source", defined[0]))
        definition.append(InspectionRow("All layers", " → ".join(defined)))
    sections.append(("Definition", tuple(definition)))
    return MarkerInspection(marker, True, tuple(sections))


__all__ = ["InspectionRow", "MarkerInspection", "inspect_marker", "marker_at"]
