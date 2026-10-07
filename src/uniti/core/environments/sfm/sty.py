"""`.STY` stylesheet reading (Phase E5).

Two layers, per the handover spec's own distinction:

- `RawStyleSheet`/`RawStyleRecord`/`RawStyleEntry`: one record per
  `\\Marker` block, preserving field order and unknown fields exactly as
  written, so nothing an unrecognized PTXprint/future field carries is lost
  just because this reader doesn't know its name.
- `SfmStyle`/`StyleRegistry`: a typed view over the fields Phase E5's
  structural queries need (`OccursUnder`, `Rank`, `EndMarker`,
  `StyleType`, `TextType`, `TextProperties`, `NotRepeatable`), built by
  layering multiple `RawStyleSheet`s (e.g. official baseline, then a
  project's custom stylesheet) with later layers overriding earlier ones
  field-by-field.

Scope deliberately excludes, for this phase:

- A `.STY` *writer*. Nothing in Phase E5 needs to export a stylesheet, and
  building one before there is a caller would be exactly the speculative
  generalization this project avoids. `RawStyleRecord`/`RawStyleEntry`
  already keep the raw field text (`RawStyleEntry.raw_line`), so a
  loss-minimizing writer has what it needs whenever E6+ actually wants one.
- Typographic/presentation fields (`FontSize`, `Justification`, margins,
  ...). Those belong to the Standard/Preview views (Phase E9), not to structural
  validation or the marker inspector this phase enables. Unrecognized
  fields, typographic or otherwise, still round-trip through
  `SfmStyle.extensions` rather than being silently dropped.
- Byte-exact round-trip of comments and blank lines. The raw layer keeps
  per-record field order and text, but not the comment/blank-line
  structure between records — that precision only matters once a writer
  exists to preserve it for.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, fields, replace

_FIELD_RE = re.compile(r"^\\(\S+)(?:\s+(.*\S))?\s*$")

# Known structural/semantic fields (case-insensitive, as USFM stylesheets
# are conventionally written in CamelCase but not reliably so in the wild).
_MARKER_KEY = "marker"
_NAME_KEY = "name"
_DESCRIPTION_KEY = "description"
_STYLE_TYPE_KEY = "styletype"
_TEXT_TYPE_KEY = "texttype"
_TEXT_PROPERTIES_KEY = "textproperties"
_OCCURS_UNDER_KEY = "occursunder"
_RANK_KEY = "rank"
_END_MARKER_KEY = "endmarker"
_NOT_REPEATABLE_KEY = "notrepeatable"


@dataclass(frozen=True, slots=True)
class RawStyleEntry:
    key: str
    value: str | None
    raw_line: str


@dataclass(frozen=True, slots=True)
class RawStyleRecord:
    marker: str
    entries: tuple[RawStyleEntry, ...]
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class RawStyleSheet:
    records: tuple[RawStyleRecord, ...]


def parse_raw_stylesheet(text: str) -> RawStyleSheet:
    """Parse `.STY` source into one `RawStyleRecord` per `\\Marker` block."""

    records: list[RawStyleRecord] = []
    entries: list[RawStyleEntry] = []
    marker: str | None = None
    record_start = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            match = _FIELD_RE.match(stripped)
            if match is not None:
                key, value = match.group(1), match.group(2)
                if key.lower() == _MARKER_KEY:
                    if marker is not None:
                        records.append(RawStyleRecord(marker, tuple(entries), record_start, offset))
                    marker = value or ""
                    entries = []
                    record_start = offset
                elif marker is not None:
                    entries.append(RawStyleEntry(key, value, line))
        offset += len(line)
    if marker is not None:
        records.append(RawStyleRecord(marker, tuple(entries), record_start, offset))
    return RawStyleSheet(tuple(records))


@dataclass(frozen=True, slots=True)
class SfmStyle:
    marker: str
    name: str | None = None
    description: str | None = None
    style_type: str | None = None
    text_type: str | None = None
    text_properties: frozenset[str] = frozenset()
    occurs_under: tuple[str, ...] = ()
    rank: int | None = None
    repeatable: bool | None = None
    end_marker: str | None = None
    extensions: tuple[tuple[str, str | None], ...] = ()


def normalize_style(record: RawStyleRecord) -> SfmStyle:
    """Build the typed `SfmStyle` view of one raw stylesheet record."""

    known: dict[str, object] = {}
    extensions: list[tuple[str, str | None]] = []
    for entry in record.entries:
        lowered = entry.key.lower()
        if lowered == _NAME_KEY:
            known["name"] = entry.value
        elif lowered == _DESCRIPTION_KEY:
            known["description"] = entry.value
        elif lowered == _STYLE_TYPE_KEY:
            known["style_type"] = entry.value
        elif lowered == _TEXT_TYPE_KEY:
            known["text_type"] = entry.value
        elif lowered == _TEXT_PROPERTIES_KEY:
            known["text_properties"] = frozenset((entry.value or "").split())
        elif lowered == _OCCURS_UNDER_KEY:
            known["occurs_under"] = tuple((entry.value or "").split())
        elif lowered == _RANK_KEY:
            known["rank"] = _parse_int(entry.value)
        elif lowered == _END_MARKER_KEY:
            known["end_marker"] = entry.value
        elif lowered == _NOT_REPEATABLE_KEY:
            known["repeatable"] = False
        else:
            extensions.append((entry.key, entry.value))
    return SfmStyle(marker=record.marker, extensions=tuple(extensions), **known)


def _parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _merge_styles(base: SfmStyle, override: SfmStyle) -> SfmStyle:
    """Layer `override` onto `base`: only override's non-default fields win."""

    updates: dict[str, object] = {}
    for field_ in fields(SfmStyle):
        if field_.name in ("marker", "extensions"):
            continue
        value = getattr(override, field_.name)
        default = field_.default_factory() if callable(field_.default_factory) else field_.default  # type: ignore[misc]
        if value != default:
            updates[field_.name] = value
    if override.extensions:
        updates["extensions"] = base.extensions + override.extensions
    return replace(base, **updates)


@dataclass(frozen=True, slots=True)
class StyleRegistry:
    """Layered, effective marker styles from one or more `RawStyleSheet`s."""

    styles: dict[str, SfmStyle]

    @classmethod
    def from_layers(cls, *sheets: RawStyleSheet) -> "StyleRegistry":
        merged: dict[str, SfmStyle] = {}
        for sheet in sheets:
            for record in sheet.records:
                style = normalize_style(record)
                existing = merged.get(style.marker)
                merged[style.marker] = _merge_styles(existing, style) if existing else style
        return cls(merged)

    def style_for(self, marker: str) -> SfmStyle | None:
        return self.styles.get(marker)

    def occurs_under(self, marker: str) -> tuple[str, ...]:
        style = self.style_for(marker)
        return style.occurs_under if style else ()

    def end_marker(self, marker: str) -> str | None:
        style = self.style_for(marker)
        return style.end_marker if style else None

    def rank(self, marker: str) -> int | None:
        style = self.style_for(marker)
        return style.rank if style else None

    def is_repeatable(self, marker: str) -> bool | None:
        style = self.style_for(marker)
        return style.repeatable if style else None

    def style_type(self, marker: str) -> str | None:
        style = self.style_for(marker)
        return style.style_type if style else None

    def markers(self) -> Iterable[str]:
        return self.styles.keys()
