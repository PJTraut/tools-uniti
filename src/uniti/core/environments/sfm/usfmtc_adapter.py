"""`usfmtc` reference/conformance validation adapter (ADR-0013, Phase E6).

Per the handover spec's own conclusion: `usfmtc` is a standards-reference
parser, not UNITI's canonical document owner (§3, §43) — it is used here
purely as a diagnostics source, never to build or store UNITI's document
model. It is imported lazily, inside this function, so `import usfmtc` (and
whatever grammar-construction cost it carries) is paid only when a `.usfm`
document is actually validated, never at process/package-import time —
`UsfmEnvironment`'s decoration path never touches this module at all.

**Position-mapping limitation, by design, not oversight:** `usfmtc`'s error
positions (`Pos(line, col)`) are measured against its own internal parse
state, not raw source line/column — empirically, its line counter does not
match a naive `text.splitlines()` count (verified against several small
fixtures while building this adapter: the same offending line reports a
different line number depending on which header markers precede it).
Reverse-engineering its exact counting convention well enough to trust for
`EnvironmentFinding.start`/`end` was judged not worth the risk of silently
mislocating an error onto the wrong source range — worse than not
localizing at all. So every finding from this adapter spans the whole
document (`0, len(text)`) rather than a guessed, possibly-wrong range; the
message text itself includes `usfmtc`'s own verse reference (e.g.
`"GEN 1:1"`) where available, which is what makes the finding actionable
without a precise span. A future phase can revisit this if `usfmtc` is
studied enough to map positions reliably, or if a lower-level API turns out
to expose true source offsets.
"""

from __future__ import annotations

import logging

from uniti.core.environment_findings import EnvironmentFinding, FindingSeverity

logger = logging.getLogger("uniti.environment.usfm")

_grammar: object | None = None


def validate_with_usfmtc(text: str) -> tuple[EnvironmentFinding, ...]:
    """Run `usfmtc`'s reference USFM parser and surface its diagnostics."""

    if not text.strip():
        return ()
    try:
        import usfmtc
    except ImportError:
        logger.warning("usfmtc is not installed; skipping reference USFM validation")
        return ()

    global _grammar
    try:
        if _grammar is None:
            _grammar = usfmtc.usfmGrammar(None)
        usx = usfmtc.USX.fromUsfm(text, grammar=_grammar)
    except Exception as exc:  # usfmtc raises assorted internal exception types on bad input
        logger.warning("usfmtc failed to parse USFM document: %s", exc)
        return (
            EnvironmentFinding(
                0,
                len(text),
                FindingSeverity.ERROR,
                f"USFM reference parser could not process this document: {exc}",
                code="usfm.usfmtc-parse-error",
            ),
        )

    findings: list[EnvironmentFinding] = []
    for message, _pos, reference in getattr(usx, "errors", ()):
        suffix = f" ({reference.strip()})" if reference and reference.strip() else ""
        findings.append(
            EnvironmentFinding(
                0,
                len(text),
                FindingSeverity.WARNING,
                f"{message}{suffix}",
                code="usfm.usfmtc-reference",
            )
        )
    return tuple(findings)


__all__ = ["validate_with_usfmtc"]
