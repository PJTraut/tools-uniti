"""Export Preview as HTML (text direction plan W8, W-D8).

A second renderer of Preview's projection, Qt-free: the paragraphs, runs
and notes Preview shows, with the stylesheet's logical values kept logical
in CSS (`dir`, `text-align: start|end`, `margin-inline-start|end`). It is
faithful to the stylesheet, not pixel-identical to Preview: a browser's
justification, hyphenation and bidi differ from Qt's in small ways.

- Every paragraph is a `<p>` (a `\\tr` row a `<tr>`) with `data-marker`
  and a class per distinct set of paragraph attributes; every run of text
  a `<span>` with a class per distinct set of merged character attributes,
  layered as `rich_view.render_projection` layers them. Sizes are `rem`, so
  nested styles never compound.
- A footnote caller links to its note and back. A caller sits at its note's
  opener in the source and its note's body follows it, so the n-th note
  after a caller's source offset is its own.
- Generated soft hyphens are written as `&shy;`, and directional control
  characters (LRM, RLE, isolates …) as numeric references, never raw.
"""

from __future__ import annotations

import bisect
import html
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from uniti.core.rich_views.projection import Projection
from uniti.core.rich_views.source_map import SegmentRole

from .hyphenation import SOFT_HYPHEN

_CALLER = "caller"
_TAG_COLOR = "#1a56db"
# Directional formatting characters: invisible, so written as references.
_BIDI_CONTROLS = frozenset("؜‎‏‪‫‬‭‮⁦⁧⁨⁩")
_ALIGN_CSS = {
    "left": "start",
    "start": "start",
    "right": "end",
    "end": "end",
    "center": "center",
    "justify": "justify",
}
_PARAGRAPH_ONLY = ("direction", "table_row")


def _number(value: str, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _char_css(attrs: Mapping[str, str]) -> list[str]:
    if attrs.get("marker_token") == "yes":
        # An undefined marker Preview keeps visible: a tag, as on screen.
        return [
            "font-family: monospace",
            "font-weight: normal",
            "font-style: normal",
            "font-variant: normal",
            "text-decoration: none",
            "vertical-align: baseline",
            "font-size: 0.85em",
            f"color: {_TAG_COLOR}",
        ]
    css = []
    if attrs.get("bold") == "yes":
        css.append("font-weight: bold")
    if attrs.get("italic") == "yes":
        css.append("font-style: italic")
    if attrs.get("underline") == "yes":
        css.append("text-decoration: underline")
    if attrs.get("smallcaps") == "yes":
        css.append("font-variant: small-caps")
    if attrs.get("monospace") == "yes":
        css.append("font-family: monospace")
    scale = _number(attrs.get("font_scale", ""), 0.0)
    if attrs.get("superscript") == "yes":
        css.append("vertical-align: super")
        css.append(f"font-size: {scale * 0.7:.3g}rem" if scale > 0 else "font-size: 0.7em")
    elif scale > 0:
        css.append(f"font-size: {scale:.3g}rem")
    if attrs.get("color"):
        css.append(f"color: {attrs['color']}")
    if attrs.get("muted") == "yes":
        css.append("opacity: 0.6")
    return css


def _paragraph_css(attrs: Mapping[str, str]) -> list[str]:
    css = []
    align = _ALIGN_CSS.get(attrs.get("align", ""))
    if align:
        css.append(f"text-align: {align}")
    for key, prop, unit in (
        ("left_margin", "margin-inline-start", "in"),
        ("right_margin", "margin-inline-end", "in"),
        ("first_indent", "text-indent", "in"),
        ("space_before", "margin-block-start", "pt"),
        ("space_after", "margin-block-end", "pt"),
    ):
        if key in attrs:
            css.append(f"{prop}: {_number(attrs[key]):g}{unit}")
    if attrs.get("hyphenate") == "yes":
        css.append("hyphens: manual")
    return css + _char_css(attrs)


class _Classes:
    """One CSS class per distinct attribute set, named in order of use."""

    def __init__(self, prefix: str, css) -> None:
        self._prefix = prefix
        self._css = css
        self._names: dict[tuple, str] = {}
        self.rules: list[str] = []

    def name(self, attrs: Mapping[str, str]) -> str | None:
        key = tuple(sorted(attrs.items()))
        if not key:
            return None
        name = self._names.get(key)
        if name is None:
            declarations = self._css(attrs)
            if not declarations:
                self._names[key] = ""
                return None
            name = self._names[key] = f"{self._prefix}{len(self._names) + 1}"
            self.rules.append(f".{name} {{ {'; '.join(declarations)}; }}")
        return name or None


def _escape(text: str) -> str:
    escaped = html.escape(text, quote=False)
    if SOFT_HYPHEN in escaped:
        escaped = escaped.replace(SOFT_HYPHEN, "&shy;")
    if any(char in _BIDI_CONTROLS for char in escaped):
        escaped = "".join(f"&#x{ord(char):04X};" if char in _BIDI_CONTROLS else char for char in escaped)
    return escaped


def _attribute(value: str) -> str:
    return html.escape(value, quote=True)


@dataclass(frozen=True, slots=True)
class _Run:
    start: int
    end: int
    attrs: Mapping[str, str]
    markers: tuple[str, ...]  # of the spans over it, outer first


def _runs(projection: Projection, extra_boundaries: Iterable[int]) -> list[_Run]:
    """The text cut at every span edge, line break and tab, each run with
    its spans' attributes merged as Preview merges them (spans in order,
    marker tags last)."""

    text = projection.text
    length = len(text)
    layers = [
        span
        for span in sorted(projection.spans, key=lambda span: span.attrs.get("marker_token") == "yes")
        if span.view_end > span.view_start
    ]
    starts_at: dict[int, list[int]] = {}
    ends_at: dict[int, list[int]] = {}
    for index, span in enumerate(layers):
        starts_at.setdefault(max(0, span.view_start), []).append(index)
        ends_at.setdefault(min(length, span.view_end), []).append(index)
    cuts = {0, length, *starts_at, *ends_at, *extra_boundaries}
    for index, char in enumerate(text):
        if char in "\n\t":
            cuts.update((index, index + 1))
    active: set[int] = set()
    runs = []
    boundaries = sorted(cut for cut in cuts if 0 <= cut <= length)
    for position, following in zip(boundaries, boundaries[1:]):
        for index in ends_at.get(position, ()):
            active.discard(index)
        active.update(starts_at.get(position, ()))
        merged: dict[str, str] = {}
        markers = []
        for index in sorted(active):
            span = layers[index]
            if span.attrs.get("marker_token") == "yes":
                merged = {"marker_token": "yes"}
            else:
                merged.update(span.attrs)
            if span.marker:
                markers.append(span.marker)
        runs.append(_Run(position, following, merged, tuple(markers)))
    return runs


class _Writer:
    def __init__(self) -> None:
        self.paragraphs = _Classes("p", _paragraph_css)
        self.runs = _Classes("r", _char_css)
        self._text = ""

    def render(
        self,
        projection: Projection,
        links: Mapping[int, tuple[str, str]],
        ids: Mapping[int, str],
        default_marker: str | None = None,
    ) -> list[str]:
        """`projection`'s paragraphs as HTML lines. `links`: view position
        of a caller's text -> (href, id or ""); `ids`: view position a
        paragraph starts at -> its id; `default_marker`: the `data-marker`
        of a paragraph no block describes (a note entry)."""

        text = self._text = projection.text
        blocks = sorted(projection.blocks, key=lambda block: block.view_start)
        block_starts = [block.view_start for block in blocks]
        runs = _runs(projection, (*links, *self._caller_ends(projection, links)))
        lines: list[str] = []
        table: list[str] | None = None
        paragraph: list[_Run] = []

        def block_at(position: int):
            index = bisect.bisect_right(block_starts, position) - 1
            if index >= 0 and blocks[index].view_start <= position < max(blocks[index].view_end, blocks[index].view_start + 1):
                return blocks[index]
            return None

        def flush() -> None:
            nonlocal table
            if not paragraph:
                return
            start = paragraph[0].start
            block = block_at(start)
            attrs = dict(block.attrs) if block is not None else {}
            marker = block.marker if block is not None else default_marker
            if attrs.get("table_row") == "yes":
                if table is None:
                    table = []
                table.append(self._row(paragraph, attrs, marker, links))
            else:
                if table is not None:
                    lines.append("<table>\n" + "\n".join(table) + "\n</table>")
                    table = None
                lines.append(self._paragraph("p", paragraph, attrs, marker, links, ids.get(start)))
            paragraph.clear()

        for run in runs:
            if text[run.start : run.end] == "\n":
                flush()
            else:
                paragraph.append(run)
        flush()
        if table is not None:
            lines.append("<table>\n" + "\n".join(table) + "\n</table>")
        return lines

    @staticmethod
    def _caller_ends(projection: Projection, links: Mapping[int, tuple[str, str]]) -> list[int]:
        return [
            segment.view_end
            for segment in projection.source_map.segments
            if segment.role is SegmentRole.GENERATED and segment.view_start in links
        ]

    def _open_tag(self, tag: str, attrs: Mapping[str, str], marker: str | None, element_id: str | None) -> str:
        parts = [tag]
        if element_id:
            parts.append(f'id="{_attribute(element_id)}"')
        own = {key: value for key, value in attrs.items() if key not in _PARAGRAPH_ONLY}
        name = self.paragraphs.name(own)
        if name:
            parts.append(f'class="{name}"')
        if marker:
            parts.append(f'data-marker="{_attribute(marker)}"')
        parts.append(f'dir="{attrs["direction"]}"' if attrs.get("direction") in ("ltr", "rtl") else 'dir="auto"')
        return "<" + " ".join(parts) + ">"

    def _paragraph(self, tag, runs, attrs, marker, links, element_id) -> str:
        return self._open_tag(tag, attrs, marker, element_id) + self._inline(runs, links) + f"</{tag}>"

    def _row(self, runs: list[_Run], attrs, marker, links) -> str:
        cells: list[list[_Run]] = [[]]
        for run in runs:
            if self._text[run.start : run.end] == "\t":
                cells.append([])
            else:
                cells[-1].append(run)
        html_cells = []
        for cell in cells:
            header = any(name.startswith("th") for run in cell[:1] for name in run.markers)
            tag = "th" if header else "td"
            html_cells.append(f"<{tag}>{self._inline(cell, links)}</{tag}>")
        return self._open_tag("tr", attrs, marker, None) + "".join(html_cells) + "</tr>"

    def _inline(self, runs: Iterable[_Run], links: Mapping[int, tuple[str, str]]) -> str:
        out = []
        for run in runs:
            content = _escape(self._text[run.start : run.end])
            if not content:
                continue
            name = self.runs.name(run.attrs)
            if name:
                marker = run.markers[-1] if run.markers else None
                data = f' data-marker="{_attribute(marker)}"' if marker else ""
                content = f'<span class="{name}"{data}>{content}</span>'
            link = links.get(run.start)
            if link is not None:
                href, element_id = link
                anchor_id = f' id="{_attribute(element_id)}"' if element_id else ""
                content = f'<a class="caller" href="#{_attribute(href)}"{anchor_id}>{content}</a>'
            out.append(content)
        return "".join(out)


def _caller_segments(projection: Projection) -> list[tuple[int, int]]:
    """(source offset, view start) of every caller's text, in order."""

    return [
        (segment.source_start, segment.view_start)
        for segment in projection.source_map.segments
        if segment.role is SegmentRole.GENERATED and segment.marker == _CALLER and segment.view_end > segment.view_start
        and projection.text[segment.view_start : segment.view_end].strip()
    ]


def export_preview_html(
    projection: Projection,
    *,
    title: str,
    base_size: float = 12.0,
    language: str | None = None,
    direction: str | None = None,
    font: str | None = None,
) -> str:
    """Preview's `projection` (text and notes) as a standalone HTML page."""

    # Each note entry: its id, and where its body starts in the source.
    entries: list[tuple[int, str, int, str]] = []  # (body source, id, view start, kind)
    for section in projection.notes:
        # One entry per line (a block records it only when it has attributes).
        section_map, text = section.projection.source_map, section.projection.text
        starts = [0, *(index + 1 for index, char in enumerate(text) if char == "\n" and index + 1 < len(text))]
        for number, view_start in enumerate(starts, 1):
            source = section_map.view_to_source(view_start, prefer_left=False)
            entries.append((source, f"{section.key}-{number}", view_start, section.key))
    entries.sort()
    entry_sources = [entry[0] for entry in entries]
    main_links: dict[int, tuple[str, str]] = {}
    referenced: set[str] = set()
    for source, view_start in _caller_segments(projection):
        index = bisect.bisect_left(entry_sources, source)
        if index < len(entries):
            entry_id = entries[index][1]
            main_links[view_start] = (entry_id, f"{entry_id}-ref")
            referenced.add(entry_id)

    writer = _Writer()
    body = ["<main>", *writer.render(projection, main_links, {}), "</main>"]
    for section in projection.notes:
        ids = {view_start: entry_id for _source, entry_id, view_start, kind in entries if kind == section.key}
        back_links: dict[int, tuple[str, str]] = {}
        for _source, view_start in _caller_segments(section.projection):
            entry_id = ids.get(view_start)
            if entry_id in referenced:
                back_links[view_start] = (f"{entry_id}-ref", "")
        body.append(f'<section class="notes" data-note="{_attribute(section.key)}">')
        body.append(f"<h2>{_escape(section.label)}</h2>")
        body.extend(writer.render(section.projection, back_links, ids, section.key))
        body.append("</section>")

    families = [f'"{_font_name(font)}"'] if font and _font_name(font) else []
    css = [
        f"html {{ font-size: {base_size:g}pt; }}",
        f"body {{ font-family: {', '.join([*families, 'serif'])}; line-height: 1.4; max-width: 42em; margin: 2em auto; padding: 0 1em; }}",
        "p { margin: 0; }",
        "table { border-collapse: collapse; }",
        "td, th { padding: 0 1em 0 0; text-align: start; vertical-align: top; font-weight: inherit; }",
        "a.caller { color: inherit; text-decoration: none; }",
        ".notes { margin-block-start: 2em; padding-block-start: 0.5em; border-block-start: 1px solid #999; }",
        ".notes h2 { font-size: 1rem; margin: 0 0 0.5em; }",
        *writer.paragraphs.rules,
        *writer.runs.rules,
    ]
    html_attrs = []
    if language:
        html_attrs.append(f'lang="{_attribute(language)}"')
    if direction in ("ltr", "rtl"):
        html_attrs.append(f'dir="{direction}"')
    open_html = "<html" + "".join(f" {attr}" for attr in html_attrs) + ">"
    head = [
        "<!DOCTYPE html>",
        open_html,
        "<head>",
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1">',
        '<meta name="generator" content="UNITI">',
        f"<title>{_escape(title)}</title>",
        "<style>",
        *css,
        "</style>",
        "</head>",
        "<body>",
    ]
    return "\n".join([*head, *body, "</body>", "</html>"]) + "\n"


def _font_name(font: str) -> str:
    """A font family name safe inside a quoted CSS string."""

    return "".join(char for char in font.strip() if char not in '"\\<>{};').strip()


__all__ = ["export_preview_html"]
