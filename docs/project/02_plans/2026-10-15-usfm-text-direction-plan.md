# USFM Text Direction (LTR / RTL) — Plan

Date: 2026-10-15
Status: **Planned, not started.** Written after a review of the `uniti.sty` extension, with the decisions below proposed and awaiting the user's confirmation (see [Questions for the user](#questions-for-the-user)). Phases W1–W8 (W8 is the HTML export, added at the user's request the same day).
Origin: the user, 2026-10-15: "review UNITI SFM ENV style sheet extension; focus on l2r/r2l and justification", then "explore more: should paragraph style have a global direction assigned; and character style explicit assigned direction to have inline roman text inside arabic paragraph", then "PTXPrint renders everything L2R and flips the image in xetex", then "write the plan and add to project docs", then (after asking whether UNITI renders through a browser engine, which it doesn't: Qt's own text layout) "can we "save to html"" and "add HTML export as phase W8 in the plan".
Builds on: the [hyphenation, justification and spelling follow-ups plan](../03_implemented/milestones/2026-10-15-usfm-hyphenation-and-spelling-followups-plan.md) (J1 and its "As built" note), the [USFM Stylesheet Rules](../../usfm-stylesheet-rules.md) reference and [ADR-0015](../05_decisions/ADR-0015-stylesheet-layers-and-rich-views.md).

## The problem in one paragraph

J1 made `\Justification Left` and `Right` the physical edges (`AlignAbsolute`). Paratext's and PTXprint's stylesheets don't mean that: their directional values are logical, so a stock `usfm.sty` or `custom.sty` used in a right-to-left book gives the wrong result in UNITI. Underneath, UNITI never decides a paragraph's direction. It lets Qt guess from the first strong character of the visible text, so a Standard-view paragraph (which starts with a Latin marker tag) is always left-to-right, and a Preview paragraph that starts with Latin text or only digits flips. The project's own direction setting is never read.

## What was checked first

All measured 2026-10-15, PySide6 6.11.2 (Qt 6.11), offscreen, with the real `block_format`, the real Standard and Preview projections, and the Arabic project `arNAV12` (a Paratext project mounted on `/Volumes/Win11Arm64`).

1. **The built-in `usfm.sty` does use `Left` and `Right`.** The J1 "As built" note says it has none. `\Justification Right` is on `\ipr`, `\pr`, `\cls`, `\pmr`, `\qr`, `\lit` and the `thr*`/`tcr*` cell styles; `Left` is on `\s3`, `\s4` and `\sp`. Before J1, Qt turned those around in a right-to-left paragraph; since J1 `\qr` sits on the start edge like every other line, and `\s3`, `\s4` and `\sp` jump to the left of a right-aligned book.
2. **PTXprint's stylesheet geometry is logical in a right-to-left book.** The [PTXprint release notes](https://raw.githubusercontent.com/sillsdev/ptx2pdf/master/docs/inno-docs/ReleaseNotes.txt): 1.7.9 (2021-05-20) "The TeX macros have been changed for RTL for Right and Left Justification such that they are swapped … If justification is Left, it will be Right-justified"; 2.2.30 "Fix RTL aligned (not justified) text (for example, \qr)". The user's account of the mechanism is that PTXprint typesets everything left-to-right and flips the result in XeTeX, which makes every directional stylesheet value start- or end-relative. The mechanism is the user's; the justification swap is documented; that margins mirror too is an inference, to be confirmed (W3's gate).
3. **Margins and first-line indent disagree in Qt.** `leftMargin` and `rightMargin` are physical; `textIndent` and a plain alignment follow the paragraph's direction. Stock `\q1` (`LeftMargin 0.75`, `FirstLineIndent -0.5`) in an RTL paragraph: the first line sits flush at the right edge (gap 0, clipped) and the continuation lines get no indent at all, because the 0.75" lands on the empty left side. In LTR the first line is 29 px in and the rest 77 px in, as intended.
4. **Direction is whatever Qt's first-strong rule gives.** Standard: all four blocks of a Hebrew sample were left-to-right (`\p …`, `\q1 …`, `\qr …`, and `\c 1`). Preview: right-to-left only when the text starts with an RTL letter or a digit; `Paul שלום עולם` is left-to-right, and the chapter heading `1` is too. The rich views read nothing of the plain-text view's Auto/LTR/RTL override.
5. **The project declares its direction and UNITI doesn't read it.** `arNAV12/Settings.xml` has `<LeftToRight>F</LeftToRight>`. `paratext_project.py` reads `Name`, `FullName`, `LanguageIsoCode`, `Encoding`, `Versification`, `StyleSheet`, `Guid`, `BooksPresent`, the file naming and the word affixes.
6. **PTXprint's own direction is per print configuration, not per project.** `arNAV12/shared/ptxprint`: `Mark`, `John` and `Luke` have `ifrtl = Right-to-Left`, `script = Arab`, `mirrorlayout = False`; `Matthew` and `NewArabicVersion` have `ifrtl = Left-to-Right`, `script = Zyyy`, `mirrorlayout = True`; `Default` has `ifrtl = ltr`. They disagree with each other, so the Paratext `LeftToRight` flag is the project-level source and the PTXprint configurations are not read.
7. **Marker tags scramble in an RTL paragraph.** Under an explicit RTL base, Standard's `\p \v 1 …` renders as `p \v 1\`. Wrapping each marker token in LRI…PDI (U+2066, U+2069) fixes it: the markers read `\p \v 1` from the right.
8. **Isolates work in Qt and cost nothing.** LRI, PDI, LRE, PDF and FSI are honoured; an isolate adds no width (75 px with and without). In an Arabic paragraph, `Paul,` renders as `,Paul` (the comma jumps to the wrong side) and as `Paul,` inside LRI…PDI. Brackets and digits were already right.
9. **Inline Latin in Arabic is rare, and authors already mark it in the source.** `arNAV12`: 69 books, 41,095 lines; 3 lines mix Latin and Arabic, all front matter. The source holds 277 LRM, 62 RLM, 5 LRE and 6 RLE characters, which Qt honours as written. PTXprint also reads those characters (1.8.3 "Fix handling of Grk/Hbr embedded within RTL/LTR text"; 2.2.35 "Added RLE,LRE,PDF…") but has no stylesheet field for a direction.
10. **Justification itself is fine.** `Both` fills lines in RTL and puts the last line on the start edge; an unset `\Justification` sits on the start edge.
11. **UNITI is screen-only and has no browser engine.** Standard and Preview are a `QTextEdit` (`rich_view.py`) filled from the projection; the plain-text editor paints itself over Qt's text shaping; the Markdown view is a `QTextBrowser`. No QtWebEngine, no `setHtml`. HTML's `dir`, `<bdi>` and logical margins are therefore not available on screen, but they are exactly what an export can use.
12. **There is no HTML export, and the pieces for one exist.** The only export of the rich views is the `.sty` one (`stylesheet_support.py`, an `EnvironmentCommand` returning `SaveTextFile(title, default name, text, filters)`). Preview's projection is Qt-free and already carries everything an export needs: the text, a block per paragraph with `align`, margins, `first_indent`, `space_before`, `hyphenate` (and `direction` after W2), spans with their flags, size and colour, and the notes section. Colours in the projection are the stylesheet's raw `#rrggbb`; the readable-on-theme adjustment happens only in `rich_view.char_format`.

## Decisions

- **W-D1: the stylesheet's directional values are logical, as in PTXprint.** `Left` and `Right` are the start and end edges of the paragraph's reading direction; `\LeftMargin` and `\RightMargin` are the start-side and end-side margins; `\FirstLineIndent` is the start-side indent. In a left-to-right paragraph nothing changes. `Start` and `End` stay as synonyms of `Left` and `Right` (clearer in a rule meant for both directions). This reverses J1's "physical" decision; the stock stylesheets and Paratext projects then behave as authored. A physical edge isn't offered: nobody has asked for one.
- **W-D2: where a paragraph's direction comes from, highest first.** (1) `\Direction` on its style or a rule (W-D4); (2) the view's Auto / Left-to-Right / Right-to-Left choice, the same one the plain-text view has, saved per view; (3) the project's `LeftToRight` setting; (4) the first strong character, as today. A file outside a project has no setting, so it keeps 4 unless the user chooses a direction for the view.
- **W-D3: the direction applies in Standard and Preview, including the notes frame.** The projection carries a `direction` attribute on each block; `block_format` sets the block's layout direction from it, so alignment, indent and the margins resolve against a known direction and not Qt's guess. In an RTL paragraph, Standard puts each marker tag in an LRI…PDI isolate (generated segments), so source markers keep reading `\p \v 1`.
- **W-D4: `\Direction LTR|RTL|Auto` on paragraph styles and rules.** A UNITI field, read from any layer but meant for `uniti.sty` (Paratext and PTXprint ignore unknown fields, and PTXprint has no equivalent). `Auto` means "use W-D2's lower sources". It's for exceptions, such as English front matter in an Arabic project. Registered as a known presentation field, so the Style Inspector shows it.
- **W-D5: character direction is Unicode isolates, optional and last.** Qt has no per-character direction, so `\Direction LTR|RTL` on a character style makes the projection put a generated LRI or RLI before and a PDI after the span. The source map skips them, as it does soft hyphens (H-D5), and copy leaves them out. Only built if a project asks for it (see the evidence in point 9); authors who need it today put LRM or LRE in the source, which already works.
- **W-D6: no automatic isolation of Latin runs.** It would be a display-only heuristic that could be wrong; not planned.
- **W-D7: PTXprint's `ifrtl` and `mirrorlayout` are not read** (point 6).
- **W-D8: Preview can be exported as HTML, from the projection, not from Qt.** A Qt-free serializer in core writes the paragraphs, spans and notes the Preview shows, with the stylesheet's logical values kept logical in CSS (`dir`, `text-align: start|end`, `margin-inline-start|end`, `text-indent`, `<bdi>`, `hyphens`). It does not use `QTextDocument.toHtml()`, whose output is physical and Qt-specific. This needs the projection to keep margins logical (see W3). Preview only: Standard is the source, and its tags are not publishable text.

## Questions for the user

1. **Confirm margins mirror in PTXprint** (W3's gate). Produce a PDF from a Right-to-Left configuration (`Mark` or `John`) of `arNAV12` with a `\q1` hanging-indent passage and a `\qr` line; I'll render it with `pdftoppm` and read the margins. If PTXprint does not mirror margins, W3 keeps margins physical and mirrors only alignment.
2. **Standard view in RTL.** W-D3 lays Standard out right to left for an RTL project, with tags kept readable. The alternative is Standard always left-to-right (it is the source), where `Start` and `End` have no meaning in Standard. Proposed: right to left.
3. **Character `\Direction` (W6):** build it now, or only on request? Proposed: on request.
4. **HTML export scope (W8):** the text the Preview shows (the whole book, or the one chapter when Show One Chapter is on), with the tab's footnote category filter and Hyphenate Preview as they are now; or always the whole book; or every book of the project into a folder. Proposed: what the Preview shows. A project-wide export would be a later addition.

## Phases

### W1: Read the project's direction (core, Qt-free)
`ParatextProject.right_to_left: bool | None`, from `Settings.xml`'s `LeftToRight` (`F` is right-to-left, `T` left-to-right, missing or unreadable is `None`). W8 also needs the project's `DefaultFont` (`ParatextProject.default_font: str | None`), read in the same place; `Language` and `LanguageIsoCode` are already read. Tests with a temporary project folder: `F`, `T`, missing, garbage, and the Paratext 8+ and older layouts.

### W2: Block direction in the projection
`layout_projection(..., direction=…)` sets `direction: ltr|rtl` on every block (and the notes frame's blocks) by W-D2's order: style or rule `\Direction`, then the view's choice, then the project. No source means no attribute (Qt's first-strong, unchanged). `block_format` calls `setLayoutDirection` when the attribute is there. The rich views read the same per-view Auto/LTR/RTL choice as the plain-text view, and the projection cache key includes it. Tests: a tag-led and a Latin-led Hebrew paragraph, a digit-only heading, and the chapter heading `\c`, all take the project's direction; no attribute, no change.

### W3: Logical `Left`/`Right` and margins (reverses J1)
`block_format` maps `left` and `right` to the plain flags (no `AlignAbsolute`) and `start` and `end` the same; `block_format` swaps `left_margin` and `right_margin` when the block is right-to-left, from the block's `direction` attribute (W2) or, when there is none, from the first strong character of the block's text (`render_projection` passes `block_format` the resolved direction). The projection itself keeps the margins logical, start-side and end-side as the stylesheet wrote them, so the HTML export (W8) can write them as `margin-inline-start` and `margin-inline-end` without undoing a swap. `FirstLineIndent` is left as is. **Gate: question 1.** Tests: replace `test_left_and_right_are_physical_in_either_direction` with the logical one; stock `\qr`, `\s3`, `\sp`, `\pr` and `\q1`/`\li1` hanging indents in RTL (first line outdented into the end-side margin, continuation lines indented), and unchanged output in LTR.

### W4: Tags in Standard stay readable
In a right-to-left Standard paragraph the marker tokens get a generated LRI before and PDI after. Tests: the source map round-trips every offset, Find and copy take source text only, the text with the isolates removed equals today's, an LTR paragraph gets none, and the caret reaches each marker (the arrow keys step over a zero-width character; if they stall, fix with the source map as H-D5 did).

### W5: `\Direction` on paragraph styles
Parse `\Direction` (`LTR`, `RTL`, `Auto`, any case, anything else ignored), carry it through `formatting_attrs`, register it with the Style Inspector, add it to the `uniti.sty` template and to W2's precedence. Tests: a marker record, an `a+b` rule, layer order, and a project `uniti.sty` beating the project setting.

### W6: `\Direction` on character styles (only if asked, W-D5)
`LTR` and `RTL` on a character style: a generated LRI or RLI at the span's start and PDI at its end, nested spans in order, closed at the paragraph's end. Tests: `Paul,` between Arabic words reads `Paul,`; nesting; source map, Find, copy and spelling underlines skip the generated characters.

### W7: Documentation and records
- [USFM Stylesheet Rules](../../usfm-stylesheet-rules.md): rewrite the Justification section (logical, PTXprint-compatible), say how direction is decided (W-D2) in a new "Text direction" section, add `\Direction` to the Fields table, say margins are start- and end-side, add a recipe and the stock-style examples.
- The `uniti.sty` template comment (`assets/uniti.sty`, `configuration.py`), the comment on `_ALIGN`, `projection.py`'s `align` note and the new `direction` attribute.
- [USFM](../../environments/usfm.md), the [live-app checklist](../LIVE_APP_CHECKLIST.md) (an Arabic or Hebrew project in Standard and Preview: alignment, hanging indents, `\qr`, a Latin-led paragraph), [Current Status](../01_current/STATUS.md) (the J1 line) and the handover.
- W8's own documentation (the USFM page's export section, the cheat sheet and the menu list) lands with W8.
- Add a "superseded by W3" note to J1's "As built" in the follow-ups plan and correct its "has no `Left` or `Right`" sentence. The history of that plan stays otherwise as written.

### W8: Export Preview as HTML
- **Command.** **Export Preview as HTML…** in the USFM menu and on the Preview right-click menu, an `EnvironmentCommand` that returns `SaveTextFile` like the `.sty` exports (default name `<book>.html`, filter `HTML (*.html)`). It exports what the Preview shows now (question 4): the footnote category filter and Hyphenate Preview of the tab apply. If the command context doesn't carry those, it is given the tab's Preview settings the way `project_with` receives them.
- **Serializer.** `sfm/html_export.py`, Qt-free: `export_preview_html(projection, *, title, language, direction, font) -> str`. UTF-8, `<meta charset>`, everything escaped; one `<style>` block with a class per distinct block and span attribute set (each element also gets `data-marker="q1"`, so the file can be restyled), no inline style except where a `p+q1`-style rule changes a block.

  | Projection | HTML and CSS |
  |---|---|
  | project direction | `<html lang dir>`; blocks with `direction` get `dir`; a block without one gets `dir="auto"` (the browser's first-strong, as Qt's Auto) |
  | `align` `left`/`start` | `text-align: start`; `right`/`end` → `text-align: end`; `center`, `justify` as written |
  | `left_margin`, `right_margin` | `margin-inline-start`, `margin-inline-end` in `in` |
  | `first_indent` | `text-indent` |
  | `space_before`, `space_after` | `margin-block-start`, `margin-block-end` in `pt` |
  | bold, italic, underline, small caps, superscript | `font-weight`, `font-style`, `text-decoration`, `font-variant: small-caps`, `<sup>` |
  | `font_scale`, `color` | `font-size: …em`; the stylesheet's own colour, not the editor theme's |
  | `hyphenate` | `hyphens: manual`; the soft hyphens go out as `&shy;` |
  | character `\Direction` (W6) | `<bdi dir>` around the span |
  | table rows (`\tr`) | `<table>`: one `<tr>` per row, a `<td>` per cell, header cells as `<th>` |
  | notes | the caller as `<sup><a href="#n1" id="r1">`, the notes after the text as an `<ol class="notes">` with a back link; categories show in brackets, as in Preview |
- **Font.** `Settings.xml`'s `DefaultFont` (arNAV12 has `Adobe Arabic`), read with the other project fields in W1's reader, goes first in `font-family`, then `serif`; the file embeds no fonts.
- **Generated text.** The projection's generated segments (the `\cat` brackets, cell tabs, callers, soft hyphens) are already in the projection text, so the export needs no source map. The U+00AD and any isolate characters are written as entities or elements, never raw.
- **Tests (core).** A golden file per direction: a Hebrew or Arabic paragraph, a left-to-right one, a stock `\qr`, `\s3` and hanging `\q1` in RTL (start-side margin and `text-align: end` in the output); escaping of `<`, `&` and `"`; soft hyphens; a table; notes with a hidden category; colour (raw, not theme-adjusted); the output parses with `html.parser` and the text content equals the projection's. **Tests (window).** The command offers `SaveTextFile` with the Preview's filter applied. **By hand:** open an `arNAV12` export in a browser and compare it with Preview (the live-app checklist entry); the browser's bidi engine is an independent check of W2–W4.
- **Not in the export.** The Standard view, page layout and pagination, printing, fonts, and the verse and chapter numbers' own styles beyond what the stylesheet gives them (they follow `\v` and `\c`'s styles like any span).

## Order

W1 → W2 → W3 (after question 1) → W4 → W5 → (W6 on request) → W8 → W7. Documentation for a phase lands with it; W7 is the sweep. W8 needs W1 (the font and language), W2 (the block directions) and W3 (logical margins), and is documented with itself; if W6 is built, W8 writes it as `<bdi>`. W1, W2 and W5 don't change how any left-to-right book looks.

## Risks

- **Qt's flags are the mechanism for `Left` and `Right`** (a plain alignment is mirrored by the block's direction). An explicit direction makes that deterministic, but a future Qt could change the behaviour: the alignment tests use real painted text, as J1's do.
- **Caret and selection over generated isolates** (W4, W6): the same family of problem soft hyphens had; the source map is where it's solved.
- **A direction chosen for the view and the project disagreeing** is intended (the view wins), but the status bar should show the direction in effect.
- **The HTML export is a second renderer of the same projection.** A browser's justification, hyphenation and bidi differ from Qt's in small ways, so the export is faithful to the stylesheet, not pixel-identical to Preview; golden tests pin the HTML, not the look.
- **PTXprint's behaviour is documented only for justification.** Margins, and whether `\FirstLineIndent` mirrors, rest on question 1.

## Out of scope

- Reading PTXprint's configurations (`ifrtl`, `mirrorlayout`, `script`).
- Automatic isolation of Latin runs inside RTL paragraphs (W-D6).
- The plain-text editor's own direction handling, which already has its override and isn't changed.
- Mirrored page layout (inner and outer margins, binding side): UNITI has no pages.
- Shaping, kashida and digit substitution.
- Exporting to PDF, ePub or any paged format, and embedding fonts in the HTML.
