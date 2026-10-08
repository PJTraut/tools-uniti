"""Layered stylesheets with per-property provenance (ADR-0015; spec §37-38).

`StyleRegistry.from_layers` (E5) merges sheets but forgets where each value
came from. This keeps the layers separate — never permanently flattened —
so an inspector can say "FontSize 11, from ptxprint-mods.sty, base 12".

Layer order, lowest to highest precedence:

1. the official baseline `usfm.sty` (USFM only; generic SFM has none),
   followed by UNITI's built-in `uniti.sty` presentation rules,
2. project stylesheets discovered next to the document (`usfm.sty`, then
   `custom.sty`, then PTXprint's `shared/ptxprint/ptxprint-mods.sty`, then
   the project's own `uniti.sty`) — filenames vary by project, so
   discovery is a small, explicit list rather than an assumption that
   every project looks the same,
3. stylesheets the user imported explicitly (any `.sty` path).

**Presentation rules** extend the STY for the Standard/Preview views
without a new file format: a record whose `\\Marker` is a CSS-like selector
instead of a marker name, carrying ordinary STY fields.

- `\\Marker p+q1` — a `\\q1` paragraph whose previous paragraph-level marker
  is `\\p` (CSS "adjacent sibling"). Its fields override `\\q1`'s own.
- `\\Marker f::caller` — a note's caller (CSS "pseudo-element").
- Several selectors may share one record: `\\Marker p+q1, q1+p`.
- A numberless marker matches its level-1 form (`q` = `q1`, `s` = `s1`).

Rule records never become marker styles: they are kept out of the
structural registry, the Style Inspector's marker list and the marker
choices. Paratext and PTXprint never read a file named `uniti.sty`, which
is why project rules belong there rather than in `custom.sty`.

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

from .sty import (
    RawStyleRecord,
    RawStyleSheet,
    SfmStyle,
    StyleRegistry,
    normalize_style,
    parse_raw_stylesheet,
)

logger = logging.getLogger("uniti.environment.sfm.styles")

MAX_STYLESHEET_BYTES = 2 * 1024 * 1024
_COMMENT_RE = re.compile(r"\s+#.*$")


class StyleOrigin(StrEnum):
    USFM_BASE = "usfm-base"
    UNITI_BUILTIN = "uniti-builtin"
    PROJECT = "project"
    PTXPRINT = "ptxprint"
    UNITI_PROJECT = "uniti-project"
    UNITI_IMPORT = "import"


# Layers that ship with UNITI rather than describing a project's changes.
BUILTIN_ORIGINS = frozenset({StyleOrigin.USFM_BASE, StyleOrigin.UNITI_BUILTIN})


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
    ("uniti.sty", StyleOrigin.UNITI_PROJECT),
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


def project_stylesheet_candidates(document_path: Path) -> tuple[tuple[str, StyleOrigin], ...]:
    """The stylesheet files to look for next to `document_path`.

    In a Paratext project the stylesheet `Settings.xml` names (e.g.
    `usfm_sb.sty`) takes the place of `usfm.sty` (plan P3).
    """

    from .paratext_project import project_for_file

    project = project_for_file(document_path)
    named = project.stylesheet if project is not None else None
    if not named or "/" in named or "\\" in named:
        return PROJECT_STYLESHEET_CANDIDATES
    return ((named, StyleOrigin.PROJECT),) + tuple(
        (relative, origin)
        for relative, origin in PROJECT_STYLESHEET_CANDIDATES
        if relative not in ("usfm.sty", named)
    )


def discover_project_stylesheets(document_path: Path | None) -> tuple[StyleLayer, ...]:
    """Project stylesheet layers for a document, in precedence order.

    Looks in the document's own folder (Paratext keeps book files and the
    project's `.sty` files together). Never raises.
    """

    if document_path is None:
        return ()
    folder = document_path.parent
    layers: list[StyleLayer] = []
    for relative, origin in project_stylesheet_candidates(document_path):
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


_SELECTOR_PARTS = ("+", "::", ",")
_LEVEL_ONE_RE = re.compile(r"([A-Za-z]+)1")


def is_selector(marker: str) -> bool:
    """Whether a record's `\\Marker` value is a presentation-rule selector."""

    return any(part in marker for part in _SELECTOR_PARTS)


def rule_marker_key(marker: str) -> str:
    """The name a selector matches on: a level-1 marker and its numberless
    form are the same (`q1` -> `q`)."""

    match = _LEVEL_ONE_RE.fullmatch(marker)
    return match.group(1) if match else marker


@dataclass(frozen=True, slots=True)
class PresentationRule:
    """One selector of a rule record, with that record's formatting fields."""

    selector: str
    target: str  # rule_marker_key of the styled marker
    previous: str | None  # rule_marker_key of the preceding paragraph (`a+b`)
    pseudo: str | None  # pseudo-element (`f::caller` -> "caller")
    fields: tuple[tuple[str, str], ...]  # (lowercased key, value)
    layer: str


def _parse_rules(record: RawStyleRecord, layer: str) -> list[PresentationRule]:
    """A rule record's selectors; anything unparseable is ignored."""

    fields_ = tuple(
        (key.lower(), clean_value(value) or "yes") for key, value in normalize_style(record).extensions
    )
    rules = []
    for selector in record.marker.split(","):
        selector = selector.strip()
        if "::" in selector:
            base, pseudo = (part.strip() for part in selector.split("::", 1))
            if base and pseudo and not is_selector(base):
                rules.append(PresentationRule(selector, rule_marker_key(base), None, pseudo.lower(), fields_, layer))
        elif selector.count("+") == 1:
            previous, target = (part.strip() for part in selector.split("+"))
            if previous and target:
                rules.append(
                    PresentationRule(
                        selector, rule_marker_key(target), rule_marker_key(previous), None, fields_, layer
                    )
                )
    return rules


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
        # Marker styles and presentation rules, kept apart (module docstring).
        marker_sheets = [
            RawStyleSheet(tuple(record for record in layer.sheet.records if not is_selector(record.marker)))
            for layer in self.layers
        ]
        self.registry = StyleRegistry.from_layers(*marker_sheets)
        self._per_layer: list[tuple[StyleLayer, dict[str, SfmStyle]]] = [
            (layer, {record.marker: normalize_style(record) for record in sheet.records})
            for layer, sheet in zip(self.layers, marker_sheets)
        ]
        self.rules: tuple[PresentationRule, ...] = tuple(
            rule
            for layer in self.layers
            for record in layer.sheet.records
            if is_selector(record.marker)
            for rule in _parse_rules(record, layer.name)
        )

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

    def formatting(self, marker: str, previous: str | None = None) -> dict[str, str]:
        """Effective presentation keys, lowercased (for renderers).

        With `previous` (the paragraph-level marker just before this one),
        matching `previous+marker` rules apply on top, in layer order.
        """

        result = {key.lower(): value.value for key, value in self.presentation(marker)}
        if previous is not None and self.rules:
            target, prior = rule_marker_key(marker), rule_marker_key(previous)
            for rule in self.rules:
                if rule.pseudo is None and rule.target == target and rule.previous == prior:
                    result.update(rule.fields)
        return result

    def pseudo_formatting(self, marker: str, pseudo: str) -> dict[str, str]:
        """Formatting of `marker::pseudo` (e.g. a note's caller); empty
        when no rule defines it."""

        result: dict[str, str] = {}
        target = rule_marker_key(marker)
        for rule in self.rules:
            if rule.pseudo == pseudo and rule.target == target:
                result.update(rule.fields)
        return result

    def caller_formatting(self, note_marker: str) -> dict[str, str]:
        return self.pseudo_formatting(note_marker, "caller")


def build_layers(
    baseline: RawStyleSheet | None,
    document_path: Path | None,
    imported: Iterable[StyleLayer] = (),
) -> tuple[StyleLayer, ...]:
    layers: list[StyleLayer] = []
    if baseline is not None and baseline.records:
        layers.append(StyleLayer("usfm.sty (official)", StyleOrigin.USFM_BASE, baseline))
        from .usfm_baseline import load_uniti_builtin

        builtin = load_uniti_builtin()
        if builtin.records:
            layers.append(StyleLayer("uniti.sty (built-in)", StyleOrigin.UNITI_BUILTIN, builtin))
    layers.extend(discover_project_stylesheets(document_path))
    layers.extend(imported)
    return tuple(layers)


__all__ = [
    "BUILTIN_ORIGINS",
    "LayeredStyleRegistry",
    "MAX_STYLESHEET_BYTES",
    "PROJECT_STYLESHEET_CANDIDATES",
    "PresentationRule",
    "PropertyValue",
    "StyleLayer",
    "StyleOrigin",
    "build_layers",
    "clean_value",
    "discover_project_stylesheets",
    "is_selector",
    "project_stylesheet_candidates",
    "load_stylesheet_file",
    "rule_marker_key",
]
