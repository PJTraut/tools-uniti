"""STY-driven marker placement check (ADR-0016; spec §41, §46).

E6 decision 5 left structural validation to `usfmtc`'s grammar. That still
holds for USFM's *grammar*, but generic SFM projects (custom markers,
project-only stylesheets) have no `usfmtc` grammar at all — this check reads
placement rules from whatever stylesheets are actually loaded, so it covers
both. It is deliberately a separate "Check Marker Placement" command, so a
USFM document's ordinary validation doesn't report the same problem twice.

Context model (lenient, to keep false positives rare):

- a paragraph-level marker (StyleType Paragraph, and `\\c`) may occur under
  the book level — `id` before the first `\\c`, `c` after it — or under the
  paragraph marker it follows (e.g. `\\toc1` under `\\h`);
- any other marker may occur under the current paragraph marker, the book
  level, or any open paired span (a note `\\f`, a character style);
  `NEST` in its list allows it inside another character style.

Markers no stylesheet defines, or with an empty `OccursUnder`, are skipped.
"""

from __future__ import annotations

from uniti.core.environment_findings import EnvironmentFinding, FindingSeverity

from .nodes import SfmNode, SfmNodeKind
from .parser import parse_sfm
from .sty import StyleRegistry
from .tokenizer import tokenize_sfm
from .tokens import SfmTokenKind

MAX_PLACEMENT_FINDINGS = 500


def _bare(marker: str) -> str:
    return marker.lstrip("\\").rstrip("*")


def _pairs(node: SfmNode, pairs: dict[int, int]) -> None:
    for child in node.children:
        if child.kind is SfmNodeKind.CHARACTER and child.marker is not None:
            pairs[child.start] = child.end
            _pairs(child, pairs)


def _describe(allowed: tuple[str, ...]) -> str:
    shown = " ".join(f"\\{marker}" for marker in allowed[:6])
    return shown + (" …" if len(allowed) > 6 else "")


def placement_findings(text: str, registry: StyleRegistry) -> tuple[EnvironmentFinding, ...]:
    tokens = tokenize_sfm(text)
    pairs: dict[int, int] = {}
    _pairs(parse_sfm(tokens), pairs)
    findings: list[EnvironmentFinding] = []
    chapter_seen = False
    paragraph: str | None = None
    open_spans: list[tuple[str, int]] = []  # (marker, span end)
    for token in tokens:
        while open_spans and open_spans[-1][1] <= token.start:
            open_spans.pop()
        if token.kind is not SfmTokenKind.MARKER or token.text.endswith("*"):
            continue
        marker = _bare(token.text)
        style = registry.style_for(marker)
        allowed = style.occurs_under if style else ()
        style_type = ((style.style_type if style else None) or "").lower()
        is_paragraph = style_type == "paragraph" or marker == "c"
        book_level = "c" if chapter_seen else "id"
        if is_paragraph:
            contexts = {book_level, "id" if marker == "c" else book_level}
            if paragraph is not None:
                contexts.add(paragraph)
        else:
            contexts = {book_level}
            if paragraph is not None:
                contexts.add(paragraph)
            contexts.update(span for span, _end in open_spans)
        ok = (
            not allowed
            or bool(contexts.intersection(allowed))
            or ("NEST" in allowed and any(
                ((registry.style_type(span) or "").lower() == "character") for span, _end in open_spans
            ))
        )
        if not ok:
            where = (
                f"inside \\{open_spans[-1][0]}"
                if open_spans and not is_paragraph
                else f"after \\{paragraph}"
                if paragraph is not None
                else "here"
            )
            findings.append(
                EnvironmentFinding(
                    token.start,
                    token.end,
                    FindingSeverity.WARNING,
                    f"\\{marker} is not expected {where} (stylesheet allows it under {_describe(allowed)})",
                    code="sfm.occurs-under",
                )
            )
            if len(findings) >= MAX_PLACEMENT_FINDINGS:
                break
        if marker == "c":
            chapter_seen = True
            paragraph = None
        elif is_paragraph:
            paragraph = marker
        if token.start in pairs:
            open_spans.append((marker, pairs[token.start]))
    return tuple(findings)


__all__ = ["MAX_PLACEMENT_FINDINGS", "placement_findings"]
