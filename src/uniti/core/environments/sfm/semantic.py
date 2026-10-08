"""SFM semantic edit commands (ADR-0015, spec §32 / Phase E8).

Each works in source offsets and returns an `EditPlan` — never a rewritten
document. Used by the Standard and Formatted views' commands.
"""

from __future__ import annotations

from collections.abc import Callable

from uniti.core.rich_views.editing import EditPlan, EditRejected

from .markers import NOTE_MARKERS, is_closing, is_milestone, is_milestone_close, marker_name
from .nodes import SfmNode, SfmNodeKind
from .parser import parse_sfm
from .sty import StyleRegistry
from .tokenizer import tokenize_sfm
from .tokens import SfmTokenKind


def _bare(marker: str) -> str:
    return marker_name(marker)


def _opening(token_text: str) -> bool:
    return not (is_closing(token_text) or is_milestone(token_text) or is_milestone_close(token_text))


def apply_character_style(source: str, start: int, end: int, marker: str) -> EditPlan:
    """Wrap [start, end) in ``\\marker …\\marker*`` — or, inside another
    character style, the nested ``\\+marker …\\+marker*`` (USFM 3)."""

    marker = _bare(marker)
    if start > end:
        start, end = end, start
    if start == end:
        raise EditRejected("select text to style first")
    enclosing = _innermost_character(parse_sfm(tokenize_sfm(source)), start)
    nested = (
        enclosing is not None
        and enclosing.marker is not None
        and _bare(enclosing.marker) not in NOTE_MARKERS
        and enclosing.start < start
        and end < enclosing.end
    )
    prefix = "+" if nested else ""
    opener = f"\\{prefix}{marker} "
    closer = f"\\{prefix}{marker}*"
    return EditPlan(((start, start, opener), (end, end, closer)), end + len(opener) + len(closer))


def _innermost_character(node: SfmNode, offset: int) -> SfmNode | None:
    for child in node.children:
        if child.kind is SfmNodeKind.CHARACTER and child.start <= offset <= child.end:
            return _innermost_character(child, offset) or child
    return None


def remove_character_style(source: str, offset: int) -> EditPlan:
    """Unwrap the innermost paired character span containing `offset`."""

    tokens = tokenize_sfm(source)
    span = _innermost_character(parse_sfm(tokens), offset)
    if span is None or span.marker is None:
        raise EditRejected("the cursor is not inside a character style")
    opener_end = span.start + len(span.marker)
    if opener_end < len(source) and source[opener_end] == " ":
        opener_end += 1
    closer = span.marker + "*"
    closer_start = span.end - len(closer)
    caret = offset - (opener_end - span.start)
    return EditPlan(((span.start, opener_end, ""), (closer_start, span.end, "")), max(span.start, caret))


def governing_paragraph_marker(source: str, offset: int, registry: StyleRegistry) -> tuple[int, int, str] | None:
    """(start, end, marker) of the paragraph marker token that governs `offset`."""

    found = None
    for token in tokenize_sfm(source):
        if token.start >= offset and found is not None:
            break
        if token.kind is not SfmTokenKind.MARKER or not _opening(token.text):
            continue
        if token.start > offset:
            break
        if (registry.style_type(_bare(token.text)) or "").lower() == "paragraph":
            found = (token.start, token.end, _bare(token.text))
    return found


def change_paragraph_marker(source: str, offset: int, marker: str, registry: StyleRegistry) -> EditPlan:
    found = governing_paragraph_marker(source, offset, registry)
    if found is None:
        raise EditRejected("no paragraph marker governs the cursor")
    start, end, _old = found
    replacement = f"\\{_bare(marker)}"
    return EditPlan(((start, end, replacement),), offset + len(replacement) - (end - start))


def insert_marker_text(offset: int, text: str) -> EditPlan:
    return EditPlan(((offset, offset, text),), offset + len(text))


def insert_verse(source: str, offset: int, number: str) -> EditPlan:
    number = number.strip()
    if not number or not number[0].isdigit():
        raise EditRejected("verse numbers start with a digit")
    prefix = "" if offset == 0 or source[offset - 1] in " \n" else " "
    return insert_marker_text(offset, f"{prefix}\\v {number} ")


def paragraph_enter_text(source: str, offset: int, registry: StyleRegistry) -> str:
    """Enter starts a new paragraph of the same kind (default ``\\p``)."""

    found = governing_paragraph_marker(source, offset, registry)
    marker = found[2] if found is not None else "p"
    return f"\n\\{marker} "


def character_markers(registry: StyleRegistry) -> tuple[str, ...]:
    return tuple(
        sorted(
            marker
            for marker in registry.markers()
            if (registry.style_type(marker) or "").lower() == "character" and registry.end_marker(marker)
        )
    )


def paragraph_markers(registry: StyleRegistry) -> tuple[str, ...]:
    return tuple(
        sorted(marker for marker in registry.markers() if (registry.style_type(marker) or "").lower() == "paragraph")
    )


RegistrySource = Callable[[], StyleRegistry]
