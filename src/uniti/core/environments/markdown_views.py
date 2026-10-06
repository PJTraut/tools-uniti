"""Markdown Rendered View (ADR-0015, spec Phase E10).

An editable projection on the same rich-view infrastructure as SFM: syntax
delimiters (``#``, ``**``, ``*``, `` ` ``, ``>``, link brackets/targets,
code fences) are hidden, list bullets are shown as a protected ``•``, and
headings/emphasis/code/quotes are formatted. Lines map 1:1 to source lines,
so structure never changes behind the user's back.

Deliberately a CommonMark *subset* (like BF-062's preview): no tables,
footnotes, nested emphasis edge cases or HTML. Anything unrecognized simply
stays visible as text — the view degrades to showing source, never hides it.
"""

from __future__ import annotations

import re

from uniti.core.rich_views.editing import EditPlan, EditRejected
from uniti.core.rich_views.projection import Projection, ProjectionBuilder
from uniti.core.rich_views.provider import ViewCommand

_HEADING_RE = re.compile(r"(#{1,6})([ \t]+)")
_QUOTE_RE = re.compile(r">[ \t]?")
_BULLET_RE = re.compile(r"([ \t]*)([-*+])([ \t]+)")
_FENCE_RE = re.compile(r"[ \t]*(```|~~~)")
_INLINE_RE = re.compile(
    r"(?P<code>`)(?P<code_body>[^`\n]+)`"
    r"|(?P<bold>\*\*|__)(?P<bold_body>(?:(?!(?P=bold)).)+?)(?P=bold)"
    r"|(?P<italic>[*_])(?P<italic_body>[^*_\n]+?)(?P=italic)"
    r"|(?P<link>\[)(?P<link_body>[^\]\n]+)\]\((?P<link_target>[^)\n]*)\)"
)
_HEADING_SCALE = {1: "1.800", 2: "1.500", 3: "1.250", 4: "1.100", 5: "1.000", 6: "0.950"}


def _inline(builder: ProjectionBuilder, source: str, start: int, end: int) -> None:
    """Project one line's inline content [start, end) (no newline)."""

    position = start
    for match in _INLINE_RE.finditer(source, start, end):
        if match.start() > position:
            builder.text(match.start(), source[position : match.start()])
        if match.group("code"):
            builder.hidden(match.start() + 1, "code")
            body_start = builder.view_position
            builder.text(match.end() - 1, source[match.start() + 1 : match.end() - 1])
            builder.span(body_start, builder.view_position, {"monospace": "yes"}, "code")
            builder.hidden(match.end(), "code")
        elif match.group("bold"):
            width = len(match.group("bold"))
            builder.hidden(match.start() + width, "strong")
            body_start = builder.view_position
            builder.text(match.end() - width, source[match.start() + width : match.end() - width])
            builder.span(body_start, builder.view_position, {"bold": "yes"}, "strong")
            builder.hidden(match.end(), "strong")
        elif match.group("italic"):
            builder.hidden(match.start() + 1, "em")
            body_start = builder.view_position
            builder.text(match.end() - 1, source[match.start() + 1 : match.end() - 1])
            builder.span(body_start, builder.view_position, {"italic": "yes"}, "em")
            builder.hidden(match.end(), "em")
        else:
            body_end = match.start("link_body") + len(match.group("link_body"))
            builder.hidden(match.start() + 1, "link")
            body_start = builder.view_position
            builder.text(body_end, source[match.start() + 1 : body_end])
            builder.span(body_start, builder.view_position, {"underline": "yes", "color": "#1a56db"}, "link")
            builder.hidden(match.end(), "link")
        position = match.end()
    if end > position:
        builder.text(end, source[position:end])


class MarkdownRenderedView:
    key = "markdown.rendered"
    label = "Rendered View"
    proportional = True

    def project(self, source: str) -> Projection:
        builder = ProjectionBuilder(self.key)
        in_fence = False
        position = 0
        length = len(source)
        while position < length:
            newline = source.find("\n", position)
            line_end = length if newline == -1 else newline
            next_line = length if newline == -1 else newline + 1
            line = source[position:line_end]
            line_view_start = builder.view_position
            if _FENCE_RE.match(line):
                builder.hidden(line_end, "fence")
                in_fence = not in_fence
            elif in_fence:
                builder.text(line_end, line)
                builder.block(line_view_start, builder.view_position + 1, {"monospace": "yes", "left_margin": "0.25"}, "code")
            else:
                heading = _HEADING_RE.match(line)
                quote = _QUOTE_RE.match(line)
                bullet = _BULLET_RE.match(line)
                if heading:
                    level = len(heading.group(1))
                    builder.hidden(position + heading.end(), "heading")
                    _inline(builder, source, builder.source_position, line_end)
                    builder.block(
                        line_view_start,
                        builder.view_position + 1,
                        {"bold": "yes", "font_scale": _HEADING_SCALE[level], "heading_level": str(level), "space_before": "6"},
                        f"h{level}",
                    )
                elif quote:
                    builder.hidden(position + quote.end(), "quote")
                    _inline(builder, source, builder.source_position, line_end)
                    builder.block(line_view_start, builder.view_position + 1, {"left_margin": "0.3", "muted": "yes", "italic": "yes"}, "quote")
                elif bullet:
                    indent = bullet.group(1)
                    if indent:
                        builder.text(position + len(indent), indent)
                    builder.hidden(position + bullet.end(), "bullet")
                    builder.generated("• ", "bullet")
                    _inline(builder, source, builder.source_position, line_end)
                else:
                    _inline(builder, source, position, line_end)
            if next_line > line_end:
                builder.text(next_line, "\n")
            position = next_line
        return builder.build(length)

    def enter_text(self, source: str, source_offset: int) -> str:
        line_start = source.rfind("\n", 0, source_offset) + 1
        bullet = _BULLET_RE.match(source, line_start)
        if bullet and bullet.end() <= source_offset:
            return "\n" + bullet.group(1) + bullet.group(2) + " "
        return "\n"

    def view_commands(self) -> tuple[ViewCommand, ...]:
        def wrap(delimiter: str):
            def run(source: str, start: int, end: int, _argument: str | None) -> EditPlan:
                if start == end:
                    raise EditRejected("select text to format first")
                return EditPlan(((start, start, delimiter), (end, end, delimiter)), end + 2 * len(delimiter))

            return run

        def heading(source: str, start: int, _end: int, argument: str | None) -> EditPlan:
            line_start = source.rfind("\n", 0, start) + 1
            existing = _HEADING_RE.match(source, line_start)
            old_end = existing.end() if existing else line_start
            level = (argument or "Body").strip()
            prefix = "" if not level.isdigit() else "#" * max(1, min(6, int(level))) + " "
            return EditPlan(((line_start, old_end, prefix),), start + len(prefix) - (old_end - line_start))

        return (
            ViewCommand("bold", "Bold", wrap("**"), shortcut="Ctrl+B"),
            ViewCommand("italic", "Italic", wrap("*"), shortcut="Ctrl+I"),
            ViewCommand("code", "Code", wrap("`")),
            ViewCommand("heading", "Heading…", heading, choices=lambda: ("Body", "1", "2", "3", "4", "5", "6")),
        )


__all__ = ["MarkdownRenderedView"]
