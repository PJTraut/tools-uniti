# USFM Stylesheet Rules

UNITI's **Standard** and **Preview** views take every look from the stylesheets: paragraph, character and note styles, by marker. They read the same `.sty` files as Paratext and PTXprint, layered from lowest to highest precedence:

1. the official `usfm.sty`, built into UNITI;
2. UNITI's built-in rules (`uniti.sty (built-in)`);
3. the project's `usfm.sty`, `custom.sty` and `shared/ptxprint/ptxprint-mods.sty`, next to the book files;
4. the project's own `uniti.sty`, next to the book files;
5. any stylesheet loaded with **Load Stylesheet…**

A plain `.sty` can only style a marker by itself. UNITI extends it with **rules**: ordinary `.sty` records whose `\Marker` is a CSS-like selector instead of a marker name. A rule takes the same fields as a marker's style: `\FontSize`, `\Bold`, `\Italic`, `\Superscript`, `\SpaceBefore`, `\SpaceAfter`, `\LeftMargin`, `\FirstLineIndent`, `\Justification`, `\Color`, and so on.

## Paragraph after paragraph: `a+b`

`\Marker p+q1` styles a `\q1` paragraph that comes straight after a `\p` paragraph, like CSS's adjacent-sibling selector `p + q1`. Its fields win over `\q1`'s own.

```
\Marker p+q1, p+q2, p+q3, q1+p, q2+p, q3+p
\Name Blank line between prose and poetry
\SpaceBefore 12
```

This rule is built in: a blank line, one 12 pt line, between prose and poetry in both directions.

- "Straight after" means the previous paragraph-level marker in the file. Paragraph styles and `\c` count; verses and character styles don't.
- A numberless marker is the same as its level-1 form, so `p+q` and `p+q1` mean the same thing.
- List several selectors in one record, separated by commas.

Other examples:

```
\Marker c+p
\Name First paragraph of a chapter is not indented
\FirstLineIndent 0

\Marker s1+p
\SpaceBefore 2
```

## Note callers: `marker::caller`

`\Marker f::caller` styles the caller of a footnote: the in-text letter in Preview, and the letter at the start of the note in the notes frame. The built-in rules are:

```
\Marker f::caller, fe::caller, ef::caller
\Superscript
\Bold

\Marker x::caller, ex::caller
\Superscript
\Italic
```

## Turning something off

A flag field is turned off with `-`. For example, cross-reference callers that aren't italic:

```
\Marker x::caller
\Italic -
```

## Where to put rules

Put a project's rules in a file named `uniti.sty` next to the book files. UNITI layers it above every other project stylesheet, and Paratext and PTXprint never read it, so it can't affect them. A rule in `custom.sty` works in UNITI too, but Paratext would see a marker called `p+q1`.

Rules apply in Standard and Preview. They don't appear in the Style Inspector's marker list, and they never count as markers for validation, placement checks or **Paragraph Style…**.
