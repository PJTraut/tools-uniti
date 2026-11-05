"""Markdown Preview stylesheets (N27, 2026-11-05).

Preview takes its look from CSS, layered like SFM's stylesheets, lowest
first:

1. built in: `assets/markdown.css` (read-only; today's look);
2. yours: `<user data>/Environments/Markdown/uniti.css`;
3. the document's: the files its front matter names
   (``stylesheet: [a.css, b.css]``, relative to the document), else a
   `uniti.css` in the document's folder (Q6);
4. loaded: **Load Stylesheet…**, until UNITI closes.

Later layers win property by property. Preview isn't a browser, so only a
subset is read: element selectors (`CSS_ELEMENTS`) and the properties in
`CSS_PROPERTIES`; anything else is ignored and noted. A small hand-written
parser, no dependency. Qt-free.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

from .user_config import environment_folder

logger = logging.getLogger(__name__)

USER_STYLESHEET = "uniti.css"
MAX_CSS_BYTES = 256 * 1024
MAX_DOCUMENT_STYLESHEETS = 8

CSS_ELEMENTS = frozenset(
    {
        *(f"h{level}" for level in range(1, 7)),
        "p", "strong", "em", "del", "mark", "sup", "sub", "code", "pre", "blockquote",
        "a", "ul", "ol", "li", "table", "th", "td", "hr", "dt", "dd",
    }
)
CSS_PROPERTIES = frozenset(
    {
        "font-family", "font-size", "font-weight", "font-style", "text-decoration",
        "color", "background-color", "margin-left", "margin-top", "text-align",
    }
)
_GENERIC_FAMILIES = frozenset({"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui"})
_COLOR_RE = re.compile(r"#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,30}|(?:rgb|rgba|hsl|hsla)\([^()]*\)")
_LENGTH_RE = re.compile(r"(-?\d+(?:\.\d+)?|-?\.\d+)\s*(px|em|rem|%|pt|in|cm|mm)?")
_PX_PER = {"px": 1.0, "em": 16.0, "rem": 16.0, "pt": 96 / 72, "in": 96.0, "cm": 96 / 2.54, "mm": 96 / 25.4}


@dataclass(frozen=True, slots=True)
class CssSheet:
    """One parsed stylesheet: `rules` in file order as (element, property,
    value), and what was ignored."""

    name: str
    path: Path | None
    rules: tuple[tuple[str, str, str], ...] = ()
    ignored: tuple[str, ...] = ()


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?(?:\*/|$)", " ", text, flags=re.DOTALL)


def parse_css(text: str, name: str = "stylesheet", path: Path | None = None) -> CssSheet:
    """The rules Preview reads from `text`, and a note per thing it doesn't."""

    text = _strip_comments(text)
    rules: list[tuple[str, str, str]] = []
    ignored: list[str] = []

    def note(item: str) -> None:
        if item not in ignored:
            ignored.append(item)

    position = 0
    length = len(text)
    while position < length:
        brace = text.find("{", position)
        if brace == -1:
            if text[position:].strip():
                note(f"text outside a rule ({text[position:].strip()[:20]})")
            break
        selector_text = text[position:brace].strip()
        # The block, to its matching brace (an @media block nests).
        depth = 1
        index = brace + 1
        while index < length and depth:
            if text[index] == "{":
                depth += 1
            elif text[index] == "}":
                depth -= 1
            index += 1
        body = text[brace + 1 : index - 1 if depth == 0 else index]
        position = index
        if selector_text.startswith("@"):
            note(selector_text.split()[0])
            continue
        elements: list[str] = []
        for selector in selector_text.split(","):
            selector = selector.strip().lower()
            if selector in CSS_ELEMENTS:
                elements.append(selector)
            elif selector:
                note(f"selector {selector}")
        for declaration in body.split(";"):
            if not declaration.strip():
                continue
            if ":" not in declaration:
                note(f"declaration {declaration.strip()[:20]}")
                continue
            prop, value = declaration.split(":", 1)
            prop = prop.strip().lower()
            value = value.replace("!important", "").strip()
            if prop not in CSS_PROPERTIES:
                note(f"property {prop}")
                continue
            if not value:
                continue
            for element in elements:
                rules.append((element, prop, value))
    return CssSheet(name, path, tuple(rules), tuple(ignored))


# --- values -> projection attributes ---------------------------------------------


def _length_px(value: str) -> float | None:
    match = _LENGTH_RE.fullmatch(value.strip())
    if match is None:
        return None
    number, unit = float(match.group(1)), match.group(2) or "px"
    if unit == "%":
        return number * 16 / 100
    return number * _PX_PER[unit]


def _font_scale(value: str) -> str | None:
    value = value.strip().lower()
    keywords = {"xx-small": 0.6, "x-small": 0.75, "small": 0.89, "medium": 1.0, "large": 1.2, "x-large": 1.5, "xx-large": 2.0}
    if value in keywords:
        return f"{keywords[value]:.3f}"
    match = _LENGTH_RE.fullmatch(value)
    if match is None:
        return None
    number, unit = float(match.group(1)), match.group(2) or "px"
    scale = number / 100 if unit == "%" else number if unit in ("em", "rem") else number * _PX_PER[unit] / 16
    return f"{scale:.3f}" if scale > 0 else None


def declarations_to_attrs(props: Mapping[str, str]) -> tuple[dict[str, str], list[str]]:
    """One element's cascaded CSS as projection attributes, and the values
    that couldn't be read."""

    attrs: dict[str, str] = {}
    bad: list[str] = []
    for prop, value in props.items():
        lowered = value.strip().lower()
        if prop == "font-weight":
            if lowered in ("bold", "bolder") or lowered.isdigit() and int(lowered) >= 600:
                attrs["bold"] = "yes"
            elif lowered not in ("normal", "lighter") and not lowered.isdigit():
                bad.append(f"font-weight: {value}")
        elif prop == "font-style":
            if lowered in ("italic", "oblique"):
                attrs["italic"] = "yes"
            elif lowered != "normal":
                bad.append(f"font-style: {value}")
        elif prop == "text-decoration":
            words = set(lowered.split())
            if "underline" in words:
                attrs["underline"] = "yes"
            if "line-through" in words:
                attrs["strikeout"] = "yes"
        elif prop in ("color", "background-color"):
            if lowered in ("transparent", "none", "inherit", "initial"):
                continue
            if prop == "color" and lowered == "graytext":
                attrs["muted"] = "yes"
            elif _COLOR_RE.fullmatch(value.strip()):
                attrs["color" if prop == "color" else "background"] = value.strip()
            else:
                bad.append(f"{prop}: {value}")
        elif prop == "font-family":
            families = [family.strip().strip("'\"") for family in value.split(",") if family.strip()]
            if families and families[0].lower() == "monospace":
                attrs["monospace"] = "yes"
            elif any(family.lower() not in _GENERIC_FAMILIES for family in families):
                # The renderer expands a generic `monospace` in the list.
                attrs["font_family"] = ",".join(families)
        elif prop == "font-size":
            scale = _font_scale(value)
            if scale is None:
                bad.append(f"font-size: {value}")
            else:
                attrs["font_scale"] = scale
        elif prop in ("margin-left", "margin-top"):
            px = _length_px(value)
            if px is None:
                bad.append(f"{prop}: {value}")
            elif prop == "margin-left":
                attrs["left_margin"] = f"{px / 96:.3f}"
            else:
                attrs["space_before"] = f"{px:g}"
        elif prop == "text-align":
            if lowered in ("left", "right", "center", "justify", "start", "end"):
                attrs["align"] = lowered
            else:
                bad.append(f"text-align: {value}")
    return attrs, bad


@dataclass(frozen=True, slots=True)
class MarkdownStyles:
    """The cascaded look of each element, from `sheets` (lowest first)."""

    sheets: tuple[CssSheet, ...] = ()
    attrs: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    notes: tuple[str, ...] = ()

    def for_element(self, *elements: str) -> dict[str, str]:
        """The attributes of `elements` merged, later ones winning."""

        merged: dict[str, str] = {}
        for element in elements:
            merged.update(self.attrs.get(element, {}))
        return merged


def cascade(sheets: Iterable[CssSheet]) -> MarkdownStyles:
    sheets = tuple(sheets)
    props: dict[str, dict[str, str]] = {}
    notes: list[str] = []
    for sheet in sheets:
        for element, prop, value in sheet.rules:
            props.setdefault(element, {})[prop] = value
        notes.extend(f"{sheet.name}: {item} ignored" for item in sheet.ignored)
    attrs: dict[str, dict[str, str]] = {}
    for element, element_props in props.items():
        attrs[element], bad = declarations_to_attrs(element_props)
        notes.extend(f"{element} {{{item}}} ignored" for item in bad)
    return MarkdownStyles(sheets, attrs, tuple(notes))


# --- the layers -----------------------------------------------------------------------


def builtin_stylesheet_path() -> Path:
    return Path(__file__).resolve().parent / "assets" / "markdown.css"


def user_stylesheet_path() -> Path | None:
    folder = environment_folder("Markdown")
    return None if folder is None else folder / USER_STYLESHEET


_FRONT_MATTER_END = re.compile(r"^(?:---|\.\.\.)[ \t]*$", re.MULTILINE)


def _front_matter(source: str) -> tuple[int, re.Match[str]] | None:
    """(end of the opening `---` line, the closing `---`/`...` line's match)
    of a YAML front matter block at the start of `source`, else None."""

    if not source.startswith("---"):
        return None
    first_line_end = source.find("\n")
    if first_line_end == -1 or source[:first_line_end].rstrip() != "---":
        return None
    closing = _FRONT_MATTER_END.search(source, first_line_end + 1)
    if closing is None:
        return None
    return first_line_end, closing


def front_matter_end(source: str) -> int | None:
    """Where a YAML front matter block at the start of `source` ends: the
    end of its closing `---` or `...` line (before its newline). None
    without one."""

    found = _front_matter(source)
    return None if found is None else found[1].end()


def front_matter_stylesheets(source: str) -> tuple[str, ...] | None:
    """The `stylesheet:` entry of a YAML front matter block at the start of
    `source`: an inline list, a block list or one name. None without one."""

    found = _front_matter(source)
    if found is None:
        return None
    first_line_end, closing = found
    lines = source[first_line_end + 1 : closing.start()].splitlines()
    for index, line in enumerate(lines):
        match = re.match(r"stylesheets?\s*:\s*(.*)$", line.strip())
        if match is None or line[:1].isspace():
            continue
        value = match.group(1).strip()
        if value.startswith("["):
            items = value.strip("[]").split(",")
        elif value:
            items = [value]
        else:
            items = []
            for item in lines[index + 1 :]:
                stripped = item.strip()
                if not stripped.startswith("- "):
                    break
                items.append(stripped[2:])
        names = tuple(name.strip().strip("'\"") for name in items if name.strip().strip("'\""))
        return names[:MAX_DOCUMENT_STYLESHEETS]
    return None


def document_stylesheet_paths(document_path: Path | None, source: str) -> tuple[Path, ...]:
    """The document's own stylesheets: its front matter's, else a
    `uniti.css` in its folder (which may not exist)."""

    if document_path is None:
        return ()
    folder = Path(document_path).parent
    named = front_matter_stylesheets(source)
    if named is not None:
        return tuple(Path(name) if Path(name).is_absolute() else folder / name for name in named)
    return (folder / USER_STYLESHEET,)


_sheet_cache: dict[str, tuple[object, CssSheet]] = {}


def load_css(path: Path, name: str | None = None, *, required: bool = False) -> CssSheet | None:
    """`path` parsed (cached until it changes); None when it doesn't exist,
    unless `required`, when that is a note."""

    label = name or path.name
    try:
        status = path.stat()
    except OSError:
        return CssSheet(label, path, (), ("not found",)) if required else None
    stamp = (status.st_mtime_ns, status.st_size)
    key = str(path)
    cached = _sheet_cache.get(key)
    if cached is not None and cached[0] == stamp:
        return cached[1]
    if status.st_size > MAX_CSS_BYTES:
        sheet = CssSheet(label, path, (), (f"larger than {MAX_CSS_BYTES // 1024} KiB",))
    else:
        try:
            sheet = parse_css(path.read_text(encoding="utf-8-sig"), label, path)
        except (OSError, UnicodeDecodeError) as exc:
            sheet = CssSheet(label, path, (), (f"unreadable ({exc.__class__.__name__})",))
    _sheet_cache[key] = (stamp, sheet)
    return sheet


def markdown_styles(document_path: Path | None, source: str, loaded: Iterable[Path] = ()) -> MarkdownStyles:
    """Preview's styles for a document: every layer that exists, cascaded."""

    sheets: list[CssSheet] = []
    builtin = load_css(builtin_stylesheet_path(), "markdown.css (built in)")
    if builtin is not None:
        sheets.append(builtin)
    user = user_stylesheet_path()
    if user is not None:
        sheet = load_css(user, "your uniti.css")
        if sheet is not None:
            sheets.append(sheet)
    named = front_matter_stylesheets(source) is not None
    for path in document_stylesheet_paths(document_path, source):
        sheet = load_css(path, required=named)
        if sheet is not None:
            sheets.append(sheet)
    for path in loaded:
        sheet = load_css(Path(path), required=True)
        if sheet is not None:
            sheets.append(sheet)
    key = tuple(sheets)
    styles = _styles_cache.get(key)
    if styles is None:
        if len(_styles_cache) >= 32:
            _styles_cache.clear()
        styles = _styles_cache[key] = cascade(sheets)
    return styles


# The same sheets give the same `MarkdownStyles` object, so a view's cache
# token stays identical while nothing changed.
_styles_cache: dict[tuple[CssSheet, ...], MarkdownStyles] = {}


def clear_css_cache() -> None:
    _sheet_cache.clear()
    _styles_cache.clear()


USER_STYLESHEET_TEMPLATE = """/* uniti.css - your Markdown Preview styles (every Markdown file).
 *
 * These rules apply above UNITI's built-in markdown.css and below a
 * document's own stylesheets. Element selectors only; for example:
 *
 *   h1 { color: #8b0000; font-size: 2em; }
 *   blockquote { color: GrayText; margin-left: 0.5in; }
 *   code { font-family: "JetBrains Mono", monospace; }
 *
 * See the built-in markdown.css (Configuration Files…) for every element
 * and property Preview reads.
 */
"""


__all__ = [
    "CSS_ELEMENTS",
    "CSS_PROPERTIES",
    "USER_STYLESHEET",
    "USER_STYLESHEET_TEMPLATE",
    "CssSheet",
    "MarkdownStyles",
    "builtin_stylesheet_path",
    "cascade",
    "clear_css_cache",
    "declarations_to_attrs",
    "document_stylesheet_paths",
    "front_matter_end",
    "front_matter_stylesheets",
    "load_css",
    "markdown_styles",
    "parse_css",
    "user_stylesheet_path",
]
