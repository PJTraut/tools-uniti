# ADR-0003: Third-Party Regex Engine Authority

Date: 2026-08-31
Status: accepted

## Context

UNITI promises advanced regex search/replace, including named and repeated captures, branch-reset constructs, duplicate-named groups, partial cross-window matching, and replacement semantics. Mixing Python stdlib `re`, Qt regex APIs, or hand-derived capture numbering with the third-party engine would create inconsistent matches and UI behavior.

## Decision

The third-party Python package `regex==2026.5.9` is authoritative for pattern compilation, matching, capture identity, and replacement semantics. UNITI may add bounded virtual-document traversal, cancellation, timeouts, result storage, and presentation around it, but alternative engines must not decide regex meaning.

## Consequences

- The dependency remains exactly pinned until a deliberate upgrade with semantic regression testing.
- Regex UI metadata consults compiled engine semantics rather than independently guessing group numbering.
- Patterns that cannot run within bounded retained context fail clearly instead of switching engines or silently changing meaning.
- Core and UI tests must cover advanced constructs affected by engine upgrades.

## Affected records

- [Current Scope](../01_current/SCOPE.md)
- [Current Architecture](../01_current/ARCHITECTURE.md)
- [Implemented Regex Core Plan](../03_implemented/milestones/2026-08-31-uniti-v0.001a6-regex-core.md)
- `pyproject.toml`
