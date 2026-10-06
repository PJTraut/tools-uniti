"""Layered stylesheets with per-property provenance (ADR-0015; spec §37-38).

`StyleRegistry.from_layers` (E5) merges sheets but forgets where each value
came from. This keeps the layers separate — never permanently flattened —
so an inspector can say "FontSize 11, from ptxprint-mods.sty, base 12".

Layer order, lowest to highest precedence:

1. the official baseline `usfm.sty` (USFM only; generic SFM has none),
2. project stylesheets discovered next to the document (`usfm.sty`, then
   `custom.sty`, then PTXprint's `shared/ptxprint/ptxprint-mods.sty`) —
   filenames vary by project, so discovery is a small, explicit list
   rather than an assumption that every project looks the same,
3. stylesheets the user imported explicitly (any `.sty` path).

Discovery and loading never raise: an unreadable or oversized file is
skipped and logged, exactly like the baseline loader.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, fields
from enum import StrEnum
from pathlib import Path

from .sty import RawStyleSheet, SfmStyle, StyleRegistry, normalize_style, parse_raw_stylesheet

logger = logging.getLogger("uniti.environment.sfm.styles")

MAX_STYLESHEET_BYTES = 2 * 1024 * 1024
_COMMENT_RE = re.compile(r"\s+#.*$")


class StyleOrigin(StrEnum):
    USFM_BASE = "usfm-base"
    PROJECT = "project"
    PTXPRINT = "ptxprint"
    UNITI_IMPORT = "import"


@dataclass(frozen=True, slots=True)
class StyleLayer:
    name: str
    origin: StyleOrigin
    sheet: RawStyleSheet
    path: Path | None = None


# (relative path, origin) in ascending precedence.
PROJECT_STYLESHEET_CANDIDATES: tuple[tuple[str, StyleOrigin], ...] = (
    ("usfm.sty", StyleOrigin.PROJECT),
    ("custom.sty", StyleOrigin.PROJECT),
    ("shared/ptxprint/ptxprint-mods.sty", StyleOrigin.PTXPRINT),
)


def load_stylesheet_file(path: Path, origin: StyleOrigin) -> StyleLayer | None:
    """Read one `.sty` file as a layer; `None` if it can't be read safely."""

    try:
        if not path.is_file() or path.stat().st_size > MAX_STYLESHEET_BYTES:
            return None
        data = path.read_bytes()
        text = data.decode("utf-8-sig", errors="replace")
        return StyleLayer(path.name, origin, parse_raw_stylesheet(text), path)
    except OSError:
        logger.warning("could not read stylesheet %s", path, exc_info=True)
        return None


def discover_project_stylesheets(document_path: Path | None) -> tuple[StyleLayer, ...]:
    """Project stylesheet layers for a document, in precedence order.

    Looks in the document's own folder (Paratext keeps book files and the
    project's `.sty` files together). Never raises.
    """

    if document_path is None:
        return ()
    folder = document_path.parent
    layers: list[StyleLayer] = []
    for relative, origin in PROJECT_STYLESHEET_CANDIDATES:
        candidate = folder / relative
        try:
            same_file = candidate.resolve() == document_path.resolve()
        except OSError:
            same_file = False
        if same_file:
            continue
        layer = load_stylesheet_file(candidate, origin)
        if layer is not None:
            layers.append(layer)
    return tuple(layers)


def clean_value(value: str | None) -> str | None:
    """Strip a trailing `# comment` (common in real `.sty` files)."""

    if value is None:
        return None
    cleaned = _COMMENT_RE.sub("", value).strip()
    return cleaned or None


@dataclass(frozen=True, slots=True)
class PropertyValue:
    value: str
    origin_layer: str
    base_value: str | None


_IDENTITY_FIELDS = ("name", "description", "style_type")
_STRUCTURE_FIELDS = ("occurs_under", "rank", "repeatable", "end_marker")
_SEMANTIC_FIELDS = ("text_type", "text_properties")


def _field_text(style: SfmStyle, name: str) -> str | None:
    value = getattr(style, name)
    if value is None:
        return None
    if isinstance(value, frozenset):
        return " ".join(sorted(value)) if value else None
    if isinstance(value, tuple):
        return " ".join(value) if value else None
    if isinstance(value, bool):
        return "yes" if value else "no"
    return clean_value(str(value))


class LayeredStyleRegistry:
    """Effective styles over separate layers, with provenance."""

    def __init__(self, layers: Sequence[StyleLayer]) -> None:
        self.layers: tuple[StyleLayer, ...] = tuple(layers)
        self.registry = StyleRegistry.from_layers(*(layer.sheet for layer in self.layers))
        self._per_layer: list[tuple[StyleLayer, dict[str, SfmStyle]]] = [
            (layer, {record.marker: normalize_style(record) for record in layer.sheet.records})
            for layer in self.layers
        ]

    def markers(self) -> tuple[str, ...]:
        return tuple(sorted(self.registry.markers()))

    def style_for(self, marker: str) -> SfmStyle | None:
        return self.registry.style_for(marker)

    def defining_layers(self, marker: str) -> tuple[str, ...]:
        return tuple(layer.name for layer, styles in self._per_layer if marker in styles)

    def _defaults(self) -> dict[str, object]:
        result: dict[str, object] = {}
        for field_ in fields(SfmStyle):
            default = field_.default_factory() if callable(field_.default_factory) else field_.default  # type: ignore[misc]
            result[field_.name] = default
        return result

    def property(self, marker: str, field_name: str) -> PropertyValue | None:
        """One typed `SfmStyle` field's effective value and where it came from."""

        defaults = self._defaults()
        found: list[tuple[str, str]] = []
        for layer, styles in self._per_layer:
            style = styles.get(marker)
            if style is None or getattr(style, field_name) == defaults[field_name]:
                continue
            text = _field_text(style, field_name)
            if text is not None:
                found.append((layer.name, text))
        if not found:
            return None
        return PropertyValue(found[-1][1], found[-1][0], found[0][1] if len(found) > 1 else None)

    def presentation(self, marker: str) -> tuple[tuple[str, PropertyValue], ...]:
        """Untyped formatting keys (`\\FontSize`, `\\Bold`, …), last layer wins."""

        seen: dict[str, list[tuple[str, str]]] = {}
        order: list[str] = []
        for layer, styles in self._per_layer:
            style = styles.get(marker)
            if style is None:
                continue
            for key, value in style.extensions:
                lowered = key.lower()
                if lowered not in seen:
                    seen[lowered] = []
                    order.append(key)
                seen[lowered].append((layer.name, clean_value(value) or "yes"))
        result = []
        for key in order:
            values = seen[key.lower()]
            result.append(
                (key, PropertyValue(values[-1][1], values[-1][0], values[0][1] if len(values) > 1 else None))
            )
        return tuple(result)

    def formatting(self, marker: str) -> dict[str, str]:
        """Effective presentation keys, lowercased (for renderers)."""

        return {key.lower(): value.value for key, value in self.presentation(marker)}


def build_layers(
    baseline: RawStyleSheet | None,
    document_path: Path | None,
    imported: Iterable[StyleLayer] = (),
) -> tuple[StyleLayer, ...]:
    layers: list[StyleLayer] = []
    if baseline is not None and baseline.records:
        layers.append(StyleLayer("usfm.sty (official)", StyleOrigin.USFM_BASE, baseline))
    layers.extend(discover_project_stylesheets(document_path))
    layers.extend(imported)
    return tuple(layers)


__all__ = [
    "LayeredStyleRegistry",
    "MAX_STYLESHEET_BYTES",
    "PROJECT_STYLESHEET_CANDIDATES",
    "PropertyValue",
    "StyleLayer",
    "StyleOrigin",
    "build_layers",
    "clean_value",
    "discover_project_stylesheets",
    "load_stylesheet_file",
]
