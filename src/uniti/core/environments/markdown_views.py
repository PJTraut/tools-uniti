"""Markdown Rendered View (ADR-0015, spec Phase E10; N28, 2026-11-05).

An editable projection on the same rich-view infrastructure as SFM: syntax
delimiters (``#``, ``**``, ``*``, `` ` ``, ``>``, link brackets/targets,
code fences …) are hidden, list bullets are shown as a protected ``•``, and
headings/emphasis/code/quotes are formatted. Lines map 1:1 to source lines,
so structure never changes behind the user's back.

What Preview recognises follows MD's **Flavour** setting (N31):

- every flavour: bold, italic, code, links, headings, quotes, lists, code
  fences, and the HTML tags `<sup>`, `<sub>` and `<del>` (what the GitHub and
  CommonMark flavours write);
- GitHub and Extended: ``~~strikethrough~~`` and pipe tables;
- GitHub and Extended: task lists (``- [ ]``, ``- [x]``, shown as a box) and
  footnotes (``[^1]`` as a superscript, ``[^1]: text`` with its label);
- Extended (the Markdown Guide cheat sheet): also ``^super^``, ``~sub~``,
  ``==highlight==`` and definition lists (a term, then ``: definition``).

YAML front matter at the start (``---`` … ``---``) is shown as written,
muted and monospace, in every flavour.

A pipe table is shown as an aligned monospace block with its pipes kept
(Q10): padding is generated, so the source isn't touched. Anything
unrecognised stays visible as text — the view degrades to showing source,
never hides it.

The right-click commands (N28) are grouped: character (wrap or unwrap the
selection), paragraph (rewrite the line's prefix) and Insert Table….
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from functools import lru_cache
from itertools import pairwise

from uniti.core.reformatters import align_table, display_width, is_table_start
from uniti.core.rich_views.editing import EditPlan, EditRejected
from uniti.core.rich_views.projection import Projection, ProjectionBuilder
from uniti.core.rich_views.provider import ViewCommand

from .markdown_css import MarkdownStyles, front_matter_end, markdown_styles
from .markdown_environment import COMMONMARK, EXTENDED, GITHUB

_HEADING_RE = re.compile(r"(#{1,6})([ \t]+)")
_QUOTE_RE = re.compile(r">[ \t]?")
_BULLET_RE = re.compile(r"([ \t]*)([-*+])([ \t]+)")
_NUMBERED_RE = re.compile(r"([ \t]*)(\d{1,9})([.)])([ \t]+)")
_FENCE_RE = re.compile(r"[ \t]*(```|~~~)")
# A task list item: a bullet or number, then `[ ]` or `[x]` (GitHub, Extended).
_TASK_RE = re.compile(r"([ \t]*)([-*+]|\d{1,9}[.)])([ \t]+)\[([ xX])\](?:[ \t]+|$)")
# A footnote's text (`[^1]: …`) and a definition (`: …`) under its term.
_FOOTNOTE_DEF_RE = re.compile(r"\[\^([^\]\s]+)\]:[ \t]?")
_DEFINITION_RE = re.compile(r":[ \t]+")
# Any paragraph prefix a paragraph command replaces (a task's box with it).
_BLOCK_PREFIX_RE = re.compile(
    r"#{1,6}[ \t]+|>[ \t]?|[ \t]*(?:[-*+]|\d{1,9}[.)])[ \t]+\[[ xX]\](?:[ \t]+|$)|[ \t]*[-*+][ \t]+|[ \t]*\d{1,9}[.)][ \t]+"
)
_FRONT_MATTER_SPAN = 16 * 1024  # how much of a document front matter may take
_LINK_RE = r"(?P<link>\[)(?P<link_body>[^\]\n]+)\]\((?P<link_target>[^)\n]*)\)"
_FOOTNOTE_REF_RE = r"(?P<fn>\[\^)(?P<fn_label>[^\]\s]+)\]"
_TASK_BOXES = {" ": "☐ ", "x": "☑ ", "X": "☑ "}
# Inline forms: name -> (open, body, close) patterns, the span's fixed look
# (the rest comes from the stylesheets, N27), and the flavours that
# recognise it. `{n}` is the form's name, for the
# backreference a close delimiter repeating the open one needs.
_FORMS: dict[str, tuple[str, str, str, dict[str, str], frozenset[str]]] = {
    "code": (r"`", r"[^`\n]+", r"`", {}, frozenset({EXTENDED, GITHUB, COMMONMARK})),
    # A close isn't the start of a longer run: `***` ends `**b *i***` with
    # the italic's star first.
    "strong": (r"\*\*|__", r"[^\n]+?", r"(?P={n}_o)(?:(?<=\*\*)(?!\*)|(?<=__)(?!_))", {}, frozenset({EXTENDED, GITHUB, COMMONMARK})),
    "del": (r"~~", r"[^~\n]+?", r"~~", {}, frozenset({EXTENDED, GITHUB})),
    "mark": (r"==", r"[^=\n]+?", r"==", {}, frozenset({EXTENDED})),
    "em": (r"[*_]", r"[^*_\n]+?", r"(?P={n}_o)", {}, frozenset({EXTENDED, GITHUB, COMMONMARK})),
    "sup": (r"\^", r"[^\^\s]+", r"\^", {"superscript": "yes"}, frozenset({EXTENDED})),
    "sub": (r"~", r"[^~\s]+", r"~", {"subscript": "yes"}, frozenset({EXTENDED})),
    "html_sup": (r"<sup>", r".+?", r"</sup>", {"superscript": "yes"}, frozenset({EXTENDED, GITHUB, COMMONMARK})),
    "html_sub": (r"<sub>", r".+?", r"</sub>", {"subscript": "yes"}, frozenset({EXTENDED, GITHUB, COMMONMARK})),
    "html_del": (r"<del>", r".+?", r"</del>", {}, frozenset({EXTENDED, GITHUB, COMMONMARK})),
}
# The element (span marker, and CSS element in N27) each form is.
_ELEMENT = {"html_sup": "sup", "html_sub": "sub", "html_del": "del"}
# The character commands: element -> its forms, in every syntax.
_ELEMENT_FORMS = {
    "strong": ("strong",),
    "em": ("em",),
    "del": ("del", "html_del"),
    "sup": ("sup", "html_sup"),
    "sub": ("sub", "html_sub"),
    "code": ("code",),
}


def _form_pattern(name: str) -> str:
    opening, body, closing, _attrs, _flavours = _FORMS[name]
    return (
        f"(?P<{name}_o>{opening.format(n=name)})"
        f"(?P<{name}_b>{body.format(n=name)})"
        f"(?P<{name}_c>{closing.format(n=name)})"
    )


@lru_cache(maxsize=8)
def _inline_re(flavour: str) -> re.Pattern[str]:
    names = [name for name, form in _FORMS.items() if flavour in form[4]]
    footnotes = [_FOOTNOTE_REF_RE] if flavour in (EXTENDED, GITHUB) else []
    return re.compile("|".join(footnotes + [_form_pattern(name) for name in names] + [_LINK_RE]))


def markdown_flavour() -> str:
    """MD's Flavour setting (N31)."""

    from .settings import environment_settings

    flavour = environment_settings("markdown").get("flavour")
    return flavour if flavour in (EXTENDED, GITHUB, COMMONMARK) else EXTENDED


def _inline(builder: ProjectionBuilder, source: str, start: int, end: int, flavour: str, styles: MarkdownStyles) -> None:
    """Project inline content [start, end) of one line (no newline);
    emphasis nests (``**bold *and italic***``)."""

    position = start
    for match in _inline_re(flavour).finditer(source, start, end):
        if match.start() > position:
            builder.text(match.start(), source[position : match.start()])
        if match.groupdict().get("fn") is not None:
            # `[^1]`: the label as a superscript link to the note.
            builder.hidden(match.start("fn_label"), "footnote")
            label_start = builder.view_position
            builder.text(match.end("fn_label"), match.group("fn_label"))
            builder.span(label_start, builder.view_position, {"superscript": "yes", **styles.for_element("sup", "a")}, "footnote")
            builder.hidden(match.end(), "footnote")
        elif match.group("link") is not None:
            body_end = match.start("link_body") + len(match.group("link_body"))
            builder.hidden(match.start() + 1, "link")
            body_start = builder.view_position
            _inline(builder, source, match.start() + 1, body_end, flavour, styles)
            builder.span(body_start, builder.view_position, styles.for_element("a"), "link")
            builder.hidden(match.end(), "link")
        else:
            form = (match.lastgroup or "").removesuffix("_c")
            element = _ELEMENT.get(form, form)
            builder.hidden(match.end(f"{form}_o"), element)
            body_start = builder.view_position
            body_end = match.end(f"{form}_b")
            if form == "code":
                builder.text(body_end, source[match.start(f"{form}_b") : body_end])
            else:
                _inline(builder, source, match.start(f"{form}_b"), body_end, flavour, styles)
            builder.span(body_start, builder.view_position, {**_FORMS[form][3], **styles.for_element(element)}, element)
            builder.hidden(match.end(), element)
        position = match.end()
    if end > position:
        builder.text(end, source[position:end])


def _table_pipes(line: str) -> list[int]:
    """Offsets in `line` of the pipes that separate cells (not an escaped
    pipe, nor one inside `code`)."""

    pipes: list[int] = []
    in_code = False
    index = 0
    while index < len(line):
        char = line[index]
        if char == "\\":
            index += 2
            continue
        if char == "`":
            in_code = not in_code
        elif char == "|" and not in_code:
            pipes.append(index)
        index += 1
    return pipes


def _project_table(builder: ProjectionBuilder, source: str, rows: list[tuple[int, int]], styles: MarkdownStyles) -> None:
    """Pipe-table rows (`(start, end)` source ranges, no newlines) as an
    aligned monospace block: each cell padded with generated spaces (dashes
    in the delimiter row) to its column's width."""

    split: list[list[str]] = []
    for start, end in rows:
        line = source[start:end]
        cuts = [-1, *_table_pipes(line), len(line)]
        split.append([line[a + 1 : b] for a, b in pairwise(cuts)])
    widths: dict[int, int] = {}
    for cells in split:
        for column, cell in enumerate(cells[:-1]):  # the text after the last pipe isn't padded
            widths[column] = max(widths.get(column, 0), display_width(cell))
    for row_index, ((start, end), cells) in enumerate(zip(rows, split)):
        view_start = builder.view_position
        position = start
        for column, cell in enumerate(cells):
            pad = widths.get(column, 0) - display_width(cell) if column < len(cells) - 1 else 0
            if pad > 0 and row_index == 1 and "-" in cell:
                cut = cell.rindex("-") + 1
                builder.text(position + cut, cell[:cut])
                builder.generated("-" * pad, "table")
                if cut < len(cell):
                    builder.text(position + len(cell), cell[cut:])
            else:
                if cell:
                    builder.text(position + len(cell), cell)
                if pad > 0:
                    builder.generated(" " * pad, "table")
            position += len(cell)
            if position < end:
                builder.text(position + 1, "|")
                position += 1
        cell = "th" if row_index == 0 else "td" if row_index > 1 else ""
        builder.block(view_start, builder.view_position + 1, styles.for_element("table", cell), "table")
        if end < len(source):
            builder.text(end + 1, "\n")


def _lines(source: str) -> Iterator[tuple[int, int]]:
    """(start, end) of each line, end before its newline."""

    position = 0
    length = len(source)
    while position <= length:
        newline = source.find("\n", position)
        end = length if newline == -1 else newline
        yield position, end
        if newline == -1:
            return
        position = newline + 1


class MarkdownRenderedView:
    key = "markdown.rendered"
    label = "Preview"
    proportional = True
    # No Bold/Italic/… buttons on the pane's top bar (field test, 2026-10-26):
    # the commands stay on the right-click menu and their shortcuts.
    command_buttons = False

    def __init__(
        self,
        flavour: str | None = None,
        styles: Callable[[str], MarkdownStyles] | None = None,
    ) -> None:
        self._flavour = flavour  # None: MD's Flavour setting, read each time
        # source -> the cascaded stylesheets (N27); by default the built-in
        # and the user's, without a document's own.
        self._styles = styles or (lambda _source: markdown_styles(None, ""))
        self.notes: tuple[str, ...] = ()  # what the stylesheets had that Preview ignores
        self._front = ""  # the head of the last source projected (its front matter)
        self._token: tuple | None = None

    def cache_token(self) -> tuple:
        """For the rich view's projection cache: the same object while the
        flavour and the stylesheets are unchanged, a new one when either
        changes (a saved `.css`, a new Flavour), so Preview re-projects."""

        candidate = (self.flavour, self._styles(self._front))
        if candidate != self._token:
            self._token = candidate
        return self._token

    @property
    def flavour(self) -> str:
        return self._flavour or markdown_flavour()

    def project(self, source: str) -> Projection:
        flavour = self.flavour
        self._front = source[:_FRONT_MATTER_SPAN]
        styles = self._styles(source)
        self.notes = styles.notes
        builder = ProjectionBuilder(self.key)
        lines = list(_lines(source))
        texts = [source[start:end] for start, end in lines]
        tables = tasks = footnotes = flavour in (EXTENDED, GITHUB)
        definitions = flavour == EXTENDED
        in_fence = False
        index = 0
        # YAML front matter: shown as written, muted monospace (it isn't
        # Markdown; its `stylesheet:` entry is read by N27's cascade).
        matter_end = front_matter_end(self._front)
        while matter_end is not None and index < len(lines) and lines[index][0] <= matter_end:
            position, line_end = lines[index]
            line_view_start = builder.view_position
            builder.text(line_end, texts[index])
            builder.block(line_view_start, builder.view_position + 1, {"monospace": "yes", "muted": "yes"}, "front_matter")
            if line_end < len(source):
                builder.text(line_end + 1, "\n")
            index += 1

        def is_definition(at: int) -> bool:
            return (
                definitions
                and 0 < at < len(texts)
                and _DEFINITION_RE.match(texts[at]) is not None
                and bool(texts[at - 1].strip())
            )

        while index < len(lines):
            position, line_end = lines[index]
            line = texts[index]
            if not in_fence and tables and is_table_start(texts, index):
                last = index + 1
                while last + 1 < len(lines) and "|" in texts[last + 1] and texts[last + 1].strip():
                    last += 1
                _project_table(builder, source, lines[index : last + 1], styles)
                index = last + 1
                continue
            line_view_start = builder.view_position
            if _FENCE_RE.match(line):
                builder.hidden(line_end, "fence")
                in_fence = not in_fence
            elif in_fence:
                builder.text(line_end, line)
                builder.block(line_view_start, builder.view_position + 1, styles.for_element("pre"), "pre")
            else:
                heading = _HEADING_RE.match(line)
                quote = _QUOTE_RE.match(line)
                bullet = _BULLET_RE.match(line)
                numbered = _NUMBERED_RE.match(line)
                task = _TASK_RE.match(line) if tasks else None
                note = _FOOTNOTE_DEF_RE.match(line) if footnotes else None
                if task:
                    indent, marker = task.group(1), task.group(2)
                    box_start = position + task.start(4) - 1  # the `[`
                    if marker[0].isdigit():
                        builder.text(box_start, line[: task.start(4) - 1])  # the number stays visible
                    elif indent:
                        builder.text(position + len(indent), indent)
                    builder.hidden(position + task.end(), "task")
                    builder.generated(_TASK_BOXES[task.group(4)], "task")
                    _inline(builder, source, builder.source_position, line_end, flavour, styles)
                    list_element = "ol" if marker[0].isdigit() else "ul"
                    builder.block(line_view_start, builder.view_position + 1, styles.for_element(list_element, "li"), "task")
                elif note:
                    # `[^1]: text`: the label as a superscript, then the text.
                    builder.hidden(position + note.start(1), "footnote")
                    label_start = builder.view_position
                    builder.text(position + note.end(1), note.group(1))
                    builder.span(label_start, builder.view_position, {"superscript": "yes", **styles.for_element("sup")}, "footnote")
                    builder.hidden(position + note.end(), "footnote")
                    builder.generated(" ", "footnote")
                    _inline(builder, source, builder.source_position, line_end, flavour, styles)
                    builder.block(line_view_start, builder.view_position + 1, styles.for_element("li"), "footnote")
                elif is_definition(index):
                    definition = _DEFINITION_RE.match(line)
                    builder.hidden(position + definition.end(), "definition")
                    _inline(builder, source, builder.source_position, line_end, flavour, styles)
                    builder.block(line_view_start, builder.view_position + 1, styles.for_element("dd"), "dd")
                elif heading:
                    level = len(heading.group(1))
                    builder.hidden(position + heading.end(), "heading")
                    _inline(builder, source, builder.source_position, line_end, flavour, styles)
                    builder.block(
                        line_view_start,
                        builder.view_position + 1,
                        {**styles.for_element(f"h{level}"), "heading_level": str(level)},
                        f"h{level}",
                    )
                elif quote:
                    builder.hidden(position + quote.end(), "quote")
                    _inline(builder, source, builder.source_position, line_end, flavour, styles)
                    builder.block(line_view_start, builder.view_position + 1, styles.for_element("blockquote"), "quote")
                elif bullet and not _is_rule(line):
                    indent = bullet.group(1)
                    if indent:
                        builder.text(position + len(indent), indent)
                    builder.hidden(position + bullet.end(), "bullet")
                    builder.generated("• ", "bullet")
                    _inline(builder, source, builder.source_position, line_end, flavour, styles)
                    builder.block(line_view_start, builder.view_position + 1, styles.for_element("ul", "li"), "li")
                elif numbered:
                    # The number stays visible and editable.
                    builder.text(position + numbered.end(), line[: numbered.end()])
                    _inline(builder, source, builder.source_position, line_end, flavour, styles)
                    builder.block(line_view_start, builder.view_position + 1, styles.for_element("ol", "li"), "li")
                elif _is_rule(line):
                    builder.text(line_end, line)
                    builder.block(line_view_start, builder.view_position + 1, styles.for_element("hr"), "hr")
                elif line.strip() and is_definition(index + 1):
                    # A term: the plain line just above its first definition.
                    _inline(builder, source, position, line_end, flavour, styles)
                    builder.block(line_view_start, builder.view_position + 1, styles.for_element("dt"), "dt")
                else:
                    _inline(builder, source, position, line_end, flavour, styles)
                    if line.strip():
                        builder.block(line_view_start, builder.view_position + 1, styles.for_element("p"), "p")
            if line_end < len(source):
                builder.text(line_end + 1, "\n")
            index += 1
        return builder.build(len(source))

    def enter_text(self, source: str, source_offset: int) -> str:
        line_start = source.rfind("\n", 0, source_offset) + 1
        task = _TASK_RE.match(source, line_start) if self.flavour in (EXTENDED, GITHUB) else None
        if task and task.end() <= source_offset:
            indent, marker = task.group(1), task.group(2)
            if marker[0].isdigit():
                marker = f"{int(marker[:-1]) + 1}{marker[-1]}"
            return f"\n{indent}{marker} [ ] "
        bullet = _BULLET_RE.match(source, line_start)
        if bullet and bullet.end() <= source_offset:
            return "\n" + bullet.group(1) + bullet.group(2) + " "
        numbered = _NUMBERED_RE.match(source, line_start)
        if numbered and numbered.end() <= source_offset:
            indent, number, delimiter, _space = numbered.groups()
            return f"\n{indent}{int(number) + 1}{delimiter} "
        return "\n"

    # --- commands (N28) ---------------------------------------------------------

    def view_commands(self) -> tuple[ViewCommand, ...]:
        def character(element: str):
            def run(source: str, start: int, end: int, _argument: str | None) -> EditPlan:
                return toggle_inline(source, start, end, element, self.flavour)

            return run

        def remove(source: str, start: int, end: int, _argument: str | None) -> EditPlan:
            return remove_formatting(source, start, end)

        def paragraph(kind: str):
            def run(source: str, start: int, end: int, _argument: str | None) -> EditPlan:
                if kind == "task" and self.flavour == COMMONMARK:
                    raise EditRejected("CommonMark has no task lists: choose Extended or GitHub in Environment Settings…")
                return set_paragraph(source, start, end, kind)

            return run

        def check_task(source: str, start: int, end: int, _argument: str | None) -> EditPlan:
            return toggle_task_done(source, start, end)

        def heading(source: str, start: int, end: int, argument: str | None) -> EditPlan:
            return set_paragraph(source, start, end, _heading_kind(argument))

        def code_block(source: str, start: int, end: int, _argument: str | None) -> EditPlan:
            return toggle_code_block(source, start, end)

        def table(source: str, start: int, _end: int, argument: str | None) -> EditPlan:
            return insert_table(source, start, argument, self.flavour)

        return (
            ViewCommand("bold", "Bold", character("strong"), shortcut="Ctrl+B", group="character"),
            ViewCommand("italic", "Italic", character("em"), shortcut="Ctrl+I", group="character"),
            ViewCommand("strikethrough", "Strikethrough", character("del"), group="character"),
            ViewCommand("superscript", "Superscript", character("sup"), group="character"),
            ViewCommand("subscript", "Subscript", character("sub"), group="character"),
            ViewCommand("code", "Code", character("code"), group="character"),
            ViewCommand("remove_formatting", "Remove Formatting", remove, group="character"),
            ViewCommand(
                "heading",
                "Headings",
                heading,
                choices=lambda: HEADING_CHOICES,
                group="paragraph",
                submenu=True,
                current=current_heading,
            ),
            ViewCommand("quote", "Quote", paragraph("quote"), group="paragraph"),
            ViewCommand("bullet_list", "Bullet List", paragraph("bullet"), group="paragraph"),
            ViewCommand("numbered_list", "Numbered List", paragraph("numbered"), group="paragraph"),
            ViewCommand("task_list", "Task List", paragraph("task"), group="paragraph"),
            ViewCommand("check_task", "Check or Uncheck Task", check_task, group="paragraph"),
            ViewCommand("indent_list", "Indent List Item", lambda s, a, b, _x: indent_list_lines(s, a, b), group="paragraph"),
            ViewCommand(
                "outdent_list", "Outdent List Item", lambda s, a, b, _x: indent_list_lines(s, a, b, True), group="paragraph"
            ),
            ViewCommand("code_block", "Code Block", code_block, group="paragraph"),
            ViewCommand(
                "insert_table",
                "Insert Table…",
                table,
                prompt="Columns × rows (for example 3 × 2):",
                group="insert",
            ),
        )


def _is_rule(line: str) -> bool:
    stripped = line.replace(" ", "").replace("\t", "")
    return len(stripped) >= 3 and len(set(stripped)) == 1 and stripped[0] in "-*_"


# --- character commands --------------------------------------------------------

_DELIMITERS = {
    # element -> {flavour: (open, close)}
    "strong": {EXTENDED: ("**", "**"), GITHUB: ("**", "**"), COMMONMARK: ("**", "**")},
    "em": {EXTENDED: ("*", "*"), GITHUB: ("*", "*"), COMMONMARK: ("*", "*")},
    "del": {EXTENDED: ("~~", "~~"), GITHUB: ("~~", "~~"), COMMONMARK: ("<del>", "</del>")},
    "sup": {EXTENDED: ("^", "^"), GITHUB: ("<sup>", "</sup>"), COMMONMARK: ("<sup>", "</sup>")},
    "sub": {EXTENDED: ("~", "~"), GITHUB: ("<sub>", "</sub>"), COMMONMARK: ("<sub>", "</sub>")},
    "code": {EXTENDED: ("`", "`"), GITHUB: ("`", "`"), COMMONMARK: ("`", "`")},
}


def _line_bounds(source: str, offset: int) -> tuple[int, int]:
    start = source.rfind("\n", 0, offset) + 1
    end = source.find("\n", offset)
    return start, len(source) if end == -1 else end


def _parse_runs(source: str, start: int, end: int) -> Iterator[re.Match[str]]:
    """Every inline run in [start, end), nested ones too, parsed as Preview
    parses them, in the Extended flavour (which knows every form)."""

    for match in _inline_re(EXTENDED).finditer(source, start, end):
        if match.group("fn") is not None:
            continue  # a footnote reference isn't formatting
        if match.group("link") is not None:
            yield from _parse_runs(source, match.start("link_body"), match.end("link_body"))
            continue
        yield match
        form = _form_of(match)
        if form != "code":
            yield from _parse_runs(source, match.start(f"{form}_b"), match.end(f"{form}_b"))


def _runs(source: str, start: int, end: int, forms) -> list[re.Match[str]]:
    """The runs of `forms` on the lines of [start, end]."""

    first, _ = _line_bounds(source, start)
    _, last = _line_bounds(source, end)
    wanted = set(forms)
    return [match for match in _parse_runs(source, first, last) if _form_of(match) in wanted]


def _form_of(match: re.Match[str]) -> str:
    groups = match.groupdict()
    return next(name for name in _FORMS if groups.get(f"{name}_o") is not None)


def _unwrap(matches: list[re.Match[str]], caret: int) -> EditPlan:
    """Remove each match's delimiters; `caret` follows the text."""

    cuts: list[tuple[int, int]] = []
    for match in matches:
        form = _form_of(match)
        cuts.append((match.start(f"{form}_o"), match.end(f"{form}_o")))
        cuts.append((match.start(f"{form}_c"), match.end(f"{form}_c")))
    kept: list[tuple[int, int]] = []
    for cut in sorted(set(cuts)):
        if kept and cut[0] < kept[-1][1]:
            continue  # overlapping delimiters (`***`): keep the first
        kept.append(cut)
    removed_before = sum(min(b, caret) - a for a, b in kept if a < caret)
    return EditPlan(tuple((a, b, "") for a, b in kept), caret - removed_before)


def toggle_inline(source: str, start: int, end: int, element: str, flavour: str) -> EditPlan:
    """Wrap the selection in `element`'s delimiters, or, inside (or over) a
    run that already has it, remove them."""

    forms = _ELEMENT_FORMS[element]
    for match in _runs(source, start, end, forms):
        form = _form_of(match)
        inside = match.start(f"{form}_b") <= start and end <= match.end(f"{form}_b")
        over = start < end and start <= match.start() and match.end() <= end
        if inside or over:
            return _unwrap([match], end)
    if start == end:
        raise EditRejected("select text to format first")
    opening, closing = _DELIMITERS[element].get(flavour, _DELIMITERS[element][EXTENDED])
    replacements: list[tuple[int, int, str]] = []
    caret = end
    line_start = start
    while line_start < end:
        line_end = source.find("\n", line_start, end)
        line_end = end if line_end == -1 else line_end
        piece = source[line_start:line_end]
        left = line_start + len(piece) - len(piece.lstrip())
        right = line_start + len(piece.rstrip())
        if right > left:  # delimiters hug the text, never spaces
            replacements.append((left, left, opening))
            replacements.append((right, right, closing))
            caret += len(opening) + (len(closing) if right <= end else 0)
        line_start = line_end + 1
    if not replacements:
        raise EditRejected("select text to format first")
    return EditPlan(tuple(replacements), caret)


def remove_formatting(source: str, start: int, end: int) -> EditPlan:
    """Strip every inline delimiter (not links) in the selection, or of the
    runs around the caret."""

    found = [
        match
        for match in _runs(source, start, end, tuple(_FORMS))
        if (match.start() < start < match.end() if start == end else match.start() < end and start < match.end())
    ]
    if not found:
        raise EditRejected("no formatting to remove here")
    return _unwrap(found, end)


# --- paragraph commands --------------------------------------------------------

HEADING_CHOICES = ("Body Text", "H1", "H2", "H3", "H4", "H5", "H6")


def _heading_kind(argument: str | None) -> str:
    value = (argument or "Body").strip().upper().removeprefix("H").removeprefix("EADING ").strip()
    if value.isdigit():
        return f"h{max(1, min(6, int(value)))}"
    return "body"


def current_heading(source: str, offset: int) -> str | None:
    """The Headings choice of the caret's line: H1–H6, Body Text for a plain
    paragraph, else None (a quote, a list item, code)."""

    line_start, line_end = _line_bounds(source, offset)
    line = source[line_start:line_end]
    if _in_fence(source, line_start):
        return None
    heading = _HEADING_RE.match(line)
    if heading:
        return f"H{len(heading.group(1))}"
    if _BLOCK_PREFIX_RE.match(line):
        return None
    return "Body Text"


def _in_fence(source: str, line_start: int) -> bool:
    inside = False
    for start, end in _lines(source[:line_start]):
        if _FENCE_RE.match(source, start, end) and start < line_start:
            inside = not inside
    return inside


def _kind_of(line: str) -> str:
    if _HEADING_RE.match(line):
        return f"h{len(_HEADING_RE.match(line).group(1))}"
    if _QUOTE_RE.match(line):
        return "quote"
    if _TASK_RE.match(line):
        return "task"
    if _BULLET_RE.match(line) and not _is_rule(line):
        return "bullet"
    if _NUMBERED_RE.match(line):
        return "numbered"
    return "body"


def set_paragraph(source: str, start: int, end: int, kind: str) -> EditPlan:
    """Give the selected lines paragraph `kind` (body, h1–h6, quote, bullet,
    numbered, task), replacing any prefix they have. A quote or list
    command on lines that are all that kind already makes them body text."""

    first, _ = _line_bounds(source, start)
    _, last = _line_bounds(source, end)
    spans = [(a, b) for a, b in _lines(source) if first <= a <= last]
    if kind in ("quote", "bullet", "numbered", "task") and all(_kind_of(source[a:b]) == kind for a, b in spans if b > a):
        kind = "body"
    replacements: list[tuple[int, int, str]] = []
    shift = 0  # how far the caret (at `end`) moves
    number = 1
    for a, b in spans:
        line = source[a:b]
        if not line.strip() and len(spans) > 1:
            continue
        prefix = _BLOCK_PREFIX_RE.match(line)
        old_end = a + (prefix.end() if prefix and not _is_rule(line) else 0)
        indent = line[: len(line) - len(line.lstrip(" \t"))] if kind in ("bullet", "numbered", "task") else ""
        if kind == "body":
            new = ""
        elif kind.startswith("h"):
            new = "#" * int(kind[1]) + " "
        elif kind == "quote":
            new = "> "
        elif kind == "bullet":
            new = f"{indent}- "
        elif kind == "task":
            new = f"{indent}- [ ] "
        else:
            new = f"{indent}{number}. "
            number += 1
        replacements.append((a, old_end, new))
        if old_end <= end:
            shift += len(new) - (old_end - a)
        elif a <= end:  # the caret was in the old prefix: it lands after the new one
            shift += len(new) - (end - a)
    return EditPlan(tuple(replacements), end + shift)


def indent_list_lines(source: str, start: int, end: int, outdent: bool = False) -> EditPlan:
    """Move every list item on the selected lines one level in (Tab) or out
    (Shift+Tab), together. A level is two spaces under a bullet or task, three
    under a number, the width of its marker, so the item nests under its
    parent. Lines that aren't list items are left alone; no list item at all
    is rejected."""

    first, _ = _line_bounds(source, start)
    _, last = _line_bounds(source, end)
    replacements: list[tuple[int, int, str]] = []
    shift = 0  # how far the caret (at `end`) moves
    items = 0
    for a, b in _lines(source):
        if not first <= a <= last:
            continue
        line = source[a:b]
        if _is_rule(line) or _in_fence(source, a):
            continue
        numbered = _NUMBERED_RE.match(line)
        if not (_BULLET_RE.match(line) or numbered):
            continue
        items += 1
        width = 3 if numbered else 2
        leading = len(line) - len(line.lstrip(" \t"))
        if not outdent:
            replacements.append((a, a, " " * width))
            change = width
        else:
            indent = line[:leading]
            cut = 1 if indent.startswith("\t") else min(width, len(indent) - len(indent.lstrip(" ")))
            if cut == 0:
                continue
            replacements.append((a, a + cut, ""))
            change = -cut
        if a <= end:
            shift += change
    if not items:
        raise EditRejected("no list item here")
    return EditPlan(tuple(replacements), max(first, end + shift))


def toggle_task_done(source: str, start: int, end: int) -> EditPlan:
    """Check the selected task items, or, when they're all checked already,
    uncheck them. The caret doesn't move: a box is one character."""

    first, _ = _line_bounds(source, start)
    _, last = _line_bounds(source, end)
    boxes = [
        (task.start(4), task.group(4))
        for a, b in _lines(source)
        if first <= a <= last and (task := _TASK_RE.match(source, a, b)) is not None
    ]
    if not boxes:
        raise EditRejected("no task list item here")
    mark = " " if all(box != " " for _, box in boxes) else "x"
    return EditPlan(tuple((offset, offset + 1, mark) for offset, box in boxes if box != mark), end)


def toggle_code_block(source: str, start: int, end: int) -> EditPlan:
    """Fence the selected lines with ``` — or, inside a fenced block,
    remove its fences."""

    first, _ = _line_bounds(source, start)
    lines = list(_lines(source))
    opening = None
    for index, (a, b) in enumerate(lines):
        if a > first:
            break
        if _FENCE_RE.match(source, a, b):
            opening = None if opening is not None else index
    if opening is not None:
        closing = next((i for i in range(opening + 1, len(lines)) if _FENCE_RE.match(source, *lines[i])), None)
        a, _b = lines[opening]
        open_next = lines[opening + 1][0] if opening + 1 < len(lines) else len(source)
        cuts = [(a, open_next)]
        if closing is not None:
            c, d = lines[closing]
            cuts.append((c - 1 if c > 0 else c, d))
        removed_before = sum(min(y, end) - x for x, y in cuts if x < end)
        return EditPlan(tuple((x, y, "") for x, y in cuts), max(0, end - removed_before))
    _, last = _line_bounds(source, end)
    return EditPlan(((first, first, "```\n"), (last, last, "\n```")), end + 4)


# --- Insert Table… -------------------------------------------------------------

_SIZE_RE = re.compile(r"\s*(\d{1,2})\s*(?:[x×X*,]|by)\s*(\d{1,3})\s*")


def insert_table(source: str, offset: int, argument: str | None, flavour: str) -> EditPlan:
    """A pipe table of `argument` ("3 × 2": columns × body rows) with a
    header row, on its own lines after the caret's line."""

    if flavour == COMMONMARK:
        raise EditRejected("CommonMark has no tables: choose Extended or GitHub in Environment Settings…")
    size = _SIZE_RE.fullmatch(argument or "")
    if size is None:
        raise EditRejected("give the size as columns × rows, for example 3 × 2")
    columns, rows = int(size.group(1)), int(size.group(2))
    if not (1 <= columns <= 20 and 1 <= rows <= 100):
        raise EditRejected("a table can have 1–20 columns and 1–100 rows")
    header = "| " + " | ".join(f"Column {n}" for n in range(1, columns + 1)) + " |"
    delimiter = "|" + "|".join("---" for _ in range(columns)) + "|"
    body = ["|" + "|".join("" for _ in range(columns)) + "|" for _ in range(rows)]
    table = "\n".join(align_table([header, delimiter, *body]))
    line_start, line_end = _line_bounds(source, offset)
    following = source[line_end + 1 : source.find("\n", line_end + 1) if "\n" in source[line_end + 1 :] else len(source)]
    after = "\n" if line_end < len(source) and following.strip() else ""  # a blank line before the next text
    if source[line_start:line_end].strip():
        # After the caret's line, with a blank line between.
        return EditPlan(((line_end, line_end, "\n\n" + table + after),), line_end + 4)
    # On the caret's empty line.
    return EditPlan(((line_start, line_end, table + after),), line_start + 2)


__all__ = [
    "HEADING_CHOICES",
    "MarkdownRenderedView",
    "current_heading",
    "insert_table",
    "markdown_flavour",
    "remove_formatting",
    "set_paragraph",
    "toggle_code_block",
    "toggle_inline",
    "toggle_task_done",
]
