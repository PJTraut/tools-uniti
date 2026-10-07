"""`.STY` export (ADR-0016; spec §39 "Export resolved" / "Export overrides").

Serializes a `LayeredStyleRegistry` back to `.sty` text. Values keep the
key spelling and raw text of the layer that set them (comments stripped),
so an exported file reads like a hand-written one. Never modifies any layer.
"""

from __future__ import annotations

from .style_layers import BUILTIN_ORIGINS, LayeredStyleRegistry, clean_value


def _effective_entries(registry: LayeredStyleRegistry, marker: str, layers) -> list[tuple[str, str | None]]:
    """Ordered (key, value) for `marker` across `layers`, last layer wins per key."""

    order: list[str] = []
    values: dict[str, tuple[str, str | None]] = {}
    for layer in layers:
        for record in layer.sheet.records:
            if record.marker != marker:
                continue
            for entry in record.entries:
                lowered = entry.key.lower()
                if lowered not in values:
                    order.append(lowered)
                values[lowered] = (entry.key, clean_value(entry.value))
    return [values[key] for key in order]


def _marker_order(registry: LayeredStyleRegistry) -> list[str]:
    seen: list[str] = []
    known: set[str] = set()
    for layer in registry.layers:
        for record in layer.sheet.records:
            if record.marker not in known:
                known.add(record.marker)
                seen.append(record.marker)
    return seen


def _block(marker: str, entries: list[tuple[str, str | None]]) -> str:
    lines = [f"\\Marker {marker}"]
    for key, value in entries:
        lines.append(f"\\{key}" if value is None else f"\\{key} {value}")
    return "\n".join(lines)


def _header(registry: LayeredStyleRegistry, kind: str) -> str:
    sources = ", ".join(layer.name for layer in registry.layers) or "no stylesheet"
    return f"# {kind} exported by UNITI\n# Layers: {sources}\n"


def export_resolved(registry: LayeredStyleRegistry) -> str:
    """Every marker with its effective properties (all layers merged)."""

    blocks = [_block(m, _effective_entries(registry, m, registry.layers)) for m in _marker_order(registry)]
    return _header(registry, "Resolved stylesheet") + "\n" + "\n\n".join(blocks) + "\n"


def export_overrides(registry: LayeredStyleRegistry) -> str:
    """Only what the project/imported layers change relative to what ships
    with UNITI (the official baseline and the built-in `uniti.sty` rules).

    A marker (or rule) the shipped layers don't define is exported whole;
    for one they do, only the keys whose effective value differs. With no
    baseline (generic SFM), this equals the resolved export.
    """

    base_layers = [layer for layer in registry.layers if layer.origin in BUILTIN_ORIGINS]
    blocks = []
    for marker in _marker_order(registry):
        effective = _effective_entries(registry, marker, registry.layers)
        base = {key.lower(): value for key, value in _effective_entries(registry, marker, base_layers)}
        changed = [(key, value) for key, value in effective if key.lower() not in base or base[key.lower()] != value]
        if changed:
            blocks.append(_block(marker, changed))
    return _header(registry, "Stylesheet overrides") + "\n" + "\n\n".join(blocks) + ("\n" if blocks else "")


__all__ = ["export_overrides", "export_resolved"]
