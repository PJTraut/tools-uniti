"""Generic-SFM basic source model (Phase E5).

Builds a permissive overlay tree from a token stream. Per the handover
spec's own "generic SFM" definition (recognize markers, recognize
paired/end markers, allow custom markers, permissive structure) this parser
nests **only** genuine `\\marker ... \\marker*` pairs into `CHARACTER`
nodes. A marker that is never closed by a matching `\\marker*` — which is
the normal case for paragraph-style markers like `\\p`/`\\v`/`\\c`, since
USFM only assigns `EndMarker`s to character-style markers — becomes a flat
`MARKER` leaf, and does **not** swallow the rest of the document as its
children.

Deciding which unclosed markers *should* nest (e.g. that a `\\v` verse
implicitly contains everything until the next `\\v`/`\\c`) needs USFM/STY
`OccursUnder`+`Rank` knowledge this phase does not load into the
environment yet — that structural nesting is Phase E6's job, once a style
registry is wired into activation. Building a wrong generic guess now would
be a worse foundation than staying flat and honest about what is actually
known: which markers were explicitly paired by the document's own author.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .nodes import SfmNode, SfmNodeKind
from .tokens import SfmToken, SfmTokenKind


@dataclass
class _Frame:
    marker: str | None
    start: int
    children: list[SfmNode] = field(default_factory=list)


def parse_sfm(tokens: Sequence[SfmToken]) -> SfmNode:
    """Parse a token stream (from `tokenizer.tokenize_sfm`) into a tree."""

    doc_start = tokens[0].start if tokens else 0
    doc_end = tokens[-1].end if tokens else 0
    stack: list[_Frame] = [_Frame(marker=None, start=doc_start)]

    for token in tokens:
        if token.kind is SfmTokenKind.TEXT:
            stack[-1].children.append(SfmNode(SfmNodeKind.TEXT, token.start, token.end))
            continue
        if token.text.endswith("*"):
            base = token.text[:-1]
            match_index = next(
                (i for i in range(len(stack) - 1, 0, -1) if stack[i].marker == base),
                None,
            )
            if match_index is None:
                stack[-1].children.append(
                    SfmNode(SfmNodeKind.MARKER, token.start, token.end, marker=token.text)
                )
                continue
            while len(stack) - 1 > match_index:
                _flatten_top(stack)
            frame = stack.pop()
            stack[-1].children.append(
                SfmNode(
                    SfmNodeKind.CHARACTER,
                    frame.start,
                    token.end,
                    marker=frame.marker,
                    children=tuple(frame.children),
                )
            )
        else:
            stack.append(_Frame(marker=token.text, start=token.start))

    while len(stack) > 1:
        _flatten_top(stack)

    return SfmNode(SfmNodeKind.DOCUMENT, doc_start, doc_end, children=tuple(stack[0].children))


def _flatten_top(stack: list[_Frame]) -> None:
    """Pop an unclosed frame, demoting it to a flat leaf plus its children.

    This is what makes an ordinary unclosed `\\p`/`\\v` degrade to a flat
    sibling sequence instead of nesting the rest of the document under it:
    the marker becomes a childless `MARKER` leaf, and whatever it had
    accumulated as children is spliced into the parent frame right after it,
    at the same level — not nested inside it.
    """

    frame = stack.pop()
    parent = stack[-1]
    assert frame.marker is not None
    marker_end = frame.start + len(frame.marker)
    parent.children.append(SfmNode(SfmNodeKind.MARKER, frame.start, marker_end, marker=frame.marker))
    parent.children.extend(frame.children)
