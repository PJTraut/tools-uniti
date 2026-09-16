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
import xml.dom.minidom
from dataclasses import dataclass
from typing import Callable
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
    format: Callable[[str], str]
    minify: Callable[[str], str] | None

    @property
    def can_minify(self) -> bool:
        return self.minify is not None


def _format_json(text: str) -> str:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReformatFailure(ReformatError(exc.msg, exc.lineno, exc.colno)) from exc
    return json.dumps(value, indent=2, ensure_ascii=False) + "\n"


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


def _open_tag(element) -> str:
    # Reuse minidom's own attribute-escaping by cloning the element without
    # children (renders self-closed) rather than reimplementing it.
    clone = element.cloneNode(False)
    self_closed = clone.toxml()
    return self_closed[:-2] + ">"


def _render_xml_node(node, depth: int, indent: str, out: list[str]) -> None:
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
        out.append(f"{pad}{_open_tag(node)}")
        for child in children:
            _render_xml_node(child, depth + 1, indent, out)
        out.append(f"{pad}</{node.tagName}>")
    else:
        # Comments, processing instructions, DOCTYPE, and any other node
        # type are reproduced verbatim, only indented.
        out.append(f"{pad}{node.toxml()}")


_XML_DECLARATION_RE = re.compile(r"^\s*(<\?xml[^>]*\?>)")


def _format_xml(text: str) -> str:
    dom = _parse_xml(text)
    out: list[str] = []
    # The original declaration (with its exact encoding/standalone
    # attributes, if any) is reused verbatim rather than minidom's
    # regenerated one, which always emits a bare `version="1.0"` and would
    # silently drop an explicit `encoding=`/`standalone=` the source had.
    declaration_match = _XML_DECLARATION_RE.match(text)
    if declaration_match:
        out.append(declaration_match.group(1))
    for child in dom.childNodes:
        _render_xml_node(child, 0, "  ", out)
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
_LIST_BULLET_RE = re.compile(r"^(\s*)[*+]([ \t]+)")
_FENCE_MARKERS = ("```", "~~~")


def _format_markdown(text: str) -> str:
    lines = text.split("\n")
    result: list[str] = []
    in_fence = False
    fence_marker = ""
    blank_run = 0
    for line in lines:
        stripped_line = line.strip()
        if any(stripped_line.startswith(marker) for marker in _FENCE_MARKERS):
            marker = stripped_line[:3]
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif stripped_line.startswith(fence_marker):
                in_fence = False
            result.append(line.rstrip())
            blank_run = 0
            continue
        if in_fence:
            # Code-fence content is left completely untouched, including
            # trailing whitespace and blank lines, since it isn't prose.
            result.append(line)
            continue
        rstripped = line.rstrip()
        if rstripped == "":
            blank_run += 1
            if blank_run <= 1:
                result.append("")
            continue
        blank_run = 0
        heading_match = _ATX_HEADING_RE.match(rstripped)
        if heading_match and not (heading_match.group(2) or "").startswith("!"):
            hashes = heading_match.group(1)
            content = heading_match.group(2) or ""
            rstripped = f"{hashes} {content}" if content else hashes
        else:
            bullet_match = _LIST_BULLET_RE.match(rstripped)
            if bullet_match:
                indent = bullet_match.group(1)
                rest = rstripped[bullet_match.end():]
                rstripped = f"{indent}- {rest}"
        result.append(rstripped)
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
