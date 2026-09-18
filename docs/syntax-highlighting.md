# Syntax highlighting: file-type definitions

[User Manual](user-manual.md) · [User Cheat Sheet](user-cheat-sheet.md) · [Regex Flags Guide](regex-flags.md)

This specifies exactly what UNITI's built-in syntax-highlighting profiles tokenize and color for **XML**, **JSON**, **YAML** (`.yml`), **SFM**, and **Plain Text** — the five profiles most relevant to markup/data-interchange and translation-format documents. Two more profiles exist (Markdown, CSV, TSV) but aren't covered here; see `src/uniti/core/syntax_profiles.py` for their rules if needed.

Every profile is implemented in `uniti.core.syntax_profiles` (`src/uniti/core/syntax_profiles.py`) and selected per document by file extension — see [Assigning a profile](#assigning-a-profile) below. All eight color categories used across every profile (`keyword`, `string`, `number`, `tag`, `attribute`, `heading`, `comment`, `punctuation`) are user-recolorable per theme profile in **View → Theme → Edit Themes** (the `syntax.*` roles), not fixed colors.

## How tokenizing works

Each profile is called once per **logical line** (not per visible/wrapped row), taking that line's text and the tokenizer's own state as of the line's start, and returns the line's colored spans plus the state to carry into the *next* logical line. This is what lets a construct that spans multiple lines — an XML comment, a YAML block scalar — highlight correctly across every line it covers, not just the one line that happens to contain both its opening and closing markers.

Within one line, rules are tried in a fixed order at each character position; the **first rule that matches wins** for that position, and scanning resumes right after the match. A character that matches no rule gets no token at all and renders in the document's ordinary text color — most of an XML tag's or JSON string's surrounding punctuation-free content works this way.

Every profile is presentation-only: a heuristic pattern match over the visible line, not a real parser. Each profile's known heuristic gaps are listed in its own section below rather than hidden.

## XML

- **Extensions:** `.xml`
- **Stateful** — an XML comment or CDATA section left open at the end of one line carries into the next, so a multi-line `<!-- ... -->` or `<![CDATA[ ... ]]>` highlights correctly across every line it spans, not just where it opens.

| Category | Matches |
|---|---|
| `comment` | `<!-- ... -->`, including when it spans multiple lines |
| `keyword` | `<![CDATA[ ... ]]>`, **including its inner content** — the whole CDATA section is colored as `keyword`, not `string`; there is no separate coloring for the raw character data inside it |
| `tag` | An opening or closing tag name: `<name` or `</name` |
| `punctuation` | The tag close: `>` or `/>` |
| `attribute` | An attribute name, only when immediately followed by `=` (matched by lookahead, so the `=` itself belongs to no category) |
| `string` | A double- or single-quoted attribute value; tolerates an unterminated quote at end of line (colors to line end rather than emitting no token) |
| *(none)* | Element text content between tags — deliberately uncolored |

**Known limitation:** state threads across whole logical lines only, not within one very long logical line's own wrapped/horizontal-scroll rows — a comment or CDATA section that opens and closes within different visible rows of the *same* giant line won't highlight correctly; separate logical lines (the overwhelmingly common case) work correctly.

## JSON

- **Extensions:** `.json`
- **Stateless** — a JSON string cannot legally contain a literal newline, so no construct here can span a line.

| Category | Matches |
|---|---|
| `comment` | `// ...` to end of line. **Note:** standard JSON has no comment syntax; this is a deliberate tolerance for JSON5/JSONC-style content, not strict-JSON grammar enforcement |
| `string` | `"..."`, escape-aware (`\"`, `\\`, etc. don't end the string early); tolerates an unterminated quote at end of line. This also covers object keys — JSON has no separate key syntax |
| `number` | An optional leading `-`, digits, an optional decimal fraction, an optional exponent (`e`/`E`, optional sign) |
| `keyword` | `true`, `false`, `null` (whole-word matched) |
| `punctuation` | Any of `{ } [ ] : ,` |
| *(none)* | Anything else — in valid JSON, nothing should reach this, since every value/key is one of the categories above |

## YAML (`.yaml` / `.yml`)

- **Extensions:** `.yaml`, `.yml`
- **Stateful** — a block scalar (`|` or `>`) leaves the document in "inside the block" mode until a line dedents below the block's own established indent, so multi-line block scalar content highlights as a single `string` span across every line it covers.

| Category | Matches |
|---|---|
| `comment` | `#` to end of line |
| `string` | `"..."` (backslash-escape aware) or `'...'` (YAML's own doubled-single-quote `''` escape aware); either tolerates an unterminated quote at end of line |
| `keyword` | `true`, `false`, `null`, `yes`, `no` — case-insensitive, whole-word matched |
| `number` | An optional leading `-`, digits, an optional decimal fraction |
| `punctuation` | A list-item dash (`-`) at the start of a line (before whitespace or end of line), and separately, any `:` character |
| `attribute` | A mapping key at the start of a (possibly indented) line, up to but not including its colon |

**Block scalars:** a line ending in `: |`, `: >`, `- |2-`, etc. (a colon or dash, then `|`/`>`, an optional sign/digit indent indicator, optionally followed by a trailing comment) opens block-scalar mode. The first content line inside establishes the reference indent; every following line at or beyond that indent (including blank lines) stays inside the block and colors as `string`; the first line that dedents below it closes the block and returns to normal line tokenizing.

**Known limitation, called out directly in the source rather than hidden:** block-scalar-open detection is a heuristic regex match on the line's end, not full YAML grammar — a literal `|` or `>` that happens to sit right after a colon or dash inside a quoted string or a comment can falsely open block-scalar mode.

## SFM

- **Extensions:** `.sfm`
- **Stateless** — SFM markers are inherently line-oriented (per the source's own note).

| Category | Matches |
|---|---|
| `keyword` | A backslash marker: a backslash, a letter, then any run of letters/digits, with an optional trailing `*` for an end marker — e.g. `\id`, `\v`, `\wj*` |
| *(none)* | Everything else — marker content, verse text, footnote text, and all other prose is deliberately uncolored |

This is the narrowest profile by design: only the marker tokens themselves are colored. Nothing about a marker's *meaning* (paragraph vs. character vs. milestone marker, nesting, footnote/cross-reference structure) is distinguished — every marker gets the same single `keyword` category regardless of kind.

**Noted 2026-09-18, for future reference:** Paratext ships `.sty` stylesheet files (a hybrid DTD-and-stylesheet format, per the user directly) that define the actual set of valid SFM markers and their per-marker properties (style type — paragraph/character/note/milestone — plus formatting). UNITI's current SFM profile knows none of this; it recognizes the generic `\marker`/`\marker*` shape only, with no notion of which markers are valid, what kind each one is, or how a `.sty` file would inform richer per-marker-kind coloring. Recorded here as a possible future input, not yet scoped or committed to any plan — see also the [Feature Wishlist](FEATURE_WISHLIST.md#sfm-highlighting-informed-by-paratext-sty-stylesheets).

## Plain Text

- **Extensions:** none are mapped to it explicitly by default — it's the universal fallback (see below), which also covers `.txt` and any other unrecognized extension.
- **Stateless**, and produces **no tokens at all, ever** — this is the true "no highlighting" baseline, not an empty rule set that happens to match nothing.

## Assigning a profile

An extension resolves to a profile by (in priority order):

1. A per-document override the user has assigned via **View → Text-Type Profiles…** (`ExtensionProfileEditor`, persisted in `Settings.syntax_extension_overrides`) — e.g. mapping a custom `.usj` extension to the JSON profile.
2. Otherwise, the built-in default mapping: `md`/`markdown` → Markdown, `xml` → XML, `json` → JSON, `yaml`/`yml` → YAML, `sfm` → SFM, `csv` → CSV, `tsv` → TSV.
3. Any extension matched by neither — including `.txt`, and including an override/default that names an unknown profile key — falls back to Plain Text. Highlighting must never fail to display a document.

Matching is case-insensitive and tolerates a leading dot on the extension.

## See also

- [BF-027 / BF-041](project/BETA_FEEDBACK.md#bf-027--file-type-syntax-highlighting-profiles-xml-yml-json-sfm-md-tsv-csv-) — original profile implementation and the extension-mapping extension point.
- [BF-071](project/BETA_FEEDBACK.md#bf-071--multiline-aware-syntax-highlighting) — the multi-line/stateful tokenizing this document describes for XML and YAML (and Markdown fences, not covered here).
- [BF-063](project/BETA_FEEDBACK.md#bf-063--theme--text-type-profile-editor) and [ADR-0011](project/05_decisions/ADR-0011-syntax-category-color-editing.md) — the extension-mapping editor UI, and making all eight categories user-recolorable per theme.
