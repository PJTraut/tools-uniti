"""SFM Standard and Preview views (ADR-0015, spec §33–34, Phases E8–E9).

Plain Text is the ordinary source editor. The two rich modes are
projections of the canonical source through `rich_views`, sharing one
layout (`layout_projection`): a block per paragraph/chapter marker, and
source line breaks inside a paragraph flowing as spaces.

**All styling comes from the stylesheet, by tag.** Text takes the effective
STY formatting of the marker that tags it: its paragraph (or chapter)
style, the character style around it (verse numbers from `\\v`, table
cells from their cell marker, note text from `\\fr`/`\\ft`/… — note-internal
markers USFM leaves unclosed style the text up to the next marker), and
the note style for note bodies. Nothing is hard-coded. What USFM tags
don't cover comes from presentation rules in the same stylesheets
(`style_layers.py`): `\\Marker p+q1` (a paragraph after another) and
`\\Marker f::caller` (a note's caller). Sizes are relative to the body
paragraph's (``\\p``) STY size.

- **Standard** (editable) keeps every marker inline as a small protected
  tag of uniform size, so nothing in the source is ever invisible.
- **Preview** (read-only, spec §34 "PreviewSurface") hides markers and
  their separator whitespace, and leaves out book metadata (identification
  markers and non-publishable paragraphs). A closed footnote or
  cross-reference shows only its caller in the text (``+`` -> a, b, c …
  per note kind, restarting at each chapter; ``-`` -> none); the note
  bodies are listed below the text, one `NoteSection` per kind
  (`Projection.notes`). Table rows put a tab between cells.

In both, a marker no loaded stylesheet defines stays visible as a
protected token, so unknown content never silently disappears.

This is a best-effort renderer, not a typesetter (spec Phase E9): spacing
and margins approximate the STY values; PTXprint-grade layout is out of
scope.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from uniti.core.rich_views.editing import EditPlan
from uniti.core.rich_views.projection import NoteSection, Projection, ProjectionBuilder
from uniti.core.rich_views.provider import ViewCommand
from uniti.core.rich_views.source_map import HYPHEN, ISOLATE, LRI, PDI

from .hyphenation import SOFT_HYPHEN, HyphenationRules
from .markers import NOTE_MARKERS, is_closing, is_milestone, is_milestone_close, is_nested, marker_name
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
# USFM identification markers: book metadata for running headers, tables of
# contents and tooling, never body text — Preview leaves them out. (The STY
# calls \\h and \\toc* "publishable" because they do print, elsewhere.)
_METADATA_MARKERS = re.compile(r"(?:id|ide|sts|rem|usfm|h\d?|toca?\d)")
_OFF_VALUES = ("-", "no", "false", "0")
# `\Justification` values. As in PTXprint, `Left` and `Right` are the edges
# a line starts and ends on in the paragraph's reading direction (text
# direction plan W-D1); UNITI's `Start` and `End` are synonyms, kept apart
# so an export can write what the author did.
_ALIGN = {
    "left": "left",
    "center": "center",
    "right": "right",
    "both": "justify",
    "justify": "justify",
    "start": "start",
    "end": "end",
}


# Markers whose content Preview shows between generated brackets: a
# note's category (`\cat People\cat*` -> "[People]").
_BRACKETED = frozenset({"cat"})

# The footnote category filter (plan 2026-10-14-footnote-category-filter):
# `\cat aa bb cc\cat*` gives a note the categories aa, bb and cc. A note
# with none is in `NO_CATEGORY`, which the filter lists as "None".
NO_CATEGORY = ""
_CATEGORY_RE = re.compile(r"\\\+?cat\s+(.*?)\\\+?cat\*", re.DOTALL)


def note_categories(body: str) -> tuple[str, ...]:
    """The categories of one note's text: every word inside its
    `\\cat …\\cat*` spans, or `(NO_CATEGORY,)` when it has none."""

    found: list[str] = []
    for match in _CATEGORY_RE.finditer(body):
        for word in match.group(1).split():
            if word not in found:
                found.append(word)
    return tuple(found) or (NO_CATEGORY,)


def source_note_categories(source: str) -> tuple[str, ...]:
    """The categories used by the notes of `source`, in order of first
    appearance, with `NO_CATEGORY` last when some note has none."""

    found: list[str] = []
    uncategorized = False
    tokens = tokenize_sfm(source)
    pairs: dict[int, tuple[int, str]] = {}
    _paired_openers(parse_sfm(tokens), pairs)
    for token in tokens:
        if token.kind is not SfmTokenKind.MARKER or token.start not in pairs or marker_name(token.text) not in NOTE_MARKERS:
            continue
        for category in note_categories(source[token.end : pairs[token.start][0]]):
            if category == NO_CATEGORY:
                uncategorized = True
            elif category not in found:
                found.append(category)
    return tuple(found) + ((NO_CATEGORY,) if uncategorized else ())


def note_is_hidden(body: str, hidden: frozenset[str]) -> bool:
    """A note is hidden when every one of its categories is."""

    return bool(hidden) and all(category in hidden for category in note_categories(body))


def _bare(marker: str) -> str:
    return marker_name(marker)


def _milestone_end(tokens, index: int) -> int:
    """Where a milestone (``\\qt-s |who="Pilate"\\*``) ends: after its own
    ``\\*`` when one follows (its attributes may sit between)."""

    token = tokens[index]
    if is_milestone_close(token.text):
        return token.end
    for offset in (1, 2):
        following = tokens[index + offset] if index + offset < len(tokens) else None
        if following is None:
            break
        if following.kind is SfmTokenKind.MARKER:
            return following.end if is_milestone_close(following.text) else token.end
        if "\n" in following.text or "\r" in following.text:
            break
    return token.end


def _attribute_start(tokens, index: int, closers: dict[int, int]) -> int | None:
    """Where ``|attributes`` start in text token `index`, when they run up to
    the end marker of the character span they belong to (``\\w word|x\\w*``)."""

    token = tokens[index]
    bar = token.text.find("|")
    following = tokens[index + 1] if index + 1 < len(tokens) else None
    if bar < 0 or following is None or following.kind is not SfmTokenKind.MARKER:
        return None
    if not is_closing(following.text) or following.start not in closers:
        return None
    return token.start + bar


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


def body_font_size(styles: LayeredStyleRegistry) -> float:
    """The body paragraph (``\\p``) size every other size is relative to."""

    try:
        size = float(styles.formatting("p").get("fontsize", ""))
    except ValueError:
        return BASE_FONT_SIZE
    return size if size > 0 else BASE_FONT_SIZE


def presentation_attrs(
    styles: LayeredStyleRegistry, marker: str, *, block: bool, previous: str | None = None
) -> dict[str, str]:
    """Backend-neutral attributes from a marker's effective STY formatting.

    `previous` is the paragraph-level marker before this one, for
    `previous+marker` presentation rules.
    """

    return formatting_attrs(styles, styles.formatting(marker, previous), block=block)


def caller_attrs(styles: LayeredStyleRegistry, note_marker: str) -> dict[str, str]:
    """A note caller's attributes, from `note_marker::caller` rules only."""

    return formatting_attrs(styles, styles.caller_formatting(note_marker), block=False)


def formatting_attrs(styles: LayeredStyleRegistry, formatting: dict[str, str], *, block: bool) -> dict[str, str]:
    """Backend-neutral attributes from lowercased STY formatting keys."""

    attrs: dict[str, str] = {}
    for key, attr in _FLAG_ATTRS.items():
        if key in formatting and formatting[key].lower() not in _OFF_VALUES:
            attrs[attr] = "yes"
    size = formatting.get("fontsize")
    if size:
        try:
            scale = float(size) / body_font_size(styles)
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
        hyphenate = formatting.get("hyphenate")
        if hyphenate is not None:
            attrs["hyphenate"] = "no" if hyphenate.lower() in _OFF_VALUES else "yes"
        # UNITI's `\Direction` (text direction plan W-D4): beats the view's
        # and the project's direction; `Auto` (or anything else) leaves them.
        direction = formatting.get("direction", "").strip().lower()
        if direction in ("ltr", "rtl"):
            attrs["direction"] = direction
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

    @property
    def styles(self) -> LayeredStyleRegistry:
        """The stylesheets this view renders with now."""

        return self._styles()

    def cache_token(self) -> LayeredStyleRegistry:
        """The stylesheets this view renders with: a new object whenever
        they reload, so a cached projection is reused only while they
        haven't changed."""

        return self._styles()

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


def _starts_block(marker_text: str, registry) -> bool:
    """Whether marker token `marker_text` begins a new view block."""

    if is_closing(marker_text) or is_milestone(marker_text) or is_milestone_close(marker_text):
        return False
    marker = _bare(marker_text)
    if marker == "c":
        return True
    style = registry.style_for(marker)
    return style is not None and (style.style_type or "").lower() == "paragraph"


def _separator_end(source: str, offset: int) -> int:
    """`offset` moved past the one whitespace character (or CRLF) that
    separates a marker from what follows."""

    if source.startswith("\r\n", offset):
        return offset + 2
    if offset < len(source) and source[offset] in " \n\r":
        return offset + 1
    return offset


def _cell_style_marker(marker: str) -> str:
    """A column-range cell (``tc1-2``) is styled like its first column."""

    return marker.split("-", 1)[0]


def auto_caller(index: int) -> str:
    """The `index`-th generated caller: a … z, aa, ab …"""

    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("a") + remainder) + letters
    return letters


@dataclass(frozen=True, slots=True)
class _Note:
    """One closed note Preview moved into the notes frame."""

    marker: str  # bare note marker, e.g. "f"
    body_start: int  # source offset after the opener, its caller and separators
    closer_start: int
    closer_end: int
    caller: str  # display caller; "" for none


def _caller_bounds(source: str, opener_end: int, closer_start: int) -> tuple[int, int, int]:
    """(caller start, caller end, body start) of a note whose opener ends at
    `opener_end`. The caller is the word right after the opener (``+``,
    ``-`` or a literal); it may be missing."""

    start = min(_separator_end(source, opener_end), closer_start)
    end = start
    while end < closer_start and not source[end].isspace() and source[end] != "\\":
        end += 1
    body = min(_separator_end(source, end), closer_start) if end > start else start
    return start, end, body


def _with_direction(attrs: dict[str, str], direction: str | None) -> dict[str, str]:
    """`attrs` with the view's `direction` as a default for the block (an
    attribute the block already has is kept)."""

    return attrs if direction is None else {"direction": direction, **attrs}


_NOTE_ORDER = ("f", "fe", "ef", "x", "ex")


def note_label(styles: LayeredStyleRegistry, marker: str) -> str:
    """Plural label for a note kind from its STY name (``x...x* - Cross
    Reference`` -> ``Cross References``); the marker when unnamed."""

    style = styles.style_for(marker)
    name = (style.name or "") if style is not None else ""
    label = name.rsplit(" - ", 1)[1].strip() if " - " in name else ""
    if not label:
        return marker
    return label if label.endswith("s") else label + "s"


def layout_projection(
    source: str,
    styles: LayeredStyleRegistry,
    key: str,
    *,
    show_markers: bool,
    hidden_categories: frozenset[str] = frozenset(),
    hyphenation: "HyphenationRules | None" = None,
    direction: str | None = None,
) -> Projection:
    """Paragraph blocks with each marker's effective STY formatting.

    `show_markers` keeps every marker visible as a protected tag (Standard
    View); otherwise markers are hidden and closed notes leave only their
    caller in the text, their bodies going to `Projection.notes`
    (Preview). In Preview, a note whose categories are all in
    `hidden_categories` leaves neither its caller nor its body, and
    `hyphenation` puts a soft hyphen (U+00AD, a generated segment the
    source map skips) at the listed break points of the words in
    hyphenating paragraphs. In both, source line breaks inside a paragraph flow as
    spaces — in USFM a line break is just whitespace — and a new block
    starts at each paragraph or chapter marker.

    `direction` (``"ltr"`` or ``"rtl"``; the view's choice, else the
    project's) is put on every block, the notes frame's too, as the
    ``direction`` attribute; a block's own ``direction`` (a style's) wins.
    None leaves it off, so the UI decides from the text as before.
    """

    if direction not in ("ltr", "rtl"):
        direction = None
    registry = styles.registry
    tokens = tokenize_sfm(source)
    pairs: dict[int, tuple[int, str]] = {}
    _paired_openers(parse_sfm(tokens), pairs)
    closers = {closer: opener for opener, (closer, _marker) in pairs.items()}
    # For each token: does the next marker token start a block (or is it
    # the end of the document)? Then a text token's trailing line break is
    # that block break rather than flowing whitespace.
    block_follows = [True] * len(tokens)
    following = True
    for index in range(len(tokens) - 1, -1, -1):
        block_follows[index] = following
        token = tokens[index]
        if token.kind is not SfmTokenKind.TEXT:
            following = _starts_block(token.text, registry)
    builder = ProjectionBuilder(key)
    spans: list[tuple[int, int, dict[str, str], str | None]] = []
    open_spans: list[tuple[int, int, str]] = []  # (opener start, view start, marker)
    block: tuple[int, str, dict[str, str]] | None = None
    pending_number: str | None = None  # "verse" | "chapter"
    pending_caller: str | None = None  # Standard: the next text starts this note's caller
    note_openers: set[int] = set()
    unclosed_note = False  # inside a note with no end marker (until the paragraph ends)
    implicit: tuple[int, str] | None = None  # unclosed note-internal character style
    row_cells = -1  # cells seen in the current \\tr row; -1 outside rows
    skipping = False  # Preview: inside a metadata paragraph, shown not at all
    skip_until = -1  # Preview: source offset the current note's body runs to
    cell: tuple[int, str] | None = None  # open cell span (view start, marker)
    previous_paragraph: str | None = None  # last paragraph-level marker, in source order
    caller_counts: dict[str, int] = {}  # generated callers per note kind, this chapter
    notes: list[_Note] = []

    def add_span(start: int, end: int, attrs: dict[str, str], marker: str | None) -> None:
        if end > start and attrs:
            spans.append((start, end, attrs, marker))

    def emit_text(end: int, *, keep_break: bool) -> None:
        """Source text up to `end`; a trailing line break stays a line
        break only when `keep_break` (a block follows)."""

        start = builder.source_position
        if end <= start:
            return
        text = source[start:end]
        trailing = 0
        if keep_break:
            if text.endswith("\r\n"):
                trailing = 2
            elif text.endswith(("\n", "\r")):
                trailing = 1
        if trailing < len(text):
            body = text[: len(text) - trailing]
            cuts = hyphen_points(body) if hyphenation is not None else ()
            last = 0
            for cut in cuts:
                builder.text(start + cut, body[last:cut], line_break=" ")
                builder.generated(SOFT_HYPHEN, HYPHEN)
                last = cut
            builder.text(end - trailing, body[last:], line_break=" ")
        if trailing:
            builder.text(end, text[len(text) - trailing :])

    def hyphen_points(body: str) -> list[int]:
        """Where a soft hyphen goes in `body`: only in the main text of a
        hyphenating paragraph (H-D3), never in a note."""

        if show_markers or block is None or note_openers or unclosed_note or implicit is not None:
            return []
        marker, attrs = block[1], block[2]
        wanted = attrs.get("hyphenate")
        if wanted is None:
            style = registry.style_for(marker)
            if not hyphenation.marker_hyphenates(marker, style.text_type if style else None):
                return []
        elif wanted != "yes":
            return []
        return hyphenation.points(body)

    def close_implicit() -> None:
        nonlocal implicit
        if implicit is not None:
            add_span(implicit[0], builder.view_position, presentation_attrs(styles, implicit[1], block=False), implicit[1])
            implicit = None

    def close_cell() -> None:
        nonlocal cell
        if cell is not None:
            add_span(
                cell[0],
                builder.view_position,
                presentation_attrs(styles, _cell_style_marker(cell[1]), block=False),
                cell[1],
            )
            cell = None

    def close_block() -> None:
        nonlocal block, unclosed_note
        close_implicit()
        close_cell()
        unclosed_note = False
        if block is not None:
            builder.block(block[0], builder.view_position, _with_direction(block[2], direction), block[1])
            block = None

    def isolated() -> bool:
        """Whether a tag shown now goes in an LRI…PDI isolate (W-D3): in a
        right-to-left paragraph, so `\\p \\v 1` still reads as written."""

        own = block[2].get("direction") if block is not None else None
        return (own or direction) == "rtl"

    def shown_tag(source_end: int, label: str, marker: str, token_length: int, span_marker: str | None = None) -> None:
        """A protected tag; the first `token_length` characters of `label`
        are the marker token."""

        isolate = isolated()
        if isolate:
            builder.generated(LRI, ISOLATE)
        view_start = builder.view_position
        builder.marker(source_end, label, marker)
        add_span(view_start, view_start + token_length, {"marker_token": "yes"}, span_marker or marker)
        if isolate:
            builder.generated(PDI, ISOLATE)

    def tag(token_end: int, token_text: str, marker: str, *, separator: bool = True) -> None:
        """Hide the marker (and its separating whitespace) or, with
        `show_markers`, show it as a protected tag."""

        end = _separator_end(source, token_end) if separator else token_end
        if not show_markers:
            builder.hidden(end, marker)
            return
        shown_tag(end, token_text + (" " if end > token_end else ""), marker, len(token_text))

    def visible_token(token_end: int, token_text: str, marker: str) -> None:
        """A marker shown as a protected token in every mode."""

        shown_tag(token_end, token_text, marker, len(token_text))

    def new_block_line(marker: str) -> None:
        if builder.view_position and not builder_ends_with_newline(builder, source):
            builder.generated("\n", marker)

    def move_note_to_frame(token, marker: str) -> None:
        """Preview: leave only the caller of a closed note in the text."""

        nonlocal skip_until
        closer_start = pairs[token.start][0]
        closer_end = closer_start + len(token.text) + 1
        caller_start, caller_end, body_start = _caller_bounds(source, token.end, closer_start)
        if hidden_categories and note_is_hidden(source[body_start:closer_start], hidden_categories):
            # Filtered out: no caller, no body, and the callers after it
            # number as if it weren't there.
            builder.hidden(closer_end, marker)
            skip_until = closer_end
            return
        written = source[caller_start:caller_end]
        if written == "-":
            caller = ""
        elif written in ("", "+"):
            count = caller_counts.get(marker, 0)
            caller_counts[marker] = count + 1
            caller = auto_caller(count)
        else:
            caller = written
        builder.hidden(token.end, marker)
        if caller:
            view_start = builder.view_position
            builder.generated(caller, "caller")
            add_span(view_start, builder.view_position, caller_attrs(styles, marker), "caller")
        builder.hidden(closer_end, marker)
        skip_until = closer_end
        notes.append(_Note(marker, body_start, closer_start, closer_end, caller))

    for index, token in enumerate(tokens):
        if token.start < skip_until:
            continue
        if skipping:
            if token.kind is SfmTokenKind.TEXT or not _starts_block(token.text, registry):
                builder.hidden(max(token.end, builder.source_position), _bare(token.text) if token.kind is not SfmTokenKind.TEXT else None)
                continue
            skipping = False
        if token.kind is SfmTokenKind.TEXT:
            if token.end <= builder.source_position:
                continue
            keep_break = block_follows[index]
            start = builder.source_position
            text = source[start : token.end]
            if pending_caller is not None:
                note_marker, pending_caller = pending_caller, None
                if text and not text[0].isspace():
                    caller_start = builder.view_position
                    builder.text(start + 1, text[0])
                    add_span(caller_start, builder.view_position, caller_attrs(styles, note_marker), "caller")
                emit_text(token.end, keep_break=keep_break)
                continue
            if pending_number is not None:
                digits = len(text) - len(text.lstrip("0123456789-abc"))
                number_end = start + digits
                if digits:
                    view_start = builder.view_position
                    builder.text(number_end, source[start:number_end])
                    number_marker = "v" if pending_number == "verse" else "c"
                    add_span(
                        view_start,
                        builder.view_position,
                        presentation_attrs(styles, number_marker, block=False),
                        number_marker,
                    )
                    if (
                        pending_number == "verse"
                        and not show_markers
                        and number_end < token.end
                        and source[number_end] == " "
                    ):
                        builder.hidden(number_end + 1, "v")
                pending_number = None
                emit_text(token.end, keep_break=keep_break)
                continue
            attributes = None if show_markers else _attribute_start(tokens, index, closers)
            if attributes is not None:
                # Preview: `|attributes` of a character span aren't text.
                emit_text(attributes, keep_break=False)
                builder.hidden(token.end, "attributes")
                continue
            emit_text(token.end, keep_break=keep_break)
            continue

        if is_milestone(token.text) or is_milestone_close(token.text):
            # A milestone marks a position, never text: one protected tag,
            # attributes and all, in Standard; nothing in Preview.
            unit_end = _milestone_end(tokens, index)
            if show_markers:
                label = source[token.start : unit_end]
                shown_tag(unit_end, label, _bare(token.text) or "milestone", len(label), "milestone")
            else:
                builder.hidden(unit_end, "milestone")
            skip_until = unit_end
            continue

        marker = _bare(token.text)
        if not is_nested(token.text):
            # A nested style (`\\+xt`) sits inside the note-internal style
            # around it rather than ending it.
            close_implicit()
        if is_closing(token.text):
            opener = closers.get(token.start)
            if opener is None:
                visible_token(token.end, token.text, marker)
                continue
            if not show_markers and marker in _BRACKETED:
                builder.generated("]", marker)
            note_openers.discard(opener)
            for span_index in range(len(open_spans) - 1, -1, -1):
                if open_spans[span_index][0] == opener:
                    _start, span_view_start, span_marker = open_spans.pop(span_index)
                    add_span(
                        span_view_start,
                        builder.view_position,
                        presentation_attrs(styles, span_marker, block=False),
                        span_marker,
                    )
                    break
            tag(token.end, token.text, marker, separator=False)
            continue

        if _CELL_RE.fullmatch(marker):
            # Table cell: a tab between cells, styled by its cell marker.
            close_cell()
            if row_cells > 0:
                builder.generated("\t", marker)
            tag(token.end, token.text, marker)
            row_cells = max(row_cells, 0) + 1
            cell = (builder.view_position, marker)
            continue

        style = registry.style_for(marker)
        style_type = (style.style_type or "").lower() if style else ""
        if marker == "c":
            close_block()
            new_block_line(marker)
            block = (builder.view_position, marker, presentation_attrs(styles, "c", block=True, previous=previous_paragraph))
            previous_paragraph = marker
            caller_counts.clear()
            tag(token.end, token.text, marker)
            pending_number = "chapter"
            continue
        if marker == "v":
            tag(token.end, token.text, marker)
            pending_number = "verse"
            continue
        if style is None:
            # A marker no loaded stylesheet defines stays visible in every
            # mode, so unknown content never silently disappears.
            visible_token(token.end, token.text, marker)
            continue
        if style_type == "paragraph":
            close_block()
            previous, previous_paragraph = previous_paragraph, marker
            publishable = "publishable" in (style.text_properties or frozenset())
            if not show_markers and (not publishable or _METADATA_MARKERS.fullmatch(marker)):
                builder.hidden(token.end, marker)
                skipping = True
                continue
            new_block_line(marker)
            attrs = presentation_attrs(styles, marker, block=True, previous=previous)
            if marker == "tr":
                attrs["table_row"] = "yes"
                row_cells = 0
            else:
                row_cells = -1
            # The paragraph style's character-level attrs (bold headings,
            # sizes) reach its text through the block format.
            block = (builder.view_position, marker, attrs)
            tag(token.end, token.text, marker)
            continue
        if style_type == "note" and token.start in pairs and not show_markers:
            move_note_to_frame(token, marker)
            continue
        in_note = bool(note_openers) or unclosed_note
        if token.start in pairs:
            open_spans.append((token.start, builder.view_position, marker))
            if style_type == "note":
                note_openers.add(token.start)
                pending_caller = marker
        elif style_type == "note":
            unclosed_note = True
        tag(token.end, token.text, marker)
        if not show_markers and marker in _BRACKETED and token.start in pairs:
            builder.generated("[", marker)
        if in_note and style_type == "character" and token.start not in pairs:
            # Note-internal markers (\fr, \ft, \xo …) style the text up to
            # the next marker; USFM leaves them unclosed.
            implicit = (builder.view_position, marker)
    close_block()
    for start, end, attrs, marker in sorted(spans, key=lambda span: (span[0], -span[1])):
        # Outer spans first, so a nested style is merged over its parent's.
        builder.span(start, end, attrs, marker)
    sections = _note_sections(source, tokens, styles, pairs, closers, notes, key, direction) if notes else ()
    return builder.build(len(source), notes=sections)


def _note_sections(
    source: str,
    tokens,
    styles: LayeredStyleRegistry,
    pairs: dict[int, tuple[int, str]],
    closers: dict[int, int],
    notes: list[_Note],
    key: str,
    direction: str | None = None,
) -> tuple[NoteSection, ...]:
    """One `NoteSection` per note kind: every note body of that kind on
    its own line, after its caller."""

    kinds: list[str] = []
    for note in notes:
        if note.marker not in kinds:
            kinds.append(note.marker)
    order = [kind for kind in _NOTE_ORDER if kind in kinds] + [kind for kind in kinds if kind not in _NOTE_ORDER]
    sections = []
    for kind in order:
        builder = ProjectionBuilder(f"{key}.notes.{kind}")
        spans: list[tuple[int, int, dict[str, str], str | None]] = []
        block_attrs = _with_direction(presentation_attrs(styles, kind, block=True), direction)
        first = True
        for note in (note for note in notes if note.marker == kind):
            builder.hidden(note.body_start, kind)
            if not first:
                builder.generated("\n", kind)
            first = False
            entry_start = builder.view_position
            if note.caller:
                builder.generated(note.caller, "caller")
                spans.append((entry_start, builder.view_position, caller_attrs(styles, kind), "caller"))
                builder.generated(" ", "caller")
            _note_body(builder, source, tokens, styles, pairs, closers, spans, note)
            builder.hidden(note.closer_end, kind)
            builder.block(entry_start, builder.view_position, block_attrs, kind)
        builder.hidden(len(source))
        for start, end, attrs, marker in sorted(spans, key=lambda span: (span[0], -span[1])):
            builder.span(start, end, attrs, marker)
        sections.append(NoteSection(kind, note_label(styles, kind), builder.build(len(source))))
    return tuple(sections)


def _note_body(builder: ProjectionBuilder, source: str, tokens, styles, pairs, closers, spans, note: _Note) -> None:
    """A note's body as text, its markers hidden and their styles applied."""

    registry = styles.registry
    implicit: tuple[int, str] | None = None
    open_spans: list[tuple[int, int, str]] = []

    def close_implicit() -> None:
        nonlocal implicit
        if implicit is not None:
            attrs = presentation_attrs(styles, implicit[1], block=False)
            if builder.view_position > implicit[0] and attrs:
                spans.append((implicit[0], builder.view_position, attrs, implicit[1]))
            implicit = None

    for index, token in enumerate(tokens):
        if token.end <= note.body_start or token.end <= builder.source_position:
            continue
        if token.start >= note.closer_start:
            break
        if token.kind is SfmTokenKind.TEXT:
            end = min(token.end, note.closer_start)
            attributes = _attribute_start(tokens, index, closers)
            if attributes is not None and attributes < end:
                if attributes > builder.source_position:
                    builder.text(attributes, source[builder.source_position : attributes], line_break=" ")
                builder.hidden(end, "attributes")
            elif end > builder.source_position:
                builder.text(end, source[builder.source_position : end], line_break=" ")
            continue
        if is_milestone(token.text) or is_milestone_close(token.text):
            builder.hidden(min(_milestone_end(tokens, index), note.closer_start), "milestone")
            continue
        marker = _bare(token.text)
        if not is_nested(token.text):
            close_implicit()
        if is_closing(token.text):
            opener = closers.get(token.start)
            if opener is not None and marker in _BRACKETED:
                builder.generated("]", marker)
            for index in range(len(open_spans) - 1, -1, -1):
                if open_spans[index][0] == opener:
                    _start, view_start, span_marker = open_spans.pop(index)
                    attrs = presentation_attrs(styles, span_marker, block=False)
                    if builder.view_position > view_start and attrs:
                        spans.append((view_start, builder.view_position, attrs, span_marker))
                    break
            if opener is None:
                view_start = builder.view_position
                builder.marker(token.end, token.text, marker)
                spans.append((view_start, builder.view_position, {"marker_token": "yes"}, marker))
            else:
                builder.hidden(token.end, marker)
            continue
        style = registry.style_for(marker)
        if style is None:
            view_start = builder.view_position
            builder.marker(token.end, token.text, marker)
            spans.append((view_start, builder.view_position, {"marker_token": "yes"}, marker))
            continue
        builder.hidden(min(_separator_end(source, token.end), note.closer_start), marker)
        if token.start in pairs:
            open_spans.append((token.start, builder.view_position, marker))
            if marker in _BRACKETED:
                builder.generated("[", marker)
        elif (style.style_type or "").lower() == "character":
            implicit = (builder.view_position, marker)
    close_implicit()


class SfmStandardView(_SfmViewBase):
    """Text formatted per the STY with every marker inline as a tag."""

    key = "sfm.standard"
    label = "Standard"
    proportional = True
    editable = True
    # No Bold/Italic/… buttons on the pane's top bar (field test, 2026-10-09):
    # the commands stay on the right-click menu and their shortcuts.
    command_buttons = False

    def project(self, source: str) -> Projection:
        return layout_projection(source, self._styles(), self.key, show_markers=True)

    def project_with(
        self,
        source: str,
        hidden_categories: frozenset[str] = frozenset(),
        hyphenation: "HyphenationRules | None" = None,
        direction: str | None = None,
    ) -> Projection:
        """Standard with the reading `direction` of its blocks (the
        categories and hyphenation are Preview's, and ignored here)."""

        return layout_projection(source, self._styles(), self.key, show_markers=True, direction=direction)


class SfmPreviewView(_SfmViewBase):
    """Best-effort print-like rendering: no markup, read-only."""

    key = "sfm.preview"
    label = "Preview"
    proportional = True
    editable = False

    def project(self, source: str) -> Projection:
        return layout_projection(source, self._styles(), self.key, show_markers=False)

    def project_filtered(
        self,
        source: str,
        hidden_categories: frozenset[str] = frozenset(),
        hyphenation: "HyphenationRules | None" = None,
    ) -> Projection:
        """Preview without the notes of the hidden categories, and with
        soft hyphens at `hyphenation`'s break points."""

        return self.project_with(source, hidden_categories, hyphenation)

    def project_with(
        self,
        source: str,
        hidden_categories: frozenset[str] = frozenset(),
        hyphenation: "HyphenationRules | None" = None,
        direction: str | None = None,
    ) -> Projection:
        """Preview with everything a tab can ask of it: the hidden
        categories, hyphenation and the reading `direction` of its blocks."""

        return layout_projection(
            source,
            self._styles(),
            self.key,
            show_markers=False,
            hidden_categories=hidden_categories,
            hyphenation=hyphenation,
            direction=direction,
        )

    def view_commands(self) -> tuple[ViewCommand, ...]:
        return ()


def builder_ends_with_newline(builder: ProjectionBuilder, source: str) -> bool:
    del source
    view = builder._view  # noqa: SLF001 - same-package helper
    for chunk in reversed(view):
        if chunk:
            return chunk.endswith("\n")
    return True


__all__ = [
    "SfmPreviewView",
    "SfmStandardView",
    "auto_caller",
    "caller_attrs",
    "formatting_attrs",
    "layout_projection",
    "note_label",
    "presentation_attrs",
    "sty_color",
]
