"""SFM Standard and Formatted views (ADR-0015, spec §33, Phases E8–E9).

Both are projections of the canonical source through `rich_views`:

- **Standard View** shows every marker as a protected token (so nothing in
  the source is ever invisible), with character styles applied to the text
  they wrap. Lines match the source's lines.
- **Formatted View** hides markers and their separator whitespace, starts a
  block per paragraph marker with that marker's effective STY formatting,
  renders chapter numbers large and verse numbers superscript, and applies
  character styles. Footnotes/cross-references show their caller
  superscript and their text muted in generated brackets; table rows put
  a tab between cells, with header cells bold. A marker no loaded stylesheet defines stays visible as
  a protected token, so unknown content never silently disappears.

This is an *editing* renderer, not a typesetter (spec Phase E9): spacing and
margins approximate the STY values; PTXprint-grade layout is out of scope.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from uniti.core.rich_views.editing import EditPlan
from uniti.core.rich_views.projection import Projection, ProjectionBuilder
from uniti.core.rich_views.provider import ViewCommand

from .nodes import SfmNode, SfmNodeKind
from .parser import parse_sfm
from .semantic import (
    apply_character_style,
    change_paragraph_marker,
    character_markers,
    insert_verse,
    paragraph_enter_text,
    paragraph_markers,
    remove_character_style,
)
from .style_layers import LayeredStyleRegistry
from .tokenizer import tokenize_sfm
from .tokens import SfmTokenKind

BASE_FONT_SIZE = 12.0
# Table cells: th1, thr2, tc1, tcr3, thc1, tcc2, and column ranges (tc1-2).
_CELL_RE = re.compile(r"t[hc][rc]?\d+(?:-\d+)?")

_FLAG_ATTRS = {
    "bold": "bold",
    "italic": "italic",
    "underline": "underline",
    "superscript": "superscript",
    "smallcaps": "smallcaps",
}
_ALIGN = {"left": "left", "center": "center", "right": "right", "both": "justify", "justify": "justify"}


def _bare(marker: str) -> str:
    return marker.lstrip("\\").rstrip("*")


def sty_color(value: str) -> str | None:
    """Paratext `\\Color` is a decimal 0xBBGGRR integer -> ``#rrggbb``."""

    try:
        number = int(value)
    except ValueError:
        return None
    if not 0 <= number <= 0xFFFFFF:
        return None
    red, green, blue = number & 0xFF, (number >> 8) & 0xFF, (number >> 16) & 0xFF
    return f"#{red:02x}{green:02x}{blue:02x}"


def presentation_attrs(styles: LayeredStyleRegistry, marker: str, *, block: bool) -> dict[str, str]:
    """Backend-neutral attributes from a marker's effective STY formatting."""

    formatting = styles.formatting(marker)
    attrs: dict[str, str] = {}
    for key, attr in _FLAG_ATTRS.items():
        if key in formatting and formatting[key].lower() not in ("-", "no", "false", "0"):
            attrs[attr] = "yes"
    size = formatting.get("fontsize")
    if size:
        try:
            scale = float(size) / BASE_FONT_SIZE
            if abs(scale - 1.0) > 0.01:
                attrs["font_scale"] = f"{scale:.3f}"
        except ValueError:
            pass
    color = sty_color(formatting.get("color", ""))
    if color and color != "#000000":
        attrs["color"] = color
    if block:
        align = _ALIGN.get(formatting.get("justification", "").lower())
        if align:
            attrs["align"] = align
        for key, attr in (
            ("leftmargin", "left_margin"),
            ("rightmargin", "right_margin"),
            ("firstlineindent", "first_indent"),
            ("spacebefore", "space_before"),
            ("spaceafter", "space_after"),
        ):
            if key in formatting:
                try:
                    float(formatting[key])
                    attrs[attr] = formatting[key]
                except ValueError:
                    pass
    return attrs


def _paired_openers(node: SfmNode, pairs: dict[int, tuple[int, str]]) -> None:
    """opener token start -> (closer token start, marker) for every paired span."""

    for child in node.children:
        if child.kind is SfmNodeKind.CHARACTER and child.marker is not None:
            pairs[child.start] = (child.end - len(child.marker) - 1, child.marker)
            _paired_openers(child, pairs)


class _SfmViewBase:
    key: str
    label: str

    def __init__(self, styles: Callable[[], LayeredStyleRegistry]) -> None:
        self._styles = styles

    def enter_text(self, source: str, source_offset: int) -> str:
        return paragraph_enter_text(source, source_offset, self._styles().registry)

    def view_commands(self) -> tuple[ViewCommand, ...]:
        registry = lambda: self._styles().registry  # noqa: E731

        def style(marker: str) -> Callable[[str, int, int, str | None], EditPlan]:
            return lambda source, start, end, _argument: apply_character_style(source, start, end, marker)

        return (
            ViewCommand("bold", "Bold", style("bd"), shortcut="Ctrl+B"),
            ViewCommand("italic", "Italic", style("it"), shortcut="Ctrl+I"),
            ViewCommand(
                "character_style",
                "Character Style…",
                lambda source, start, end, argument: apply_character_style(source, start, end, argument or ""),
                choices=lambda: character_markers(registry()),
            ),
            ViewCommand(
                "remove_style",
                "Remove Character Style",
                lambda source, start, _end, _argument: remove_character_style(source, start),
            ),
            ViewCommand(
                "paragraph_style",
                "Paragraph Style…",
                lambda source, start, _end, argument: change_paragraph_marker(source, start, argument or "p", registry()),
                choices=lambda: paragraph_markers(registry()),
            ),
            ViewCommand(
                "insert_verse",
                "Insert Verse…",
                lambda source, start, _end, argument: insert_verse(source, start, argument or ""),
                prompt="Verse number:",
            ),
        )


class SfmStandardView(_SfmViewBase):
    key = "sfm.standard"
    label = "Standard View"

    def project(self, source: str) -> Projection:
        styles = self._styles()
        tokens = tokenize_sfm(source)
        pairs: dict[int, tuple[int, str]] = {}
        _paired_openers(parse_sfm(tokens), pairs)
        closers = {closer: opener for opener, (closer, _marker) in pairs.items()}
        builder = ProjectionBuilder(self.key)
        open_spans: list[tuple[int, int, str]] = []  # (opener start, view start, marker)
        for token in tokens:
            if token.kind is SfmTokenKind.TEXT:
                builder.text(token.end, token.text)
                continue
            view_start = builder.view_position
            builder.marker(token.end, token.text, _bare(token.text))
            builder.span(view_start, builder.view_position, {"marker_token": "yes"}, _bare(token.text))
            if token.start in pairs:
                open_spans.append((token.start, builder.view_position, _bare(token.text)))
            elif token.start in closers:
                opener = closers[token.start]
                for index in range(len(open_spans) - 1, -1, -1):
                    if open_spans[index][0] == opener:
                        _start, span_view_start, marker = open_spans.pop(index)
                        builder.span(
                            span_view_start,
                            view_start,
                            presentation_attrs(styles, marker, block=False),
                            marker,
                        )
                        break
        return builder.build(len(source))


class SfmFormattedView(_SfmViewBase):
    key = "sfm.formatted"
    label = "Formatted View"
    proportional = True

    def project(self, source: str) -> Projection:
        styles = self._styles()
        registry = styles.registry
        tokens = tokenize_sfm(source)
        pairs: dict[int, tuple[int, str]] = {}
        _paired_openers(parse_sfm(tokens), pairs)
        closers = {closer: opener for opener, (closer, _marker) in pairs.items()}
        builder = ProjectionBuilder(self.key)
        open_spans: list[tuple[int, int, str]] = []
        block: tuple[int, str, dict[str, str]] | None = None
        pending_number: str | None = None  # "verse" | "chapter"
        pending_caller = False  # next text starts a note's caller (+, -, a…)
        note_openers: set[int] = set()
        row_cells = -1  # cells seen in the current \\tr row; -1 outside rows
        cell: tuple[int, str] | None = None  # open cell span (view start, marker)

        def close_cell() -> None:
            nonlocal cell
            if cell is not None:
                header = cell[1].startswith("th")
                builder.span(cell[0], builder.view_position, {"bold": "yes"} if header else {}, cell[1])
                cell = None

        def close_block() -> None:
            nonlocal block
            close_cell()
            if block is not None:
                builder.block(block[0], builder.view_position, block[2], block[1])
                block = None

        def hide_marker(token_end: int, marker: str) -> None:
            end = token_end
            if end < len(source) and source[end] in " \n":
                end += 1
            builder.hidden(end, marker)

        for token in tokens:
            if token.kind is SfmTokenKind.TEXT:
                if token.end <= builder.source_position:
                    continue
                start = builder.source_position
                text = source[start : token.end]
                if pending_caller:
                    pending_caller = False
                    if text and not text[0].isspace():
                        caller_start = builder.view_position
                        builder.text(start + 1, text[0])
                        builder.span(caller_start, builder.view_position, {"superscript": "yes", "bold": "yes"}, "caller")
                        if start + 1 < token.end and source[start + 1] == " ":
                            builder.hidden(start + 2, "caller")
                    builder.generated("[", "note")
                    if builder.source_position < token.end:
                        builder.text(token.end, source[builder.source_position : token.end])
                    continue
                if pending_number is not None:
                    digits = len(text) - len(text.lstrip("0123456789-abc"))
                    number_end = start + digits
                    if digits:
                        view_start = builder.view_position
                        builder.text(number_end, source[start:number_end])
                        attrs = (
                            {"superscript": "yes", "bold": "yes", "muted": "yes"}
                            if pending_number == "verse"
                            else {"bold": "yes", "font_scale": "2.000"}
                        )
                        builder.span(view_start, builder.view_position, attrs, "v" if pending_number == "verse" else "c")
                        if pending_number == "verse" and number_end < token.end and source[number_end] == " ":
                            builder.hidden(number_end + 1, "v")
                    pending_number = None
                    if builder.source_position < token.end:
                        builder.text(token.end, source[builder.source_position : token.end])
                    continue
                builder.text(token.end, text)
                continue

            marker = _bare(token.text)
            is_end = token.text.endswith("*")
            if is_end:
                opener = closers.get(token.start)
                if opener is None:
                    view_start = builder.view_position
                    builder.marker(token.end, token.text, marker)
                    builder.span(view_start, builder.view_position, {"marker_token": "yes"}, marker)
                    continue
                is_note = opener in note_openers
                if is_note:
                    close_cell()
                    builder.generated("]", marker)
                    note_openers.discard(opener)
                builder.hidden(token.end, marker)
                for index in range(len(open_spans) - 1, -1, -1):
                    if open_spans[index][0] == opener:
                        _start, span_view_start, span_marker = open_spans.pop(index)
                        builder.span(
                            span_view_start,
                            builder.view_position,
                            {"muted": "yes", "font_scale": "0.850"}
                            if is_note
                            else presentation_attrs(styles, span_marker, block=False),
                            span_marker,
                        )
                        break
                continue

            if _CELL_RE.fullmatch(marker):
                # Table cell: a tab between cells, header cells bold.
                close_cell()
                if row_cells > 0:
                    builder.generated("\t", marker)
                hide_marker(token.end, marker)
                row_cells = max(row_cells, 0) + 1
                cell = (builder.view_position, marker)
                continue

            style = registry.style_for(marker)
            style_type = (style.style_type or "").lower() if style else ""
            if marker in ("c", "v"):
                if marker == "c":
                    close_block()
                    if builder.view_position and not builder_ends_with_newline(builder, source):
                        builder.generated("\n", marker)
                    block = (builder.view_position, marker, {"space_before": "8"})
                hide_marker(token.end, marker)
                pending_number = "chapter" if marker == "c" else "verse"
                continue
            if style is None:
                view_start = builder.view_position
                builder.marker(token.end, token.text, marker)
                builder.span(view_start, builder.view_position, {"marker_token": "yes"}, marker)
                continue
            if style_type == "paragraph":
                close_block()
                if builder.view_position and not builder_ends_with_newline(builder, source):
                    builder.generated("\n", marker)
                attrs = presentation_attrs(styles, marker, block=True)
                if "publishable" not in (style.text_properties or frozenset()):
                    attrs["muted"] = "yes"
                if marker == "tr":
                    attrs["table_row"] = "yes"
                    row_cells = 0
                else:
                    row_cells = -1
                block = (builder.view_position, marker, attrs)
                # The paragraph style's character-level attrs (bold headings,
                # sizes) reach its text through the block format.
                hide_marker(token.end, marker)
                continue
            hide_marker(token.end, marker)
            if token.start in pairs:
                open_spans.append((token.start, builder.view_position, marker))
                if style_type == "note":
                    note_openers.add(token.start)
                    pending_caller = True
        close_block()
        return builder.build(len(source))


def builder_ends_with_newline(builder: ProjectionBuilder, source: str) -> bool:
    del source
    view = builder._view  # noqa: SLF001 - same-package helper
    for chunk in reversed(view):
        if chunk:
            return chunk.endswith("\n")
    return True


__all__ = [
    "SfmFormattedView",
    "SfmStandardView",
    "presentation_attrs",
    "sty_color",
]
