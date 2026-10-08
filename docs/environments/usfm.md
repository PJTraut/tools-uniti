# USFM

Scripture text in USFM (Unified Standard Format Markers) and its older SFM form. Paratext projects, single books and anything else in backslash-marker format live here. See the [overview](README.md) for what all environments share.

- **Extensions:** `.usfm`, `.sfm` (any case). The separate "SFM" environment was folded into USFM on 2026-10-08. A setting saved under the old name is read as USFM.
- **Highlighting:** every marker is colored as a keyword: `\v`, `\wj*`, nested `\+it`, milestones `\qt-s … \*`, table cells `\th1-2`. The text is uncolored.

## Views

A USFM tab has three modes. Switch with the environment toolbar, the menu's **View As** block, or the mode list at the top of the view. Each tab keeps its own mode, and it's restored with the session.

| Mode | What it shows | Editing |
|---|---|---|
| **Plain Text** | the source, exactly as written | yes |
| **Standard** | formatted from the stylesheets, with every marker shown as a small tag | yes: typing goes into the text, markers are protected; Bold, Italic, Character Style…, Remove Character Style, Paragraph Style…, Insert Verse…; Enter starts a paragraph of the same kind |
| **Preview** | a print-like rendering: no markers, book metadata left out | read-only |

What Standard and Preview show:
- **Styling.** Every look comes from the stylesheets: paragraph, character and note styles, by marker. Chapter numbers use `\c`'s style, verse numbers `\v`'s.
- **Nested markers.** A nested marker (`\nd Lord \+it God\+it*\nd*`) is styled by its own marker (`\it`) on top of its parent's.
- **Attributes.** Preview hides `|attributes` (`\w king|lemma="king"\w*` shows "king") and milestones.
- **Notes frame (Preview).** Footnotes, cross references and other notes leave the text and are stacked below it, one section per kind. The text keeps the caller: `+` becomes a, b, c… (restarting each chapter), `-` shows none, anything else is shown as written.
  - Clicking a note moves the caret to it.
  - Putting the caret on a caller highlights its note.
  - A note's category (`\cat People\cat*`) shows as "[People]".

**Find and Replace always search the source text**, in every mode. A pattern like `\\v (\d+)` finds verse markers even in Preview. The current match is shown as the selection.

## Book, chapter and verse

The environment window's toolbar has **Book**, **Chapter** and **Verse** at its right end.
- **Book** lists the books available here:
  - in a Paratext project, the project's books;
  - otherwise, the open files of this window's group.

  Each book shows its `\id` code and its `\h` line, e.g. "GEN Genesis". UNITI looks for `\h` in the book's first 10 lines; a project book without one uses its `BookNames.xml` name. Choosing a book opens it in this window and group, in the current mode.
- **Chapter** and **Verse** jump to that place and follow the caret as it moves.

Jumping, here or with **Go to Chapter:Verse…** (Ctrl+Alt+G), puts the verse a third of the way down and highlights it in every mode. The highlight clears when the caret leaves the verse.

## Side-by-side sync

When two or more splits of one window show files of the **same document group**, moving the caret in one moves the others to the same chapter and verse, and highlights the verse in all of them.
- If another split shows a different book, it switches to a tab of that book in the same split, if there is one.
- Verse bridges (`\v 10-12`) and parts (`\v 11a`) are matched.
- Ungrouped files don't sync.
- Turn sync on or off with **Sync Side-by-Side by Reference** (toolbar or menu).

## Projects

**File → Open USFM Project…** opens a Paratext project folder: one with a `Settings.xml`.
- **Book:** UNITI opens one book, the one you were last in (otherwise the first), and the Book list opens the rest.
- **Group:** the project goes to the USFM window of its group. That's the last group used, otherwise the active USFM window's group, otherwise Ungrouped.
- **Recent Projects:** **File → Recent Projects** remembers each project's book, chapter:verse and group.
- **From `Settings.xml`,** UNITI reads the name, the book-file naming, the encoding (books open in it), the versification, and the stylesheet to use in place of `usfm.sty`.
- **Single files:** a book opened with Open File inside a project folder counts as that project's book. A file outside any project is a single file.

## Commands

| Command | Shortcut | What it does |
|---|---|---|
| Go to Chapter:Verse… | Ctrl+Alt+G | jump to e.g. `3:16` or `3` |
| Validate USFM | Ctrl+Alt+V | unmatched end markers, plus the `usfmtc` reference grammar check |
| Check Marker Placement | — | each marker's `OccursUnder` against the loaded stylesheets |
| Inspect Marker at Cursor | Ctrl+Alt+S | the Style Inspector at the marker under the caret |
| Style Inspector… | — | every marker's effective style, with the layer each value comes from |
| Load Stylesheet… | — | layer another `.sty` on top, for this session |
| Reload Project Stylesheets | — | re-read the stylesheets next to the file |
| Export Resolved Stylesheet… / Export Stylesheet Overrides… | — | write the effective styles, or just what's changed from the built-in ones, as a `.sty` |

Findings from Validate and Check Marker Placement open in a list. Activating a row moves the caret there. Files above 1 MiB aren't checked.

## Configuration files

These apply from top to bottom, later ones winning. **Configuration Files…** lists the ones for the current file.

| # | File | Where | Edit |
|---|---|---|---|
| 1 | Official `usfm.sty` | built in | read-only (copy to read) |
| 2 | UNITI built-in rules, `uniti.sty` | built in | read-only (copy to read) |
| 3 | **Your rules**, `uniti.sty` | your configuration folder: `…/Environments/USFM/uniti.sty` | yes; applies to every USFM file |
| 4 | Project stylesheet: `usfm.sty`, or the one `Settings.xml` names | project folder | yes |
| 5 | Project `custom.sty` | project folder | yes; Paratext and PTXprint read it too |
| 6 | PTXprint changes, `shared/ptxprint/ptxprint-mods.sty` | project folder | yes |
| 7 | Project rules, `uniti.sty` | project folder | yes; UNITI only |
| 8 | Loaded stylesheets | wherever you loaded them from | yes |

Other files:
- `Settings.xml`, `BookNames.xml` and `custom.vrs` in the project folder.
- **Your versification files**, `…/Environments/USFM/Versification/*.vrs`. Copy Septuagint, Vulgate or Russian versification files there from a Paratext installation; English and Original are built in.

The two `uniti.sty` files can hold **rules** that a plain `.sty` can't express:
- a paragraph straight after another, e.g. a blank line between prose and poetry (`\Marker p+q1`);
- a note's caller (`\Marker f::caller`).

They can also hold ordinary marker records, such as the built-in `\Marker nd` with `\SmallCaps`. See [USFM Stylesheet Rules](../usfm-stylesheet-rules.md) for the syntax.

Creating your rules or a project `uniti.sty` starts from a template that explains the syntax and lists UNITI's built-in rules, commented out, to copy and change. Saving any of these files reloads the stylesheets, and Standard and Preview update straight away.
