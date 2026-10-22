# USFM Stylesheet Rules

UNITI's **Standard** and **Preview** views take every look from the stylesheets: paragraph, character and note styles, by marker. They read the same `.sty` files as Paratext and PTXprint, and add a small CSS-like layer on top: **rules**. This page is the whole reference for them: the file format, every field UNITI reads, the selectors, justification, hyphenation, the built-in rules, and how it all fits with Paratext.

- [Stylesheet layers](#stylesheet-layers) — which file wins
- [The file format](#the-file-format) — records, fields, flags, comments
- [Fields](#fields) — everything UNITI reads, with units
- [Marker records](#marker-records) — change a marker's own style
- [Rules and selectors](#rules-and-selectors) — `a+b`, `marker::caller`, lists
- [Justification](#justification) — `Left`, `Right`, `Center`, `Both`, `Start`, `End`
- [Text direction](#text-direction) — `\Direction`, and where a paragraph's direction comes from
- [Hyphenation](#hyphenation) — `\Hyphenate` and the Hyphenate Preview toggle
- [Built-in rules](#built-in-rules)
- [How a style is worked out](#how-a-style-is-worked-out)
- [Where to put rules](#where-to-put-rules)
- [What rules don't do](#what-rules-dont-do)
- [Recipes](#recipes)

## Stylesheet layers

Layered from lowest to highest precedence:

1. the official `usfm.sty`, built into UNITI;
2. UNITI's built-in rules (`uniti.sty (built-in)`);
3. **your** rules, `uniti.sty` in your configuration folder (`…/Environments/USFM/uniti.sty`), for every USFM file;
4. the project's stylesheet: `usfm.sty`, or the one `Settings.xml` names (`StyleSheet`), next to the book files;
5. the project's `custom.sty`;
6. the project's `shared/ptxprint/ptxprint-mods.sty`;
7. the project's own `uniti.sty`, next to the book files;
8. any stylesheet loaded with **Load Stylesheet…**, for the session.

A later layer wins, field by field: a project `custom.sty` that sets `\FontSize 14` on `\p` changes only the size; every other field of `\p` still comes from the layers below. The **Style Inspector** shows each value with the layer it came from, and **Configuration Files…** lists the files that apply to the current book. Saving any of them reloads the stylesheets, and Standard and Preview update straight away.

## The file format

A `.sty` file is a list of **records**. A record starts with `\Marker` and holds the lines after it, one `\Field value` per line, until the next `\Marker`.

```
# A comment: from # to the end of the line, on its own line or after a value.
\Marker nd
\Name nd - Name of Deity, shown in small capitals
\SmallCaps
\Underline -
```

- **Fields are case-insensitive** (`\SmallCaps`, `\smallcaps`). The marker name is not: `\Marker nd`.
- **A flag is on when written bare** (`\Bold`), or with `Yes`, `True` or `1`. **It's off with `-`**, `No`, `False` or `0`. A later layer can turn off what an earlier one turned on (`\Underline -`).
- **A value** is the text after the field name; a trailing `# comment` is dropped.
- **Unknown fields are kept and ignored.** UNITI reads the fields below and leaves the rest alone, including PTXprint's.
- Files are UTF-8, with or without a BOM, up to 2 MiB. A file that can't be read is skipped.

## Fields

These fields change how Standard and Preview look. Paratext and PTXprint read the same fields in their own way; `\Hyphenate` and `\Direction` are UNITI's own.

| Field | Value | Applies to | What it does |
|---|---|---|---|
| `\Bold` | flag | any style | bold |
| `\Italic` | flag | any style | italic |
| `\Underline` | flag | any style | underlined |
| `\Superscript` | flag | any style | raised, smaller |
| `\SmallCaps` | flag | any style | small capitals |
| `\FontSize` | points | any style | the size, as a multiple of `\p`'s own `\FontSize` (12 if `\p` has none): `\FontSize 18` on a 12-point body is 1.5 times larger. Changing `\p`'s size rescales every other style. |
| `\Color` | number | any style | Paratext's `0xBBGGRR` colour as a decimal integer (red is `255`, blue is `16711680`). Black (`0`) means no colour. The colour is adjusted to stay readable on the editor theme's background. |
| `\Justification` | `Left` `Center` `Right` `Both` `Justify` `Start` `End` | paragraph | which edge the lines sit against; see [Justification](#justification) |
| `\Hyphenate` | flag | paragraph | whether Preview breaks this paragraph's words at their hyphenation points; see [Hyphenation](#hyphenation) |
| `\Direction` | `LTR` `RTL` `Auto` | paragraph, character | a paragraph's reading direction, over the tab's and the project's; on a character style, the direction its text reads in, inside any paragraph; see [Text direction](#text-direction) |
| `\LeftMargin` | inches | paragraph | indent of every line from the start edge (the right edge in a right-to-left paragraph) |
| `\RightMargin` | inches | paragraph | indent from the end edge |
| `\FirstLineIndent` | inches | paragraph | extra indent of the first line on the start side (negative for a hanging indent) |
| `\SpaceBefore` | points | paragraph | space above the paragraph |
| `\SpaceAfter` | points | paragraph | space below it |

"Paragraph" fields apply to a paragraph style (`\p`, `\q1`, `\s1`, …), a `\c` chapter heading and a rule that targets one. A character style (`\nd`, `\w`) and a note caller take the flags, `\FontSize` and `\Color`. Setting a paragraph field on a character style does nothing.

The structural fields of a marker (`\Name`, `\Description`, `\StyleType`, `\TextType`, `\TextProperties`, `\OccursUnder`, `\Rank`, `\Endmarker`, `\NotRepeatable`) are read as in Paratext. They define what a marker is rather than how it looks, and they drive validation, placement checks and the Book list.

## Marker records

A record whose `\Marker` is an ordinary marker name changes that marker's style, like any stylesheet layer. It can restyle a marker the official `usfm.sty` defines, or define a new one:

```
\Marker nd
\SmallCaps
\Underline -
```

Nested markers such as `\+it` inside `\nd` take the style of `\it`, applied on top of `\nd`'s: italic small capitals.

A marker no loaded stylesheet defines is shown as a tag and reported by **Check Undefined Markers**. A record gives it a definition:

```
\Marker zfoo
\Endmarker zfoo*
\Name zfoo - Project term
\StyleType Character
\TextProperties publishable
\Italic
```

## Rules and selectors

A plain `.sty` can only style a marker by itself. A **rule** is an ordinary record whose `\Marker` is a **selector**: a CSS-like pattern, not a marker name. A rule takes the same fields as a marker record. There are two kinds of selector.

### Paragraph after paragraph: `a+b`

`\Marker p+q1` styles a `\q1` paragraph that comes straight after a `\p` paragraph, like CSS's adjacent-sibling selector `p + q1`. Its fields win over `\q1`'s own.

```
\Marker p+q1, p+q2, p+q3, q1+p, q2+p, q3+p
\Name Blank line between prose and poetry
\SpaceBefore 12
```

- **"Straight after"** means the previous paragraph-level marker in the file. Paragraph styles and `\c` count; verses, character styles, notes and milestones don't.
- **Order matters:** `p+q1` is about the `\q1`, with the `\p` before it. `q1+p` is the other direction.
- **Table rows and headings** are paragraphs too, so `s1+p` is a `\p` straight after a section heading.
- The first paragraph of the book has no previous paragraph, so no `a+b` rule applies to it.

### A part of a marker: `marker::caller`

`\Marker f::caller` styles the **caller** of a footnote: the in-text letter in Preview, and the letter at the start of the note in the notes frame. It works for every note marker: `f`, `fe`, `ef`, `x`, `ex`. A caller takes the flags, `\FontSize` and `\Color`.

```
\Marker x::caller
\Italic -
```

`caller` is the only part UNITI knows. A selector with another part is accepted and never matches.

### Lists, and the numberless form

- **Several selectors can share one record**, separated by commas: `\Marker f::caller, fe::caller, ef::caller`. Write each selector whole: inside a list, a name without `+` or `::` is ignored, so give a plain marker its own record.
- **A level-1 marker and its numberless form are the same:** `q` = `q1`, `s` = `s1`, `li` = `li1`. `p+q` and `p+q1` mean the same thing. Levels 2 and up are always written out (`q2`).
- **Malformed selectors are ignored**, silently: `+q1`, `a+b+c` (only one `+`), `::caller`.

### When more than one thing applies

Fields combine; the more specific and later one wins:
1. the marker's own style, from all layers, the last layer winning per field;
2. then every matching rule, in layer order and, inside a layer, file order: a later rule overrides an earlier one field by field.

So a project's `uniti.sty` rule beats the built-in rule for the same selector, and a rule on `p+q1` beats whatever `\q1` itself says.

## Justification

`\Justification` sets which edge a paragraph's lines sit against. It works on any paragraph style or paragraph rule, in Standard and Preview.

| Value | Result |
|---|---|
| `Left` | against the edge the paragraph starts on: left in a left-to-right paragraph, right in a right-to-left one (Arabic, Hebrew) |
| `Right` | the opposite edge: right in a left-to-right paragraph, left in a right-to-left one |
| `Center` | centred (the headings in `usfm.sty` use it) |
| `Both` or `Justify` | both edges: the space between words is spread so every line but the last fills the width |
| `Start` | the same as `Left` |
| `End` | the same as `Right` |

`Left` and `Right` follow the paragraph's reading direction, as they do in PTXprint, so a stock `usfm.sty` gives a right-to-left book what its authors meant: `\qr` sits on the left edge, and `\s3` and `\sp` on the right. The margins and the first-line indent turn round with them. In a right-to-left paragraph, `\LeftMargin` is the right-hand margin and a hanging `\q1` hangs from the right. `Start` and `End` are UNITI's synonyms; they read more clearly in a rule meant for books of both directions. A paragraph with no `\Justification` sits on its start edge. Anything else written there is ignored.

How a paragraph's direction is decided is under [Text direction](#text-direction).

```
# Justify the body text of every book
\Marker p
\Justification Both

# Poetry stays on the start edge in any direction
\Marker q1, q2, q3
\Justification Start
```

Justified text looks best with [hyphenation](#hyphenation).

## Text direction

Each paragraph in Standard and Preview reads left to right or right to left. Its direction decides which edge is the start for `\Justification`, the margins and the first-line indent. The first of these that gives a direction wins:

1. **`\Direction`** on the paragraph's style or on a rule: `LTR` or `RTL` (any case). `Auto` gives none, nor does anything else written there.
2. The tab's **View → Text Direction** choice, when it isn't Auto.
3. The Paratext project's own setting (`LeftToRight` in its `Settings.xml`), read again whenever the window is activated.
4. The paragraph's first letter, when none of the above gives a direction (a file outside a project, with Auto).

The status bar shows what 2 and 3 give the tab (`RTL`, `LTR`, `Auto`, or `LTR (project RTL)` when the tab's choice overrides the project's), and its tooltip names the source. A style's own `\Direction` is per paragraph or span, so it isn't shown there.

`\Direction` is UNITI's. Paratext and PTXprint ignore it, so it belongs in a `uniti.sty`. It's for exceptions, such as English front matter in an Arabic project:

```
# Front matter in English, in a right-to-left project
\Marker ip, is1, imt1
\Direction LTR
```

It works on paragraph styles, the `\c` chapter heading, note styles (the notes below Preview's text) and rules that target them.

On a **character style**, `\Direction LTR` or `RTL` makes its text read in that direction inside any paragraph, without changing the paragraph's. UNITI shows the text in an isolate, as if the span were a paragraph of its own: a Latin name keeps its comma on the right of it (`Paul,`, not `,Paul`) in an Arabic line. Spans inside spans nest, and a span still open at the end of its paragraph ends there. The isolates are the view's: Find, spelling, copy and the file see only the text, and Export Preview as HTML writes them as `<bdi>`.

```
# Transliterated words read left to right, in a right-to-left project
\Marker tl
\Direction LTR
```

Paratext and PTXprint don't read a character style's `\Direction`. For a book that has to look the same there, put the Unicode marks in the text instead (LRM, or LRE … PDF): all three read them.

## Hyphenation

**Hyphenate Preview** breaks long words at the end of a line, at the points in the project's `hyphenatedWords.txt` (Paratext Publishing Assistant's list). It's a per-project-tab switch, off by default, in the USFM menu and on the tab's right-click menu; see [USFM](environments/usfm.md#hyphenating-preview). Which paragraphs it reaches is decided by the stylesheets:

1. **`\Hyphenate`** on the paragraph's style (or a rule): `\Hyphenate` or `\Hyphenate Yes` turns it on, `\Hyphenate -` or `No` turns it off, in any layer;
2. otherwise the list file's own `HyphenatedMarkers` line (`p m pi1 …`);
3. otherwise every paragraph whose `\TextType` is `VerseText`.

```
# Never hyphenate poetry, even if the list's markers include it
\Marker q1, q2
\Hyphenate -

# Hyphenate the list items too
\Marker li1
\Hyphenate
```

A word breaks only where the list gives a point (`a=ro=se`); a word not in the list never breaks. Preview's notes frame hyphenates by the same rules, a kind of note standing in for the paragraph marker (`\Marker f`, `\Hyphenate -` turns footnotes off); with no `\Hyphenate`, the list's `HyphenatedMarkers` line decides when it has one, and without one notes hyphenate. Standard and Plain Text show the source and never hyphenate.

## Built-in rules

UNITI ships these in `uniti.sty (built-in)`. They are on for everyone and can be changed in any layer above.

```
\Marker f::caller, fe::caller, ef::caller
\Superscript
\Bold

\Marker x::caller, ex::caller
\Superscript
\Italic

\Marker p+q1, p+q2, p+q3, q1+p, q2+p, q3+p
\SpaceBefore 12

\Marker nd
\SmallCaps
\Underline -

\Marker cat
\Endmarker cat*
\StyleType Character
\TextProperties publishable
\Italic
```

- **Callers:** footnote callers are bold superscript; cross-reference callers italic superscript.
- **Prose and poetry:** a blank line, one 12-point line, between prose and poetry in both directions.
- **The name of God** (`\nd`) is shown in small capitals instead of the official `usfm.sty`'s underline.
- **`\cat`** (a note's or sidebar's category) is an italic character style. Preview shows its content in brackets: "a [People] 1:1 …" in the notes frame. See [Footnote categories](environments/usfm.md#footnote-categories).

The template UNITI creates for your own or a project `uniti.sty` lists these, commented out, to copy and change.

## How a style is worked out

For a paragraph, UNITI takes:

1. the marker's style from the stylesheet layers (field by field, later layers winning);
2. any `a+b` rule that matches this paragraph and the one before it;
3. then turns the fields into the look: flags and size and colour on the text, margins, spacing, justification and hyphenation on the paragraph.

A character style's look is applied on top of its paragraph's, so a `\nd` inside a `\q1` is small capitals in the poetry's size. A note's caller takes the note marker's `::caller` rules.

## Where to put rules

| Put it in | When |
|---|---|
| your `uniti.sty` (configuration folder) | rules for every USFM file you open |
| the project's `uniti.sty`, next to the book files | rules for this project; layers above every other project stylesheet |
| the project's `custom.sty` | ordinary marker changes that Paratext and PTXprint should see too |

**Paratext and PTXprint never read a file named `uniti.sty`**, so rules there can't affect them. A rule in `custom.sty` works in UNITI too, but Paratext would see a marker called `p+q1`, so keep rules in `uniti.sty`. Creating either `uniti.sty` from **Configuration Files…** starts from a template that explains the syntax.

## What rules don't do

- **They are for Standard and Preview.** Plain Text shows the source.
- **They don't appear in the Style Inspector's marker list,** and never count as markers for validation, placement checks, **Paragraph Style…** or the Book list.
- **There is no descendant selector** (`p q`), no class, no `:first-child`, and no selecting by verse or chapter.
- **They don't change the text,** only how it looks. Edits always go to the source.
- **Export Resolved Stylesheet…** and **Export Stylesheet Overrides…** write rules out like any record, so a rule you added is in the overrides file. The built-in rules are left out of the overrides.

## Recipes

```
# First paragraph after a chapter number isn't indented
\Marker c+p
\FirstLineIndent 0

# A little air above a paragraph after a section heading
\Marker s1+p
\SpaceBefore 2

# Italic cross-reference callers off
\Marker x::caller
\Italic -

# Bigger, dark blue section headings (0xBBGGRR: 0x800000)
\Marker s1
\FontSize 16
\Color 8388608

# Indent block quotes on both sides and justify them
\Marker pi1
\LeftMargin 0.5
\RightMargin 0.5
\Justification Both

# A project's own character style
\Marker zterm
\Endmarker zterm*
\Name zterm - Glossary term
\StyleType Character
\TextProperties publishable
\Bold
\Color 255
```
