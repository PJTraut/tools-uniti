"""Whole-document reformatters for structured text (BF-061).

Text/whitespace reformatting only — re-indentation and spacing
normalization. Not AST-aware structural refactors (no key sorting, tag
rename, heading promotion, etc.); that would be a materially larger,
separately-scoped effort. JSON and XML validate first: an invalid/malformed
document raises `ReformatFailure` with the parser's reported position and is
never partially rewritten. Markdown has no strict grammar to fail against,
so its formatter always succeeds.

Formatting requires the complete document text in memory (a real tree for
JSON/XML, whole-document context for Markdown's blank-line collapsing) —
callers must apply `MAX_REFORMAT_CHARS` themselves before reading a whole
document into memory; this module does not enforce it, since it operates on
plain strings without any document/size context.
"""

from __future__ import annotations

import json
import re
import unicodedata
import xml.dom.minidom
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from xml.parsers.expat import ExpatError

# Structured documents (config files, API payloads, short docs) are not
# UNITI's giant-log-file use case, but formatting still needs the whole
# document in memory (see module docstring) — this bounds that cost. Counted
# in characters, not bytes, for simplicity.
MAX_REFORMAT_CHARS = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ReformatError:
    message: str
    line: int | None
    column: int | None


class ReformatFailure(Exception):
    """Raised by a reformatter's `format`/`minify` on invalid input."""

    def __init__(self, error: ReformatError) -> None:
        super().__init__(error.message)
        self.error = error


@dataclass(frozen=True, slots=True)
class Reformatter:
    key: str
    label: str
    # format(text, options): `options` are the environment's settings (N31).
    format: Callable[[str, Mapping[str, object] | None], str]
    minify: Callable[[str], str] | None

    @property
    def can_minify(self) -> bool:
        return self.minify is not None


def _indent_option(options: Mapping[str, object] | None, default: int = 2) -> int:
    indent = _option(options, "indent", default)
    if not isinstance(indent, int) or isinstance(indent, bool) or not 1 <= indent <= 8:
        return default
    return indent


def _format_json(text: str, options: Mapping[str, object] | None = None) -> str:
    """JSON's Format Document; `options` are JSON's Environment Settings
    (N31): indent, sort_keys, ascii."""

    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReformatFailure(ReformatError(exc.msg, exc.lineno, exc.colno)) from exc
    return (
        json.dumps(
            value,
            indent=_indent_option(options),
            sort_keys=_option(options, "sort_keys", False) is True,
            ensure_ascii=_option(options, "ascii", False) is True,
        )
        + "\n"
    )


def _minify_json(text: str) -> str:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReformatFailure(ReformatError(exc.msg, exc.lineno, exc.colno)) from exc
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _parse_xml(text: str) -> xml.dom.minidom.Document:
    # `xml.dom.minidom` is used instead of `xml.etree.ElementTree` because
    # ElementTree silently drops comments and processing instructions on
    # parse — an unacceptable fidelity loss for a "reformat my file"
    # feature. minidom preserves comments, CDATA, and processing
    # instructions in its DOM tree.
    try:
        return xml.dom.minidom.parseString(text)
    except ExpatError as exc:
        column = None if exc.offset is None else exc.offset + 1
        raise ReformatFailure(ReformatError(str(exc), exc.lineno, column)) from exc


def _meaningful_children(node) -> list:
    """`node`'s children, excluding purely-whitespace text nodes — those are
    formatting artifacts of the original source, not meaningful content."""

    Node = xml.dom.minidom.Node
    return [
        child
        for child in node.childNodes
        if not (child.nodeType == Node.TEXT_NODE and child.data.strip() == "")
    ]


def _has_significant_text(children: list) -> bool:
    Node = xml.dom.minidom.Node
    for child in children:
        if child.nodeType == Node.CDATA_SECTION_NODE:
            return True
        if child.nodeType == Node.TEXT_NODE and child.data.strip() != "":
            return True
    return False


def _open_tag(element, pad: str = "", wrap: bool = False) -> str:
    # Reuse minidom's own attribute-escaping by cloning the element without
    # children (renders self-closed) rather than reimplementing it.
    clone = element.cloneNode(False)
    self_closed = clone.toxml()
    tag = self_closed[:-2] + ">"
    if not wrap or element.attributes.length < 2:
        return tag
    # One attribute per line, lined up under the first (XML's "Attributes"
    # setting, N31). Each is rendered by minidom too, alone on a clone.
    rendered = []
    for name in element.attributes.keys():
        alone = element.ownerDocument.createElement(element.tagName)
        alone.setAttribute(name, element.getAttribute(name))
        rendered.append(alone.toxml()[len(element.tagName) + 2 : -2])
    hang = "\n" + pad + " " * (len(element.tagName) + 2)
    return f"<{element.tagName} " + hang.join(rendered) + ">"


def _render_xml_node(node, depth: int, indent: str, out: list[str], wrap: bool = False) -> None:
    Node = xml.dom.minidom.Node
    pad = indent * depth
    if node.nodeType == Node.ELEMENT_NODE:
        children = _meaningful_children(node)
        if not children or _has_significant_text(children):
            # Empty, text-only, or mixed content: reformatting inside would
            # change meaning (added whitespace becomes part of the text), so
            # this element's contents are kept exactly as written; only its
            # position among siblings is indented.
            out.append(f"{pad}{node.toxml()}")
            return
        out.append(f"{pad}{_open_tag(node, pad, wrap)}")
        for child in children:
            _render_xml_node(child, depth + 1, indent, out, wrap)
        out.append(f"{pad}</{node.tagName}>")
    else:
        # Comments, processing instructions, DOCTYPE, and any other node
        # type are reproduced verbatim, only indented.
        out.append(f"{pad}{node.toxml()}")


_XML_DECLARATION_RE = re.compile(r"^\s*(<\?xml[^>]*\?>)")


def _format_xml(text: str, options: Mapping[str, object] | None = None) -> str:
    """XML's Format Document; `options` are XML's Environment Settings
    (N31): indent, attributes ("one-line" or "wrapped")."""

    dom = _parse_xml(text)
    indent = " " * _indent_option(options)
    wrap = _option(options, "attributes", "one-line") == "wrapped"
    out: list[str] = []
    # The original declaration (with its exact encoding/standalone
    # attributes, if any) is reused verbatim rather than minidom's
    # regenerated one, which always emits a bare `version="1.0"` and would
    # silently drop an explicit `encoding=`/`standalone=` the source had.
    declaration_match = _XML_DECLARATION_RE.match(text)
    if declaration_match:
        out.append(declaration_match.group(1))
    for child in dom.childNodes:
        _render_xml_node(child, 0, indent, out, wrap)
    return "\n".join(out) + "\n"


_INTER_TAG_WHITESPACE_RE = re.compile(r">\s+<")


def _minify_xml(text: str) -> str:
    dom = _parse_xml(text)
    # minidom's `toxml()` always prepends its own regenerated declaration
    # (bare `version="1.0"`, dropping any `encoding=`/`standalone=`); drop
    # it here too and reuse the original verbatim, matching `_format_xml`.
    compact = dom.toxml()
    if compact.startswith("<?xml"):
        compact = compact.split("?>", 1)[1]
    declaration_match = _XML_DECLARATION_RE.match(text)
    if declaration_match:
        compact = declaration_match.group(1) + compact
    # A "safe minify": only purely-whitespace text nodes between tags are
    # collapsed. Whitespace inside any other text content is left alone,
    # since XML whitespace can be significant there (mixed content,
    # `xml:space="preserve"`). This does not guarantee minimum byte size.
    return _INTER_TAG_WHITESPACE_RE.sub("><", compact)


_ATX_HEADING_RE = re.compile(r"^(#{1,6})(?:[ \t]*(.*?))?[ \t]*#*[ \t]*$")
_LIST_BULLET_RE = re.compile(r"^(\s*)[-*+]([ \t]+)")
_THEMATIC_BREAK_RE = re.compile(r"^\s*([-*_])(?:[ \t]*\1){2,}[ \t]*$")
_NUMBERED_RE = re.compile(r"^(\s*)(\d{1,9})([.)])([ \t]+)")
_TABLE_DELIMITER_CELL_RE = re.compile(r"^\s*:?-+:?\s*$")
_FENCE_MARKERS = ("```", "~~~")
# The emphasis forms Preview recognises (markdown_views), outside code spans.
_STRONG_RE = re.compile(r"(?<![\w*_])(\*\*|__)(?=\S)(.+?)(?<=\S)\1(?![\w*_])")
_EMPHASIS_RE = re.compile(r"(?<![\w*_])([*_])(?=[^\s*_])([^*_\n]+?)(?<=[^\s*_])\1(?![\w*_])")
AS_WRITTEN = "as-written"


def _option(options: Mapping[str, object] | None, key: str, default: object) -> object:
    if options is None:
        return default
    return options.get(key, default)


def _outside_code_spans(line: str, change: Callable[[str], str]) -> str:
    """`change` applied to the parts of `line` outside `code` spans."""

    parts = re.split(r"(`+[^`]*`+)", line)
    return "".join(part if index % 2 else change(part) for index, part in enumerate(parts))


def _normalise_emphasis(line: str, emphasis: object, strong: object) -> str:
    if emphasis not in ("*", "_") and strong not in ("**", "__"):
        return line

    def change(part: str) -> str:
        if strong in ("**", "__"):
            part = _STRONG_RE.sub(lambda m: f"{strong}{m.group(2)}{strong}", part)
        if emphasis in ("*", "_"):
            part = _EMPHASIS_RE.sub(lambda m: f"{emphasis}{m.group(2)}{emphasis}", part)
        return part

    return _outside_code_spans(line, change)


def display_width(text: str) -> int:
    """Columns `text` takes in a monospace font (wide CJK counts 2)."""

    width = 0
    for char in text:
        if unicodedata.combining(char) or unicodedata.category(char) in ("Mn", "Me", "Cf"):
            continue
        width += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return width


def table_cells(line: str) -> list[str]:
    """A pipe-table row's cells, stripped; an escaped pipe and pipes inside
    `code` don't split."""

    body = line.strip()
    body = body.removeprefix("|")
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    cells: list[str] = []
    current: list[str] = []
    in_code = False
    index = 0
    while index < len(body):
        char = body[index]
        if char == "\\" and index + 1 < len(body):
            current.append(body[index : index + 2])
            index += 2
            continue
        if char == "`":
            in_code = not in_code
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(char)
        index += 1
    cells.append("".join(current).strip())
    return cells


def is_table_delimiter(line: str) -> bool:
    """A pipe table's second row: `| --- | :-: |`."""

    if "-" not in line or "|" not in line:
        return False
    cells = table_cells(line)
    return bool(cells) and all(_TABLE_DELIMITER_CELL_RE.match(cell) for cell in cells)


def is_table_start(lines: list[str], index: int) -> bool:
    """Whether `lines[index]` is a pipe table's header row."""

    return (
        "|" in lines[index]
        and index + 1 < len(lines)
        and is_table_delimiter(lines[index + 1])
        and len(table_cells(lines[index])) == len(table_cells(lines[index + 1]))
    )


def align_table(rows: list[str]) -> list[str]:
    """A pipe table (header, delimiter, body rows) with padded columns,
    each cell aligned as its delimiter's colons say."""

    table = [table_cells(row) for row in rows]
    columns = max(len(cells) for cells in table)
    for cells in table:
        cells.extend([""] * (columns - len(cells)))
    alignments = [(cell.startswith(":"), cell.endswith(":")) for cell in table[1]]
    widths = [3] * columns
    for row_index, cells in enumerate(table):
        if row_index != 1:
            for column, cell in enumerate(cells):
                widths[column] = max(widths[column], display_width(cell))
    out = []
    for row_index, cells in enumerate(table):
        rendered = []
        for column, cell in enumerate(cells):
            width = widths[column]
            left, right = alignments[column]
            if row_index == 1:
                rendered.append(f"{':' if left else ''}{'-' * (width - left - right)}{':' if right else ''}")
                continue
            pad = width - display_width(cell)
            if left and right:
                rendered.append(" " * (pad // 2) + cell + " " * (pad - pad // 2))
            elif right:
                rendered.append(" " * pad + cell)
            else:
                rendered.append(cell + " " * pad)
        out.append("| " + " | ".join(rendered) + " |")
    return out


def _format_markdown(text: str, options: Mapping[str, object] | None = None) -> str:
    """Markdown's Format Document. `options` are MD's Environment Settings
    (N31): bullet, emphasis, strong, numbering, blank_lines, align_tables."""

    bullet = _option(options, "bullet", "-")
    emphasis = _option(options, "emphasis", AS_WRITTEN)
    strong = _option(options, "strong", AS_WRITTEN)
    numbering = _option(options, "numbering", AS_WRITTEN)
    most_blank = _option(options, "blank_lines", 1)
    align_tables = _option(options, "align_tables", True)
    if bullet not in ("-", "*", "+"):
        bullet = "-"
    if not isinstance(most_blank, int) or isinstance(most_blank, bool) or most_blank < 1:
        most_blank = 1
    lines = text.split("\n")
    result: list[str] = []
    # YAML front matter (`---` … `---` or `...` at the start) is left
    # exactly as written: it isn't Markdown.
    front_matter = 0
    if lines and lines[0].rstrip() == "---":
        closing = next((i for i in range(1, len(lines)) if lines[i].rstrip() in ("---", "...")), None)
        if closing is not None:
            front_matter = closing + 1
            result.extend(lines[:front_matter])
    in_fence = False
    fence_marker = ""
    blank_run = 0
    counters: dict[int, int] = {}  # numbered lists: indent -> next number
    table_start: int | None = None  # index in `result` of a table's header

    def close_table() -> None:
        nonlocal table_start
        if table_start is not None and align_tables and len(result) - table_start >= 2:
            result[table_start:] = align_table(result[table_start:])
        table_start = None

    for index, line in enumerate(lines):
        if index < front_matter:
            continue
        stripped_line = line.strip()
        if any(stripped_line.startswith(marker) for marker in _FENCE_MARKERS):
            close_table()
            marker = stripped_line[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif stripped_line.startswith(fence_marker):
                in_fence = False
            result.append(line.rstrip())
            blank_run = 0
            counters.clear()
            continue
        if in_fence:
            # Code-fence content is left completely untouched, including
            # trailing whitespace and blank lines, since it isn't prose.
            result.append(line)
            continue
        rstripped = line.rstrip()
        if rstripped == "":
            close_table()
            blank_run += 1
            if blank_run <= most_blank:
                result.append("")
            continue
        blank_run = 0
        if table_start is not None:
            if "|" in rstripped:
                result.append(_normalise_emphasis(rstripped, emphasis, strong))
                continue
            close_table()
        elif is_table_start(lines, index):
            table_start = len(result)
            counters.clear()
            result.append(_normalise_emphasis(rstripped, emphasis, strong))
            continue
        indent_width = len(rstripped) - len(rstripped.lstrip())
        heading_match = _ATX_HEADING_RE.match(rstripped)
        numbered_match = _NUMBERED_RE.match(rstripped)
        if heading_match and not (heading_match.group(2) or "").startswith("!"):
            hashes = heading_match.group(1)
            content = heading_match.group(2) or ""
            rstripped = f"{hashes} {content}" if content else hashes
            counters.clear()
        elif _THEMATIC_BREAK_RE.match(rstripped):
            counters.clear()  # `* * *` is a rule, not a bullet
        elif numbered_match:
            indent, number, delimiter, space = numbered_match.groups()
            for deeper in [level for level in counters if level > indent_width]:
                del counters[deeper]
            if numbering == "ones":
                number = "1"
            elif numbering == "renumber":
                current = counters.get(indent_width, int(number))
                number = str(current)
                counters[indent_width] = current + 1
            rstripped = f"{indent}{number}{delimiter}{space}{rstripped[numbered_match.end():]}"
        else:
            bullet_match = _LIST_BULLET_RE.match(rstripped)
            if bullet_match:
                indent = bullet_match.group(1)
                rest = rstripped[bullet_match.end():]
                rstripped = f"{indent}{bullet} {rest}"
            # A line at or left of a numbered list's indent ends that list.
            for level in [level for level in counters if level >= indent_width]:
                del counters[level]
        result.append(_normalise_emphasis(rstripped, emphasis, strong))
    close_table()
    return "\n".join(result).strip("\n") + "\n"


JSON = Reformatter("json", "JSON", _format_json, _minify_json)
XML = Reformatter("xml", "XML", _format_xml, _minify_xml)
MARKDOWN = Reformatter("markdown", "Markdown", _format_markdown, None)

REFORMATTERS: tuple[Reformatter, ...] = (JSON, XML, MARKDOWN)
REFORMATTERS_BY_KEY: dict[str, Reformatter] = {
    reformatter.key: reformatter for reformatter in REFORMATTERS
}


def reformatter_for_key(key: str) -> Reformatter | None:
    return REFORMATTERS_BY_KEY.get(key)
