# UNITI Architecture Deviations

Date: 2026-10-27

This register lists UNITI behaviour that goes beyond, or against, an accepted architecture decision. It is a record of what the code does today, not an approval. An entry stays here until the owner either amends the decision (a new or superseding ADR) or removes the behaviour.

## Status grammar

- `open`: the deviation is in the code and no decision covers it.
- `accepted`: an ADR now covers it; the entry links to that ADR.
- `removed`: the behaviour was taken out; the entry is kept for history.

## Index

| ID | Status | Decision deviated from | Summary |
|---|---|---|---|
| [AD-001](#ad-001--replacement-case-escapes-u-l-e-u-l) | open | [ADR-0003](05_decisions/ADR-0003-regex-engine-authority.md) | UNITI itself implements `\U`, `\L`, `\E`, `\u` and `\l` in replacement text. |

## AD-001 — Replacement case escapes `\U` `\L` `\E` `\u` `\l`

Status: open
Recorded: 2026-10-27
Code: commit `acd641c` (`regex: replacement case escapes`); user documentation in commit `efcb851`.

### What the decision says

[ADR-0003](05_decisions/ADR-0003-regex-engine-authority.md): the third-party `regex` package is "authoritative for pattern compilation, matching, capture identity, and **replacement semantics**". UNITI may add traversal, cancellation, timeouts, result storage and presentation around it, but "alternative engines must not decide regex meaning". UNITI's design intent is raw, native `regex` behaviour, not a UNITI-defined dialect.

### What the code does

`regex.Match.expand()` has no case conversion. (The library's own `\u` and `\U` are pattern-side code point escapes, not case changes.) UNITI therefore:

- tokenizes the replacement template (`tokenize_replacement`, `src/uniti/regex/lexer.py`), emitting a `case_escape` token for `\U`, `\L`, `\E`, `\u` and `\l`;
- expands each other token separately with `match.expand()`;
- applies the case changes itself in `src/uniti/regex/replacement_expand.py` (`_CaseState`, `expand_tokens`, `expand_replacement`), using Python's `str.upper()` and `str.lower()`.

It is used by Replace, Replace All, the streamed file replace (`replace.py`) and the capture preview (`captures.py`). The regex input highlights the escapes (`ui/regex_input.py`). Tests: `tests/test_regex_lexer.py`, `tests/test_regex_replace.py`.

### Why it is a deviation

- The engine does not define these escapes. UNITI does, so UNITI, not the engine, decides what part of a replacement template means.
- The template is split into tokens and expanded piece by piece, rather than handed to the engine whole.
- A replacement written for UNITI is not valid for a bare `regex` call: `\U` and `\L` would be rejected as bad escapes, or `\u` would be read as a code point escape.
- The behaviour follows Perl, PCRE and Notepad++ conventions, not the engine's. Edge cases (for example `ß`.upper() is `SS`) follow Python's rules.
- It was committed without checking it against ADR-0003 or recording the conflict.

### What is not affected

Group references (`\1`, `\g<name>`), character escapes and code point escapes (`\uHHHH`, `\UHHHHHHHH`, `\xHH`, `\N{...}`) are still expanded by the engine through `match.expand()`. Pattern compilation and matching are untouched. Case conversion is the only replacement semantics UNITI decides itself.

### Open decision (owner)

1. **Remove** the escapes and keep the engine as the only authority; revert `acd641c` and trim `efcb851`.
2. **Accept as a narrow exception** by amending ADR-0003 for replacement-side case conversion, noting that the engine has no equivalent.
3. **Accept but gate it** (for example, opt-in) and record that in an ADR.

Until the owner decides, the behaviour stays in the tree and the user cheat sheet says it is a UNITI extension.

### Known gaps in this register

This register was started because of AD-001. It has not been used to audit the rest of the code against ADR-0002 and ADR-0003, so other deviations may exist and are not listed.
