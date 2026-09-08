# Regex flags and line anchors

[User Manual](user-manual.md) · [User Cheat Sheet](user-cheat-sheet.md)

UNITI's Regex mode uses the pinned Python `regex` engine (`2026.5.9`) without automatically enabling editor-style multiline matching. Matching is case-sensitive by default. `^` means the start of the entire document, and `.` excludes LF (`\n`). Enter patterns directly in Find; no Python quotes, `r"..."` wrapper, or `/.../` delimiters are needed.

With **Regex** enabled, **Case** and **Whole word** are disabled; inline flags control regex behavior. With Regex disabled, the input is literal text and those checkboxes apply.

## Standard inline flags

Put flags at the beginning of the pattern for the clearest whole-pattern intent.

| Flag | Name | Effect and example |
|---|---|---|
| `(?i)` | Case-insensitive | `(?i)apple` matches `Apple`, `APPLE`, and `apple`. |
| `(?m)` | Multiline | Makes `^` and `$` recognize line boundaries. `(?m)^apple$` matches a complete LF-delimited line containing `apple`. |
| `(?s)` | Dot-all / single-line | Makes `.` include newline characters. `(?s)a.b` matches `a`, a newline, then `b`. |
| `(?x)` | Extended / free-spacing | Ignores unescaped pattern whitespace outside character classes and permits `#` comments to the end of the pattern line. |

`m` changes anchors; `s` changes the dot. Neither changes the other. Dot-all does not override an explicit character class such as `[^\r\n]`.

In free-spacing mode, use `[ ]` or `\ ` for a literal space, and `\#` or `[#]` for a literal hash. It changes how the pattern is read, not the document's whitespace. These standard behaviors are described in the [Python regex syntax reference](https://docs.python.org/3.12/library/re.html#regular-expression-syntax); UNITI uses the third-party engine for its additional features.

## Document start versus line start

For this document:

```text
# Tasks
1. Train staff
2. Review publications
3. Add QA
```

| Pattern | Matches |
|---|---|
| `(\d+)\D([^\r\n]+)` | All three numbered entries. |
| `^(\d+)\D([^\r\n]+)` | None: the document begins with `#`, not a digit. |
| `(?m)^(\d+)\D([^\r\n]+)` | All three numbered entries at line starts. |

If the document begins directly with `1.`, the pattern without `(?m)` matches the first entry only. Cursor position does not change these anchor semantics. A valid pattern can produce zero matches.

For strict document boundaries, use `\A` and `\Z`, even with multiline enabled. `$` also matches immediately before a final LF, so it is not a strict end-of-document assertion: `apple$` matches `apple\n`, whereas `apple\Z` does not. See the [anchor reference](https://docs.python.org/3.12/library/re.html#regular-expression-syntax).

## Combining and scoping flags

- `(?im)^apple$` combines case-insensitive and multiline matching.
- `(?i:apple)` applies case-insensitive matching only inside that group.
- `(?i:apple)-(?-i:ID)` accepts `APPLE-ID` but rejects `apple-id`; `-i` explicitly disables case-insensitive matching in the second group.

Scoped flag groups do not add captures. The engine documents the form [`(?flags-flags:...)`](https://pypi.org/project/regex/2026.5.9/#scoped-flags-issue-433028).

## Unicode and engine-specific options

- `(?a)` selects ASCII behavior for shorthand classes and related boundaries. For example, `(?a)\d+` matches ASCII digits; default Unicode `\d+` also matches digits such as `١٢٣`. `(?u)` explicitly selects Unicode behavior, already the default for UNITI text.
- `(?w)` selects Unicode word boundaries and broader line-separator recognition. Combine it with `m`, as in `(?mw)^\d+`, to recognize starts after CR-only and other Unicode line separators as well as LF/CRLF. It also affects `.` when dot-all is off. UNITI searches actual line endings; ordinary `(?m)` uses LF boundaries, so CR in CRLF remains relevant when matching immediately before `$`.
- `(?f)` asks the engine for full Unicode case folding when `i` is also enabled. This mode has an open B2 search-boundary qualification issue; see [BF-012](project/BETA_FEEDBACK.md#bf-012--full-unicode-case-folding-misses-a-match-with-one-character-search-windows).
- `(?V0)` and `(?V1)` select engine behavior versions. The pinned engine defaults to V0. V1 changes flag scope, set syntax, and Unicode case folding; its full-folding mode is also covered by BF-012. It is not required for ordinary multiline matching.

These options are described in the pinned engine's [flags documentation](https://pypi.org/project/regex/2026.5.9/#flags) and [Unicode line-separator rules](https://pypi.org/project/regex/2026.5.9/#unicode-line-separators). Other advanced engine flags are outside this everyday guide; engine support alone does not establish qualification for every bounded UNITI operation.
